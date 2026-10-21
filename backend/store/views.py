"""
NexusCart - views.py  (business logic + JSON API for the frontend)
Author: Ishant Birra
 
The frontend (Jaswanth) talks to these endpoints with JSON. Authentication
uses Django sessions (cookie), and every write request needs a CSRF token:
  1. GET  /api/csrf/        -> sets the `csrftoken` cookie
  2. send it back in the `X-CSRFToken` header on every POST/PATCH/DELETE.
 
Sections:
  A. Helpers + RBAC decorators
  B. Auth (register / login / logout)
  C. Products   (everyone reads, ONLY admins write)
  D. Cart
  E. Checkout   (row-level locking => no negative stock)
  F. Payment + Orders
"""
import json
from decimal import Decimal, InvalidOperation
from functools import wraps
 
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods
 
from .models import (Cart, CartItem, Order, OrderItem, Payment, Product, Review, ShopperActivity,
                     User)
 
 
# ═════════════════════════════════════════════════════════════════════════
# A. HELPERS + ROLE-BASED ACCESS CONTROL
# ═════════════════════════════════════════════════════════════════════════
def error(message, status=400, **extra):
    return JsonResponse({"error": message, **extra}, status=status)
 
 
def read_json(request):
    """Parse the JSON body; returns {} for an empty body, None if invalid."""
    try:
        return json.loads(request.body or b"{}")
    except (ValueError, UnicodeDecodeError):
        return None
 
 
def login_required_api(view):
    """RBAC layer 1: must be logged in (else 401)."""
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return error("Authentication required.", 401)
        return view(request, *args, **kwargs)
    return wrapper
 
 
def admin_required(view):
    """RBAC layer 2: must be logged in AND have role=ADMIN (else 403)."""
    @wraps(view)
    @login_required_api
    def wrapper(request, *args, **kwargs):
        if not request.user.is_store_admin:
            return error("Admin access required.", 403)
        return view(request, *args, **kwargs)
    return wrapper
 
 
def customer_required(view):
    """Only customers place orders (admins manage the store, they don't shop)."""
    @wraps(view)
    @login_required_api
    def wrapper(request, *args, **kwargs):
        if request.user.role != User.Role.CUSTOMER:
            return error("Customer account required.", 403)
        return view(request, *args, **kwargs)
    return wrapper
 
 
# --- small serializers: model -> dict ---
def product_json(p):
    return {"id": p.id, "sku": p.sku, "name": p.name, "category": p.category, "brand": p.brand,
            "description": p.description, "price": float(p.price), "stock": p.stock,
            "image": p.image_path, "image_path": p.image_path, "is_active": p.is_active,
            "is_deleted": p.is_deleted}
 
 
def order_json(o):
    try:
        ship_to = json.loads(o.shipping_address)
    except (TypeError, ValueError):
        ship_to = None
    return {
        "id": o.id, "user": o.user.username, "status": o.status, "total_price": str(o.total_price),
        "subtotal": str(o.subtotal), "discount": str(o.discount), "date": o.created_at.isoformat(),
        "shipping_address": o.shipping_address, "ship_to": ship_to,
        "created_at": o.created_at.isoformat(),
        "items": [{"product_id": i.product_id, "name": i.product_name,
                   "unit_price": str(i.unit_price), "quantity": i.quantity,
                   "line_total": str(i.line_total)} for i in o.items.all()],
        "payments": [{"transaction_id": p.transaction_id, "amount": str(p.amount),
                      "method": p.method, "status": p.status,
                      "date": p.created_at.isoformat()} for p in o.payments.all()],
    }
 
 
# ═════════════════════════════════════════════════════════════════════════
# B. AUTHENTICATION
# ═════════════════════════════════════════════════════════════════════════
@ensure_csrf_cookie
@require_http_methods(["GET"])
def csrf(request):
    return JsonResponse({"detail": "CSRF cookie set."})
 
 
