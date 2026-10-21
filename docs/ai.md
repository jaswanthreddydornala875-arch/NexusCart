# AI features

The AI engines live in `backend/app/ai/`. Django exposes them through the same API and catalog used by
the persistent desktop app. They operate on active products, stored reviews, customer activity, carts,
and completed orders. `sample_data.py` remains available for deterministic demos and isolated tests.

| Module | Status | What it does |
|--------|--------|--------------|
| `smart_search.py` | Connected | Typo-tolerant, meaning-aware product search with synonyms and price phrases |
| `sentiment.py` | Connected | VADER and TF-IDF/logistic-regression sentiment analysis; review summaries and mismatch flags |
| `recommender.py` | Connected | Hybrid product/content, collaborative, and shopper-history recommendations |
| `fraud_detection.py` | Connected | Explainable order-risk scores shown to admins for human review |
| `forecasting.py` | Connected | Recent sales-based demand and restocking estimates shown to admins |
| `assistant.py` | Connected | In-app shopping assistant for product and order questions |

## Start the backend

From the project root:

```bash
python3 -m pip install -r requirements.txt
python3 backend/manage.py migrate
python3 scripts/import_products.py database/products.csv --django --dry-run
python3 scripts/import_products.py database/products.csv --django
python3 backend/manage.py runserver
```

`--django` imports the catalog into the database used by the API. Create a customer account in the
desktop app to use personalized recommendations; product search and review summaries are public.
Run `pytest` for the deterministic AI and importer tests, and `python3 backend/manage.py test store`
for API integration tests.

## Django API

| Endpoint | Example |
|----------|---------|
| Smart search | `GET /api/products/search/?q=wireles%20mouse` |
| Filtered search | `GET /api/products/search/?q=earphones%20under%2050&in_stock=1` |
| Review sentiment | `GET /api/products/1/sentiment/` |
| Product reviews and summary | `GET /api/products/1/reviews/` |
| Recommendations | `POST /api/recommendations/?k=6` |
| Shopper activity | `GET /api/activity/` (customer session required) |

The recommendation endpoint uses the authenticated customer's stored purchases, cart, views, searches,
and positive reviews when available. Anonymous requests can still receive general/popularity-based picks.
The desktop app records search and product-view activity through the API when backend mode is enabled.
The assistant appears as **Ask AI** in the customer header; it uses the API-backed store for search,
recommendations, product reviews, customer orders, and cart actions. Adding an item requires customer
confirmation. The **Reports** tab in the admin screen includes fraud-risk review and demand forecast
sections, calculated from orders, payments, and active catalog stock fetched from Django.

Fraud detection is a human-review aid: it does not block orders or establish that fraud occurred.
Forecasts use recent order history and are estimates, not guarantees. The assistant is rule-based and
offline; it does not require or call an external language model.

## How the engines work

**Smart search.** Price phrases become filters and synonyms are added to the query. Word n-grams and
character n-grams score products; the latter help recover results from typos. Product names receive a
small match bonus.

**Sentiment.** VADER is a rule-based baseline. `SentimentAnalyzer.train(reviews)` fits a TF-IDF and
logistic-regression model using star ratings as labels (4-5 positive, 3 neutral, 1-2 negative).
Summaries extract strongly positive and negative review sentences and flag star/text mismatches.

**Recommender.** Content similarity, item-item collaborative similarity, and recent search relevance
are blended. Purchases weigh more than cart items, which weigh more than views. Owned and out-of-stock
products are excluded; shoppers without history receive general popular picks.

**Evaluation.** `evaluate_hit_rate()` hides a purchase per shopper and checks whether it appears in the
top five recommendations, compared with a popularity baseline. Synthetic-data results are a sanity
check, not a production quality guarantee.

## Remaining AI work

- Evaluate recommendation quality against production usage with privacy-appropriate metrics.
- Build more real sales history before relying on forecasts; little history yields low confidence.
- Payment confirmation is currently a mock flow; connect and verify a payment provider before accepting
  real payments.
