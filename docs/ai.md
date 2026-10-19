# AI features

All modules live in `backend/app/ai/` and work on plain lists of dicts, so they run (and are tested)
before the database layer exists. `sample_data.py` provides a seeded demo catalog, reviews and shopper
activity. Once the models exist, build the same lists from the database.

| Module | Status | What it does |
|--------|--------|--------------|
| `smart_search.py` | Done | Typo-tolerant, meaning-aware search with synonyms and price words ("keyboard under 100") |
| `sentiment.py` | Done | VADER sentiment + a trainable TF-IDF/logistic-regression model; review summaries (praise / complaints); flags reviews where stars disagree with the words |
| `recommender.py` | Done | Hybrid content + collaborative + search-history recommender with a reason on every pick; offline evaluation |
| `fraud_detection.py` | Planned | Flag suspicious payments / orders (payment_events, repeated failures, odd amounts) |
| `forecasting.py` | Planned | Demand forecasting for stock planning |
| `assistant.py` | Planned | Shopping assistant that answers product and order questions |

## Try it

```bash
pip install -r requirements.txt
python backend/scripts/ai_demo.py          # prints search, sentiment, recommendations, evaluation
pytest                                     # includes backend/tests/test_ai.py
python backend/run.py                      # then open the URLs below
```

| Endpoint | Example |
|----------|---------|
| Smart search | `GET /api/products/search?q=wireles mouse` , `?q=earphones under 50` |
| Review summary | `GET /api/reviews/sentiment/1` |
| Recommendations | `POST /api/recommendations/` with `{"views":[2],"searches":["keyboard"]}` |
| Demo shopper | `GET /api/recommendations/demo/5` |

## How the pieces work

**Smart search.** Price phrases become filters and synonyms are added to the query. Two TF-IDF indexes
score every product: word n-grams (whole terms) and character n-grams (survive typos). The scores are
blended, with a small bonus when the query appears in the product name.

**Sentiment.** VADER (a rule-based lexicon that handles negation and emphasis) works with no training.
`SentimentAnalyzer.train(reviews)` fits a TF-IDF + logistic-regression model using star ratings as labels
(4-5 positive, 3 neutral, 1-2 negative). `summarize()` pulls the most-mentioned strongly positive and
negative sentences per product (a sentence counts only when the review's stars and words agree) and flags
reviews whose stars contradict their text.

**Recommender.** Three signals are scaled to 0-1 and blended (45% content, 35% collaborative, 20% search):
similarity (same category plus text) to products the shopper bought / carted / viewed, "shoppers like you also bought"
(item-item cosine similarity), and match to recent searches. Purchases weigh 3, cart 2, views 1 (newer
views weigh more). Owned and out-of-stock products are never suggested; a shopper with no history gets
popular, well-rated products. A reason such as "Similar to X" is shown only when the evidence is strong enough;
otherwise it says "Popular with shoppers like you".

## Measuring it

`evaluate_hit_rate()` hides one purchase per shopper and checks whether the recommender brings it back
in its top 5, compared with a "most popular" baseline. The numbers on the synthetic shoppers are a sanity
check only (the data was generated with category preferences). Re-run it on real orders once you have them.

## Next

- Connect the engines to the database (`services/`) instead of `sample_data`.
- Frontend: call `/api/products/search` and `/api/recommendations/` from `api_client.py`.
- Build `fraud_detection.py`, `forecasting.py`, then `assistant.py`.