@require_http_methods(["POST"])
def register(request):
    """Public sign-up. ALWAYS creates a CUSTOMER; a client can never pick
    its own role (that would let anyone make themselves admin)."""
    data = read_json(request)
    if data is None:
        return error("Invalid JSON.")
    username, password = data.get("username", "").strip(), data.get("password", "")
    if not username or not password:
        return error("username and password are required.")
    try:
        validate_password(password)
        user = User.objects.create_user(username=username, email=data.get("email", ""),
                                        password=password, role=User.Role.CUSTOMER)
    except ValidationError as exc:
        return error("Weak password.", password=list(exc.messages))
    except IntegrityError:
        return error("Username already taken.", 409)
    user.first_name = str(data.get("full_name", "")).strip()
    user.email = str(data.get("email", "")).strip()
    user.phone = str(data.get("phone", "")).strip()
    user.save(update_fields=["first_name", "email", "phone"])
    return JsonResponse({"id": user.id, "username": user.username, "role": user.role}, status=201)
 
 
@require_http_methods(["POST"])
def login_view(request):
    data = read_json(request)
    if data is None:
        return error("Invalid JSON.")
    user = authenticate(request, username=data.get("username"), password=data.get("password"))
    if user is None:
        return error("Invalid credentials.", 401)
    login(request, user)
    return JsonResponse({"id": user.id, "username": user.username, "role": user.role,
                         "full_name": user.first_name, "email": user.email})
 
 
@require_http_methods(["POST"])
def logout_view(request):
    logout(request)
    return JsonResponse({"detail": "Logged out."})
 
 
# ═════════════════════════════════════════════════════════════════════════
# C. PRODUCTS  (read: everyone | create/update/delete: ADMIN only)
# ═════════════════════════════════════════════════════════════════════════
@require_http_methods(["GET", "POST"])
def product_collection(request):
    if request.method == "GET":
        # Product.objects already hides soft-deleted items.
        qs = Product.objects.all()
        q = request.GET.get("q")
        if q:
            from django.db.models import Q
            qs = qs.filter(Q(name__icontains=q) | Q(category__icontains=q) | Q(description__icontains=q))
        category = request.GET.get("category")
        if category and category not in ("", "All"):
            qs = qs.filter(category__iexact=category)
        return JsonResponse({"products": [product_json(p) for p in qs]})
    return _product_create(request)
 
 
@admin_required
def _product_create(request):
    data = read_json(request)
    if data is None:
        return error("Invalid JSON.")
    try:
        product_fields = {
            "name": data.get("name", ""), "category": data.get("category", "General"),
            "brand": data.get("brand", ""), "description": data.get("description", ""),
            "price": Decimal(str(data.get("price", ""))), "stock": int(data.get("stock", 0)),
            "image_path": data.get("image_path", data.get("image", "")),
            "is_active": data.get("is_active", True),
        }
        sku = str(data.get("sku") or "").strip()
        if sku:
            product_fields["sku"] = sku
        product = Product(**product_fields)
        product.full_clean()  # runs model validators (price >= 0.01, stock >= 0 ...)
        product.save()
    except (InvalidOperation, ValueError, TypeError):
        return error("price must be a number and stock an integer.")
    except ValidationError as exc:
        return error("Validation failed.", details=exc.message_dict)
    return JsonResponse(product_json(product), status=201)
 
 
@require_http_methods(["GET", "PATCH", "DELETE"])
def product_detail(request, pk):
    if request.method == "GET":
        try:
            return JsonResponse(product_json(Product.objects.get(pk=pk)))
        except Product.DoesNotExist:
            return error("Product not found.", 404)
    if request.method == "PATCH":
        return _product_update(request, pk)
    return _product_soft_delete(request, pk)
 
 
@admin_required
def _product_update(request, pk):
    data = read_json(request)
    if data is None:
        return error("Invalid JSON.")
    # Lock the row while editing so an admin's stock edit can't be lost
    # or overwritten by a customer checkout happening at the same moment.
    with transaction.atomic():
        try:
            product = Product.objects.select_for_update().get(pk=pk)
        except Product.DoesNotExist:
            return error("Product not found.", 404)
        try:
            for field in ("sku", "name", "category", "brand", "description", "image_path", "is_active"):
                if field in data:
                    setattr(product, field, data[field])
            if "price" in data:
                product.price = Decimal(str(data["price"]))
            if "stock" in data:
                product.stock = int(data["stock"])
            if "image" in data and "image_path" not in data:
                product.image_path = data["image"]
            product.full_clean()
            product.save()
        except (InvalidOperation, ValueError, TypeError):
            return error("price must be a number and stock an integer.")
        except ValidationError as exc:
            return error("Validation failed.", details=exc.message_dict)
    return JsonResponse(product_json(product))
 
 
