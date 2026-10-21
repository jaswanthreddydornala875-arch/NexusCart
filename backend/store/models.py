"""
NexusCart - models.py
Author: Ishant Birra (Backend & Database Architecture Lead)

DATABASE DESIGN AT A GLANCE
---------------------------
User ──1:1── Cart ──1:N── CartItem ──N:1── Product
User ──1:N── Order ──1:N── OrderItem ──N:1── Product
Order ──1:N── Payment

Three enterprise ideas live in this file:
  1. SOFT DELETE    -> Product.is_deleted + a manager that hides deleted rows.
  2. RBAC           -> User.role (ADMIN / CUSTOMER), checked in views.py.
  3. STOCK SAFETY   -> stock is a PositiveIntegerField (the DB itself refuses
                       negative numbers); the row locking that prevents
                       overselling lives in views.checkout().
"""
import uuid
from decimal import Decimal

from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


def _new_sku() -> str:
    return "NC-" + uuid.uuid4().hex[:12].upper()


# ═════════════════════════════════════════════════════════════════════════
# 1. USER + ROLE-BASED ACCESS CONTROL
# ═════════════════════════════════════════════════════════════════════════
class User(AbstractUser):
    """
    We extend Django's built-in user (keeps hashed passwords, login,
    sessions, admin integration) and add ONE field: `role`.

    IMPORTANT: settings.py must contain  AUTH_USER_MODEL = "store.User"
    *before* the first migration is run.
    """

    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Admin"
        CUSTOMER = "CUSTOMER", "Customer"

    role = models.CharField(max_length=10, choices=Role.choices, default=Role.CUSTOMER)
    phone = models.CharField(max_length=30, blank=True)
    alt_phone = models.CharField(max_length=30, blank=True)
    address_line1 = models.CharField(max_length=200, blank=True)
    address_line2 = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=60, blank=True)
    address_type = models.CharField(max_length=10, default="Home")
    delivery_notes = models.CharField(max_length=300, blank=True)

    @property
    def is_store_admin(self) -> bool:
        """True only for active users whose role is ADMIN. Views use this."""
        return self.is_active and self.role == self.Role.ADMIN

    def save(self, *args, **kwargs):
        # A superuser made with `createsuperuser` is always a store admin.
        if self.is_superuser:
            self.role = self.Role.ADMIN
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.username} ({self.role})"


# ═════════════════════════════════════════════════════════════════════════
# 2. PRODUCT WITH SOFT DELETE
# ═════════════════════════════════════════════════════════════════════════
class ProductQuerySet(models.QuerySet):
    """
    Overrides bulk .delete() so that  Product.objects.filter(...).delete()
    also performs a SOFT delete. Nobody can wipe data by accident.
    """

    def delete(self):
        return self.update(is_deleted=True, deleted_at=timezone.now())

    def hard_delete(self):
        """Real SQL DELETE. Only for maintenance scripts, never for views."""
        return super().delete()

    def restore(self):
        return self.update(is_deleted=False, deleted_at=None)


class ActiveProductManager(models.Manager.from_queryset(ProductQuerySet)):
    """
    The DEFAULT manager (`Product.objects`). It automatically hides deleted
    products, so the storefront never needs to remember `is_deleted=False`.
    """

    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False, is_active=True)


class Product(models.Model):
    sku = models.CharField(max_length=40, unique=True, default=_new_sku)
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=60, default="General", db_index=True)
    brand = models.CharField(max_length=80, blank=True)
    description = models.TextField(blank=True)
    price = models.DecimalField(
        max_digits=10, decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],  # money => Decimal, never float
    )
    # PositiveIntegerField => the database adds CHECK (stock >= 0). Even if
    # a bug slipped through our Python code, the DB would refuse negative stock.
    stock = models.PositiveIntegerField(default=0)
    image_path = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    # --- soft delete fields ---
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ActiveProductManager()            # active products only (default)
    all_objects = ProductQuerySet.as_manager()  # everything, incl. deleted (admin, checkout, history)

    class Meta:
        ordering = ["name"]

    def delete(self, using=None, keep_parents=False):
        """Soft delete: flag the row instead of removing it, so old orders
        that reference this product keep working."""
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=["is_deleted", "deleted_at", "updated_at"])

    def restore(self):
        self.is_deleted = False
        self.deleted_at = None
        self.save(update_fields=["is_deleted", "deleted_at", "updated_at"])

    def __str__(self):
        return f"{self.name}{' [deleted]' if self.is_deleted else ''}"


