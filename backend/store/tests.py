"""
NexusCart - tests.py
Run with:  python manage.py test store -v 2
(The concurrency test needs PostgreSQL/MySQL: SQLite has no row locks, so it
is skipped there.)
"""
import threading
from decimal import Decimal
 
from django.db import connection
from django.test import Client, TestCase, TransactionTestCase, skipUnlessDBFeature
 
from .models import Cart, CartItem, Order, Product, User
from .views import CheckoutError, place_order
 
 
def make_users():
    admin = User.objects.create_user("boss", password="Str0ng!pass#1", role=User.Role.ADMIN)
    cust = User.objects.create_user("alice", password="Str0ng!pass#1")
    return admin, cust
 
 
class SoftDeleteTests(TestCase):
    def test_default_manager_hides_deleted_but_all_objects_sees_it(self):
        p = Product.objects.create(name="Phone", price=Decimal("100"), stock=5)
        p.delete()
        self.assertEqual(Product.objects.count(), 0)
        self.assertEqual(Product.all_objects.count(), 1)   # row still in the DB
 
    def test_queryset_delete_is_also_soft(self):
        Product.objects.create(name="A", price=Decimal("1"), stock=1)
        Product.objects.all().delete()
        self.assertEqual(Product.all_objects.filter(is_deleted=True).count(), 1)
 
    def test_old_orders_survive_product_deletion(self):
        _, cust = make_users()
        p = Product.objects.create(name="Phone", price=Decimal("100"), stock=5)
        cart = Cart.objects.create(user=cust)
        CartItem.objects.create(cart=cart, product=p, quantity=2)
        order = place_order(cust)
        p.delete()
        order.refresh_from_db()
        self.assertEqual(order.items.first().product_name, "Phone")
        self.assertEqual(order.total_price, Decimal("200.00"))
 
 
class CheckoutTests(TestCase):
    def setUp(self):
        _, self.cust = make_users()
        self.product = Product.objects.create(name="Phone", price=Decimal("100"), stock=1)
        self.cart = Cart.objects.create(user=self.cust)
 
    def test_successful_checkout_deducts_stock_and_clears_cart(self):
        CartItem.objects.create(cart=self.cart, product=self.product, quantity=1)
        order = place_order(self.cust)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 0)
        self.assertEqual(order.status, Order.Status.PENDING)
        self.assertEqual(order.payments.count(), 1)
        self.assertEqual(self.cart.items.count(), 0)
 
    def test_cannot_buy_more_than_stock_and_nothing_changes(self):
        CartItem.objects.create(cart=self.cart, product=self.product, quantity=2)
        with self.assertRaises(CheckoutError):
            place_order(self.cust)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 1)          # rolled back / untouched
        self.assertEqual(Order.objects.count(), 0)
 
    def test_last_item_second_buyer_is_rejected(self):
        bob = User.objects.create_user("bob", password="Str0ng!pass#1")
        for u in (self.cust, bob):
            CartItem.objects.create(cart=Cart.objects.get_or_create(user=u)[0], product=self.product, quantity=1)
        place_order(self.cust)
        with self.assertRaises(CheckoutError):
            place_order(bob)
 
    def test_soft_deleted_product_cannot_be_checked_out(self):
        CartItem.objects.create(cart=self.cart, product=self.product, quantity=1)
        self.product.delete()
        with self.assertRaises(CheckoutError):
            place_order(self.cust)
 
 