@admin_required
def _product_soft_delete(request, pk):
    try:
        product = Product.objects.get(pk=pk)
    except Product.DoesNotExist:
        return error("Product not found.", 404)
    product.delete()  # SOFT delete (see models.py)
    return JsonResponse({"detail": "Product soft-deleted."})


def _ai_products():
    return [{
        "id": product.id, "name": product.name, "category": product.category,
        "price": float(product.price), "stock": product.stock, "description": product.description,
        "image": product.image_path,
    } for product in Product.objects.all()]


@require_http_methods(["GET"])
def product_search(request):
    from app.ai.smart_search import SmartSearch

    try:
        limit = min(max(int(request.GET.get("limit", 10)), 1), 50)
    except ValueError:
        return error("limit must be an integer.")
    products = _ai_products()
    if not products:
        return JsonResponse({
            "query": request.GET.get("q", ""),
            "interpreted": {"text": request.GET.get("q", ""), "max_price": None, "min_price": None},
            "did_you_mean": None, "results": [],
        })
    result = SmartSearch(products).search(
        request.GET.get("q", ""), limit=limit, category=request.GET.get("category"),
        in_stock_only=request.GET.get("in_stock") == "1",
    )
    return JsonResponse(result)


@require_http_methods(["POST"])
def product_recommendations(request):
    from django.db.models import Avg
    from app.ai.recommender import HybridRecommender

    try:
        limit = min(max(int(request.GET.get("k", 6)), 1), 20)
    except ValueError:
        return error("k must be an integer.")
    activity = read_json(request)
    if not isinstance(activity, dict):
        return error("The request body must be a JSON object.")

    products = _ai_products()
    if not products:
        return JsonResponse({"personalized": False, "items": []})
    if request.user.is_authenticated and request.user.role == User.Role.CUSTOMER:
        cart = Cart.objects.filter(user=request.user).first()
        activity = {
            "purchases": list(OrderItem.objects.filter(order__user=request.user)
                              .exclude(order__status=Order.Status.CANCELLED)
                              .values_list("product_id", flat=True)),
            "cart": list(CartItem.objects.filter(cart=cart).values_list("product_id", flat=True))
            if cart else [],
            "views": list(ShopperActivity.objects.filter(
                user=request.user, kind=ShopperActivity.Kind.VIEW, product__isnull=False,
            ).values_list("product_id", flat=True)[:20]),
            "searches": list(ShopperActivity.objects.filter(
                user=request.user, kind=ShopperActivity.Kind.SEARCH,
            ).values_list("query", flat=True)[:8]),
            "liked": list(Review.objects.filter(user=request.user, rating__gte=4)
                          .values_list("product_id", flat=True)),
        }
    ratings = {
        row["product_id"]: float(row["average"])
        for row in Review.objects.values("product_id").annotate(average=Avg("rating"))
    }
    interactions = []
    for item in CartItem.objects.select_related("cart__user"):
        interactions.extend([(item.cart.user.username, item.product_id, "cart")] * item.quantity)
    for item in OrderItem.objects.select_related("order__user"):
        interactions.extend([(item.order.user.username, item.product_id, "purchase")] * item.quantity)
    for item in ShopperActivity.objects.filter(kind=ShopperActivity.Kind.VIEW, product__isnull=False):
        interactions.append((item.user.username, item.product_id, "view"))
    result = HybridRecommender(products, interactions, ratings).recommend(activity, k=limit)
    return JsonResponse(result)


