"""Demo catalog, reviews and shopper activity.

The AI modules work on plain lists of dicts, so they run (and are tested) before the database
layer exists. Once the models are done, build the same lists from the database instead.
Everything here is synthetic and seeded, so results are repeatable.
"""
import csv
import os
import random
import re
from datetime import date, timedelta
from pathlib import Path

_PRODUCT_SEED = [
    # name, category, price, stock, description
    ("Wireless Mouse", "Electronics", 19.99, 40, "Ergonomic 2.4 GHz wireless mouse with silent clicks, adjustable DPI and a 12-month battery life. Plug-and-play USB receiver."),
    ("Mechanical Keyboard", "Electronics", 59.50, 15, "Compact tenkeyless keyboard with tactile switches, per-key backlight and a detachable USB-C cable. Aluminium top plate."),
    ("USB-C Cable", "Electronics", 6.99, 120, "1.5 m braided USB-C cable supporting 60 W fast charging and 480 Mbps data transfer."),
    ("Bluetooth Speaker", "Electronics", 34.90, 28, "Portable Bluetooth 5.3 speaker with deep bass, 14-hour playtime and an IPX6 splash-proof body."),
    ("Wireless Earbuds", "Electronics", 44.00, 35, "True wireless earbuds with active noise reduction, touch controls and a pocket-sized charging case."),
    ("Power Bank", "Electronics", 26.50, 50, "10,000 mAh slim power bank with fast charging, two outputs and LED battery indicator."),
    ("HD Webcam", "Electronics", 31.00, 18, "1080p webcam with built-in microphone, auto light correction and a privacy shutter."),
    ("Smart Watch", "Electronics", 79.00, 0, "Fitness smart watch with heart-rate and sleep tracking, 7-day battery and water resistance."),
    ("Python Crash Course", "Books", 28.00, 25, "A hands-on, project-based introduction to programming with Python. Build a game, a data visualisation and a simple web app."),
    ("Machine Learning Basics", "Books", 32.00, 20, "A friendly introduction to machine learning: regression, classification, clustering and neural networks with worked examples."),
    ("SQL Made Simple", "Books", 22.50, 30, "Learn to query, design and optimise relational databases with clear explanations and practice exercises."),
    ("Algorithms Illustrated", "Books", 29.00, 16, "Understand sorting, searching, graphs and dynamic programming through hundreds of step-by-step diagrams."),
    ("Notebook (A5)", "Stationery", 3.49, 200, "120 pages of 100 gsm dotted paper with a lay-flat spiral binding and elastic closure. No bleed-through."),
    ("Gel Pen Set", "Stationery", 7.99, 90, "Set of three smooth-writing gel pens in blue, red and green with quick-dry ink and comfortable grips."),
    ("Sticky Notes", "Stationery", 2.99, 150, "Pack of bright, repositionable sticky notes in assorted colours. Strong adhesive that leaves no residue."),
    ("Desk Lamp", "Home", 24.90, 4, "Dimmable LED desk lamp with three colour temperatures, a flexible neck and a built-in USB charging port."),
    ("Water Bottle", "Home", 14.00, 60, "750 ml insulated stainless steel bottle that keeps drinks cold for 24 hours or hot for 12."),
    ("Ceramic Coffee Mug", "Home", 9.50, 75, "350 ml glazed ceramic mug with a comfortable handle. Microwave and dishwasher safe."),
    ("Scented Candle", "Home", 12.00, 45, "Hand-poured soy wax candle with a calming lavender scent and up to 40 hours of burn time."),
    ("Plant Pot", "Home", 11.50, 38, "Terracotta plant pot with drainage hole, perfect for succulents, herbs and small indoor plants."),
    ("Backpack", "Fashion", 39.99, 22, "Water-resistant 25 L backpack with a padded 15-inch laptop sleeve, hidden anti-theft pocket and USB pass-through."),
    ("Sunglasses", "Fashion", 18.00, 55, "Polarised UV400 sunglasses with a lightweight, durable frame for everyday wear."),
    ("Baseball Cap", "Fashion", 12.99, 64, "Classic cotton baseball cap with an adjustable strap and breathable eyelets."),
    ("Running Sneakers", "Fashion", 54.00, 26, "Lightweight running shoes with breathable mesh, cushioned sole and a secure lace-up fit."),
    ("Yoga Mat", "Sports", 21.00, 42, "6 mm non-slip yoga mat with a carrying strap. Comfortable cushioning for floor workouts."),
    ("Dumbbell Set", "Sports", 36.00, 12, "Pair of adjustable 5 kg dumbbells with a knurled grip and secure locking collars."),
    ("Football", "Sports", 17.50, 33, "Size 5 match football with a durable stitched cover and consistent bounce."),
    ("Non-stick Frying Pan", "Kitchen", 23.00, 29, "28 cm non-stick frying pan with even heat distribution and a heat-resistant handle. Induction compatible."),
    ("Chef's Knife", "Kitchen", 27.00, 21, "20 cm stainless steel chef's knife with a razor-sharp edge and a balanced, comfortable handle."),
    ("Electric Kettle", "Kitchen", 25.50, 3, "1.7 L electric kettle with auto shut-off, boil-dry protection and a rapid 3-minute boil."),
]

_DEFAULT_ASPECTS = (["Good quality and great value.", "Exactly as described."],
                    ["The quality is not what I expected.", "It arrived damaged."])


def _csv_path():
    env = os.getenv("PRODUCTS_CSV")
    return Path(env) if env else Path(__file__).resolve().parents[3] / "database" / "products.csv"