class RBACTests(TestCase):
    def setUp(self):
        self.admin, self.cust = make_users()
        self.product = Product.objects.create(name="Phone", price=Decimal("100"), stock=3)
 
    def client_for(self, user=None):
        c = Client(enforce_csrf_checks=False)
        if user:
            c.force_login(user)
        return c
 
    def test_anonymous_can_view_products_but_not_create(self):
        c = self.client_for()
        self.assertEqual(c.get("/api/products/").status_code, 200)
        r = c.post("/api/products/", {"name": "X", "price": "5", "stock": 1}, content_type="application/json")
        self.assertEqual(r.status_code, 401)
 
    def test_customer_cannot_write_products(self):
        c = self.client_for(self.cust)
        body = {"name": "X", "price": "5", "stock": 1}
        self.assertEqual(c.post("/api/products/", body, content_type="application/json").status_code, 403)
        self.assertEqual(c.patch(f"/api/products/{self.product.id}/", {"price": "1"}, content_type="application/json").status_code, 403)
        self.assertEqual(c.delete(f"/api/products/{self.product.id}/").status_code, 403)
 
    def test_admin_can_create_update_and_soft_delete(self):
        c = self.client_for(self.admin)
        r = c.post("/api/products/", {"name": "TV", "price": "999.50", "stock": 4}, content_type="application/json")
        self.assertEqual(r.status_code, 201)
        pid = r.json()["id"]
        self.assertEqual(c.patch(f"/api/products/{pid}/", {"stock": 10}, content_type="application/json").json()["stock"], 10)
        self.assertEqual(c.delete(f"/api/products/{pid}/").status_code, 200)
        self.assertTrue(Product.all_objects.get(pk=pid).is_deleted)
        self.assertEqual(c.get(f"/api/products/{pid}/").status_code, 404)
 
    def test_admin_cannot_place_orders_and_customer_cannot_change_status(self):
        self.assertEqual(self.client_for(self.admin).post("/api/checkout/", {}, content_type="application/json").status_code, 403)
        self.assertEqual(self.client_for(self.cust).patch("/api/orders/1/status/", {"status": "SHIPPED"}, content_type="application/json").status_code, 403)
 
    def test_register_always_creates_customer(self):
        r = Client().post("/api/auth/register/", {"username": "eve", "password": "Str0ng!pass#1", "role": "ADMIN"},
                          content_type="application/json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["role"], "CUSTOMER")
 
    def test_full_api_flow_and_cancel_restocks(self):
        c = self.client_for(self.cust)
        c.post("/api/cart/add/", {"product_id": self.product.id, "quantity": 2}, content_type="application/json")
        r = c.post("/api/checkout/", {"shipping_address": "Chennai"}, content_type="application/json")
        self.assertEqual(r.status_code, 201)
        oid, txn = r.json()["id"], r.json()["payments"][0]["transaction_id"]
        self.product.refresh_from_db(); self.assertEqual(self.product.stock, 1)
        # pay (twice => idempotent)
        for _ in range(2):
            c.post("/api/payments/confirm/", {"transaction_id": txn, "success": True}, content_type="application/json")
        self.assertEqual(Order.objects.get(pk=oid).status, "PROCESSING")
        # customer sees only own orders; admin cancels -> stock returns
        self.assertEqual(len(c.get("/api/orders/").json()["orders"]), 1)
        a = self.client_for(self.admin)
        self.assertEqual(a.patch(f"/api/orders/{oid}/status/", {"status": "CANCELLED"}, content_type="application/json").status_code, 200)
        self.product.refresh_from_db(); self.assertEqual(self.product.stock, 3)
        self.assertEqual(a.patch(f"/api/orders/{oid}/status/", {"status": "SHIPPED"}, content_type="application/json").status_code, 409)
 
 
class AdminSiteTests(TestCase):
    def test_admin_delete_button_is_soft_even_for_products_in_orders(self):
        su = User.objects.create_superuser("root", password="Str0ng!pass#1")
        _, cust = make_users()
        p = Product.objects.create(name="Phone", price=Decimal("100"), stock=5)
        CartItem.objects.create(cart=Cart.objects.create(user=cust), product=p, quantity=1)
        place_order(cust)
        c = Client(); c.force_login(su)
        self.assertEqual(c.get(f"/admin/store/product/{p.pk}/delete/").status_code, 200)
        c.post(f"/admin/store/product/{p.pk}/delete/", {"post": "yes"})
        self.assertTrue(Product.all_objects.get(pk=p.pk).is_deleted)
        # bulk action path
        p2 = Product.objects.create(name="B", price=Decimal("1"), stock=1)
        c.post("/admin/store/product/", {"action": "soft_delete_selected", "_selected_action": [p2.pk]})
        self.assertTrue(Product.all_objects.get(pk=p2.pk).is_deleted)
 
 
@skipUnlessDBFeature("has_select_for_update")
class ConcurrencyTests(TransactionTestCase):
    """10 customers fight for 3 items at the same instant. Exactly 3 must win."""
    def test_no_overselling_under_concurrency(self):
        product = Product.objects.create(name="Last items", price=Decimal("10"), stock=3)
        users = [User.objects.create_user(f"u{i}", password="x") for i in range(10)]
        for u in users:
            CartItem.objects.create(cart=Cart.objects.create(user=u), product=product, quantity=1)
        results, barrier = [], threading.Barrier(10)
 
        def buy(u):
            try:
                barrier.wait()
                place_order(u); results.append("ok")
            except CheckoutError:
                results.append("rejected")
            finally:
                connection.close()
 
        threads = [threading.Thread(target=buy, args=(u,)) for u in users]
        [t.start() for t in threads]; [t.join() for t in threads]
        product.refresh_from_db()
        self.assertEqual(results.count("ok"), 3)
        self.assertEqual(product.stock, 0)
 