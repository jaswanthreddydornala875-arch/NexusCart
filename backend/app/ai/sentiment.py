"""Review sentiment analysis.

Two engines behind one interface:
  * VADER (rule-based lexicon, no training, works from day one)
  * an optional model (TF-IDF + logistic regression) trained on your own labelled reviews with
    train(); star ratings are used as labels (4-5 positive, 3 neutral, 1-2 negative).

summarize() turns a product's reviews into what shoppers praise and complain about (a sentence
counts only when the review's stars and words agree), and flags
reviews whose stars disagree with the words (possible fake or mistaken ratings).
"""
import re
from collections import Counter

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def label_from_rating(rating):
    return "positive" if rating >= 4 else "neutral" if rating == 3 else "negative"


class SentimentAnalyzer:
    def __init__(self, threshold=0.25):
        self._vader = SentimentIntensityAnalyzer()
        self.threshold = threshold
        self.model = None

    # ---- single text ----------------------------------------------------------------
    def analyze(self, text, use_model=True):
        """Returns {"label", "score"} with score in [-1, 1]."""
        if use_model and self.model is not None:
            proba = dict(zip(self.model.classes_, self.model.predict_proba([text])[0]))
            score = proba.get("positive", 0.0) - proba.get("negative", 0.0)
            return {"label": max(proba, key=proba.get), "score": round(float(score), 3), "engine": "model"}
        score = self._vader.polarity_scores(text)["compound"]
        label = "positive" if score >= self.threshold else "negative" if score <= -self.threshold else "neutral"
        return {"label": label, "score": round(score, 3), "engine": "vader"}

    # ---- optional: learn from your own reviews ----------------------------------------
    def train(self, reviews, test_size=0.25, seed=0):
        """reviews: dicts with "text" and "rating". Returns held-out accuracy and macro-F1."""
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import accuracy_score, f1_score
        from sklearn.model_selection import train_test_split
        from sklearn.pipeline import make_pipeline

        texts = [r["text"] for r in reviews]
        labels = [label_from_rating(r["rating"]) for r in reviews]
        x_tr, x_te, y_tr, y_te = train_test_split(texts, labels, test_size=test_size,
                                                  stratify=labels, random_state=seed)
        model = make_pipeline(TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True),
                              LogisticRegression(max_iter=1000, class_weight="balanced"))
        model.fit(x_tr, y_tr)
        pred = model.predict(x_te)
        self.model = model
        return {"accuracy": round(accuracy_score(y_te, pred), 3),
                "macro_f1": round(f1_score(y_te, pred, average="macro"), 3),
                "train_size": len(x_tr), "test_size": len(x_te)}

    # ---- a product's reviews --------------------------------------------------------
    def summarize(self, reviews, product_name="", top=3):
        """reviews: dicts with "rating" and "text". Uses VADER so the summary is explainable."""
        if not reviews:
            return {"count": 0, "avg_rating": 0.0, "avg_sentiment": 0.0, "labels": {}, "praise": [],
                    "complaints": [], "mismatches": []}
        labels, scores, mismatches = Counter(), [], []
        praise, complaints = Counter(), Counter()
        shown = {}
        name = product_name.lower()
        for r in reviews:
            a = self.analyze(r["text"], use_model=False)
            labels[a["label"]] += 1
            scores.append(a["score"])
            if (r["rating"] >= 4 and a["score"] <= -0.3) or (r["rating"] <= 2 and a["score"] >= 0.3):
                mismatches.append({"rating": r["rating"], "text": r["text"], "sentiment": a["score"]})
            # a review counts as praise / complaint only when the stars AND the words agree
            positive_review = r["rating"] >= 4 and a["score"] > -0.3
            negative_review = r["rating"] <= 2 and a["score"] < 0.3
            for s in _SENT_SPLIT.split(r["text"].strip()):
                key = s.lower().strip()
                if not key or (name and name in key):
                    continue                       # skip generic sentences that just name the product
                c = self._vader.polarity_scores(s)["compound"]
                shown.setdefault(key, s)
                if positive_review and c > -0.2:
                    praise[key] += 1
                elif negative_review and c < 0.2:
                    complaints[key] += 1
        pick = lambda counter: [{"text": shown[k], "mentions": n} for k, n in counter.most_common(top)]
        return {"count": len(reviews),
                "avg_rating": round(sum(r["rating"] for r in reviews) / len(reviews), 2),
                "avg_sentiment": round(sum(scores) / len(scores), 3),
                "labels": dict(labels), "praise": pick(praise), "complaints": pick(complaints),
                "mismatches": mismatches}