def _read_catalog_csv(path):
    """Products from database/products.csv (the same file the bulk importer reads)."""
    out = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            r = {str(k).strip().lower(): (v or "").strip() for k, v in r.items() if k}
            if r.get("is_active", "").lower() in ("0", "false", "no", "n", "inactive", "off"):
                continue
            try:
                price = float(re.sub(r"[^\d.]", "", r.get("price", "").replace(",", "")))
                stock = int(float(r.get("stock") or 0))
            except ValueError:
                continue
            if r.get("name") and r.get("category"):
                out.append((r["name"], r["category"], price, stock, r.get("description", "")))
    return out


_OPENERS = {
    "pos": ["Absolutely love this {n}.", "Really happy with the {n}.", "The {n} exceeded my expectations.",
            "Great purchase, the {n} works perfectly."],
    "neu": ["The {n} is okay for the price.", "Average {n}, nothing special.", "The {n} does the job but nothing more."],
    "neg": ["Very disappointed with the {n}.", "The {n} stopped working after a week.",
            "I would not recommend the {n}.", "The {n} feels cheap and flimsy."],
}
_ASPECTS = {   # category -> (praise, complaints)
    "Electronics": (["Battery life is excellent.", "Build quality feels premium.", "Setup took only seconds."],
                    ["Battery drains too fast.", "The connection keeps dropping.", "Build quality is poor."]),
    "Books": (["The explanations are clear and easy to follow.", "The examples are very practical."],
              ["The examples are outdated.", "Too many typos and confusing explanations."]),
    "Stationery": (["The quality is lovely and it feels great to use.", "Great value for the price."],
                   ["The ink smudges badly.", "The paper is thin and tears easily."]),
    "Home": (["It looks beautiful in my room.", "Very sturdy and well made."],
             ["It arrived scratched and damaged.", "The finish started peeling quickly."]),
    "Fashion": (["Comfortable and fits perfectly.", "The stitching is strong and the style is great."],
                ["The zip broke within days.", "Runs small and the material feels cheap."]),
    "Sports": (["Great grip and very durable.", "Perfect for my daily workout."],
               ["It wore out quickly.", "The grip is slippery and uncomfortable."]),
    "Kitchen": (["Heats evenly and is easy to clean.", "Looks great and works fast."],
                ["It stopped heating properly.", "Hard to clean and the handle feels loose."]),
}
_REVIEWERS = ["Priya S.", "Marcus T.", "Elena R.", "Dev K.", "Sam W.", "Nora B.", "Chen L.", "Ana M.", "Ravi P.",
              "Julia H.", "Tom G.", "Isha N.", "Leo F.", "Maya D.", "Omar J.", "Zoe K.", "Ben A.", "Kavya R."]
_TITLES = {"pos": ["Love it", "Excellent", "Highly recommended", "Worth the money"],
           "neu": ["It's okay", "Average", "Decent"], "neg": ["Disappointed", "Not good", "Would not buy again"]}


def products():
    """30 products: id, name, category, price, stock, description."""
    rows = []
    path = _csv_path()
    if path.is_file():
        try:
            rows = _read_catalog_csv(path)
        except (OSError, ValueError):
            rows = []
    rows = rows or _PRODUCT_SEED                       # fall back to the built-in demo catalog
    return [{"id": i, "name": n, "category": c, "price": p, "stock": s, "description": d}
            for i, (n, c, p, s, d) in enumerate(rows, start=1)]


def reviews(seed=42, per_product=(5, 9)):
    """Reviews whose star rating matches the tone of the text (a few are deliberately mismatched
    so the sentiment module has something to flag)."""
    rng = random.Random(seed)
    prods = products()
    out, rid = [], 1
    start = date(2026, 8, 1)
    for p in prods:
        quality = rng.uniform(0.45, 0.9)                      # how good this product "really" is
        for reviewer in rng.sample(_REVIEWERS, rng.randint(*per_product)):
            r = rng.random()
            tone = "pos" if r < quality else ("neu" if r < quality + (1 - quality) * 0.4 else "neg")
            rating = {"pos": rng.choice([5, 5, 4]), "neu": 3, "neg": rng.choice([1, 2, 2])}[tone]
            praise, complaints = _ASPECTS.get(p["category"], _DEFAULT_ASPECTS)
            aspect = rng.choice(praise if tone == "pos" else complaints if tone == "neg" else praise + complaints)
            text = f"{rng.choice(_OPENERS[tone]).format(n=p['name'])} {aspect}"
            if rng.random() < 0.04:                           # rare mismatch: stars disagree with the words
                rating = 5 if tone == "neg" else 1
            out.append({"id": rid, "product_id": p["id"], "user": reviewer, "rating": rating,
                        "title": rng.choice(_TITLES[tone]), "text": text,
                        "date": (start + timedelta(days=rng.randint(0, 70))).isoformat()})
            rid += 1
    return out


def interactions(seed=7, users=90):
    """(user_id, product_id, kind) with kind in view | cart | purchase.
    Each shopper mostly browses and buys from one or two favourite categories."""
    rng = random.Random(seed)
    prods = [p for p in products() if p["stock"] > 0]
    cats = sorted({p["category"] for p in prods})
    out = []
    for u in range(1, users + 1):
        favs = rng.sample(cats, rng.choice([1, 2]))
        pool_fav = [p for p in prods if p["category"] in favs]
        for _ in range(rng.randint(7, 12)):
            p = rng.choice(pool_fav if rng.random() < 0.85 else prods)
            kind = rng.choices(["view", "cart", "purchase"], [5, 2, 4])[0]
            out.append((f"u{u:03d}", p["id"], kind))
    return out


def load():
    return products(), reviews(), interactions()
