"""Build AI engines from the storefront catalog, with synthetic data as a demo fallback."""
import csv
import os
import sys
from functools import lru_cache
from types import SimpleNamespace

if __package__:
    from . import sample_data
    from .recommender import HybridRecommender, activity_from_interactions
    from .sentiment import SentimentAnalyzer
    from .smart_search import SmartSearch
else:
    sys.path.insert(0, os.path.dirname(__file__))
    import sample_data
    from recommender import HybridRecommender, activity_from_interactions
    from sentiment import SentimentAnalyzer
    from smart_search import SmartSearch


def _catalog_path():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "database", "products.csv"))


def _load_catalog(path):
    if not os.path.isfile(path):
        return []
    products = []
    try:
        with open(path, newline="", encoding="utf-8-sig") as catalog_file:
            for row in csv.DictReader(catalog_file):
                name = (row.get("name") or "").strip()
                if not name:
                    continue
                product_id = len(products) + 1
                products.append({
                    "id": product_id,
                    "name": name,
                    "category": (row.get("category") or "General").strip(),
                    "price": float(row.get("price") or 0),
                    "stock": int(float(row.get("stock") or 0)),
                    "description": (row.get("description") or "").strip(),
                    "image": (row.get("image_path") or row.get("image") or "").strip(),
                })
    except (OSError, TypeError, ValueError, csv.Error):
        return []
    return products


@lru_cache(maxsize=2)
def _build_engines(path, modified_ns, size):
    products = _load_catalog(path)
    if products:
        reviews, interactions = [], []
    else:
        products, reviews, interactions = sample_data.load()
    ratings = {}
    for r in reviews:
        ratings.setdefault(r["product_id"], []).append(r["rating"])
    ratings = {pid: sum(v) / len(v) for pid, v in ratings.items()}
    return SimpleNamespace(
        products={p["id"]: p for p in products},
        reviews=reviews,
        interactions=interactions,
        search=SmartSearch(products),
        sentiment=SentimentAnalyzer(),
        recommender=HybridRecommender(products, interactions, ratings),
    )


def get_engines():
    path = _catalog_path()
    try:
        stat = os.stat(path)
        signature = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        signature = (0, 0)
    return _build_engines(path, *signature)


def demo_activity(user_number):
    """Activity of demo shopper u001, u002 ... for trying the recommender."""
    uid = f"u{int(user_number):03d}"
    items = [(pid, kind) for u, pid, kind in get_engines().interactions if u == uid]
    return activity_from_interactions(items)
