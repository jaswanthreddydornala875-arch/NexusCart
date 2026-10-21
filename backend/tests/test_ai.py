import warnings

import pytest

from app import create_app
from app.ai import sample_data
from app.ai import engines
from app.ai.engines import demo_activity, get_engines
from app.ai.recommender import HybridRecommender, evaluate_hit_rate
from app.ai.sentiment import SentimentAnalyzer
from app.ai.smart_search import SmartSearch


@pytest.fixture(autouse=True)
def use_demo_catalog(monkeypatch, tmp_path):
    monkeypatch.setattr(engines, "_catalog_path", lambda: str(tmp_path / "missing-products.csv"))


@pytest.fixture
def e(use_demo_catalog):
    return get_engines()


def names(result):
    return [r["product"]["name"] for r in result["results"]]


# ------------------------------------------------------------------ smart search
def test_search_exact_and_typo(e):
    assert names(e.search.search("wireless mouse"))[0] == "Wireless Mouse"
    typo = e.search.search("wireles mose")
    assert names(typo)[0] == "Wireless Mouse"
    assert typo["did_you_mean"]


def test_search_synonyms(e):
    assert "Wireless Earbuds" in names(e.search.search("earphones"))[:3]
    assert "Backpack" in names(e.search.search("laptop bag"))[:3]


def test_search_price_filters(e):
    res = e.search.search("under 10")
    assert res["results"] and all(r["product"]["price"] <= 10 for r in res["results"])
    res = e.search.search("keyboard under 100")
    assert names(res)[0] == "Mechanical Keyboard"
    assert not e.search.search("keyboard under 5")["results"]


def test_search_nonsense_returns_nothing(e):
    assert e.search.search("zzzzqqqq")["results"] == []


# ------------------------------------------------------------------ sentiment
def test_sentiment_labels_and_negation():
    s = SentimentAnalyzer()
    assert s.analyze("I absolutely love this, it is fantastic!")["label"] == "positive"
    assert s.analyze("Terrible quality, it broke in a day. Awful.")["label"] == "negative"
    assert s.analyze("This is not good at all")["label"] == "negative"      # negation handled


def test_sentiment_analyzer_initialization_has_no_deprecation_warning():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", DeprecationWarning)
        SentimentAnalyzer()
    assert not [warning for warning in caught if issubclass(warning.category, DeprecationWarning)]


def test_sentiment_summary_and_mismatch(e):
    reviews = [r for r in e.reviews if r["product_id"] == 1]
    summary = e.sentiment.summarize(reviews, "Wireless Mouse")
    assert summary["count"] == len(reviews)
    assert 1 <= summary["avg_rating"] <= 5
    flagged = e.sentiment.summarize(
        [{"rating": 5, "text": "Terrible. It broke immediately and I hate it."}], "x")
    assert len(flagged["mismatches"]) == 1


def test_sentiment_model_trains_on_ratings(e):
    s = SentimentAnalyzer()
    metrics = s.train(e.reviews)
    assert metrics["accuracy"] > 0.8
    assert s.analyze("The battery drains too fast and it feels cheap")["label"] == "negative"


# ------------------------------------------------------------------ recommender
def test_recommender_personalises_and_excludes_owned(e):
    keyboard = 2
    out = e.recommender.recommend({"purchases": [keyboard], "views": [1]}, k=5)
    ids = [x["product"]["id"] for x in out["items"]]
    assert out["personalized"] and keyboard not in ids
    assert all(x["reason"] for x in out["items"])
    assert sum(e.products[i]["category"] == "Electronics" for i in ids) >= 3


def test_recommender_uses_searches(e):
    out = e.recommender.recommend({"searches": ["yoga"]}, k=3)
    assert out["items"][0]["product"]["name"] == "Yoga Mat"
    assert "yoga" in out["items"][0]["reason"]


def test_recommender_cold_start_and_stock(e):
    out = e.recommender.recommend({}, k=5)
    assert not out["personalized"] and len(out["items"]) == 5
    assert all(x["product"]["stock"] > 0 for x in out["items"])


def test_hybrid_beats_popularity_baseline():
    prods = sample_data.products()
    result = evaluate_hit_rate(prods, sample_data.interactions(), k=5)
    assert result["shoppers_tested"] >= 40
    assert result["hybrid_hit_rate"] > result["popularity_hit_rate"]


# ------------------------------------------------------------------ API
def test_api_endpoints():
    c = create_app().test_client()
    res = c.get("/api/products/search?q=wireles mouse").get_json()
    assert res["results"][0]["product"]["name"] == "Wireless Mouse"
    s = c.get("/api/reviews/sentiment/1").get_json()
    assert s["product"] == "Wireless Mouse" and s["count"] > 0
    assert c.get("/api/reviews/sentiment/999").status_code == 404
    r = c.post("/api/recommendations/", json={"searches": ["keyboard"]}).get_json()
    assert r["personalized"] and r["items"]
    assert c.get("/api/recommendations/demo/3").get_json()["items"]


def test_engines_use_storefront_catalog(tmp_path, monkeypatch):
    catalog = tmp_path / "products.csv"
    catalog.write_text(
        "name,category,price,stock,description,image_path\n"
        "Canvas Tote,Accessories,18.5,7,Reusable cotton bag,tote.jpg\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(engines, "_catalog_path", lambda: str(catalog))

    store_engines = engines.get_engines()

    assert list(store_engines.products) == [1]
    assert store_engines.products[1]["name"] == "Canvas Tote"
    assert store_engines.products[1]["image"] == "tote.jpg"
    assert store_engines.reviews == []
    assert store_engines.interactions == []
    assert store_engines.search.search("cotton bag")["results"][0]["product"]["id"] == 1


# ------------------------------------------------------------------ regression tests (bugs found by running the demo)
def test_search_does_not_correct_plain_english_and_handles_price_only(e):
    res = e.search.search("something under 8")
    assert res["did_you_mean"] is None
    assert res["results"] and all(r["product"]["price"] <= 8 for r in res["results"])


def test_summary_has_complaints_when_reviews_are_negative(e):
    found = False
    for pid in e.products:
        reviews = [r for r in e.reviews if r["product_id"] == pid]
        if sum(r["rating"] <= 2 for r in reviews) >= 2:
            s = e.sentiment.summarize(reviews, e.products[pid]["name"])
            assert s["complaints"], f"no complaints surfaced for product {pid}"
            found = True
    assert found


def test_similar_to_reasons_are_believable(e):
    checked = 0
    for n in range(1, 60):
        for item in e.recommender.recommend(demo_activity(n), k=6)["items"]:
            if item["reason"].startswith("Similar to "):
                source = item["reason"][len("Similar to "):]
                src = next(p for p in e.products.values() if p["name"] == source)
                assert src["category"] == item["product"]["category"]
                checked += 1
    assert checked > 10