@customer_required
@require_http_methods(["GET", "POST", "DELETE"])
def activity(request):
    if request.method == "GET":
        searches = []
        seen_queries = set()
        for row in ShopperActivity.objects.filter(user=request.user, kind=ShopperActivity.Kind.SEARCH)[:100]:
            key = row.query.casefold()
            if key not in seen_queries:
                searches.append({"q": row.query, "ts": row.created_at.strftime("%Y-%m-%d %H:%M")})
                seen_queries.add(key)
            if len(searches) == 15:
                break
        views = []
        seen_products = set()
        for product_id in ShopperActivity.objects.filter(
            user=request.user, kind=ShopperActivity.Kind.VIEW, product__isnull=False,
        ).values_list("product_id", flat=True)[:100]:
            if product_id not in seen_products:
                views.append(product_id)
                seen_products.add(product_id)
            if len(views) == 20:
                break
        return JsonResponse({"searches": searches, "views": views})
    if request.method == "DELETE":
        kind = request.GET.get("kind", ShopperActivity.Kind.SEARCH)
        if kind not in ShopperActivity.Kind.values:
            return error("kind must be search or view.")
        rows = ShopperActivity.objects.filter(user=request.user, kind=kind)
        query = request.GET.get("q")
        if query is not None:
            rows = rows.filter(query__iexact=query)
        deleted, _ = rows.delete()
        return JsonResponse({"deleted": deleted})

    data = read_json(request)
    if not isinstance(data, dict):
        return error("Invalid JSON.")
    kind = data.get("kind")
    if kind == ShopperActivity.Kind.SEARCH:
        query = str(data.get("query", "")).strip()
        if not query:
            return error("query is required for a search activity.")
        ShopperActivity.objects.create(user=request.user, kind=kind, query=query[:250])
    elif kind == ShopperActivity.Kind.VIEW:
        try:
            product = Product.objects.get(pk=data.get("product_id"))
        except (Product.DoesNotExist, ValueError, TypeError):
            return error("Product not found.", 404)
        ShopperActivity.objects.create(user=request.user, kind=kind, product=product)
    else:
        return error("kind must be search or view.")
    return JsonResponse({"detail": "Activity saved."}, status=201)


def review_json(review):
    return {
        "id": review.id, "pid": review.product_id, "product_id": review.product_id,
        "user": review.user.username, "rating": review.rating, "title": review.title,
        "text": review.text, "date": review.created_at.date().isoformat(),
        "verified": review.verified,
    }


@admin_required
@require_http_methods(["GET"])
def review_collection(request):
    reviews = Review.objects.select_related("product", "user")
    return JsonResponse({"reviews": [review_json(review) for review in reviews]})


@require_http_methods(["GET", "POST"])
def product_reviews(request, product_id):
    try:
        product = Product.objects.get(pk=product_id)
    except Product.DoesNotExist:
        return error("Product not found.", 404)
    if request.method == "GET":
        from django.db.models import Avg
        reviews = list(Review.objects.filter(product=product).select_related("user"))
        rows = [{"rating": review.rating, "text": f"{review.title}. {review.text}".strip(". ")}
                for review in reviews]
        from app.ai.sentiment import SentimentAnalyzer
        summary = SentimentAnalyzer().summarize(rows, product.name)
        return JsonResponse({"reviews": [review_json(r) for r in reviews], "summary": summary,
                             "count": len(reviews),
                             "avg_rating": float(Review.objects.filter(product=product).aggregate(
                                 average=Avg("rating"))["average"] or 0),
                             "hist": {rating: Review.objects.filter(product=product, rating=rating).count()
                                      for rating in range(1, 6)}})
    if not request.user.is_authenticated:
        return error("Authentication required.", 401)
    if request.user.role != User.Role.CUSTOMER:
        return error("Customer account required.", 403)
    data = read_json(request)
    if not isinstance(data, dict):
        return error("Invalid JSON.")
    try:
        rating = int(data.get("rating"))
    except (TypeError, ValueError):
        return error("rating must be an integer from 1 to 5.")
    if not 1 <= rating <= 5:
        return error("rating must be an integer from 1 to 5.")
    title, text = str(data.get("title", "")).strip(), str(data.get("text", "")).strip()
    if not title and not text:
        return error("Please add a headline or a written review.")
    verified = OrderItem.objects.filter(
        order__user=request.user, product=product, order__status=Order.Status.DELIVERED,
    ).exists()
    review, _ = Review.objects.update_or_create(
        product=product, user=request.user,
        defaults={"rating": rating, "title": title, "text": text, "verified": verified},
    )
    return JsonResponse(review_json(review))


@admin_required
@require_http_methods(["DELETE"])
def review_delete(request, review_id):
    deleted, _ = Review.objects.filter(pk=review_id).delete()
    if not deleted:
        return error("Review not found.", 404)
    return JsonResponse({"detail": "Review deleted."})


@require_http_methods(["GET"])
def review_sentiment(request, product_id):
    from app.ai.sentiment import SentimentAnalyzer

    try:
        product = Product.objects.get(pk=product_id)
    except Product.DoesNotExist:
        return error("Product not found.", 404)
    reviews = Review.objects.filter(product=product)
    data = [{"rating": review.rating, "text": f"{review.title}. {review.text}".strip(". ")}
            for review in reviews]
    return JsonResponse({"product": product.name, **SentimentAnalyzer().summarize(data, product.name)})


