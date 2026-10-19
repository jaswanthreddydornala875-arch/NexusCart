"""Hybrid personal recommender.

For one shopper it blends three signals and explains each pick:
  content  - products similar (same category + TF-IDF text) to what they bought, carted, viewed or liked
  collab   - products that shoppers with similar behaviour also bought (item-item cosine
             similarity over the user x product interaction matrix)
  search   - products that match what they recently searched for
Out-of-stock and already bought / carted products are never suggested. A shopper with no
history gets the popular, well-rated products instead (cold start).

evaluate_hit_rate() measures it offline: hide one purchase per shopper and check whether the
recommender brings it back in its top-k, compared with a "most popular" baseline.
"""
import random
from collections import defaultdict

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

KIND_WEIGHT = {"view": 1.0, "cart": 2.0, "purchase": 3.0}
WEIGHTS = {"content": 0.45, "collab": 0.35, "search": 0.20}
MIN_CONTENT, MIN_COLLAB = 0.3, 0.05      # a reason is only shown when the evidence is at least this strong


def activity_from_interactions(items):
    """[(product_id, kind)] -> the activity dict recommend() expects."""
    act = {"purchases": [], "cart": [], "views": [], "searches": [], "liked": []}
    for pid, kind in items:
        act[{"purchase": "purchases", "cart": "cart", "view": "views"}[kind]].append(pid)
    return act


def _norm(x):
    m = x.max()
    return x / m if m > 0 else x


class HybridRecommender:
    def __init__(self, products, interactions=(), ratings=None):
        self.products = list(products)
        self.ids = [p["id"] for p in self.products]
        self.index = {pid: i for i, pid in enumerate(self.ids)}
        self.name = {p["id"]: p["name"] for p in self.products}
        docs = [f"{p['name']} {p['category']} {p['description']}" for p in self.products]
        self._vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True)
        self._x = self._vec.fit_transform(docs)
        cats = np.array([p["category"] for p in self.products])
        same_category = (cats[:, None] == cats[None, :]).astype(float)
        self.content_sim = 0.65 * same_category + 0.35 * cosine_similarity(self._x)
        np.fill_diagonal(self.content_sim, 0.0)
        self.prior = np.array([(ratings or {}).get(pid, 3.5) / 5.0 for pid in self.ids])
        self._in_stock = np.array([p.get("stock", 1) > 0 for p in self.products])
        self.fit(interactions)

    def fit(self, interactions):
        """(Re)learn popularity and item-item similarity from (user, product_id, kind) tuples."""
        n = len(self.ids)
        users = {}
        for u, _, _ in interactions:
            users.setdefault(u, len(users))
        r = np.zeros((max(len(users), 1), n))
        for u, pid, kind in interactions:
            if pid in self.index:
                r[users[u], self.index[pid]] += KIND_WEIGHT[kind]
        self.popularity = r.sum(axis=0)
        self.collab_sim = np.nan_to_num(cosine_similarity(r.T)) if len(users) else np.zeros((n, n))
        np.fill_diagonal(self.collab_sim, 0.0)

    def recommend(self, activity, k=6):
        n = len(self.ids)
        w = np.zeros(n)
        seen = set()
        for rank, pid in enumerate(activity.get("views", [])):
            if pid in self.index:
                w[self.index[pid]] += max(0.4, 1.0 - 0.1 * rank)
        for key, weight in (("cart", 2.0), ("purchases", 3.0), ("liked", 3.0)):
            for pid in activity.get(key, []):
                if pid in self.index:
                    w[self.index[pid]] += weight
        seen.update(activity.get("purchases", []))
        seen.update(activity.get("cart", []))
        searches = [s for s in activity.get("searches", []) if s.strip()][:5]
        candidates = np.array([self.ids[i] not in seen for i in range(n)]) & self._in_stock

        if w.sum() == 0 and not searches:                        # cold start
            score = _norm(self.popularity) * 0.6 + self.prior * 0.4
            order = [i for i in np.argsort(-score) if candidates[i]][:k]
            return {"personalized": False, "items": [
                {"product": self.products[i], "score": round(float(score[i]), 3),
                 "reason": "Popular with customers", "signals": {}} for i in order]}

        total = w.sum()
        content = (w @ self.content_sim) / total if total else np.zeros(n)
        collab = (w @ self.collab_sim) / total if total else np.zeros(n)
        search, best_q = np.zeros(n), [""] * n
        for rank, q in enumerate(searches):
            sim = cosine_similarity(self._vec.transform([q]), self._x)[0] * max(0.4, 1.0 - 0.15 * rank)
            for i in range(n):
                if sim[i] > search[i]:
                    search[i], best_q[i] = sim[i], q
        comps = {"content": _norm(content), "collab": _norm(collab), "search": _norm(search)}
        score = sum(WEIGHTS[c] * comps[c] for c in comps) + 0.05 * self.prior
        order = [i for i in np.argsort(-score) if candidates[i]][:k]

        items = []
        for i in order:
            contrib = {c: WEIGHTS[c] * float(comps[c][i]) for c in comps}
            main = max(contrib, key=contrib.get)
            reason = "Popular with shoppers like you"
            if main == "search":
                reason = f'Matches your search "{best_q[i]}"'
            elif main == "collab" and total:
                j = int(np.argmax(w * self.collab_sim[:, i]))
                if self.collab_sim[j, i] >= MIN_COLLAB:
                    reason = f"Shoppers who liked {self.name[self.ids[j]]} also liked this"
            elif total:
                j = int(np.argmax(w * self.content_sim[:, i]))
                if self.content_sim[j, i] >= MIN_CONTENT:
                    reason = f"Similar to {self.name[self.ids[j]]}"
            items.append({"product": self.products[i], "score": round(float(score[i]), 3), "reason": reason,
                          "signals": {c: round(v, 3) for c, v in contrib.items()}})
        return {"personalized": True, "items": items}


def evaluate_hit_rate(products, interactions, k=5, seed=0):
    """Leave-one-purchase-out test. Returns hit-rate@k for the hybrid model and for a
    'most popular' baseline (higher is better)."""
    rng = random.Random(seed)
    by_user = defaultdict(list)
    for u, pid, kind in interactions:
        by_user[u].append((pid, kind))
    rec = HybridRecommender(products)
    stock = {p["id"]: p.get("stock", 1) > 0 for p in products}
    hybrid_hits = pop_hits = trials = 0
    for u, items in by_user.items():
        purchases = [pid for pid, kind in items if kind == "purchase"]
        if len(set(purchases)) < 3:
            continue
        held = rng.choice(purchases)
        train = [(uu, pid, kind) for uu, pid, kind in interactions
                 if not (uu == u and pid == held and kind == "purchase")]
        rest = [(pid, kind) for pid, kind in items if not (pid == held and kind == "purchase")]
        if held in {pid for pid, kind in rest if kind == "purchase"}:       # bought twice: not a fair test
            continue
        rec.fit(train)
        act = activity_from_interactions(rest)
        top = [x["product"]["id"] for x in rec.recommend(act, k=k)["items"]]
        seen = set(act["purchases"]) | set(act["cart"])
        pop_rank = [rec.ids[i] for i in np.argsort(-rec.popularity) if rec.ids[i] not in seen and stock[rec.ids[i]]][:k]
        hybrid_hits += held in top
        pop_hits += held in pop_rank
        trials += 1
    return {"k": k, "shoppers_tested": trials,
            "hybrid_hit_rate": round(hybrid_hits / trials, 3) if trials else 0.0,
            "popularity_hit_rate": round(pop_hits / trials, 3) if trials else 0.0}
