"""Prints what the AI modules do (handy for the demo / presentation).

Run from the repo root:   python backend/scripts/ai_demo.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app.ai import sample_data  # noqa: E402
from app.ai.engines import demo_activity, get_engines  # noqa: E402
from app.ai.recommender import evaluate_hit_rate  # noqa: E402
from app.ai.sentiment import SentimentAnalyzer  # noqa: E402

e = get_engines()


def title(t):
    print("\n" + "=" * 70 + f"\n{t}\n" + "=" * 70)


title("1. SMART SEARCH (typos, synonyms, price words)")
for q in ["wireles mose", "earphones", "keyboard under 100", "something under 8"]:
    r = e.search.search(q, limit=3)
    hint = f'   (did you mean "{r["did_you_mean"]}"?)' if r["did_you_mean"] else ""
    print(f'\n"{q}"{hint}')
    for x in r["results"]:
        print(f'   {x["score"]:.2f}  {x["product"]["name"]:<24} ${x["product"]["price"]}')

title("2. REVIEW SENTIMENT")
for text in ["I absolutely love it, fantastic quality!", "This is not good at all.", "It is okay, nothing special."]:
    print(f"   {e.sentiment.analyze(text)['label']:<9} <- {text}")
product = e.products[2]
summary = e.sentiment.summarize([r for r in e.reviews if r["product_id"] == 2], product["name"])
print(f'\n{product["name"]}: {summary["count"]} reviews, avg {summary["avg_rating"]} stars, '
      f'sentiment {summary["avg_sentiment"]:+.2f}, labels {summary["labels"]}')
print("   Customers praise   :", [p["text"] for p in summary["praise"]])
print("   Customers complain :", [c["text"] for c in summary["complaints"]])
print("   Stars vs words mismatches:", len(summary["mismatches"]))
trained = SentimentAnalyzer().train(e.reviews)
print("   Model trained on star ratings:", trained)

title("3. PERSONAL RECOMMENDATIONS")
print("New shopper (cold start):")
for x in e.recommender.recommend({}, k=3)["items"]:
    print(f'   {x["product"]["name"]:<24} {x["reason"]}')
act = {"views": [2, 1], "searches": ["keyboard"], "purchases": []}
print(f"\nShopper who viewed the keyboard + mouse and searched 'keyboard':")
for x in e.recommender.recommend(act, k=4)["items"]:
    print(f'   {x["product"]["name"]:<24} {x["reason"]}')
print("\nDemo shopper u005:")
for x in e.recommender.recommend(demo_activity(5), k=4)["items"]:
    print(f'   {x["product"]["name"]:<24} {x["reason"]}')

title("4. OFFLINE EVALUATION (synthetic shoppers - hide one purchase, see if it comes back)")
print(evaluate_hit_rate(sample_data.products(), sample_data.interactions(), k=5))