@login_required_api
@require_http_methods(["GET", "PATCH"])
def profile(request):
    user = request.user
    if request.method == "GET":
        return JsonResponse({
            "full_name": user.first_name, "email": user.email, "phone": user.phone,
            "alt_phone": user.alt_phone, "address_line1": user.address_line1,
            "address_line2": user.address_line2, "city": user.city, "state": user.state,
            "postal_code": user.postal_code, "country": user.country,
            "address_type": user.address_type, "delivery_notes": user.delivery_notes,
        })
    data = read_json(request)
    if not isinstance(data, dict):
        return error("Invalid JSON.")
    fields = {
        "full_name": "first_name", "email": "email", "phone": "phone", "alt_phone": "alt_phone",
        "address_line1": "address_line1", "address_line2": "address_line2", "city": "city",
        "state": "state", "postal_code": "postal_code", "country": "country",
        "address_type": "address_type", "delivery_notes": "delivery_notes",
    }
    for source, target in fields.items():
        if source in data:
            setattr(user, target, str(data[source]).strip())
    if user.address_type not in {"Home", "Work"}:
        return error("address_type must be Home or Work.")
    user.save(update_fields=list(fields.values()))
    return JsonResponse({"detail": "Profile saved."})


# ═════════════════════════════════════════════════════════════════════════
# D. CART
# ═════════════════════════════════════════════════════════════════════════
def cart_json(cart):
    items = cart.items.select_related("product")
    return {"items": [{"product_id": i.product_id, "product": product_json(i.product),
                       "name": i.product.name, "unit_price": str(i.product.price),
                       "quantity": i.quantity, "line_total": str(i.line_total)} for i in items],
            "total": str(cart.total)}
 
 
@customer_required
@require_http_methods(["GET"])
def cart_detail(request):
    cart, _ = Cart.objects.get_or_create(user=request.user)
    return JsonResponse(cart_json(cart))
 
 
@customer_required
@require_http_methods(["POST"])
def cart_add(request):
    """Body: {"product_id": 1, "quantity": 2}. Adds to the existing quantity."""
    data = read_json(request) or {}
    try:
        quantity = int(data.get("quantity", 1))
        product = Product.objects.get(pk=data.get("product_id"))  # deleted products can't be added
    except (ValueError, TypeError):
        return error("quantity must be an integer.")
    except Product.DoesNotExist:
        return error("Product not found.", 404)
    if quantity < 1:
        return error("quantity must be at least 1.")
 
    cart, _ = Cart.objects.get_or_create(user=request.user)
    item, created = CartItem.objects.get_or_create(cart=cart, product=product, defaults={"quantity": 0})
    item.quantity += quantity
    # Friendly early warning only. The REAL stock guarantee is in checkout().
    if item.quantity > product.stock:
        if created:
            item.delete()
        return error(f"Only {product.stock} in stock.", 409)
    item.save()
    return JsonResponse(cart_json(cart))
 
 
@customer_required
@require_http_methods(["POST"])
def cart_remove(request):
    """Body: {"product_id": 1}"""
    data = read_json(request) or {}
    cart, _ = Cart.objects.get_or_create(user=request.user)
    CartItem.objects.filter(cart=cart, product_id=data.get("product_id")).delete()
    return JsonResponse(cart_json(cart))


@customer_required
@require_http_methods(["POST"])
def cart_update(request):
    data = read_json(request)
    if data is None:
        return error("Invalid JSON.")
    try:
        quantity = int(data.get("quantity", 0))
        product_id = int(data.get("product_id"))
    except (TypeError, ValueError):
        return error("product_id and quantity must be integers.")
    cart = Cart.objects.filter(user=request.user).first()
    item = CartItem.objects.filter(cart=cart, product_id=product_id).first() if cart else None
    if item is None:
        return error("Cart item not found.", 404)
    if quantity < 1:
        item.delete()
    elif quantity > item.product.stock:
        return error(f"Only {item.product.stock} in stock.", 409)
    else:
        item.quantity = quantity
        item.save(update_fields=["quantity"])
    return JsonResponse(cart_json(cart))
 
 
# ═════════════════════════════════════════════════════════════════════════
# E. CHECKOUT - THE RACE-CONDITION-PROOF HEART OF THE PROJECT
# ═════════════════════════════════════════════════════════════════════════
class CheckoutError(Exception):
    """Raised for business-rule failures (empty cart, out of stock...)."""
    def __init__(self, messages):
        self.messages = messages if isinstance(messages, list) else [messages]
        super().__init__("; ".join(self.messages))
 
 
