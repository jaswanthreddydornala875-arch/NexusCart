"""Session-aware REST client for the NexusCart Django API."""
from http.cookiejar import CookieJar
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener


class APIError(RuntimeError):
    pass


class APIClient:
    def __init__(self, base_url=None, timeout=8):
        self.base_url = (base_url or os.getenv(
            "NEXUSCART_API_URL", "http://127.0.0.1:8000/api"
        )).rstrip("/")
        self.timeout = timeout
        self.cookies = CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.cookies))

    def _csrf_token(self):
        return next((cookie.value for cookie in self.cookies if cookie.name == "csrftoken"), None)

    def request(self, method, path, data=None, params=None):
        method = method.upper()
        if method not in {"GET", "HEAD", "OPTIONS", "TRACE"} and not self._csrf_token():
            self.get("csrf/")
        url = f"{self.base_url}/{path.lstrip('/')}"
        if params:
            from urllib.parse import urlencode
            url += "?" + urlencode(params)
        body = None if data is None else json.dumps(data).encode("utf-8")
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        csrf = self._csrf_token()
        if csrf and method not in {"GET", "HEAD", "OPTIONS", "TRACE"}:
            headers["X-CSRFToken"] = csrf
        req = Request(url, data=body, headers=headers, method=method)
        try:
            with self.opener.open(req, timeout=self.timeout) as response:
                raw = response.read()
                if not raw:
                    return None
                try:
                    return json.loads(raw.decode("utf-8"))
                except json.JSONDecodeError:
                    return raw.decode("utf-8", errors="replace")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            try:
                detail = json.loads(detail)
            except json.JSONDecodeError:
                pass
            raise APIError(f"API returned HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise APIError(f"Cannot connect to NexusCart API at {self.base_url}: {exc.reason}") from exc

    def get(self, path, params=None):
        return self.request("GET", path, params=params)

    def post(self, path, data=None):
        return self.request("POST", path, data=data)

    def put(self, path, data=None):
        return self.request("PUT", path, data=data)

    def patch(self, path, data=None):
        return self.request("PATCH", path, data=data)

    def delete(self, path, params=None):
        return self.request("DELETE", path, params=params)

    def login(self, username, password):
        return self.post("auth/login/", {"username": username, "password": password})

    def register(self, username, password, full_name="", email="", phone=""):
        return self.post("auth/register/", {
            "username": username, "password": password, "full_name": full_name,
            "email": email, "phone": phone,
        })

    def list_products(self, search=None, category=None, sort=None):
        params = {k: v for k, v in {"q": search, "category": category, "sort": sort}.items() if v}
        return self.get("products/", params=params)

    def search_products(self, query, category=None, limit=10, in_stock=False):
        params = {"q": query, "limit": limit}
        if category:
            params["category"] = category
        if in_stock:
            params["in_stock"] = "1"
        return self.get("products/search/", params=params)

    def recommend_products(self, activity, limit=6):
        return self.post_with_params("recommendations/", activity, {"k": limit})

    def post_with_params(self, path, data, params):
        return self.request("POST", path, data=data, params=params)

    def review_sentiment(self, product_id):
        return self.get(f"products/{int(product_id)}/sentiment/")

    def get_profile(self):
        return self.get("profile/")

    def save_profile(self, data):
        return self.patch("profile/", data)

    def get_activity(self):
        return self.get("activity/")

    def record_activity(self, kind, **data):
        return self.post("activity/", {"kind": kind, **data})

    def clear_activity(self, kind="search", query=None):
        params = {"kind": kind}
        if query is not None:
            params["q"] = query
        return self.delete("activity/", params=params)

    def cart(self):
        return self.get("cart/")

    def add_cart_item(self, product_id, quantity):
        return self.post("cart/add/", {"product_id": product_id, "quantity": quantity})

    def update_cart_item(self, product_id, quantity):
        return self.post("cart/update/", {"product_id": product_id, "quantity": quantity})

    def remove_cart_item(self, product_id):
        return self.post("cart/remove/", {"product_id": product_id})

    def checkout(self, coupon, payment_method):
        return self.post("checkout/", {"coupon": coupon, "payment_method": payment_method})

    def orders(self):
        return self.get("orders/")["orders"]

    def cancel_order(self, order_id):
        return self.post(f"orders/{int(order_id)}/cancel/", {})

    def set_order_status(self, order_id, status):
        return self.patch(f"orders/{int(order_id)}/status/", {"status": status})

    def product_reviews(self, product_id):
        return self.get(f"products/{int(product_id)}/reviews/")

    def save_review(self, product_id, rating, title, text):
        return self.post(f"products/{int(product_id)}/reviews/", {
            "rating": rating, "title": title, "text": text,
        })

    def delete_review(self, review_id):
        return self.delete(f"reviews/{int(review_id)}/")

    def create_product(self, product):
        return self.post("products/", product)

    def update_product(self, product_id, product):
        return self.patch(f"products/{int(product_id)}/", product)

    def delete_product(self, product_id):
        return self.delete(f"products/{int(product_id)}/")