class Review(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="reviews")
    user = models.ForeignKey("store.User", on_delete=models.CASCADE, related_name="reviews")
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])
    title = models.CharField(max_length=150, blank=True)
    text = models.TextField(blank=True)
    verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["product", "user"], name="uniq_review_per_user_product"),
            models.CheckConstraint(condition=models.Q(rating__gte=1, rating__lte=5),
                                   name="ck_review_rating_range"),
        ]
        ordering = ["-created_at"]


class ShopperActivity(models.Model):
    class Kind(models.TextChoices):
        SEARCH = "search", "Search"
        VIEW = "view", "Product view"

    user = models.ForeignKey("store.User", on_delete=models.CASCADE, related_name="shopper_activity")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    product = models.ForeignKey(Product, null=True, blank=True, on_delete=models.SET_NULL)
    query = models.CharField(max_length=250, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


# ═════════════════════════════════════════════════════════════════════════
# 3. CART
# ═════════════════════════════════════════════════════════════════════════
class Cart(models.Model):
    """One cart per user (OneToOne). Created lazily on first 'add to cart'."""
    user = models.OneToOneField("store.User", on_delete=models.CASCADE, related_name="cart")
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def total(self) -> Decimal:
        return sum((i.line_total for i in self.items.all()), Decimal("0.00"))

    def __str__(self):
        return f"Cart of {self.user.username}"


class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])

    class Meta:
        # Same product twice in one cart => one row with a bigger quantity.
        constraints = [models.UniqueConstraint(fields=["cart", "product"], name="uniq_product_per_cart")]

    @property
    def line_total(self) -> Decimal:
        return self.product.price * self.quantity

    def __str__(self):
        return f"{self.quantity} x {self.product.name}"


# ═════════════════════════════════════════════════════════════════════════
# 4. ORDERS
# ═════════════════════════════════════════════════════════════════════════
class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PROCESSING = "PROCESSING", "Processing"
        SHIPPED = "SHIPPED", "Shipped"
        DELIVERED = "DELIVERED", "Delivered"
        CANCELLED = "CANCELLED", "Cancelled"

    # Order lifecycle rules: which status may follow which.
    ALLOWED_TRANSITIONS = {
        Status.PENDING: {Status.PROCESSING, Status.CANCELLED},
        Status.PROCESSING: {Status.SHIPPED, Status.CANCELLED},
        Status.SHIPPED: {Status.DELIVERED},
        Status.DELIVERED: set(),
        Status.CANCELLED: set(),
    }

    # PROTECT: a user who has orders can't be hard-deleted (keeps history).
    user = models.ForeignKey("store.User", on_delete=models.PROTECT, related_name="orders")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    total_price = models.DecimalField(max_digits=12, decimal_places=2)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    shipping_address = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def can_move_to(self, new_status: str) -> bool:
        return new_status in self.ALLOWED_TRANSITIONS.get(self.status, set())

    def __str__(self):
        return f"Order #{self.pk} - {self.status}"


class OrderItem(models.Model):
    """
    SNAPSHOT pattern: we copy the product name and price at purchase time.
    If the price changes or the product is soft-deleted later, the old
    order still shows exactly what the customer bought and paid.
    """
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    # PROTECT: Django refuses to hard-delete a product that appears in an order.
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="order_items")
    product_name = models.CharField(max_length=200)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])

    @property
    def line_total(self) -> Decimal:
        return self.unit_price * self.quantity

    def __str__(self):
        return f"{self.quantity} x {self.product_name}"


# ═════════════════════════════════════════════════════════════════════════
# 5. PAYMENT
# ═════════════════════════════════════════════════════════════════════════
def _new_transaction_id() -> str:
    return "TXN-" + uuid.uuid4().hex[:16].upper()


class Payment(models.Model):
    class Status(models.TextChoices):
        INITIATED = "INITIATED", "Initiated"
        SUCCESS = "SUCCESS", "Success"
        FAILED = "FAILED", "Failed"
        REFUNDED = "REFUNDED", "Refunded"

    # ForeignKey (not OneToOne): a failed payment can be retried, giving
    # several Payment rows for the same order.
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="payments")
    transaction_id = models.CharField(max_length=40, unique=True, default=_new_transaction_id)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(max_length=30, default="COD")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.INITIATED)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.transaction_id} ({self.status})"