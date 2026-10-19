"""Small standard-library REST client for the NexusCart Flask API.

This client is separated from the Tkinter UI so it can be wired into the store
service adapter as backend routes are finalized. It does not silently fall back
to mock data when a request fails.
"""
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class APIError(RuntimeError):
    pass


class APIClient:
    def __init__(self, base_url=None, timeout=8):
        self.base_url = (base_url or os.getenv("NEXUSCART_API_URL", "http://127.0.0.1:5000/api")).rstrip("/")
        self.timeout = timeout
        self.token = None

    def request(self, method, path, data=None, params=None):
        path = path.lstrip("/")
        url = f"{self.base_url}/{path}"
        if params:
            from urllib.parse import urlencode
            url += "?" + urlencode(params)
        body = None if data is None else json.dumps(data).encode("utf-8")
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = Request(url, data=body, headers=headers, method=method.upper())
        try:
            with urlopen(req, timeout=self.timeout) as response:
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

    def delete(self, path):
        return self.request("DELETE", path)

    def login(self, username, password):
        result = self.post("auth/login", {"username": username, "password": password})
        if isinstance(result, dict):
            self.token = result.get("access_token") or result.get("token")
        return result

    def list_products(self, search=None, category=None, sort=None):
        params = {k: v for k, v in {"search": search, "category": category, "sort": sort}.items() if v}
        return self.get("products", params=params)

    def search_products(self, query, category=None, limit=10, in_stock=False):
        params = {"q": query, "limit": limit}
        if category:
            params["category"] = category
        if in_stock:
            params["in_stock"] = "1"
        return self.get("products/search", params=params)

    def recommend_products(self, activity, limit=6):
        return self.request("POST", "recommendations/", data=activity, params={"k": limit})

    def review_sentiment(self, product_id):
        return self.get(f"reviews/sentiment/{int(product_id)}")
