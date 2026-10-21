"""
NexusCart - admin.py
Author: Ishant Birra
 
Django's admin site is our ready-made back office. Here we customise it and,
most importantly, make Product deletion SOFT so order history is never broken.
"""
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
 
from .models import Cart, CartItem, Order, OrderItem, Payment, Product, User
 
 
# ─────────────────────────── Users ───────────────────────────
@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """Built-in user admin + the `role` column/field."""
    list_display = ("username", "email", "role", "is_active", "date_joined")
    list_filter = ("role", "is_active")
    fieldsets = DjangoUserAdmin.fieldsets + (("NexusCart access", {"fields": ("role",)}),)
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (("NexusCart access", {"fields": ("role",)}),)
 
 
# ─────────────────────────── Products (SOFT DELETE) ───────────────────────────
@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "price", "stock", "is_deleted", "updated_at")
    list_filter = ("is_deleted",)
    search_fields = ("name",)
    readonly_fields = ("deleted_at", "created_at", "updated_at")
    actions = ["soft_delete_selected", "restore_selected"]
 
    def get_queryset(self, request):
        # Product.objects hides deleted rows; the admin needs to SEE them
        # (to restore them), so we use the unfiltered manager here.
        return Product.all_objects.all()
 
    # ---- Remove Django's built-in "Delete selected" (hard delete) action ----
    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions
 
    # ---- Our replacement bulk action ----
    @admin.action(description="Soft delete selected products (keeps order history)")
    def soft_delete_selected(self, request, queryset):
        count = queryset.filter(is_deleted=False).delete()  # QuerySet.delete() is soft (see models.py)
        self.message_user(request, f"{count} product(s) soft-deleted.", messages.SUCCESS)
 
    @admin.action(description="Restore selected products")
    def restore_selected(self, request, queryset):
        count = queryset.filter(is_deleted=True).restore()
        self.message_user(request, f"{count} product(s) restored.", messages.SUCCESS)
 
    # ---- The red "Delete" button on a single product page ----
    def delete_model(self, request, obj):
        obj.delete()  # Product.delete() sets is_deleted=True; no SQL DELETE ever runs
 
    def delete_queryset(self, request, queryset):
        queryset.delete()  # soft, via ProductQuerySet.delete()
 
    def get_deleted_objects(self, objs, request):
        # Django's confirmation page would otherwise say "can't delete, this
        # product is protected by existing order items". Since our delete is
        # soft, there is nothing to protect against, so we skip that check.
        return ([f"Product: {o}" for o in objs], {}, set(), [])
 
 
# ─────────────────────────── Carts ───────────────────────────
class CartItemInline(admin.TabularInline):
    model = CartItem
    extra = 0
 
 
@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ("user", "updated_at")
    inlines = [CartItemInline]
 
 
# ─────────────────────────── Orders & Payments (history is protected) ───────────────────────────
class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    can_delete = False
    readonly_fields = ("product", "product_name", "unit_price", "quantity")
 
    def has_add_permission(self, request, obj=None):
        return False
 
 
class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    can_delete = False
    readonly_fields = ("transaction_id", "amount", "method", "status", "created_at")
 
    def has_add_permission(self, request, obj=None):
        return False
 
 
@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "status", "total_price", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("user__username", "id")
    readonly_fields = ("user", "total_price", "created_at", "updated_at")
    inlines = [OrderItemInline, PaymentInline]
 
    def has_delete_permission(self, request, obj=None):
        return False  # orders are financial records: cancel them, never delete them
 
 
@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("transaction_id", "order", "amount", "method", "status", "created_at")
    list_filter = ("status", "method")
    search_fields = ("transaction_id",)
    readonly_fields = ("transaction_id", "order", "amount", "created_at", "updated_at")
 
    def has_delete_permission(self, request, obj=None):
        return False
 