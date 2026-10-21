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
 
from .models import Cart, CartItem, Order, OrderItem, Payment, Product, User
 
 
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
    return {"id": p.id, "name": p.name, "description": p.description,
            "price": str(p.price), "stock": p.stock, "is_deleted": p.is_deleted}
 
 
def order_json(o):
    return {
        "id": o.id, "status": o.status, "total_price": str(o.total_price),
        "shipping_address": o.shipping_address, "created_at": o.created_at.isoformat(),
        "items": [{"product_id": i.product_id, "name": i.product_name,
                   "unit_price": str(i.unit_price), "quantity": i.quantity,
                   "line_total": str(i.line_total)} for i in o.items.all()],
        "payments": [{"transaction_id": p.transaction_id, "amount": str(p.amount),
                      "method": p.method, "status": p.status} for p in o.payments.all()],
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
    return JsonResponse({"id": user.id, "username": user.username, "role": user.role}, status=201)
 
 
@require_http_methods(["POST"])
def login_view(request):
    data = read_json(request) or {}
    user = authenticate(request, username=data.get("username"), password=data.get("password"))
    if user is None:
        return error("Invalid credentials.", 401)
    login(request, user)
    return JsonResponse({"id": user.id, "username": user.username, "role": user.role})
 
 
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
            qs = qs.filter(name__icontains=q)
        return JsonResponse({"products": [product_json(p) for p in qs]})
    return _product_create(request)
 
 
@admin_required
def _product_create(request):
    data = read_json(request)
    if data is None:
        return error("Invalid JSON.")
    try:
        product = Product(name=data.get("name", ""), description=data.get("description", ""),
                          price=Decimal(str(data.get("price", ""))), stock=int(data.get("stock", 0)))
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
            for field in ("name", "description"):
                if field in data:
                    setattr(product, field, data[field])
            if "price" in data:
                product.price = Decimal(str(data["price"]))
            if "stock" in data:
                product.stock = int(data["stock"])
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
 
 
# ═════════════════════════════════════════════════════════════════════════
# D. CART
# ═════════════════════════════════════════════════════════════════════════
def cart_json(cart):
    items = cart.items.select_related("product")
    return {"items": [{"product_id": i.product_id, "name": i.product.name,
                       "unit_price": str(i.product.price), "quantity": i.quantity,
                       "line_total": str(i.line_total)} for i in items],
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
 
 
# ═════════════════════════════════════════════════════════════════════════
# E. CHECKOUT - THE RACE-CONDITION-PROOF HEART OF THE PROJECT
# ═════════════════════════════════════════════════════════════════════════
class CheckoutError(Exception):
    """Raised for business-rule failures (empty cart, out of stock...)."""
    def __init__(self, messages):
        self.messages = messages if isinstance(messages, list) else [messages]
        super().__init__("; ".join(self.messages))
 
 
def place_order(user, shipping_address="", payment_method="COD"):
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
        total = Decimal("0.00")
        for item in items:
            product = locked[item.product_id]
            OrderItem.objects.create(order=order, product=product, product_name=product.name,
                                     unit_price=product.price, quantity=item.quantity)
            product.stock -= item.quantity          # safe: we hold the lock
            product.save(update_fields=["stock", "updated_at"])
            total += product.price * item.quantity
 
        order.total_price = total
        order.save(update_fields=["total_price", "updated_at"])
 
        # Step 5: payment record (INITIATED until the gateway confirms) + empty the cart.
        Payment.objects.create(order=order, amount=total, method=payment_method)
        CartItem.objects.filter(cart=cart).delete()
        return order
    # Leaving the `with` block commits and releases all locks.
 
 
@customer_required
@require_http_methods(["POST"])
def checkout(request):
    """Body (optional): {"shipping_address": "...", "payment_method": "UPI"}"""
    data = read_json(request) or {}
    try:
        order = place_order(request.user, data.get("shipping_address", ""), data.get("payment_method", "COD"))
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
 