def place_order(user, shipping_address="", payment_method="COD", coupon=""):
    """
    THE PROBLEM (race condition):
        Only 1 phone left. Alice and Bob click "Buy" in the same millisecond.
        Both read stock=1, both think "ok", both subtract 1 -> stock = -1
        and we've sold something we don't have.
 
    THE FIX (pessimistic row-level locking):
        select_for_update() makes the database lock the product row until our
        transaction finishes. Bob's transaction WAITS at that line. When Alice
        commits (stock now 0), Bob's query finally runs, reads stock=0 and is
        correctly told "out of stock".
 
    Everything below is ONE atomic transaction: any failure rolls back ALL
    changes (no half-created orders, no stock deducted without an order).
    """
    with transaction.atomic():
        # Step 1: lock the user's cart row. This also blocks a double-click /
        # duplicate request from the same user creating two orders.
        cart = Cart.objects.select_for_update().filter(user=user).first()
        items = list(CartItem.objects.filter(cart=cart)) if cart else []
        if not items:
            raise CheckoutError("Your cart is empty.")
 
        # Step 2: lock every product being bought. Sorted by id so that two
        # checkouts always lock rows in the SAME order => no deadlocks.
        # We use all_objects because we want to detect soft-deleted products
        # explicitly and report them, not silently pretend they don't exist.
        product_ids = sorted(i.product_id for i in items)
        locked = {p.pk: p for p in
                  Product.all_objects.select_for_update().filter(pk__in=product_ids).order_by("pk")}
 
        # Step 3: validate against the LOCKED (fresh, trustworthy) numbers.
        problems = []
        for item in items:
            product = locked[item.product_id]
            if product.is_deleted:
                problems.append(f"'{product.name}' is no longer available.")
            elif product.stock < item.quantity:
                problems.append(f"Only {product.stock} of '{product.name}' left (you asked for {item.quantity}).")
        if problems:
            raise CheckoutError(problems)  # nothing was changed yet; the lock is released
 
        # Step 4: create the order, snapshot the prices, deduct stock.
        order = Order.objects.create(user=user, total_price=Decimal("0.00"),
                                     shipping_address=shipping_address, status=Order.Status.PENDING)
        subtotal = Decimal("0.00")
        for item in items:
            product = locked[item.product_id]
            OrderItem.objects.create(order=order, product=product, product_name=product.name,
                                     unit_price=product.price, quantity=item.quantity)
            product.stock -= item.quantity          # safe: we hold the lock
            product.save(update_fields=["stock", "updated_at"])
            subtotal += product.price * item.quantity

        code = str(coupon or "").strip().upper()
        if code and code != "SAVE10":
            raise CheckoutError("Invalid coupon code.")
        discount = (subtotal * Decimal("0.10")).quantize(Decimal("0.01")) if code else Decimal("0.00")
        total = subtotal - discount
        order.subtotal = subtotal
        order.discount = discount
        order.total_price = total
        order.save(update_fields=["subtotal", "discount", "total_price", "updated_at"])
 
        # Step 5: payment record (INITIATED until the gateway confirms) + empty the cart.
        Payment.objects.create(order=order, amount=total, method=payment_method)
        CartItem.objects.filter(cart=cart).delete()
        return order
    # Leaving the `with` block commits and releases all locks.
 
 
@customer_required
@require_http_methods(["POST"])
def checkout(request):
    """Body (optional): {"shipping_address": "...", "payment_method": "UPI"}"""
    data = read_json(request)
    if data is None:
        return error("Invalid JSON.")
    try:
        address = data.get("shipping_address") or json.dumps({
            "full_name": request.user.first_name, "email": request.user.email,
            "phone": request.user.phone, "alt_phone": request.user.alt_phone,
            "address_line1": request.user.address_line1, "address_line2": request.user.address_line2,
            "city": request.user.city, "state": request.user.state,
            "postal_code": request.user.postal_code, "country": request.user.country,
            "address_type": request.user.address_type, "delivery_notes": request.user.delivery_notes,
        })
        order = place_order(request.user, address, data.get("payment_method", "COD"), data.get("coupon", ""))
    except CheckoutError as exc:
        return error("Checkout failed.", 409, reasons=exc.messages)
    return JsonResponse(order_json(order), status=201)
 
 
