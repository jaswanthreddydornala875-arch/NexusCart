"""Smart search: typo-tolerant, meaning-aware product search.

How it works
  1. The query is cleaned: price phrases ("under 30") become filters, synonyms are added
     ("earphones" -> earbuds), and misspelt words are corrected for the "did you mean" hint.
  2. Two TF-IDF indexes score every product against the query:
       - word n-grams  -> matches whole terms and phrases
       - character n-grams -> survives typos ("wireles mouse", "keybord")
  3. The scores are blended, a small bonus is given when the query appears in the product name,
     and weak matches are dropped.
"""
import difflib
import re

from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

SYNONYMS = {
    "earphones": "earbuds", "headphones": "earbuds", "airpods": "earbuds", "laptop bag": "backpack",
    "bag": "backpack", "rucksack": "backpack", "diary": "notebook", "journal": "notebook",
    "pen": "gel pen", "pens": "gel pen", "cup": "coffee mug", "flask": "water bottle",
    "sneakers": "running sneakers", "shoes": "running sneakers", "watch": "smart watch",
    "cam": "webcam", "charger": "power bank", "wire": "cable", "pan": "frying pan",
    "ball": "football", "dumbbells": "dumbbell", "hat": "baseball cap", "shades": "sunglasses",
    "mat": "yoga mat", "plant": "plant pot", "candle": "scented candle",
}
_UNDER = re.compile(r"\b(?:under|below|less than|upto|up to|within|max)\s*\$?\s*(\d+(?:\.\d+)?)")
_OVER = re.compile(r"\b(?:over|above|more than|min)\s*\$?\s*(\d+(?:\.\d+)?)")
_WORD = re.compile(r"[a-z0-9]+")


class SmartSearch:
    def __init__(self, products):
        self.products = list(products)
        docs = [f"{p['name']} {p['name']} {p['name']} {p['category']} {p['description']}" for p in self.products]
        self._word = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True)
        self._char = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True)
        self._wm = self._word.fit_transform(docs)
        self._cm = self._char.fit_transform(docs)
        self._vocab = sorted({t for d in docs for t in _WORD.findall(d.lower()) if len(t) >= 4})
        self._names = [p["name"].lower() for p in self.products]

    # ---- query understanding -----------------------------------------------------
    def parse(self, query):
        q = query.lower()
        max_price = min_price = None
        m = _UNDER.search(q)
        if m:
            max_price, q = float(m.group(1)), q.replace(m.group(0), " ")
        m = _OVER.search(q)
        if m:
            min_price, q = float(m.group(1)), q.replace(m.group(0), " ")
        tokens = _WORD.findall(q)
        fixed, changed = [], False
        for t in tokens:
            if t in ENGLISH_STOP_WORDS:                       # filler words ("something", "the") say nothing
                continue
            if len(t) >= 4 and t not in self._vocab:
                close = [c for c in difflib.get_close_matches(t, self._vocab, n=3, cutoff=0.8) if c[0] == t[0]]
                if close:
                    fixed.append(close[0])
                    changed = True
                    continue
            fixed.append(t)
        text = " ".join(fixed)
        extra = [v for k, v in SYNONYMS.items() if re.search(rf"\b{re.escape(k)}\b", text)]
        return {"text": text, "expanded": " ".join([text] + extra).strip(),
                "did_you_mean": text if changed else None,
                "max_price": max_price, "min_price": min_price}

    # ---- search ------------------------------------------------------------------
    def search(self, query, limit=10, category=None, max_price=None, in_stock_only=False):
        q = self.parse(query)
        max_price = q["max_price"] if max_price is None else max_price
        keep = [i for i, p in enumerate(self.products)
                if (category in (None, "", "All") or p["category"] == category)
                and (max_price is None or p["price"] <= max_price)
                and (q["min_price"] is None or p["price"] >= q["min_price"])
                and (not in_stock_only or p["stock"] > 0)]
        scores = {}
        if q["expanded"]:
            ws = cosine_similarity(self._word.transform([q["expanded"]]), self._wm)[0]
            cs = cosine_similarity(self._char.transform([q["expanded"]]), self._cm)[0]
            terms = [t for t in _WORD.findall(q["expanded"]) if len(t) >= 3]
            for i in keep:
                s = 0.55 * ws[i] + 0.45 * cs[i]
                if any(t in self._names[i] for t in terms):
                    s += 0.15
                if s >= 0.12:
                    scores[i] = min(1.0, s)
        else:                                    # e.g. "under 20": filters only
            scores = {i: 0.5 for i in keep}
        ranked = sorted(scores, key=lambda i: (-scores[i], self.products[i]["price"]))[:limit]
        words = set(_WORD.findall(q["expanded"]))
        return {
            "query": query,
            "interpreted": {"text": q["text"], "max_price": max_price, "min_price": q["min_price"]},
            "did_you_mean": q["did_you_mean"],
            "results": [{"product": self.products[i], "score": round(float(scores[i]), 3),
                         "matched": sorted(words & set(_WORD.findall(
                             f"{self.products[i]['name']} {self.products[i]['category']} "
                             f"{self.products[i]['description']}".lower())))[:5]}
                        for i in ranked],
        }
