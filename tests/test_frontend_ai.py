import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
sys.path.insert(0, str(FRONTEND))

from main import DjangoStore, ShoppingAssistant  # noqa: E402


class FakeAPI:
    def __init__(self, orders=None):
        self.product = {
            "id": 1, "name": "Wireless Mouse", "category": "Electronics",
            "price": 20.0, "stock": 20, "description": "Wireless computer mouse",
        }
        self.added_items = []
        self._orders = orders or []

    def list_products(self, **_params):
        return {"products": [self.product]}

    def search_products(self, _query, **_params):
        return {"results": [{"product": self.product}], "did_you_mean": None}

    def recommend_products(self, _activity, _limit):
        return {"items": [{"product": self.product, "reason": "Similar to your recent views"}],
                "personalized": True}

    def add_cart_item(self, product_id, quantity):
        self.added_items.append((product_id, quantity))

    def product_reviews(self, _product_id):
        return {"reviews": [], "avg_rating": 0, "count": 0, "hist": {}}

    def review_sentiment(self, _product_id):
        return {"count": 1, "praise": [{"text": "Quiet clicks"}], "complaints": []}

    def orders(self):
        return self._orders

    def get(self, path):
        assert path == "reviews/"
        return {"reviews": []}


def _order(order_id, total, quantity, when):
    return {
        "id": order_id,
        "user": f"customer-{order_id}",
        "status": "PENDING",
        "total_price": str(total),
        "subtotal": str(total),
        "discount": "0",
        "date": when.isoformat(),
        "ship_to": {"address_line1": "1 Main Street", "postal_code": "10001"},
        "items": [{
            "product_id": 1, "name": "Wireless Mouse", "unit_price": "10",
            "quantity": quantity,
        }],
        "payments": [{
            "amount": str(total), "method": "Cash on Delivery",
            "status": "INITIATED", "date": when.isoformat(),
        }],
    }


def test_assistant_uses_backend_search_recommendations_and_cart():
    store = DjangoStore()
    store.api = FakeAPI()
    store.products = {1: store.api.product}
    store.current_username = "alice"
    bot = ShoppingAssistant(store, "alice", currency="₹")

    search = bot.reply("wireless mouse")
    assert search["products"][0]["id"] == 1

    recommendation = bot.reply("recommend something for me")
    assert recommendation["products"][0]["id"] == 1
    assert "Picks for you" in recommendation["text"]

    review = bot.reply("reviews of wireless mouse")
    assert "Customers say: Quiet clicks" in review["text"]

    bot.reply("add the first one to my cart")
    confirmed = bot.reply("yes")
    assert confirmed["action"] == {"type": "cart_updated"}
    assert store.api.added_items == [(1, 1)]


def test_admin_report_runs_fraud_detection_and_demand_forecast():
    now = datetime.now(timezone.utc)
    orders = [
        _order(i, 10, 1, now - timedelta(days=i))
        for i in range(1, 6)
    ]
    orders.append(_order(6, 1000, 5, now))

    store = DjangoStore()
    store.api = FakeAPI(orders)
    store.products = {1: {
        "id": 1, "name": "Wireless Mouse", "category": "Electronics",
        "price": 10.0, "stock": 1, "description": "",
    }}
    report = store.report()

    assert "T" not in store.orders[-1]["payments"][0]["date"]
    assert report["fraud_risks"]
    assert report["fraud_risks"][0]["order_id"] == 6
    assert report["fraud_risks"][0]["score"] >= 30
    assert report["forecast"][0]["product"]["id"] == 1
    assert report["forecast"][0]["status"] == "Restock now"