# ═════════════════════════════════════════════════════════════════════════
# F. PAYMENT CONFIRMATION + ORDERS
# ═════════════════════════════════════════════════════════════════════════
@customer_required
@require_http_methods(["POST"])
def payment_confirm(request):
    """
    MOCK payment gateway callback. Body: {"transaction_id": "TXN-...", "success": true}
    In production this would be a signed webhook from Razorpay/Stripe.
    It is IDEMPOTENT: calling it twice never double-processes an order.
    """
    data = read_json(request) or {}
    with transaction.atomic():
        payment = (Payment.objects.select_for_update()
                   .filter(transaction_id=data.get("transaction_id"), order__user=request.user).first())
        if payment is None:
            return error("Payment not found.", 404)
        if payment.status != Payment.Status.INITIATED:
            return JsonResponse({"transaction_id": payment.transaction_id, "status": payment.status})
        if data.get("success"):
            payment.status = Payment.Status.SUCCESS
            Order.objects.filter(pk=payment.order_id, status=Order.Status.PENDING).update(
                status=Order.Status.PROCESSING)
        else:
            payment.status = Payment.Status.FAILED   # order stays PENDING; the customer can retry/cancel
        payment.save(update_fields=["status", "updated_at"])
    return JsonResponse({"transaction_id": payment.transaction_id, "status": payment.status})
 
 
@login_required_api
@require_http_methods(["GET"])
def order_list(request):
    """Customers see ONLY their own orders. Admins see everyone's (order history report)."""
    qs = Order.objects.prefetch_related("items", "payments")
    if not request.user.is_store_admin:
        qs = qs.filter(user=request.user)
    status = request.GET.get("status")
    if status:
        qs = qs.filter(status=status.upper())
    return JsonResponse({"orders": [order_json(o) for o in qs]})
 
 
@login_required_api
@require_http_methods(["GET"])
def order_detail(request, pk):
    qs = Order.objects.prefetch_related("items", "payments")
    if not request.user.is_store_admin:
        qs = qs.filter(user=request.user)   # someone else's order => 404, not 403 (don't leak existence)
    try:
        return JsonResponse(order_json(qs.get(pk=pk)))
    except Order.DoesNotExist:
        return error("Order not found.", 404)


@customer_required
@require_http_methods(["POST"])
def order_cancel(request, pk):
    with transaction.atomic():
        try:
            order = Order.objects.select_for_update().get(pk=pk, user=request.user)
        except Order.DoesNotExist:
            return error("Order not found.", 404)
        if not order.can_move_to(Order.Status.CANCELLED):
            return error(f"Cannot cancel an order in {order.status} status.", 409)
        items = list(order.items.all())
        locked = {
            product.pk: product
            for product in Product.all_objects.select_for_update()
            .filter(pk__in=sorted(item.product_id for item in items)).order_by("pk")
        }
        for item in items:
            locked[item.product_id].stock += item.quantity
            locked[item.product_id].save(update_fields=["stock", "updated_at"])
        order.status = Order.Status.CANCELLED
        order.save(update_fields=["status", "updated_at"])
    return JsonResponse(order_json(order))


@admin_required
@require_http_methods(["PATCH"])
def order_update_status(request, pk):
    """Admin moves an order along its lifecycle. Body: {"status": "SHIPPED"}.
    Cancelling puts the stock back (under the same row locks as checkout)."""
    data = read_json(request) or {}
    new_status = str(data.get("status", "")).upper()
    if new_status not in Order.Status.values:
        return error(f"status must be one of {Order.Status.values}.")
    with transaction.atomic():
        try:
            order = Order.objects.select_for_update().get(pk=pk)
        except Order.DoesNotExist:
            return error("Order not found.", 404)
        if not order.can_move_to(new_status):
            return error(f"Cannot move order from {order.status} to {new_status}.", 409)
        if new_status == Order.Status.CANCELLED:
            order_items = list(order.items.all())
            locked = {p.pk: p for p in Product.all_objects.select_for_update()
                      .filter(pk__in=sorted(i.product_id for i in order_items)).order_by("pk")}
            for item in order_items:
                locked[item.product_id].stock += item.quantity
                locked[item.product_id].save(update_fields=["stock", "updated_at"])
        order.status = new_status
        order.save(update_fields=["status", "updated_at"])
    return JsonResponse(order_json(order))
 