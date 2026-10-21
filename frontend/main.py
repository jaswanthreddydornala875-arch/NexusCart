"""
Online Store - Tkinter frontend (Amazon-style layout)
======================================================
Run from the project root:  python frontend/main.py

Project location:
    frontend/main.py      Tkinter application
    frontend/theme.py     shared theme and styles
    frontend/api_client.py REST client for the Django backend
    frontend/assets/images/ product images grouped by category

Optional:  pip install pillow      (enables JPG/WEBP images and smoother resizing)

WHAT'S IN IT
  * Sign in / register (role based: customer or admin)
  * First login: a profile form (name, email, phone, delivery address ...)
  * Account page: view and edit those details, plus your search history
  * Home: personal recommendations, recently viewed, recent searches, all products
  * Product page: images, details, customer reviews (write / update your own)
  * Cart -> Checkout (delivery address + payment method) -> Orders
  * Admin: products (with images), orders, review moderation, reports

DATA
  By default the GUI uses an in-memory demo store. Set NEXUSCART_API_URL to use
  the persistent Django API for accounts, catalog, cart, checkout and orders.

Demo logins:  admin / admin123  (admin)      alice / alice123  (customer)
Demo coupon:  SAVE10  (10% off)
"""
import csv
import hashlib
import os
import shutil
import random
import re
import sys
import tkinter as tk
from datetime import date, datetime, timedelta
from tkinter import filedialog, font as tkfont, messagebox, ttk

try:
    from PIL import Image, ImageTk
    PIL_OK = True
except ImportError:          # the app still works; PNG/GIF images are shown without Pillow
    PIL_OK = False

CURRENCY = "₹"
ORDER_STATUSES = ["Pending", "Paid", "Shipped", "Delivered", "Cancelled"]
PAYMENT_METHODS = ["Cash on Delivery", "UPI", "Credit / Debit Card", "Net Banking"]
SORTS = ["Featured", "Price: Low to High", "Price: High to Low", "Avg. Customer Review"]
COUNTRIES = ["India", "United States", "United Kingdom", "Canada", "Australia", "Germany",
             "France", "Singapore", "United Arab Emirates", "Other"]
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)
IMAGE_DIR = os.path.join(BASE_DIR, "assets", "images")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp")
CARD_W = 220
CARD_IMG, DETAIL_IMG, THUMB_IMG, SMALL_IMG = 150, 300, 100, 60

sys.path.insert(0, os.path.join(PROJECT_DIR, "backend"))
from app.ai.assistant import ShoppingAssistant
from app.ai.fraud_detection import fraud_lines, scan_orders
from app.ai.forecasting import forecast_demand, forecast_lines
from app.ai.sentiment import SentimentAnalyzer
from app.ai.smart_search import SmartSearch

from theme import (NAVY, NAVY_2, BG, SURFACE, TEXT, MUTED, LINK, LINK_HOVER, LINE, HOVER,
                   HEAD_BG, PRICE, RED, GREEN, WARN, STAR, YELLOW, YELLOW_H, ORANGE, ORANGE_H,
                   FONT, HEAD, MONO, apply_style, get_fonts)
from api_client import APIClient, APIError

PROFILE_KEYS = ("full_name", "email", "phone", "alt_phone", "address_line1", "address_line2",
                "city", "state", "postal_code", "country", "address_type", "delivery_notes")
REQUIRED_PROFILE = ("full_name", "email", "phone", "address_line1", "city", "state",
                    "postal_code", "country")

# --- Theme: Amazon-inspired palette, flat and clean ---------------------------
NAVY, NAVY_2 = "#131921", "#232F3E"
BG, SURFACE = "#EAEDED", "#FFFFFF"
TEXT, MUTED = "#0F1111", "#565959"
LINK, LINK_HOVER = "#007185", "#C7511F"
LINE, HOVER, HEAD_BG = "#D5D9D9", "#F7FAFA", "#F0F2F2"
PRICE, RED, GREEN, WARN = "#B12704", "#B12704", "#007600", "#C45500"
STAR = "#FFA41C"
YELLOW, YELLOW_H = "#FFD814", "#F7CA00"
ORANGE, ORANGE_H = "#FFA41C", "#FA8900"

# Fonts: first installed one wins. Edit the lists to taste (Tkinter can only use
# fonts installed on the machine).
BODY_FONTS = ["Inter", "Nunito Sans", "Segoe UI", "SF Pro Text", "Helvetica Neue", "Ubuntu", "DejaVu Sans"]
HEADING_FONTS = ["Poppins", "Montserrat", "Inter", "Segoe UI Semibold", "Helvetica Neue", "DejaVu Sans"]
MONO_FONTS = ["JetBrains Mono", "Fira Code", "Cascadia Code", "Consolas", "Menlo", "DejaVu Sans Mono"]
FONT, HEAD, MONO = "Segoe UI", "Segoe UI", "Consolas"   # replaced at startup by pick_fonts()


class StoreError(Exception):
    """Raised for any user-facing problem (bad login, out of stock, ...)."""


EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")


def validate_field(key, value):
    """Returns an error message, or "" when the value is fine.  Used live by the forms
    (so mistakes show up right under the field) and again by the store."""
    v = str(value).strip()
    if key == "username":
        if len(v) < 3:
            return "Username must be at least 3 characters."
        if len(v) > 20:
            return "Username can be at most 20 characters."
        if not re.fullmatch(r"[A-Za-z0-9._-]+", v):
            return "Use only letters, numbers, dot, dash or underscore."
    elif key == "password":
        if len(str(value)) < 6:
            return "Password must be at least 6 characters."
    elif key == "full_name":
        if len(v) < 2:
            return "Please enter your full name."
        if any(c.isdigit() for c in v):
            return "Name shouldn't contain numbers."
    elif key == "email":
        if not v:
            return "Please enter your email address."
        if not EMAIL_RE.fullmatch(v):
            return "Enter a valid email address, like name@example.com."
    elif key in ("phone", "alt_phone"):
        if not v:
            return "" if key == "alt_phone" else "Please enter your mobile number."
        if not re.fullmatch(r"\+?[\d\s\-()]+", v):
            return "Use digits only (you can add +, spaces, - or brackets)."
        if not 7 <= len(re.sub(r"\D", "", v)) <= 15:
            return "Enter 7 to 15 digits, e.g. +91 98765 43210."
    elif key == "address_line1":
        if len(v) < 3:
            return "Please enter your house / flat number and street."
    elif key in ("city", "state"):
        label = "city or town" if key == "city" else "state or province"
        if not v:
            return f"Please enter your {label}."
        if any(c.isdigit() for c in v):
            return f"The {label} shouldn't contain numbers."
    elif key == "postal_code":
        if not v:
            return "Please enter your postal / PIN code."
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 \-]{2,9}", v):
            return "Enter a valid postal / PIN code (3-10 letters or digits)."
    elif key == "country":
        if not v:
            return "Please choose your country."
    return ""


def ensure_images():
    """Ensure the project image folders exist; product images live under assets/images."""
    for category in ("electronics", "clothing", "footwear", "accessories"):
        os.makedirs(os.path.join(IMAGE_DIR, category), exist_ok=True)


# ----------------------------------------------------------------------------
# Mock data layer  (replace with real DB / API calls later)
# ----------------------------------------------------------------------------
PRODUCT_SEED = [
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

REVIEW_BANK = {
    5: [("Absolutely love it", "The {n} is even better than I expected. Great quality and fast delivery."),
        ("Worth every penny", "Really happy with this purchase - the {n} feels premium and works perfectly."),
        ("Highly recommended", "Bought the {n} as a gift and it was a hit. Would buy again.")],
    4: [("Very good", "The {n} does exactly what it promises. Only small nitpicks, nothing serious."),
        ("Solid purchase", "Good value for money. The {n} has been reliable so far.")],
    3: [("It's okay", "The {n} is decent but not outstanding. Does the job."),
        ("Average", "Fine for the price, though I expected a slightly better finish.")],
    2: [("Not impressed", "The {n} didn't quite live up to the description for me.")],
}
REVIEWERS = ["Priya S.", "Marcus T.", "Elena R.", "Dev K.", "Sam W.", "Nora B.", "Chen L.", "Ana M.",
             "Ravi P.", "Julia H.", "Tom G.", "Isha N.", "Leo F.", "Maya D.", "Omar J.", "Zoe K.",
             "Ben A.", "Kavya R.", "Lucas M.", "Aisha Q."]


class MockStore:
    def __init__(self):
        self.users = {}      # username -> {"username", "pw_hash", "role", "profile"}
        self.products = {}   # id -> {"id","name","category","price","stock","description","image"}
        self.carts = {}      # username -> {product_id: qty}
        self.orders = []     # order dicts; items are (name, price, qty, product_id)
        self.payments = []   # {"order_id","method","amount","status","date"}
        self.reviews = []    # {"id","pid","user","rating","title","text","date","verified"}
        self.history = {}    # username -> [{"q", "ts"}] newest first
        self.views = {}      # username -> [product_id] newest first
        self.coupons = {"SAVE10": 0.10}
        self._pid, self._oid, self._rid = 1, 1001, 1

        self.register("admin", "admin123", "admin")
        self.register("alice", "alice123", "customer")
        self._seed()

    def _seed(self):
        catalog_path = os.path.join(PROJECT_DIR, "database", "products.csv")
        loaded_catalog = False
        if os.path.isfile(catalog_path):
            try:
                import csv
                with open(catalog_path, "r", newline="", encoding="utf-8-sig") as catalog_file:
                    rows = list(csv.DictReader(catalog_file))
                for row in rows:
                    name = (row.get("name") or "").strip()
                    if not name:
                        continue
                    category = (row.get("category") or "General").strip()
                    price = row.get("price") or "0"
                    stock = row.get("stock") or "0"
                    description = (row.get("description") or "").strip()
                    image = (row.get("image_path") or row.get("image") or "").strip()
                    if image and not os.path.isabs(image):
                        image = os.path.normpath(os.path.join(PROJECT_DIR, image))
                    self.add_product(name, category, price, stock, description, image)
                    loaded_catalog = True
            except (OSError, ValueError, StoreError):
                loaded_catalog = False
                self.products.clear()
                self._pid = 1
        if not loaded_catalog:
            for name, cat, price, stock, desc in PRODUCT_SEED:
                self.add_product(name, cat, price, stock, desc)
        rng = random.Random(42)
        start = date(2026, 8, 1)
        span = (date(2026, 10, 13) - start).days
        for pid, p in self.products.items():
            for reviewer in rng.sample(REVIEWERS, rng.randint(2, 5)):
                rating = rng.choices([5, 4, 3, 2], [50, 30, 14, 6])[0]
                title, text = rng.choice(REVIEW_BANK[rating])
                self.reviews.append({
                    "id": self._rid, "pid": pid, "user": reviewer, "rating": rating, "title": title,
                    "text": text.format(n=p["name"]),
                    "date": (start + timedelta(days=rng.randint(0, span))).isoformat(),
                    "verified": rng.random() < 0.7})
                self._rid += 1

    # ---- auth --------------------------------------------------------------
    @staticmethod
    def _hash(pw):
        # Demo only. In the real backend use bcrypt/argon2 (or Django's auth).
        return hashlib.sha256(pw.encode()).hexdigest()

    def username_taken(self, username):
        return username.strip().lower() in (u.lower() for u in self.users)

    def register(self, username, password, role="customer", full_name="", email="", phone=""):
        username = username.strip()
        for key, val in (("username", username), ("password", password)):
            err = validate_field(key, val)
            if err:
                raise StoreError(err)
        for key, val in (("full_name", full_name), ("email", email), ("phone", phone)):
            if val.strip():
                err = validate_field(key, val)
                if err:
                    raise StoreError(err)
        if self.username_taken(username):
            raise StoreError("That username is already taken.")
        profile = {k: "" for k in PROFILE_KEYS}
        profile.update(address_type="Home", full_name=full_name.strip(), email=email.strip(), phone=phone.strip())
        self.users[username] = {"username": username, "pw_hash": self._hash(password),
                                "role": role, "profile": profile}
        self.carts[username] = {}

    def login(self, username, password):
        user = self.users.get(username.strip())
        if not user or user["pw_hash"] != self._hash(password):
            raise StoreError("Invalid username or password.")
        return {"username": user["username"], "role": user["role"]}

    # ---- profile (delivery details) ------------------------------------------
    def get_profile(self, username):
        return dict(self.users[username]["profile"])

    def profile_complete(self, username):
        p = self.users[username]["profile"]
        return all(p.get(k, "").strip() for k in REQUIRED_PROFILE)

    def save_profile(self, username, data):
        p = {k: str(data.get(k, "")).strip() for k in PROFILE_KEYS}
        for key in ("full_name", "email", "phone", "alt_phone", "address_line1", "city", "state",
                    "postal_code", "country"):
            err = validate_field(key, p[key])
            if err:
                raise StoreError(err)
        if p["address_type"] not in ("Home", "Work"):
            p["address_type"] = "Home"
        self.users[username]["profile"] = p

    # ---- search history & browsing history --------------------------------------
    def record_search(self, username, q):
        q = q.strip()
        if not q:
            return
        h = self.history.setdefault(username, [])
        h[:] = [e for e in h if e["q"].lower() != q.lower()]
        h.insert(0, {"q": q, "ts": datetime.now().strftime("%Y-%m-%d %H:%M")})
        del h[15:]

    def search_history(self, username):
        return list(self.history.get(username, []))

    def remove_search(self, username, q):
        self.history[username] = [e for e in self.history.get(username, []) if e["q"] != q]

    def clear_search_history(self, username):
        self.history[username] = []

    def record_view(self, username, pid):
        v = self.views.setdefault(username, [])
        if pid in v:
            v.remove(pid)
        v.insert(0, pid)
        del v[20:]

    def recently_viewed(self, username, limit=8):
        return [self.products[pid] for pid in self.views.get(username, []) if pid in self.products][:limit]

    # ---- personal recommendations --------------------------------------------------
    def recommendations(self, username, limit=6):
        """Returns ([(product, reason)], personalised?).  Scores products by what the
        customer bought, carted, viewed, searched for and rated highly."""
        cart_pids = set(self.carts.get(username, {}))
        bought, signals = set(), []   # signal: (weight, category, search_terms, reason, source_pid)
        for o in self.list_orders(username):
            if o["status"] == "Cancelled":
                continue
            for _, _, _, pid in o["items"]:
                p = self.products.get(pid)
                if p:
                    bought.add(pid)
                    signals.append((5.0, p["category"], (), f"Because you bought {p['name']}", pid))
        for pid in cart_pids:
            p = self.products.get(pid)
            if p:
                signals.append((3.0, p["category"], (), f"Because you added {p['name']} to your cart", pid))
        for rank, pid in enumerate(self.views.get(username, [])[:10]):
            p = self.products.get(pid)
            if p:
                signals.append((max(1.0, 2.5 - rank * 0.2), p["category"], (),
                                f"Because you viewed {p['name']}", pid))
        for rank, e in enumerate(self.history.get(username, [])[:8]):
            terms = tuple(t for t in re.findall(r"[a-z0-9]+", e["q"].lower()) if len(t) >= 3)
            if terms:
                signals.append((max(1.5, 3.5 - rank * 0.3), None, terms, f'Because you searched "{e["q"]}"', None))
        for r in self.reviews:
            p = self.products.get(r["pid"])
            if p and r["user"] == username and r["rating"] >= 4:
                signals.append((3.0, p["category"], (), f"Because you liked {p['name']}", p["id"]))

        scored = []
        for p in self.products.values():
            if p["stock"] <= 0 or p["id"] in bought or p["id"] in cart_pids:
                continue
            text = f"{p['name']} {p['category']} {p['description']}".lower()
            total, best = 0.0, (0.0, "")
            for w, cat, terms, reason, src in signals:
                if src == p["id"]:
                    continue
                s = 0.0
                if cat and p["category"] == cat:
                    s += w
                if terms and any(t in text for t in terms):
                    s += w * 1.5
                if s:
                    total += s
                    if s > best[0]:
                        best = (s, reason)
            if total > 0:
                scored.append((total + self.rating_summary(p["id"])["avg"] * 0.4, p, best[1]))
        scored.sort(key=lambda x: -x[0])
        picks = [(p, reason) for _, p, reason in scored[:limit]]
        if len(picks) < limit:          # fill with the best-rated products
            have = {p["id"] for p, _ in picks}
            rest = [p for p in self.products.values()
                    if p["id"] not in have and p["id"] not in bought and p["stock"] > 0]
            rest.sort(key=lambda p: (-self.rating_summary(p["id"])["avg"], -self.rating_summary(p["id"])["count"]))
            picks += [(p, "Top rated by customers") for p in rest[: limit - len(picks)]]
        return picks, bool(signals)

    # ---- products ----------------------------------------------------------
    def categories(self):
        return sorted({p["category"] for p in self.products.values()})

    def list_products(self, search="", category="All", sort="Featured"):
        s = search.strip().lower()
        rows = [p for p in self.products.values()
                if (category in ("", "All") or p["category"] == category)
                and (not s or s in p["name"].lower() or s in p["category"].lower()
                     or s in p["description"].lower())]
        if sort == "Price: Low to High":
            rows.sort(key=lambda p: p["price"])
        elif sort == "Price: High to Low":
            rows.sort(key=lambda p: -p["price"])
        elif sort == "Avg. Customer Review":
            rows.sort(key=lambda p: (-self.rating_summary(p["id"])["avg"], -self.rating_summary(p["id"])["count"]))
        else:
            rows.sort(key=lambda p: p["id"])
        return rows

    @staticmethod
    def _validate_product(name, category, price, stock, description, image):
        if not str(name).strip():
            raise StoreError("Product name is required.")
        try:
            price, stock = float(price), int(stock)
        except ValueError:
            raise StoreError("Price must be a number and stock must be a whole number.")
        if price < 0 or stock < 0:
            raise StoreError("Price and stock cannot be negative.")
        image = str(image).strip()
        if image and not os.path.isfile(image):
            raise StoreError("Image file not found.")
        return str(name).strip(), str(category).strip() or "General", price, stock, str(description).strip(), image

    def add_product(self, name, category, price, stock, description="", image=""):
        name, category, price, stock, description, image = self._validate_product(
            name, category, price, stock, description, image)
        pid = self._pid
        self._pid += 1
        self.products[pid] = {"id": pid, "name": name, "category": category, "price": price,
                              "stock": stock, "description": description, "image": image}
        return pid

    def update_product(self, pid, name, category, price, stock, description="", image=""):
        if pid not in self.products:
            raise StoreError("Product not found.")
        name, category, price, stock, description, image = self._validate_product(
            name, category, price, stock, description, image)
        self.products[pid].update(name=name, category=category, price=price, stock=stock,
                                  description=description, image=image)

    def upsert_product_from_csv(self, row, image_folder=""):
        name = (row.get("name") or "").strip()
        if not name:
            raise StoreError("Every CSV row must include a product name.")
        category = (row.get("category") or "General").strip() or "General"
        price = row.get("price", "0")
        stock = row.get("stock", "0")
        description = (row.get("description") or "").strip()
        image_value = (row.get("image_path") or row.get("image") or "").strip()
        product_id = (row.get("product_id") or row.get("id") or "").strip()

        existing_id = None
        if product_id:
            try:
                candidate = int(product_id)
                if candidate in self.products:
                    existing_id = candidate
            except ValueError:
                raise StoreError(f"Invalid product_id '{product_id}' for {name}.")
        if existing_id is None:
            existing_id = next((pid for pid, product in self.products.items()
                                if product["name"].strip().casefold() == name.casefold()), None)

        image_path = ""
        if image_value:
            candidates = []
            if os.path.isabs(image_value):
                candidates.append(image_value)
            else:
                candidates.append(os.path.join(PROJECT_DIR, image_value))
                if image_folder:
                    candidates.append(os.path.join(image_folder, image_value))
                    candidates.append(os.path.join(image_folder, os.path.basename(image_value)))
            source_image = next((os.path.abspath(path) for path in candidates if os.path.isfile(path)), None)
            if source_image is None:
                raise StoreError(f"Image '{image_value}' for '{name}' was not found. Select the folder containing the images and check the filename.")
            ext = os.path.splitext(source_image)[1].lower()
            if ext not in IMAGE_EXTS:
                raise StoreError(f"Unsupported image format for '{name}'. Use PNG, JPG, JPEG, GIF or WEBP.")
            safe_category = re.sub(r"[^A-Za-z0-9_-]+", "_", category).strip("_") or "General"
            target_dir = os.path.join(IMAGE_DIR, safe_category.lower())
            os.makedirs(target_dir, exist_ok=True)
            target_path = os.path.join(target_dir, os.path.basename(source_image))
            if os.path.abspath(source_image) != os.path.abspath(target_path):
                shutil.copy2(source_image, target_path)
            image_path = target_path
        elif existing_id is not None:
            image_path = self.products[existing_id].get("image", "")

        if existing_id is None:
            return self.add_product(name, category, price, stock, description, image_path), "added"
        self.update_product(existing_id, name, category, price, stock, description, image_path)
        return existing_id, "updated"

    def save_catalog_csv(self):
        catalog_path = os.path.join(PROJECT_DIR, "database", "products.csv")
        os.makedirs(os.path.dirname(catalog_path), exist_ok=True)
        with open(catalog_path, "w", newline="", encoding="utf-8") as catalog_file:
            writer = csv.DictWriter(catalog_file, fieldnames=["product_id", "name", "category", "price", "stock", "description", "image_path"])
            writer.writeheader()
            for product in self.list_products():
                image = product.get("image", "")
                if image:
                    try:
                        image = os.path.relpath(image, PROJECT_DIR)
                    except ValueError:
                        pass
                writer.writerow({"product_id": product["id"], "name": product["name"],
                                 "category": product["category"], "price": product["price"],
                                 "stock": product["stock"], "description": product["description"],
                                 "image_path": image})

    def delete_product(self, pid):
        self.products.pop(pid, None)
        self.reviews = [r for r in self.reviews if r["pid"] != pid]
        for cart in self.carts.values():
            cart.pop(pid, None)

    # ---- reviews -----------------------------------------------------------
    def rating_summary(self, pid):
        rows = [r for r in self.reviews if r["pid"] == pid]
        hist = {i: 0 for i in range(1, 6)}
        for r in rows:
            hist[r["rating"]] += 1
        n = len(rows)
        return {"avg": (sum(r["rating"] for r in rows) / n) if n else 0.0, "count": n, "hist": hist}

    def list_reviews(self, pid):
        rows = [r for r in self.reviews if r["pid"] == pid]
        return sorted(rows, key=lambda r: (r["date"], r["id"]), reverse=True)

    def list_all_reviews(self):
        return sorted(self.reviews, key=lambda r: r["id"], reverse=True)

    def get_user_review(self, username, pid):
        return next((r for r in self.reviews if r["pid"] == pid and r["user"] == username), None)

    def has_purchased(self, username, pid):
        return any(o["user"] == username and o["status"] != "Cancelled"
                   and any(item[3] == pid for item in o["items"]) for o in self.orders)

    def add_review(self, username, pid, rating, title, text):
        if pid not in self.products:
            raise StoreError("Product not found.")
        if not 1 <= int(rating) <= 5:
            raise StoreError("Please choose a star rating.")
        title, text = title.strip(), text.strip()
        if not title and not text:
            raise StoreError("Please add a headline or a written review.")
        data = {"rating": int(rating), "title": title, "text": text,
                "date": datetime.now().strftime("%Y-%m-%d"),
                "verified": self.has_purchased(username, pid)}
        existing = self.get_user_review(username, pid)
        if existing:
            existing.update(data)
        else:
            self.reviews.append({"id": self._rid, "pid": pid, "user": username, **data})
            self._rid += 1

    def delete_review(self, rid):
        self.reviews = [r for r in self.reviews if r["id"] != rid]

    # ---- cart --------------------------------------------------------------
    def cart_items(self, username):
        return [(self.products[pid], qty) for pid, qty in self.carts[username].items()
                if pid in self.products]

    def cart_count(self, username):
        return sum(self.carts[username].values())

    def cart_add(self, username, pid, qty):
        p = self.products.get(pid)
        if not p:
            raise StoreError("Product not found.")
        if qty < 1:
            raise StoreError("Quantity must be at least 1.")
        new_qty = self.carts[username].get(pid, 0) + qty
        if new_qty > p["stock"]:
            raise StoreError(f"Only {p['stock']} of '{p['name']}' in stock.")
        self.carts[username][pid] = new_qty

    def cart_set_qty(self, username, pid, qty):
        p = self.products.get(pid)
        if not p:
            raise StoreError("Product not found.")
        if qty < 1:
            return self.cart_remove(username, pid)
        if qty > p["stock"]:
            raise StoreError(f"Only {p['stock']} of '{p['name']}' in stock.")
        self.carts[username][pid] = qty

    def cart_remove(self, username, pid):
        self.carts[username].pop(pid, None)

    def coupon_rate(self, code):
        rate = self.coupons.get(code.strip().upper())
        if rate is None:
            raise StoreError("Invalid coupon code.")
        return rate

    # ---- orders & payments -------------------------------------------------------
    def checkout(self, username, coupon="", payment_method="Cash on Delivery"):
        if not self.profile_complete(username):
            raise StoreError("Please add your delivery details (Account) before placing an order.")
        if payment_method not in PAYMENT_METHODS:
            raise StoreError("Please choose a payment method.")
        items = self.cart_items(username)
        if not items:
            raise StoreError("Your cart is empty.")
        for p, qty in items:
            if qty > p["stock"]:
                raise StoreError(f"Not enough stock for '{p['name']}'.")
        rate = self.coupon_rate(coupon) if coupon.strip() else 0.0
        subtotal = sum(p["price"] * q for p, q in items)
        cod = payment_method == "Cash on Delivery"
        order = {
            "id": self._oid,
            "user": username,
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "items": [(p["name"], p["price"], q, p["id"]) for p, q in items],  # snapshot
            "subtotal": subtotal,
            "discount": subtotal * rate,
            "total": subtotal * (1 - rate),
            "status": "Pending" if cod else "Paid",
            "payment": payment_method,
            "ship_to": self.get_profile(username),                              # snapshot
        }
        self._oid += 1
        for p, q in items:
            p["stock"] -= q
        self.carts[username] = {}
        self.orders.append(order)
        self.payments.append({"order_id": order["id"], "method": payment_method, "amount": order["total"],
                              "status": "Due on delivery" if cod else "Paid", "date": order["date"]})
        return order

    def list_orders(self, username=None):
        rows = [o for o in self.orders if username is None or o["user"] == username]
        return sorted(rows, key=lambda o: o["id"], reverse=True)

    def _find_order(self, oid):
        for o in self.orders:
            if o["id"] == oid:
                return o
        raise StoreError("Order not found.")

    def set_status(self, oid, status):
        o = self._find_order(oid)
        if o["status"] == "Cancelled":
            raise StoreError("Cancelled orders cannot be changed.")
        if status == "Cancelled":
            self._restock(o)
        o["status"] = status

    def cancel_order(self, username, oid):
        o = self._find_order(oid)
        if o["user"] != username:
            raise StoreError("Not your order.")
        if o["status"] not in ("Pending", "Paid"):
            raise StoreError("Only pending or paid orders that haven't shipped can be cancelled.")
        self._restock(o)
        o["status"] = "Cancelled"

    def _restock(self, order):
        for _, _, qty, pid in order["items"]:
            if pid in self.products:
                self.products[pid]["stock"] += qty

    # ---- reports -----------------------------------------------------------
    def report(self):
        valid = [o for o in self.orders if o["status"] != "Cancelled"]
        by_status = {s: 0 for s in ORDER_STATUSES}
        sold, by_method = {}, {}
        for o in self.orders:
            by_status[o["status"]] += 1
        for o in valid:
            by_method[o["payment"]] = by_method.get(o["payment"], 0) + o["total"]
            for name, _, qty, _ in o["items"]:
                sold[name] = sold.get(name, 0) + qty
        report = {
            "orders": len(self.orders),
            "revenue": sum(o["total"] for o in valid),
            "by_status": by_status,
            "by_method": by_method,
            "top": sorted(sold.items(), key=lambda kv: kv[1], reverse=True)[:5],
            "low_stock": [p for p in self.products.values() if p["stock"] <= 10],
            "reviews": len(self.reviews),
        }
        report["fraud_risks"] = scan_orders(self.orders, self.payments)
        report["forecast"] = forecast_demand(self.orders, list(self.products.values()))
        return report

    def smart_search(self, query):
        result = SmartSearch(list(self.products.values())).search(query, limit=50)
        products = [row["product"] for row in result["results"]]
        return {
            "products": products,
            "partial": False,
            "strong": True,
            "corrected": result["did_you_mean"],
            "filters": [],
        }

    def review_insights(self, product_id):
        product = self.products.get(product_id, {})
        reviews = [review for review in self.reviews if review["pid"] == product_id]
        summary = SentimentAnalyzer().summarize(
            [{"rating": review["rating"], "text": f"{review['title']}. {review['text']}".strip(". ")}
             for review in reviews],
            product.get("name", ""),
        )
        insights = [item["text"] for item in summary["praise"] + summary["complaints"]]
        return {"count": summary["count"], "summary": "; ".join(insights)}

class DjangoStore(MockStore):
    """Persist commerce operations through the Django API while reusing the UI's data shapes."""

    backend_enabled = True

    def __init__(self):
        self.api = APIClient()
        self.current_username = None
        self.users = {}
        self.products = {}
        self.carts = {}
        self.orders = []
        self.payments = []
        self.reviews = []
        self.history = {}
        self.views = {}
        self.coupons = {"SAVE10": 0.10}
        self._pid, self._oid, self._rid = 1, 1001, 1
        self._review_cache = {}

    def _call(self, operation, *args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except APIError as exc:
            raise StoreError(str(exc)) from exc

    @staticmethod
    def _product(data):
        product = dict(data)
        product["price"] = float(product["price"])
        product["image"] = product.get("image_path") or product.get("image", "")
        return product

    def _sync_products(self):
        result = self._call(self.api.list_products)
        self.products = {p["id"]: self._product(p) for p in result["products"]}
        self._pid = max(self.products, default=0) + 1

    def _order(self, data):
        status = {
            "PENDING": "Pending", "PROCESSING": "Paid", "SHIPPED": "Shipped",
            "DELIVERED": "Delivered", "CANCELLED": "Cancelled",
        }.get(data["status"], data["status"].title())
        payment = data.get("payments", [{}])[0]
        payments = []
        for item in data.get("payments", []):
            payment_status = {
                "INITIATED": "Initiated", "SUCCESS": "Success",
                "FAILED": "Failed", "REFUNDED": "Refunded",
            }.get(item.get("status"), item.get("status", "").title())
            payment_date = str(item.get("date", data.get("date", "")))
            try:
                payment_date = datetime.fromisoformat(
                    payment_date.replace("Z", "+00:00")
                ).strftime("%Y-%m-%d %H:%M")
            except ValueError:
                pass
            payments.append({
                "order_id": data["id"], "method": item.get("method", ""),
                "amount": float(item.get("amount", 0)), "status": payment_status,
                "date": payment_date,
            })
        order_date = str(data.get("date", ""))
        try:
            order_date = datetime.fromisoformat(order_date.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            pass
        items = [(item["name"], float(item["unit_price"]), item["quantity"], item["product_id"])
                 for item in data.get("items", [])]
        return {
            "id": data["id"], "user": data.get("user", self.current_username or ""),
            "date": order_date, "items": items,
            "subtotal": float(data.get("subtotal", data["total_price"])),
            "discount": float(data.get("discount", 0)), "total": float(data["total_price"]),
            "status": status, "payment": payment.get("method", ""),
            "payments": payments,
            "ship_to": data.get("ship_to") or (
                self.users.get(self.current_username, {}).get("profile", {}) if self.current_username else {}
            ),
        }

    def login(self, username, password):
        result = self._call(self.api.login, username.strip(), password)
        self.current_username = result["username"]
        role = "admin" if result["role"] == "ADMIN" else "customer"
        self.users.setdefault(self.current_username, {
            "username": self.current_username, "role": role,
            "profile": {key: "" for key in PROFILE_KEYS},
        })
        self.users[self.current_username]["role"] = role
        self.reviews = []
        self._review_cache.clear()
        self._sync_products()
        self.get_profile(self.current_username)
        if role == "customer":
            self.cart_items(self.current_username)
            activity = self._call(self.api.get_activity)
            self.history[self.current_username] = activity["searches"]
            self.views[self.current_username] = activity["views"]
        self.list_orders(self.current_username if role != "admin" else None)
        return {"username": self.current_username, "role": role}

    def logout(self):
        self._call(self.api.post, "auth/logout/", {})
        self.current_username = None

    def username_taken(self, username):
        return False

    def register(self, username, password, role="customer", full_name="", email="", phone=""):
        self._call(self.api.register, username.strip(), password, full_name, email, phone)

    def get_profile(self, username):
        if username != self.current_username:
            return {key: "" for key in PROFILE_KEYS}
        profile = self._call(self.api.get_profile)
        profile.setdefault("address_type", "Home")
        if username in self.users:
            self.users[username]["profile"] = profile
        return profile

    def profile_complete(self, username):
        profile = self.get_profile(username)
        return all(profile.get(key, "").strip() for key in REQUIRED_PROFILE)

    def save_profile(self, username, data):
        self._call(self.api.save_profile, data)
        if username in self.users:
            self.users[username]["profile"] = dict(data)

    def record_search(self, username, query):
        super().record_search(username, query)
        if query.strip():
            self._call(self.api.record_activity, "search", query=query.strip())

    def remove_search(self, username, query):
        self._call(self.api.clear_activity, "search", query)
        super().remove_search(username, query)

    def clear_search_history(self, username):
        self._call(self.api.clear_activity, "search")
        super().clear_search_history(username)

    def record_view(self, username, pid):
        super().record_view(username, pid)
        self._call(self.api.record_activity, "view", product_id=pid)

    def categories(self):
        return sorted({product["category"] for product in self.products.values()})

    def list_products(self, search="", category="All", sort="Featured"):
        params = {"search": search or None, "category": category if category != "All" else None}
        result = self._call(self.api.list_products, **params)
        products = [self._product(product) for product in result["products"]]
        self.products.update({product["id"]: product for product in products})
        if sort == "Price: Low to High":
            products.sort(key=lambda product: product["price"])
        elif sort == "Price: High to Low":
            products.sort(key=lambda product: -product["price"])
        elif sort == "Avg. Customer Review":
            products.sort(key=lambda product: -self.rating_summary(product["id"])["avg"])
        return products

    def smart_search(self, query):
        result = self._call(self.api.search_products, query, limit=50)
        return {
            "products": [item["product"] for item in result["results"]],
            "partial": False,
            "strong": True,
            "corrected": result.get("did_you_mean"),
            "filters": [],
        }

    def recommendations(self, username, limit=6):
        result = self._call(self.api.recommend_products, {}, limit)
        items = [(item["product"], item["reason"]) for item in result.get("items", [])]
        return items, result.get("personalized", False)

    def add_product(self, name, category, price, stock, description="", image=""):
        payload = {"name": name, "category": category, "price": price, "stock": stock,
                   "description": description, "image_path": image}
        product = self._product(self._call(self.api.create_product, payload))
        self.products[product["id"]] = product
        return product["id"]

    def update_product(self, pid, name, category, price, stock, description="", image=""):
        payload = {"name": name, "category": category, "price": price, "stock": stock,
                   "description": description, "image_path": image}
        product = self._product(self._call(self.api.update_product, pid, payload))
        self.products[product["id"]] = product

    def upsert_product_from_csv(self, row, image_folder=""):
        sku = row.get("sku", "").strip()
        product_id = row.get("product_id", "").strip()
        existing = next((product for product in self.products.values()
                         if (sku and product.get("sku") == sku)
                         or (product_id and str(product["id"]) == product_id)
                         or product["name"].casefold() == row["name"].strip().casefold()), None)
        local_pid, action = super().upsert_product_from_csv(row, image_folder)
        local_product = self.products.pop(local_pid)
        image_path = local_product.get("image", "")
        if image_path:
            try:
                image_path = os.path.relpath(image_path, PROJECT_DIR)
            except ValueError:
                pass
        payload = {
            "sku": sku, "name": local_product["name"], "category": local_product["category"],
            "price": local_product["price"], "stock": local_product["stock"],
            "description": local_product["description"], "image_path": image_path,
        }
        if existing:
            payload.pop("sku", None)
            if sku:
                payload["sku"] = sku
            result = self._product(self._call(self.api.update_product, existing["id"], payload))
            self.products[result["id"]] = result
            return result["id"], "updated"
        product = self._product(self._call(self.api.create_product, payload))
        self.products[product["id"]] = product
        return product["id"], action

    def save_catalog_csv(self):
        return None

    def delete_product(self, pid):
        self._call(self.api.delete_product, pid)
        self.products.pop(pid, None)

    def rating_summary(self, pid):
        result = self._reviews(pid)
        return {"avg": result["avg_rating"], "count": result["count"],
                "hist": {int(rating): count for rating, count in result["hist"].items()}}

    def _reviews(self, pid):
        if pid not in self._review_cache:
            self._review_cache[pid] = self._call(self.api.product_reviews, pid)
        return self._review_cache[pid]

    def review_insights(self, product_id):
        result = self._call(self.api.review_sentiment, product_id)
        summary = result
        insights = [item["text"] for item in summary.get("praise", []) + summary.get("complaints", [])]
        return {"count": summary.get("count", 0), "summary": "; ".join(insights)}

    def list_reviews(self, pid):
        return self._reviews(pid)["reviews"]

    def list_all_reviews(self):
        self.reviews = self._call(self.api.get, "reviews/")["reviews"]
        return self.reviews

    def get_user_review(self, username, pid):
        return next((review for review in self.list_reviews(pid) if review["user"] == username), None)

    def has_purchased(self, username, pid):
        return any(order["user"] == username and order["status"] == "Delivered"
                   and any(item[3] == pid for item in order["items"])
                   for order in self.list_orders(username))

    def add_review(self, username, pid, rating, title, text):
        self._call(self.api.save_review, pid, rating, title, text)
        self._review_cache.pop(pid, None)

    def delete_review(self, rid):
        self._call(self.api.delete_review, rid)
        self.reviews = [review for review in self.reviews if review["id"] != rid]
        self._review_cache.clear()

    def cart_items(self, username):
        data = self._call(self.api.cart)
        items = []
        for item in data["items"]:
            product = self.products.get(item["product_id"]) or self._product(item["product"])
            self.products[product["id"]] = product
            items.append((product, item["quantity"]))
        return items

    def cart_count(self, username):
        return sum(quantity for _, quantity in self.cart_items(username))

    def cart_add(self, username, pid, qty):
        self._call(self.api.add_cart_item, pid, qty)

    def cart_set_qty(self, username, pid, qty):
        self._call(self.api.update_cart_item, pid, qty)

    def cart_remove(self, username, pid):
        self._call(self.api.remove_cart_item, pid)

    def coupon_rate(self, code):
        if code.strip().upper() != "SAVE10":
            raise StoreError("Invalid coupon code.")
        return 0.10

    def checkout(self, username, coupon="", payment_method="Cash on Delivery"):
        if not self.profile_complete(username):
            raise StoreError("Please add your delivery details (Account) before placing an order.")
        result = self._call(self.api.checkout, coupon, payment_method)
        if payment_method != "Cash on Delivery" and result.get("payments"):
            transaction_id = result["payments"][0]["transaction_id"]
            self._call(self.api.post, "payments/confirm/",
                       {"transaction_id": transaction_id, "success": True})
            result = next(order for order in self._call(self.api.orders) if order["id"] == result["id"])
        self._sync_products()
        self.orders = [self._order(order) for order in self._call(self.api.orders)]
        self.cart_items(username)
        return self._order(result)

    def list_orders(self, username=None):
        orders = [self._order(order) for order in self._call(self.api.orders)]
        if username:
            orders = [order for order in orders if order["user"] == username]
        self.orders = orders
        return orders

    def set_status(self, oid, status):
        backend_status = {"Paid": "PROCESSING"}.get(status, status.upper())
        self._call(self.api.set_order_status, oid, backend_status)
        self.list_orders(None if self.users.get(self.current_username, {}).get("role") == "admin"
                         else self.current_username)
        self._sync_products()

    def cancel_order(self, username, oid):
        self._call(self.api.cancel_order, oid)
        self.list_orders(username)
        self._sync_products()

    def report(self):
        orders = self.list_orders(None)
        reviews = self.list_all_reviews()
        by_status = {status: sum(order["status"] == status for order in orders)
                     for status in ORDER_STATUSES}
        by_method, sold = {}, {}
        valid = [order for order in orders if order["status"] != "Cancelled"]
        for order in valid:
            by_method[order["payment"]] = by_method.get(order["payment"], 0) + order["total"]
            for name, _, quantity, _ in order["items"]:
                sold[name] = sold.get(name, 0) + quantity
        report = {
            "orders": len(orders), "revenue": sum(order["total"] for order in valid),
            "by_status": by_status, "by_method": by_method,
            "top": sorted(sold.items(), key=lambda item: item[1], reverse=True)[:5],
            "low_stock": [product for product in self.products.values() if product["stock"] <= 10],
            "reviews": len(reviews),
        }
        payments = [payment for order in orders for payment in order["payments"]]
        report["fraud_risks"] = scan_orders(orders, payments)
        report["forecast"] = forecast_demand(orders, list(self.products.values()))
        return report


# ----------------------------------------------------------------------------
# Styling
# ----------------------------------------------------------------------------
def money(x):
    return f"{CURRENCY}{x:,.2f}"


def show_error(e):
    messagebox.showerror("Error", str(e))


def initials(name):
    words = re.findall(r"[A-Za-z0-9]+", name)
    return "".join(w[0] for w in words[:2]).upper() or "?"


def stock_text(p):
    if p["stock"] <= 0:
        return "Currently unavailable", RED
    if p["stock"] <= 5:
        return f"Only {p['stock']} left in stock - order soon.", WARN
    return "In Stock", GREEN


def address_lines(p):
    lines = [p.get("full_name", ""), p.get("address_line1", ""), p.get("address_line2", ""),
             f"{p.get('city', '')}, {p.get('state', '')} {p.get('postal_code', '')}".strip(" ,"),
             p.get("country", "")]
    return [ln for ln in lines if ln and ln.strip(", ")]


def order_details_text(o):
    lines = [f"{n}  x{q}  @ {money(p)}" for n, p, q, _ in o["items"]]
    if o["discount"]:
        lines.append(f"Discount: -{money(o['discount'])}")
    lines.append("")
    lines.append(f"Payment: {o.get('payment', '-')}")
    ship = o.get("ship_to")
    if ship:
        lines.append("Ship to: " + ", ".join(address_lines(ship)) + f"   Phone: {ship.get('phone', '')}")
    return "\n".join(lines)


def text_box(parent, editable=False, **kw):
    kw.setdefault("font", (FONT, 10))
    t = tk.Text(parent, wrap="word", relief="flat", bg=SURFACE, fg=TEXT, padx=12, pady=10,
                highlightthickness=1, highlightbackground=LINE, highlightcolor=STAR, **kw)
    if not editable:
        t.configure(state="disabled")
    return t


def link_label(parent, text, command, fg=LINK, bg=SURFACE, hover=LINK_HOVER, font=None, wraplength=0):
    """Clickable text that underlines on hover (like links on a web page)."""
    font = font or (FONT, 10)
    normal = tkfont.Font(font=font)
    under = tkfont.Font(font=font)
    under.configure(underline=True)
    lbl = tk.Label(parent, text=text, fg=fg, bg=bg, font=normal, cursor="hand2",
                   wraplength=wraplength, justify="left", anchor="w")
    lbl._fonts = (normal, under)    # keep references alive
    lbl.bind("<Enter>", lambda e: lbl.configure(fg=hover, font=under))
    lbl.bind("<Leave>", lambda e: lbl.configure(fg=fg, font=normal))
    lbl.bind("<Button-1>", lambda e: command())
    return lbl


def star_row(parent, avg, count=None, bg=SURFACE, size=11, on_count=None):
    f = tk.Frame(parent, bg=bg)
    full = int(round(avg))
    tk.Label(f, text="\u2605" * full, fg=STAR, bg=bg, font=(FONT, size)).pack(side="left")
    tk.Label(f, text="\u2605" * (5 - full), fg=LINE, bg=bg, font=(FONT, size)).pack(side="left")
    if count is not None:
        txt = f"{count:,}" if count else "No ratings"
        if on_count:
            link_label(f, txt, on_count, bg=bg, font=(FONT, max(size - 1, 9))).pack(side="left", padx=(6, 0))
        else:
            tk.Label(f, text=txt, fg=LINK, bg=bg, font=(FONT, max(size - 1, 9))).pack(side="left", padx=(6, 0))
    return f


class StarPicker(tk.Frame):
    """Five clickable stars for writing a review."""

    def __init__(self, master, bg=SURFACE, value=0, size=20, command=None):
        super().__init__(master, bg=bg)
        self.value, self.command = value, command
        self.labels = []
        for i in range(1, 6):
            lbl = tk.Label(self, text="\u2605", font=(FONT, size), bg=bg, cursor="hand2")
            lbl.pack(side="left")
            lbl.bind("<Button-1>", lambda e, i=i: self.set(i))
            lbl.bind("<Enter>", lambda e, i=i: self._paint(i))
            lbl.bind("<Leave>", lambda e: self._paint(self.value))
            self.labels.append(lbl)
        self._paint(value)

    def set(self, v):
        self.value = v
        self._paint(v)
        if self.command:
            self.command(v)

    def _paint(self, n):
        for i, lbl in enumerate(self.labels, 1):
            lbl.configure(fg=STAR if i <= n else LINE)


class ScrollFrame(tk.Frame):
    """A vertically scrollable area; put widgets in .inner"""

    _all = []     # every live ScrollFrame (lets the app scroll the visible page from anywhere)

    def __init__(self, master, bg=BG, height=None):
        super().__init__(master, bg=bg)
        ScrollFrame._all.append(self)
        extra = {"height": height} if height else {}
        # yscrollincrement=1 -> one scroll "unit" is one pixel, so touchpads scroll smoothly
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0, yscrollincrement=1, **extra)
        sb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._resized)
        self.on_resize = None
        self.scroll_canvas = self.canvas      # found by App._wheel

    def _resized(self, e):
        self.canvas.itemconfigure(self._win, width=e.width)
        if self.on_resize:
            self.on_resize(e.width)

    def destroy(self):
        if self in ScrollFrame._all:
            ScrollFrame._all.remove(self)
        super().destroy()

    @staticmethod
    def visible_frame():
        for sf in reversed(ScrollFrame._all):
            try:
                if sf.winfo_viewable():
                    return sf
            except tk.TclError:
                pass
        return None

    def reveal(self, widget):
        """Scroll so that `widget` is visible (used to jump to a field with a mistake)."""
        self.update_idletasks()
        total = max(self.inner.winfo_height(), 1)
        y = widget.winfo_rooty() - self.inner.winfo_rooty()
        self.canvas.yview_moveto(max(0.0, (y - 90) / total))


class FormField:
    """Label + input + inline error text.  Checks the value when you leave the field and
    then live as you type, so mistakes are shown right there - not after you submit."""

    def __init__(self, parent, label, var, validator=None, kind="entry", show=None, values=None):
        self.var, self.touched = var, False
        self.validator = validator or (lambda v: "")
        self.base = "TCombobox" if kind == "combo" else "TEntry"
        self.frame = tk.Frame(parent, bg=SURFACE)
        tk.Label(self.frame, text=label, font=(FONT, 10, "bold"), bg=SURFACE, fg=TEXT).pack(anchor="w")
        if kind == "combo":
            self.widget = ttk.Combobox(self.frame, textvariable=var, values=values or [])
            self.widget.bind("<<ComboboxSelected>>", self._key, add="+")
        else:
            self.widget = ttk.Entry(self.frame, textvariable=var, show=show or "")
            self.widget.bind("<FocusOut>", self._blur, add="+")
        self.widget.pack(fill="x", pady=(2, 0))
        self.widget.bind("<KeyRelease>", self._key, add="+")
        self.err = tk.Label(self.frame, text="", font=(FONT, 9), bg=SURFACE, fg=RED, anchor="w",
                            justify="left", wraplength=380)

    def _show(self, msg):
        if msg:
            self.err.configure(text=msg)
            self.err.pack(anchor="w", pady=(2, 0))
        else:
            self.err.configure(text="")
            self.err.pack_forget()
        self.widget.configure(style=("Error." + self.base) if msg else self.base)

    def validate(self):
        msg = self.validator(self.var.get())
        self._show(msg)
        return not msg

    def refresh(self):
        if self.touched:
            self.validate()

    def _blur(self, _=None):
        self.touched = True
        self.validate()

    def _key(self, _=None):
        if self.touched:
            self.validate()
        elif self.base == "TCombobox":
            self.touched = True
            self.validate()

    def focus(self):
        w = self.widget
        while w is not None and not hasattr(w, "reveal"):
            w = getattr(w, "master", None)
        if w is not None:
            w.reveal(self.widget)
        self.widget.focus_set()


class ImageCache:
    """Loads product images (cached). Falls back to a coloured placeholder tile."""
    PALETTE = ["#5B7C99", "#8E6C8A", "#6B9080", "#C08552", "#7A8CA5", "#A26769", "#6D8B74"]

    def __init__(self):
        self._cache = {}

    @staticmethod
    def find_path(p):
        if p.get("image") and os.path.isfile(p["image"]):
            return p["image"]
        slug = re.sub(r"[^a-z0-9]+", "-", p["name"].lower()).strip("-")
        category_slug = re.sub(r"[^a-z0-9]+", "-", p.get("category", "").lower()).strip("-")
        folders = [os.path.join(IMAGE_DIR, category_slug), IMAGE_DIR]
        for folder in folders:
            for base in (slug, str(p["id"])):
                for ext in IMAGE_EXTS:
                    path = os.path.join(folder, base + ext)
                    if os.path.isfile(path):
                        return path
        return None

    def get(self, p, size):
        path = self.find_path(p)
        key = (p["id"], path, size, p["category"])
        if key not in self._cache:
            photo = self._load(path, size) if path else None
            self._cache[key] = (photo, False) if photo else (self._placeholder(p, size), True)
        return self._cache[key]

    @staticmethod
    def _load(path, size):
        try:
            if PIL_OK:
                im = Image.open(path).convert("RGBA")
                im.thumbnail((size, size), Image.LANCZOS)
                tile = Image.new("RGBA", (size, size), (255, 255, 255, 255))
                tile.paste(im, ((size - im.width) // 2, (size - im.height) // 2), im)
                return ImageTk.PhotoImage(tile)
            if path.lower().endswith((".png", ".gif")):
                img = tk.PhotoImage(file=path)
                factor = max(1, round(max(img.width(), img.height()) / size))
                return img.subsample(factor) if factor > 1 else img
        except Exception:
            pass
        return None

    def _placeholder(self, p, size):
        color = self.PALETTE[sum(map(ord, p["category"])) % len(self.PALETTE)]
        img = tk.PhotoImage(width=size, height=size)
        img.put(color, to=(0, 0, size, size))
        return img


def product_image(parent, p, size, cache, command=None, bg=SURFACE):
    photo, placeholder = cache.get(p, size)
    lbl = tk.Label(parent, image=photo, bg=bg, bd=0, cursor="hand2" if command else "")
    lbl.image = photo
    if placeholder:
        lbl.configure(text=initials(p["name"]), compound="center", fg="white",
                      font=(HEAD, max(14, size // 4), "bold"))
    if command:
        lbl.bind("<Button-1>", lambda e: command())
    return lbl


def make_tree(parent, columns, widths, height=None):
    wrap = ttk.Frame(parent)
    extra = {"height": height} if height else {}
    tree = ttk.Treeview(wrap, columns=columns, show="headings", selectmode="browse", **extra)
    for col, w in zip(columns, widths):
        tree.heading(col, text=col, anchor="w")
        tree.column(col, width=w, anchor="w")
    sb = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    tree.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    return wrap, tree


def selected_id(tree):
    sel = tree.selection()
    return int(sel[0]) if sel else None   # the record id is the row iid


def fill_tree(tree, rows):
    keep = tree.selection()
    tree.delete(*tree.get_children())
    for iid, values in rows:
        tree.insert("", "end", iid=str(iid), values=values)
    if keep and tree.exists(keep[0]):
        tree.selection_set(keep[0])


def logo(parent, bg, size=16, fg="white", command=None):
    f = tk.Frame(parent, bg=bg, cursor="hand2" if command else "")
    a = tk.Label(f, text="Nexus", bg=bg, fg=fg, font=(HEAD, size, "bold"))
    b = tk.Label(f, text="Cart", bg=bg, fg=STAR, font=(HEAD, size, "bold"))
    a.pack(side="left")
    b.pack(side="left")
    if command:
        for w in (f, a, b):
            w.bind("<Button-1>", lambda e: command())
    return f


# ----------------------------------------------------------------------------
# Login screen
# ----------------------------------------------------------------------------
class LoginFrame(tk.Frame):
    def __init__(self, master, store, on_login, on_register):
        super().__init__(master, bg=BG)
        self.store, self.on_login = store, on_login
        outer = tk.Frame(self, bg=BG)
        outer.place(relx=0.5, rely=0.45, anchor="center")
        logo(outer, BG, size=26, fg=NAVY).pack()

        card = tk.Frame(outer, bg=SURFACE, highlightthickness=1, highlightbackground=LINE,
                        padx=30, pady=24)
        card.pack(pady=(16, 0))
        tk.Frame(card, width=330, height=1, bg=SURFACE).pack()
        tk.Label(card, text="Sign in", font=(HEAD, 18, "bold"), bg=SURFACE, fg=TEXT).pack(anchor="w", pady=(0, 8))
        self.user, self.pw = tk.StringVar(), tk.StringVar()
        self.fu = FormField(card, "Username", self.user,
                            validator=lambda v: "" if v.strip() else "Enter your username.")
        self.fp = FormField(card, "Password", self.pw, show="*",
                            validator=lambda v: "" if v else "Enter your password.")
        for f in (self.fu, self.fp):
            f.frame.pack(fill="x", pady=4)
            f.widget.bind("<Return>", lambda e: self.login())
        self.msg = tk.Label(card, text="", font=(FONT, 9), bg=SURFACE, fg=RED, wraplength=330, justify="left")
        self.msg.pack(anchor="w", pady=(4, 0))
        ttk.Button(card, text="Sign in", style="Yellow.TButton", command=self.login).pack(fill="x", pady=(8, 0))
        tk.Frame(card, height=1, bg=LINE).pack(fill="x", pady=16)
        tk.Label(card, text="New to NexusCart?", font=(FONT, 9), bg=SURFACE, fg=MUTED).pack()
        ttk.Button(card, text="Create your account", style="Secondary.TButton",
                   command=on_register).pack(fill="x", pady=(6, 0))
        if not getattr(store, "backend_enabled", False):
            tk.Label(outer, text="Demo: admin/admin123  or  alice/alice123", font=(FONT, 9),
                     bg=BG, fg=MUTED).pack(pady=12)
        self.fu.widget.focus_set()

    def login(self):
        self.msg.configure(text="")
        ok_u, ok_p = self.fu.validate(), self.fp.validate()
        if not (ok_u and ok_p):
            return (self.fu if not ok_u else self.fp).widget.focus_set()
        try:
            user = self.store.login(self.user.get(), self.pw.get())
        except StoreError as e:
            self.msg.configure(text=str(e))
            return
        self.on_login(user)


class RegisterFrame(tk.Frame):
    """Separate sign-up page. Mistakes are flagged under each field as you type, and a
    successful sign-up goes straight into the store (no second login)."""

    def __init__(self, master, store, on_done, on_back):
        super().__init__(master, bg=BG)
        self.store, self.on_done = store, on_done
        scroll = ScrollFrame(self)
        scroll.pack(fill="both", expand=True)
        outer = tk.Frame(scroll.inner, bg=BG)
        outer.pack(pady=24)
        logo(outer, BG, size=26, fg=NAVY).pack()
        card = tk.Frame(outer, bg=SURFACE, highlightthickness=1, highlightbackground=LINE,
                        padx=30, pady=24)
        card.pack(pady=(16, 0))
        tk.Frame(card, width=380, height=1, bg=SURFACE).pack()
        tk.Label(card, text="Create account", font=(HEAD, 18, "bold"), bg=SURFACE, fg=TEXT).pack(
            anchor="w", pady=(0, 8))

        self.v = {k: tk.StringVar() for k in ("full_name", "email", "phone", "username", "password", "confirm")}
        self.fields = {}

        def add(key, label, validator, show=None):
            f = FormField(card, label, self.v[key], validator=validator, show=show)
            f.frame.pack(fill="x", pady=4)
            f.widget.bind("<Return>", lambda e: self.submit())
            self.fields[key] = f

        add("full_name", "Full name", lambda v: validate_field("full_name", v))
        add("email", "Email", lambda v: validate_field("email", v))
        add("phone", "Mobile number", lambda v: validate_field("phone", v))
        add("username", "Choose a username", self._check_username)
        add("password", "Password (at least 6 characters)", lambda v: validate_field("password", v), show="*")
        add("confirm", "Re-enter password",
            lambda v: "" if v == self.v["password"].get() else "Passwords don't match.", show="*")
        self.fields["password"].widget.bind("<KeyRelease>", lambda e: self.fields["confirm"].refresh(), add="+")

        self.show = tk.BooleanVar(value=False)
        tk.Checkbutton(card, text="Show passwords", variable=self.show, command=self.toggle, bg=SURFACE,
                       activebackground=SURFACE, fg=MUTED, font=(FONT, 9), bd=0, highlightthickness=0,
                       selectcolor=SURFACE).pack(anchor="w", pady=(2, 0))
        self.msg = tk.Label(card, text="", font=(FONT, 9), bg=SURFACE, fg=RED, wraplength=380, justify="left")
        self.msg.pack(anchor="w", pady=(6, 0))
        ttk.Button(card, text="Create account", style="Yellow.TButton", command=self.submit).pack(
            fill="x", pady=(8, 0))
        tk.Frame(card, height=1, bg=LINE).pack(fill="x", pady=14)
        row = tk.Frame(card, bg=SURFACE)
        row.pack()
        tk.Label(row, text="Already have an account?", font=(FONT, 9), bg=SURFACE, fg=MUTED).pack(side="left")
        link_label(row, "Sign in", on_back, font=(FONT, 9, "bold")).pack(side="left", padx=5)
        self.fields["full_name"].widget.focus_set()

    def _check_username(self, v):
        err = validate_field("username", v)
        if err:
            return err
        return "That username is already taken." if self.store.username_taken(v) else ""

    def toggle(self):
        for k in ("password", "confirm"):
            self.fields[k].widget.configure(show="" if self.show.get() else "*")

    def submit(self):
        self.msg.configure(text="")
        first = None
        for f in self.fields.values():          # check every field (don't stop at the first)
            f.touched = True
            if not f.validate() and first is None:
                first = f
        if first:
            self.msg.configure(text="Please fix the highlighted fields.")
            return first.focus()
        v = {k: x.get() for k, x in self.v.items()}
        try:
            self.store.register(v["username"], v["password"], "customer",
                                full_name=v["full_name"], email=v["email"], phone=v["phone"])
            user = self.store.login(v["username"], v["password"])      # signed in automatically
        except StoreError as e:
            self.msg.configure(text=str(e))
            return
        self.on_done(user)


# ----------------------------------------------------------------------------
# Profile: form (used for first login and for editing later)
# ----------------------------------------------------------------------------
class ProfileForm(tk.Frame):
    def __init__(self, master, store, username, on_saved, on_cancel=None, submit_text="Save details"):
        super().__init__(master, bg=SURFACE)
        self.store, self.username, self.on_saved = store, username, on_saved
        data = store.get_profile(username)
        self.vars = {k: tk.StringVar(value=data.get(k, "")) for k in PROFILE_KEYS}
        if not self.vars["address_type"].get():
            self.vars["address_type"].set("Home")
        self.fields = {}
        self.columnconfigure(0, weight=1, uniform="col")
        self.columnconfigure(1, weight=1, uniform="col")
        self._row = 0

        self._heading("Contact details")
        self._field("Full name *", "full_name", 0)
        self._field("Email *", "email", 1)
        self._row += 1
        self._field("Mobile number *", "phone", 0)
        self._field("Alternate phone (optional)", "alt_phone", 1)
        self._row += 1
        self._heading("Delivery address")
        self._field("Address line 1 * (house / flat no., street)", "address_line1", 0, span=2)
        self._row += 1
        self._field("Address line 2 (landmark, area - optional)", "address_line2", 0, span=2)
        self._row += 1
        self._field("City / town *", "city", 0)
        self._field("State / province *", "state", 1)
        self._row += 1
        self._field("Postal / PIN code *", "postal_code", 0)
        self._field("Country *", "country", 1, kind="combo")
        self._row += 1

        cell = tk.Frame(self, bg=SURFACE)
        cell.grid(row=self._row, column=0, columnspan=2, sticky="w", pady=4)
        tk.Label(cell, text="Address type", font=(FONT, 10, "bold"), bg=SURFACE, fg=TEXT).pack(side="left", padx=(0, 14))
        for t in ("Home", "Work"):
            ttk.Radiobutton(cell, text=t, value=t, variable=self.vars["address_type"],
                            style="Card.TRadiobutton").pack(side="left", padx=(0, 12))
        self._row += 1
        self._field("Delivery instructions (optional)", "delivery_notes", 0, span=2)
        self._row += 1

        btns = tk.Frame(self, bg=SURFACE)
        btns.grid(row=self._row, column=0, columnspan=2, sticky="w", pady=(14, 0))
        ttk.Button(btns, text=submit_text, style="Yellow.TButton", command=self.save).pack(side="left")
        if on_cancel:
            ttk.Button(btns, text="Cancel", style="Secondary.TButton", command=on_cancel).pack(side="left", padx=8)
        self.msg = tk.Label(btns, text="", font=(FONT, 9), bg=SURFACE, fg=RED)
        self.msg.pack(side="left", padx=12)

    def _heading(self, text):
        tk.Label(self, text=text, font=(HEAD, 12, "bold"), bg=SURFACE, fg=TEXT).grid(
            row=self._row, column=0, columnspan=2, sticky="w", pady=(12 if self._row else 0, 4))
        self._row += 1

    def _field(self, label, key, col, span=1, kind="entry"):
        validator = (lambda v, k=key: validate_field(k, v)) if key != "address_line2" and key != "delivery_notes" else None
        f = FormField(self, label, self.vars[key], validator=validator, kind=kind,
                      values=COUNTRIES if kind == "combo" else None)
        f.frame.grid(row=self._row, column=col, columnspan=span, sticky="new", pady=4,
                     padx=(0, 14) if (col == 0 and span == 1) else 0)
        self.fields[key] = f

    def save(self):
        self.msg.configure(text="")
        first = None
        for f in self.fields.values():          # show every mistake at once, right at the field
            f.touched = True
            if not f.validate() and first is None:
                first = f
        if first:
            self.msg.configure(text="Please fix the highlighted fields.")
            return first.focus()
        try:
            self.store.save_profile(self.username, {k: v.get() for k, v in self.vars.items()})
        except StoreError as e:
            self.msg.configure(text=str(e))
            return
        self.on_saved()


class OnboardingScreen(tk.Frame):
    """Shown right after a customer signs in without delivery details (e.g. a new account)."""

    def __init__(self, master, store, user, on_done, new=False):
        super().__init__(master, bg=BG)
        header = tk.Frame(self, bg=NAVY, padx=16, pady=10)
        header.pack(fill="x")
        logo(header, NAVY).pack(side="left")
        scroll = ScrollFrame(self)
        scroll.pack(fill="both", expand=True)
        card = tk.Frame(scroll.inner, bg=SURFACE, highlightthickness=1, highlightbackground=LINE,
                        padx=34, pady=26)
        card.pack(pady=24)
        tk.Frame(card, width=680, height=1, bg=SURFACE).pack()
        first = (store.get_profile(user["username"])["full_name"] or user["username"]).split()[0]
        tk.Label(card, text=f"Your account is ready, {first}!" if new else f"Welcome, {first}!",
                 font=(HEAD, 20, "bold"), bg=SURFACE, fg=TEXT).pack(anchor="w")
        tk.Label(card, text="Just one more step - tell us where to deliver your orders. You can view and "
                            "edit these details any time from your Account.", font=(FONT, 10), bg=SURFACE,
                 fg=MUTED, wraplength=640, justify="left").pack(anchor="w", pady=(4, 8))
        ProfileForm(card, store, user["username"], on_saved=on_done,
                    submit_text="Save and continue").pack(fill="x")
        link_label(card, "Skip for now (you'll need these details before placing an order)",
                   on_done, font=(FONT, 9)).pack(anchor="w", pady=(14, 0))


# ----------------------------------------------------------------------------
# Customer pages
# ----------------------------------------------------------------------------
class AssistantPage(tk.Frame):
    def __init__(self, master, screen):
        super().__init__(master, bg=BG)
        self.screen = screen
        self.assistant = ShoppingAssistant(
            screen.store, screen.user["username"], currency=CURRENCY,
        )
        tk.Label(self, text="Shopping Assistant", font=(HEAD, 18, "bold"), bg=BG, fg=TEXT).pack(
            anchor="w", padx=22, pady=(16, 4))
        tk.Label(self, text="Ask about products, recommendations, your orders, cart, or store policies.",
                 font=(FONT, 10), bg=BG, fg=MUTED).pack(anchor="w", padx=22, pady=(0, 10))

        chat = tk.Frame(self, bg=SURFACE, highlightthickness=1, highlightbackground=LINE)
        chat.pack(fill="both", expand=True, padx=18, pady=(0, 10))
        self.transcript = tk.Text(chat, wrap="word", state="disabled", font=(FONT, 10),
                                  bg=SURFACE, fg=TEXT, padx=14, pady=12, relief="flat")
        scrollbar = ttk.Scrollbar(chat, orient="vertical", command=self.transcript.yview)
        self.transcript.configure(yscrollcommand=scrollbar.set)
        self.transcript.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.suggestions = tk.Frame(self, bg=BG)
        self.suggestions.pack(fill="x", padx=18, pady=(0, 8))
        bottom = tk.Frame(self, bg=BG)
        bottom.pack(fill="x", padx=18, pady=(0, 16))
        self.message = tk.StringVar()
        self.entry = ttk.Entry(bottom, textvariable=self.message)
        self.entry.pack(side="left", fill="x", expand=True, ipady=5)
        self.entry.bind("<Return>", lambda _event: self.send())
        ttk.Button(bottom, text="Send", style="Orange.TButton", command=self.send).pack(
            side="left", padx=(8, 0))
        self._render_reply(self.assistant.reply("hello"))
        self.entry.focus_set()

    def _append(self, speaker, text):
        self.transcript.configure(state="normal")
        self.transcript.insert("end", f"{speaker}\n{text.strip()}\n\n")
        self.transcript.configure(state="disabled")
        self.transcript.see("end")

    def _render_reply(self, reply):
        self._append("Shopping Assistant", reply["text"])
        if (reply.get("action") or {}).get("type") == "cart_updated":
            self.screen.update_cart_badge()
        for child in self.suggestions.winfo_children():
            child.destroy()
        for suggestion in reply.get("suggestions", []):
            ttk.Button(self.suggestions, text=suggestion,
                       command=lambda text=suggestion: self.send(text)).pack(side="left", padx=(0, 6))

    def send(self, text=None):
        message = (text if text is not None else self.message.get()).strip()
        if not message:
            return
        self.message.set("")
        self._append("You", message)
        try:
            reply = self.assistant.reply(message)
        except StoreError as exc:
            show_error(exc)
            return
        self._render_reply(reply)


class HomePage(tk.Frame):
    """Recommendations, recent searches, recently viewed and the product grid."""

    def __init__(self, master, screen):
        super().__init__(master, bg=BG)
        self.screen = screen
        self.api_client = (screen.store.api if getattr(screen.store, "backend_enabled", False)
                           else APIClient(timeout=2) if os.getenv("NEXUSCART_API_URL") else None)
        self.local_search = SmartSearch(list(screen.store.products.values()))
        self.sections, self._cols = [], 0

        bar = tk.Frame(self, bg=SURFACE, padx=18, pady=8)
        bar.pack(fill="x")
        self.count = tk.Label(bar, bg=SURFACE, fg=TEXT, font=(FONT, 10))
        self.count.pack(side="left")
        self.sort = tk.StringVar(value=SORTS[0])
        box = ttk.Combobox(bar, textvariable=self.sort, values=SORTS, state="readonly", width=22)
        box.pack(side="right")
        box.bind("<<ComboboxSelected>>", lambda e: self.populate())
        tk.Label(bar, text="Sort by:", bg=SURFACE, fg=MUTED, font=(FONT, 10)).pack(side="right", padx=8)
        tk.Frame(self, height=1, bg=LINE).pack(fill="x")

        self.scroll = ScrollFrame(self)
        self.scroll.pack(fill="both", expand=True)
        self.body = self.scroll.inner
        self.scroll.on_resize = self.relayout
        self.populate()

    def _recommendations(self, username):
        s = self.screen
        if self.api_client:
            activity = {"purchases": [], "cart": list(s.store.carts.get(username, {})),
                        "views": list(s.store.views.get(username, [])),
                        "searches": [e["q"] for e in s.store.history.get(username, [])[:8]],
                        "liked": [r["pid"] for r in s.store.reviews
                                  if r["user"] == username and r["rating"] >= 4]}
            for order in s.store.list_orders(username):
                if order["status"] != "Cancelled":
                    activity["purchases"].extend(item[3] for item in order["items"])
            try:
                result = self.api_client.recommend_products(activity, 6)
                items = [(item["product"], item["reason"]) for item in result["items"]]
                return items, result["personalized"]
            except APIError as exc:
                messagebox.showerror("Backend unavailable", str(exc))
                return [], False
        return s.store.recommendations(username, 6)

    def populate(self):
        s = self.screen
        user = s.user["username"]
        for w in self.body.winfo_children():
            w.destroy()
        self.sections, self._cols = [], 0
        discover = not s.query and s.category == "All"
        products = s.store.list_products(s.query, s.category, self.sort.get())
        if s.query:
            category = None if s.category == "All" else s.category
            try:
                if self.api_client:
                    result = self.api_client.search_products(s.query, category=category, limit=50)
                else:
                    result = self.local_search.search(s.query, category=category, limit=50)
            except APIError as exc:
                messagebox.showerror("Backend unavailable", str(exc))
                result = {"results": []}
            products = [item["product"] for item in result["results"]]
            if self.sort.get() == SORTS[1]:
                products.sort(key=lambda p: p["price"])
            elif self.sort.get() == SORTS[2]:
                products.sort(key=lambda p: -p["price"])
            elif self.sort.get() == SORTS[3]:
                products.sort(key=lambda p: (-s.store.rating_summary(p["id"])["avg"], p["price"]))

        if discover:
            self.count.configure(text=f"{len(products)} products")
            self.build_chips()
            recs, personal = self._recommendations(user)
            if recs:
                self.add_section("Recommended for you" if personal else "Top rated by customers",
                                 recs, max_rows=1)
            recent = s.store.recently_viewed(user, 6)
            if recent:
                self.add_section("Recently viewed", [(p, None) for p in recent], max_rows=1)
            self.add_section("All products", [(p, None) for p in products])
        else:
            label = f"{len(products)} result{'s' if len(products) != 1 else ''}"
            if s.query:
                label += f' for "{s.query}"'
            if s.category != "All":
                label += f" in {s.category}"
            self.count.configure(text=label)
            if products:
                self.add_section(None, [(p, None) for p in products])
            else:
                tk.Label(self.body, text="No products match your search.", bg=BG, fg=MUTED,
                         font=(FONT, 12)).pack(padx=40, pady=60)
        self.scroll.canvas.yview_moveto(0)
        self.relayout(self.scroll.canvas.winfo_width())

    def build_chips(self):
        s = self.screen
        hist = s.store.search_history(s.user["username"])[:6]
        if not hist:
            return
        row = tk.Frame(self.body, bg=BG)
        row.pack(anchor="w", padx=24, pady=(14, 0))
        tk.Label(row, text="Recent searches:", bg=BG, fg=MUTED, font=(FONT, 10)).pack(side="left", padx=(0, 8))
        for e in hist:
            link_label(row, f"  {e['q']}  ", lambda q=e["q"]: s.run_search(q), bg=SURFACE,
                       font=(FONT, 10)).pack(side="left", padx=3)
        link_label(row, "Clear", self.clear_history, bg=BG, font=(FONT, 10)).pack(side="left", padx=10)

    def clear_history(self):
        s = self.screen
        s.store.clear_search_history(s.user["username"])
        s.refresh_search_values()
        self.populate()

    def add_section(self, title, items, max_rows=None):
        if title:
            tk.Label(self.body, text=title, font=(HEAD, 14, "bold"), bg=BG, fg=TEXT).pack(
                anchor="w", padx=24, pady=(16, 0))
        holder = tk.Frame(self.body, bg=BG)
        holder.pack(anchor="w", padx=16, pady=(4, 0))
        cards = [self.build_card(holder, p, reason) for p, reason in items]
        self.sections.append((cards, max_rows))

    def relayout(self, width):
        if not self.sections:
            return
        cols = max(1, (width - 32) // (CARD_W + 16))
        if cols == self._cols:
            return
        self._cols = cols
        for cards, max_rows in self.sections:
            limit = cols * max_rows if max_rows else len(cards)
            for i, card in enumerate(cards):
                if i < limit:
                    card.grid(row=i // cols, column=i % cols, padx=8, pady=8, sticky="nsew")
                else:
                    card.grid_remove()

    def build_card(self, parent, p, reason=None):
        s = self.screen
        open_it = lambda pid=p["id"]: s.show_product(pid)
        card = tk.Frame(parent, bg=SURFACE, highlightthickness=1, highlightbackground=LINE,
                        padx=14, pady=12, width=CARD_W)
        tk.Frame(card, width=CARD_W - 30, height=1, bg=SURFACE).pack()   # keeps all cards the same width
        product_image(card, p, CARD_IMG, s.images, command=open_it).pack()
        link_label(card, p["name"], open_it, font=(FONT, 10), wraplength=CARD_W - 30).pack(
            anchor="w", pady=(8, 2), fill="x")
        r = s.store.rating_summary(p["id"])
        star_row(card, r["avg"], r["count"], on_count=open_it).pack(anchor="w")
        tk.Label(card, text=money(p["price"]), font=(HEAD, 15, "bold"), bg=SURFACE, fg=TEXT).pack(
            anchor="w", pady=(4, 0))
        text, color = stock_text(p)
        tk.Label(card, text=text, font=(FONT, 9), bg=SURFACE, fg=color, wraplength=CARD_W - 30,
                 justify="left").pack(anchor="w")
        if reason:
            tk.Label(card, text=reason, font=(FONT, 8), bg=SURFACE, fg=MUTED, wraplength=CARD_W - 30,
                     justify="left").pack(anchor="w", pady=(2, 0))
        btn = ttk.Button(card, text="Add to Cart", style="Yellow.TButton",
                         command=lambda pid=p["id"]: s.add_to_cart(pid))
        btn.pack(fill="x", pady=(8, 0))
        if p["stock"] <= 0:
            btn.state(["disabled"])
        return card


class ProductPage(tk.Frame):
    """Product detail page: big image, info, buy box and customer reviews."""

    def __init__(self, master, screen, pid, jump=False):
        super().__init__(master, bg=BG)
        self.screen, self.pid, self.store = screen, pid, screen.store
        self.store.record_view(screen.user["username"], pid)
        p = self.store.products[pid]
        self.scroll = ScrollFrame(self)
        self.scroll.pack(fill="both", expand=True)
        body = self.scroll.inner

        link_label(body, "\u2039 Back to results", screen.show_home, bg=BG).pack(
            anchor="w", padx=20, pady=(12, 4))
        top = tk.Frame(body, bg=SURFACE, padx=24, pady=22)
        top.pack(fill="x", padx=16, pady=(0, 12))
        top.columnconfigure(1, weight=1)

        product_image(top, p, DETAIL_IMG, screen.images).grid(row=0, column=0, sticky="n", padx=(0, 28))

        info = tk.Frame(top, bg=SURFACE)
        info.grid(row=0, column=1, sticky="nw")
        r = self.store.rating_summary(pid)
        tk.Label(info, text=p["name"], font=(HEAD, 18, "bold"), bg=SURFACE, fg=TEXT,
                 wraplength=420, justify="left").pack(anchor="w")
        row = tk.Frame(info, bg=SURFACE)
        row.pack(anchor="w", pady=(4, 8))
        star_row(row, r["avg"], r["count"], size=13, on_count=self.jump_to_reviews).pack(side="left")
        if r["count"]:
            tk.Label(row, text=f"  {r['avg']:.1f} out of 5", bg=SURFACE, fg=MUTED,
                     font=(FONT, 10)).pack(side="left")
        tk.Frame(info, height=1, bg=LINE).pack(fill="x", pady=6)
        tk.Label(info, text=money(p["price"]), font=(HEAD, 22), bg=SURFACE, fg=PRICE).pack(anchor="w")
        tk.Label(info, text=f"Category: {p['category']}", bg=SURFACE, fg=MUTED,
                 font=(FONT, 10)).pack(anchor="w", pady=(2, 8))
        tk.Label(info, text="About this item", font=(FONT, 11, "bold"), bg=SURFACE, fg=TEXT).pack(anchor="w")
        tk.Label(info, text=p["description"] or "No description available.", bg=SURFACE, fg=TEXT,
                 font=(FONT, 10), wraplength=420, justify="left").pack(anchor="w", pady=(4, 0))

        buy = tk.Frame(top, bg=SURFACE, highlightthickness=1, highlightbackground=LINE, padx=18, pady=16)
        buy.grid(row=0, column=2, sticky="n", padx=(28, 0))
        tk.Label(buy, text=money(p["price"]), font=(HEAD, 18), bg=SURFACE, fg=PRICE).pack(anchor="w")
        text, color = stock_text(p)
        tk.Label(buy, text=text, font=(FONT, 11), bg=SURFACE, fg=color, wraplength=180,
                 justify="left").pack(anchor="w", pady=(6, 10))
        qrow = tk.Frame(buy, bg=SURFACE)
        qrow.pack(anchor="w", pady=(0, 10))
        tk.Label(qrow, text="Qty:", bg=SURFACE, fg=TEXT, font=(FONT, 10)).pack(side="left", padx=(0, 6))
        self.qty = tk.StringVar(value="1")
        ttk.Combobox(qrow, textvariable=self.qty, state="readonly", width=4,
                     values=[str(i) for i in range(1, max(1, min(10, p["stock"])) + 1)]).pack(side="left")
        add = ttk.Button(buy, text="Add to Cart", style="Yellow.TButton", command=self.add)
        add.pack(fill="x", pady=(0, 8))
        now = ttk.Button(buy, text="Buy Now", style="Orange.TButton", command=self.buy_now)
        now.pack(fill="x")
        if p["stock"] <= 0:
            add.state(["disabled"])
            now.state(["disabled"])

        self.build_reviews(body, p, r)
        if jump:
            self.after(150, self.jump_to_reviews)

    # -- actions --------------------------------------------------------------
    def add(self):
        return self.screen.add_to_cart(self.pid, int(self.qty.get()))

    def buy_now(self):
        if self.add():
            self.screen.show_cart()

    def jump_to_reviews(self):
        self.update_idletasks()
        total = max(self.scroll.inner.winfo_height(), 1)
        self.scroll.canvas.yview_moveto(self.rev.winfo_y() / total)

    # -- reviews --------------------------------------------------------------
    def build_reviews(self, body, p, r):
        self.rev = rev = tk.Frame(body, bg=SURFACE, padx=24, pady=22)
        rev.pack(fill="x", padx=16, pady=(0, 16))
        left = tk.Frame(rev, bg=SURFACE)
        left.pack(side="left", anchor="n")
        right = tk.Frame(rev, bg=SURFACE)
        right.pack(side="left", fill="both", expand=True, padx=(44, 0), anchor="n")

        tk.Label(left, text="Customer reviews", font=(HEAD, 15, "bold"), bg=SURFACE, fg=TEXT).pack(anchor="w")
        head = tk.Frame(left, bg=SURFACE)
        head.pack(anchor="w", pady=(6, 2))
        star_row(head, r["avg"], size=15).pack(side="left")
        tk.Label(head, text=f"  {r['avg']:.1f} out of 5" if r["count"] else "  No ratings yet",
                 font=(FONT, 11, "bold"), bg=SURFACE, fg=TEXT).pack(side="left")
        tk.Label(left, text=f"{r['count']} global rating{'s' if r['count'] != 1 else ''}",
                 font=(FONT, 10), bg=SURFACE, fg=MUTED).pack(anchor="w", pady=(0, 8))

        for stars in range(5, 0, -1):
            n = r["hist"][stars]
            pct = round(100 * n / r["count"]) if r["count"] else 0
            line = tk.Frame(left, bg=SURFACE)
            line.pack(anchor="w", pady=2)
            tk.Label(line, text=f"{stars} star", font=(FONT, 10), bg=SURFACE, fg=LINK, width=6,
                     anchor="w").pack(side="left")
            bar = tk.Canvas(line, width=170, height=16, bg=SURFACE, highlightthickness=0)
            bar.create_rectangle(0, 2, 169, 14, fill="#E3E6E6", outline=LINE)
            if pct:
                bar.create_rectangle(0, 2, max(4, 169 * pct / 100), 14, fill=STAR, outline=ORANGE_H)
            bar.pack(side="left", padx=4)
            tk.Label(line, text=f"{pct}%", font=(FONT, 10), bg=SURFACE, fg=LINK, width=4,
                     anchor="w").pack(side="left")

        tk.Frame(left, height=1, bg=LINE).pack(fill="x", pady=16)
        mine = self.store.get_user_review(self.screen.user["username"], self.pid)
        tk.Label(left, text="Review this product" if not mine else "Your review",
                 font=(HEAD, 12, "bold"), bg=SURFACE, fg=TEXT).pack(anchor="w")
        tk.Label(left, text="Share your thoughts with other customers", font=(FONT, 9),
                 bg=SURFACE, fg=MUTED).pack(anchor="w", pady=(0, 6))
        self.picker = StarPicker(left, value=mine["rating"] if mine else 0)
        self.picker.pack(anchor="w", pady=(0, 6))
        self.rtitle = tk.StringVar(value=mine["title"] if mine else "")
        tk.Label(left, text="Headline", font=(FONT, 10, "bold"), bg=SURFACE, fg=TEXT).pack(anchor="w")
        ttk.Entry(left, textvariable=self.rtitle, width=40).pack(anchor="w", pady=(2, 8))
        tk.Label(left, text="Written review", font=(FONT, 10, "bold"), bg=SURFACE, fg=TEXT).pack(anchor="w")
        self.rtext = text_box(left, editable=True, height=5, width=40)
        self.rtext.pack(anchor="w", pady=(2, 8))
        if mine:
            self.rtext.insert("1.0", mine["text"])
        ttk.Button(left, text="Update review" if mine else "Submit", style="Yellow.TButton",
                   command=self.submit).pack(anchor="w")

        tk.Label(right, text="Top reviews", font=(HEAD, 15, "bold"), bg=SURFACE, fg=TEXT).pack(anchor="w")
        reviews = self.store.list_reviews(self.pid)
        if not reviews:
            tk.Label(right, text="No customer reviews yet. Be the first to review this product!",
                     font=(FONT, 10), bg=SURFACE, fg=MUTED).pack(anchor="w", pady=14)
        for rv in reviews:
            self.review_card(right, rv)

    def review_card(self, parent, rv):
        card = tk.Frame(parent, bg=SURFACE, pady=10)
        card.pack(fill="x", anchor="w")
        who = tk.Frame(card, bg=SURFACE)
        who.pack(anchor="w")
        tk.Label(who, text=initials(rv["user"]), width=3, bg="#C4C8C8", fg="white",
                 font=(HEAD, 9, "bold")).pack(side="left")
        tk.Label(who, text=f"  {rv['user']}", font=(FONT, 10, "bold"), bg=SURFACE, fg=TEXT).pack(side="left")
        head = tk.Frame(card, bg=SURFACE)
        head.pack(anchor="w", pady=(4, 0))
        star_row(head, rv["rating"], size=11).pack(side="left")
        tk.Label(head, text=f"  {rv['title']}", font=(FONT, 10, "bold"), bg=SURFACE, fg=TEXT).pack(side="left")
        tk.Label(card, text=f"Reviewed on {rv['date']}", font=(FONT, 9), bg=SURFACE, fg=MUTED).pack(anchor="w")
        if rv["verified"]:
            tk.Label(card, text="Verified Purchase", font=(FONT, 9, "bold"), bg=SURFACE, fg=WARN).pack(anchor="w")
        if rv["text"]:
            tk.Label(card, text=rv["text"], font=(FONT, 10), bg=SURFACE, fg=TEXT, wraplength=520,
                     justify="left").pack(anchor="w", pady=(4, 0))
        tk.Frame(parent, height=1, bg=LINE).pack(fill="x")

    def submit(self):
        try:
            self.store.add_review(self.screen.user["username"], self.pid, self.picker.value,
                                  self.rtitle.get(), self.rtext.get("1.0", "end"))
        except (StoreError, ValueError) as e:
            return show_error(e)
        self.screen.show_product(self.pid, jump=True)
        self.screen.toast("Thanks for your review!")


class CartPage(tk.Frame):
    def __init__(self, master, screen):
        super().__init__(master, bg=BG)
        self.screen, self.store, self.user = screen, screen.store, screen.user["username"]
        self.code = tk.StringVar(value=screen.coupon)
        self.render()

    def render(self):
        for w in self.winfo_children():
            w.destroy()
        s = self.screen
        items = self.store.cart_items(self.user)
        if not items:
            box = tk.Frame(self, bg=SURFACE, padx=30, pady=28)
            box.pack(fill="x", padx=16, pady=16)
            tk.Label(box, text="Your cart is empty", font=(HEAD, 16, "bold"), bg=SURFACE, fg=TEXT).pack(anchor="w")
            link_label(box, "Continue shopping", s.show_home).pack(anchor="w", pady=(8, 0))
            return

        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=16, pady=16)
        wrap.columnconfigure(0, weight=1)
        wrap.rowconfigure(0, weight=1)
        left = ScrollFrame(wrap, bg=SURFACE)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        inner = left.inner
        tk.Label(inner, text="Shopping Cart", font=(HEAD, 18, "bold"), bg=SURFACE, fg=TEXT).pack(
            anchor="w", padx=22, pady=(18, 6))
        tk.Frame(inner, height=1, bg=LINE).pack(fill="x", padx=22)

        for p, qty in items:
            row = tk.Frame(inner, bg=SURFACE, padx=22, pady=14)
            row.pack(fill="x")
            open_it = lambda pid=p["id"]: s.show_product(pid)
            product_image(row, p, THUMB_IMG, s.images, command=open_it).pack(side="left")
            mid = tk.Frame(row, bg=SURFACE)
            mid.pack(side="left", fill="x", expand=True, padx=16)
            link_label(mid, p["name"], open_it, font=(FONT, 11, "bold"), wraplength=380).pack(anchor="w")
            text, color = stock_text(p)
            tk.Label(mid, text=text, font=(FONT, 9), bg=SURFACE, fg=color).pack(anchor="w", pady=(2, 6))
            ctl = tk.Frame(mid, bg=SURFACE)
            ctl.pack(anchor="w")
            tk.Label(ctl, text="Qty:", bg=SURFACE, fg=TEXT, font=(FONT, 10)).pack(side="left", padx=(0, 6))
            var = tk.StringVar(value=str(qty))
            spin = ttk.Spinbox(ctl, from_=1, to=max(1, p["stock"]), textvariable=var, width=4,
                               command=lambda pid=p["id"], v=var, q=qty: self.set_qty(pid, v, q))
            spin.pack(side="left")
            spin.bind("<Return>", lambda e, pid=p["id"], v=var, q=qty: self.set_qty(pid, v, q))
            tk.Label(ctl, text="  |  ", bg=SURFACE, fg=LINE).pack(side="left")
            link_label(ctl, "Delete", lambda pid=p["id"]: self.remove(pid), font=(FONT, 10)).pack(side="left")
            tk.Label(row, text=money(p["price"] * qty), font=(HEAD, 13, "bold"), bg=SURFACE,
                     fg=TEXT).pack(side="right")
            tk.Frame(inner, height=1, bg=LINE).pack(fill="x", padx=22)

        sub = sum(p["price"] * q for p, q in items)
        n = sum(q for _, q in items)
        box = tk.Frame(wrap, bg=SURFACE, padx=20, pady=18, width=290)
        box.grid(row=0, column=1, sticky="n")
        tk.Label(box, text=f"Subtotal ({n} item{'s' if n != 1 else ''}):", font=(FONT, 11),
                 bg=SURFACE, fg=TEXT).pack(anchor="w")
        tk.Label(box, text=money(sub * (1 - s.rate)), font=(HEAD, 20, "bold"), bg=SURFACE,
                 fg=TEXT).pack(anchor="w", pady=(0, 4))
        if s.rate:
            tk.Label(box, text=f"Coupon applied: -{money(sub * s.rate)}", font=(FONT, 10),
                     bg=SURFACE, fg=GREEN).pack(anchor="w")
        tk.Label(box, text="Have a coupon?", font=(FONT, 10), bg=SURFACE, fg=MUTED).pack(anchor="w", pady=(10, 2))
        crow = tk.Frame(box, bg=SURFACE)
        crow.pack(fill="x", pady=(0, 12))
        ttk.Entry(crow, textvariable=self.code, width=14).pack(side="left")
        ttk.Button(crow, text="Apply", style="Secondary.TButton", command=self.apply).pack(side="left", padx=6)
        ttk.Button(box, text="Proceed to checkout", style="Yellow.TButton", command=self.checkout).pack(fill="x")

    def set_qty(self, pid, var, current):
        try:
            qty = int(var.get())
            if qty == current:
                return
            self.store.cart_set_qty(self.user, pid, qty)
        except ValueError:
            show_error("Quantity must be a whole number.")
        except StoreError as e:
            show_error(e)
        self.screen.update_cart_badge()
        self.after_idle(self.render)

    def remove(self, pid):
        self.store.cart_remove(self.user, pid)
        self.screen.update_cart_badge()
        self.render()

    def apply(self):
        s = self.screen
        try:
            s.rate = self.store.coupon_rate(self.code.get())
            s.coupon = self.code.get()
        except StoreError as e:
            s.rate, s.coupon = 0.0, ""
            show_error(e)
        self.render()

    def checkout(self):
        s = self.screen
        if not self.store.cart_items(self.user):
            return
        if not self.store.profile_complete(self.user):
            messagebox.showinfo("Delivery details needed",
                                "Please add your delivery address and contact details before checking out.")
            return s.show_account(edit=True, then=s.show_checkout)
        s.show_checkout()


class CheckoutPage(tk.Frame):
    """Delivery address + payment method + order review."""

    def __init__(self, master, screen):
        super().__init__(master, bg=BG)
        self.screen, self.store, self.user = screen, screen.store, screen.user["username"]
        self.pay = tk.StringVar(value=PAYMENT_METHODS[0])
        items = self.store.cart_items(self.user)
        if not items:
            tk.Label(self, text="Your cart is empty.", font=(HEAD, 14), bg=BG, fg=TEXT).pack(pady=40)
            return

        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=16, pady=16)
        wrap.columnconfigure(0, weight=1)
        wrap.rowconfigure(0, weight=1)
        left = ScrollFrame(wrap, bg=SURFACE)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        inner = left.inner
        tk.Label(inner, text="Checkout", font=(HEAD, 18, "bold"), bg=SURFACE, fg=TEXT).pack(
            anchor="w", padx=22, pady=(18, 8))

        # 1. delivery address
        self._step(inner, "1   Delivery address")
        prof = self.store.get_profile(self.user)
        box = tk.Frame(inner, bg=SURFACE)
        box.pack(fill="x", padx=44, pady=(0, 6))
        tk.Label(box, text="\n".join(address_lines(prof)), font=(FONT, 10), bg=SURFACE, fg=TEXT,
                 justify="left").pack(side="left", anchor="n")
        side = tk.Frame(box, bg=SURFACE)
        side.pack(side="right", anchor="n")
        link_label(side, "Change", lambda: screen.show_account(edit=True, then=screen.show_checkout)).pack(anchor="e")
        tk.Label(inner, text=f"Phone: {prof['phone']}    Email: {prof['email']}    ({prof['address_type']})",
                 font=(FONT, 9), bg=SURFACE, fg=MUTED).pack(anchor="w", padx=44, pady=(0, 6))
        tk.Frame(inner, height=1, bg=LINE).pack(fill="x", padx=22, pady=6)

        # 2. payment
        self._step(inner, "2   Payment method")
        for m in PAYMENT_METHODS:
            ttk.Radiobutton(inner, text=m, value=m, variable=self.pay,
                            style="Card.TRadiobutton").pack(anchor="w", padx=44, pady=3)
        tk.Label(inner, text="This is a demo store - no real payment is taken and no card details are stored.",
                 font=(FONT, 9), bg=SURFACE, fg=MUTED).pack(anchor="w", padx=44, pady=(4, 6))
        tk.Frame(inner, height=1, bg=LINE).pack(fill="x", padx=22, pady=6)

        # 3. items
        self._step(inner, "3   Review items")
        for p, qty in items:
            row = tk.Frame(inner, bg=SURFACE)
            row.pack(fill="x", padx=44, pady=6)
            product_image(row, p, THUMB_IMG, screen.images).pack(side="left")
            tk.Label(row, text=p["name"], font=(FONT, 10, "bold"), bg=SURFACE, fg=TEXT, wraplength=340,
                     justify="left").pack(side="left", padx=14)
            tk.Label(row, text=f"{qty} x {money(p['price'])}", font=(FONT, 10), bg=SURFACE,
                     fg=MUTED).pack(side="right")
        tk.Frame(inner, height=14, bg=SURFACE).pack()

        sub = sum(p["price"] * q for p, q in items)
        disc = sub * screen.rate
        sbox = tk.Frame(wrap, bg=SURFACE, padx=20, pady=18, width=290)
        sbox.grid(row=0, column=1, sticky="n")
        tk.Label(sbox, text="Order summary", font=(HEAD, 13, "bold"), bg=SURFACE, fg=TEXT).pack(anchor="w", pady=(0, 8))
        for label, val in (("Items:", money(sub)), ("Discount:", f"-{money(disc)}" if disc else money(0)),
                           ("Delivery:", "FREE")):
            r = tk.Frame(sbox, bg=SURFACE)
            r.pack(fill="x", pady=1)
            tk.Label(r, text=label, font=(FONT, 10), bg=SURFACE, fg=TEXT).pack(side="left")
            tk.Label(r, text=val, font=(FONT, 10), bg=SURFACE, fg=TEXT).pack(side="right")
        tk.Frame(sbox, height=1, bg=LINE).pack(fill="x", pady=8)
        r = tk.Frame(sbox, bg=SURFACE)
        r.pack(fill="x", pady=(0, 12))
        tk.Label(r, text="Order total:", font=(HEAD, 12, "bold"), bg=SURFACE, fg=PRICE).pack(side="left")
        tk.Label(r, text=money(sub - disc), font=(HEAD, 12, "bold"), bg=SURFACE, fg=PRICE).pack(side="right")
        ttk.Button(sbox, text="Place your order", style="Yellow.TButton", command=self.place).pack(fill="x")

    @staticmethod
    def _step(parent, text):
        tk.Label(parent, text=text, font=(HEAD, 12, "bold"), bg=SURFACE, fg=TEXT).pack(
            anchor="w", padx=22, pady=(8, 4))

    def place(self):
        s = self.screen
        try:
            order = self.store.checkout(self.user, s.coupon, self.pay.get())
        except StoreError as e:
            return show_error(e)
        s.coupon, s.rate = "", 0.0
        s.update_cart_badge()
        messagebox.showinfo("Order placed",
                            f"Order #{order['id']} placed.\nTotal: {money(order['total'])}\n"
                            f"Payment: {order['payment']}\nWe'll deliver to {order['ship_to']['city']}.")
        s.show_orders()


class AccountPage(tk.Frame):
    """View / edit personal details, and manage search history."""

    def __init__(self, master, screen, edit=False, then=None):
        super().__init__(master, bg=BG)
        self.screen, self.store, self.user = screen, screen.store, screen.user["username"]
        self.edit, self.then = edit, then
        self.scroll = ScrollFrame(self)
        self.scroll.pack(fill="both", expand=True)
        self.render()

    def render(self):
        body = self.scroll.inner
        for w in body.winfo_children():
            w.destroy()
        tk.Label(body, text="Your Account", font=(HEAD, 18, "bold"), bg=BG, fg=TEXT).pack(
            anchor="w", padx=24, pady=(16, 6))

        card = tk.Frame(body, bg=SURFACE, padx=26, pady=20)
        card.pack(fill="x", padx=16, pady=8)
        head = tk.Frame(card, bg=SURFACE)
        head.pack(fill="x")
        tk.Label(head, text="Personal & delivery details", font=(HEAD, 13, "bold"), bg=SURFACE,
                 fg=TEXT).pack(side="left")
        if self.edit:
            ProfileForm(card, self.store, self.user, on_saved=self.saved, on_cancel=self.cancel).pack(
                fill="x", pady=(10, 0))
        else:
            ttk.Button(head, text="Edit details", style="Secondary.TButton",
                       command=self.start_edit).pack(side="right")
            self.view_profile(card)

        self.history_card(body)

    def view_profile(self, card):
        prof = self.store.get_profile(self.user)
        if not self.store.profile_complete(self.user):
            warn = tk.Frame(card, bg="#FFF4E5", padx=12, pady=8)
            warn.pack(fill="x", pady=(10, 4))
            tk.Label(warn, text="Your delivery details are incomplete. Add them to be able to place orders.",
                     font=(FONT, 10), bg="#FFF4E5", fg=WARN).pack(anchor="w")
        grid = tk.Frame(card, bg=SURFACE)
        grid.pack(fill="x", pady=(10, 0))
        grid.columnconfigure(1, weight=1)
        rows = [("Username", self.user), ("Full name", prof["full_name"]), ("Email", prof["email"]),
                ("Mobile number", prof["phone"]), ("Alternate phone", prof["alt_phone"]),
                ("Delivery address", "\n".join(address_lines(prof)[1:])),
                ("Address type", prof["address_type"]), ("Delivery instructions", prof["delivery_notes"])]
        for i, (k, v) in enumerate(rows):
            tk.Label(grid, text=k, font=(FONT, 10, "bold"), bg=SURFACE, fg=TEXT, width=20,
                     anchor="nw").grid(row=i, column=0, sticky="nw", pady=4)
            tk.Label(grid, text=v or "-", font=(FONT, 10), bg=SURFACE, fg=TEXT if v else MUTED,
                     justify="left", anchor="nw").grid(row=i, column=1, sticky="nw", pady=4)

    def history_card(self, body):
        card = tk.Frame(body, bg=SURFACE, padx=26, pady=20)
        card.pack(fill="x", padx=16, pady=(8, 16))
        head = tk.Frame(card, bg=SURFACE)
        head.pack(fill="x")
        tk.Label(head, text="Search history", font=(HEAD, 13, "bold"), bg=SURFACE, fg=TEXT).pack(side="left")
        hist = self.store.search_history(self.user)
        if hist:
            ttk.Button(head, text="Clear all", style="Secondary.TButton", command=self.clear_history).pack(side="right")
        else:
            tk.Label(card, text="No searches yet. Things you search for will show up here and help us "
                                "recommend products you'll like.", font=(FONT, 10), bg=SURFACE, fg=MUTED,
                     wraplength=700, justify="left").pack(anchor="w", pady=(8, 0))
        for e in hist:
            row = tk.Frame(card, bg=SURFACE)
            row.pack(fill="x", pady=3)
            link_label(row, e["q"], lambda q=e["q"]: self.screen.run_search(q),
                       font=(FONT, 11)).pack(side="left")
            tk.Label(row, text=f"   {e['ts']}", font=(FONT, 9), bg=SURFACE, fg=MUTED).pack(side="left")
            link_label(row, "Remove", lambda q=e["q"]: self.remove_search(q), font=(FONT, 10)).pack(side="right")

    def start_edit(self):
        self.edit = True
        self.render()

    def cancel(self):
        self.edit = False
        self.render()

    def saved(self):
        self.screen.toast("Details saved")
        if self.then:
            self.then()
        else:
            self.edit = False
            self.render()

    def remove_search(self, q):
        self.store.remove_search(self.user, q)
        self.screen.refresh_search_values()
        self.render()

    def clear_history(self):
        self.store.clear_search_history(self.user)
        self.screen.refresh_search_values()
        self.render()


class ReviewDialog(tk.Toplevel):
    """Pop-up opened from a delivered order: rate and review the product right there."""

    def __init__(self, parent, screen, product, on_saved):
        super().__init__(parent)
        self.screen, self.store, self.p, self.on_saved = screen, screen.store, product, on_saved
        self.user = screen.user["username"]
        self.title("Write a review")
        self.configure(bg=SURFACE)
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        mine = self.store.get_user_review(self.user, product["id"])

        body = tk.Frame(self, bg=SURFACE, padx=26, pady=22)
        body.pack()
        top = tk.Frame(body, bg=SURFACE)
        top.pack(anchor="w", fill="x")
        product_image(top, product, SMALL_IMG, screen.images).pack(side="left")
        info = tk.Frame(top, bg=SURFACE)
        info.pack(side="left", padx=14)
        tk.Label(info, text=product["name"], font=(HEAD, 13, "bold"), bg=SURFACE, fg=TEXT,
                 wraplength=380, justify="left").pack(anchor="w")
        tk.Label(info, text="Verified Purchase", font=(FONT, 9, "bold"), bg=SURFACE, fg=WARN).pack(anchor="w")
        tk.Frame(body, height=1, bg=LINE).pack(fill="x", pady=12)

        tk.Label(body, text="Overall rating", font=(FONT, 10, "bold"), bg=SURFACE, fg=TEXT).pack(anchor="w")
        self.picker = StarPicker(body, value=mine["rating"] if mine else 0, size=26, command=self._rated)
        self.picker.pack(anchor="w", pady=(2, 0))
        self.err_rating = tk.Label(body, text="", font=(FONT, 9), bg=SURFACE, fg=RED)
        self.err_rating.pack(anchor="w")

        tk.Label(body, text="Add a headline", font=(FONT, 10, "bold"), bg=SURFACE, fg=TEXT).pack(anchor="w", pady=(8, 0))
        self.title_var = tk.StringVar(value=mine["title"] if mine else "")
        ttk.Entry(body, textvariable=self.title_var, width=58).pack(fill="x", pady=(2, 0))
        tk.Label(body, text="Add a written review", font=(FONT, 10, "bold"), bg=SURFACE, fg=TEXT).pack(anchor="w", pady=(10, 0))
        self.text = text_box(body, editable=True, height=6, width=58)
        self.text.pack(fill="x", pady=(2, 0))
        if mine:
            self.text.insert("1.0", mine["text"])
        self.text.bind("<KeyRelease>", lambda e: self.err_text.configure(text=""), add="+")
        self.err_text = tk.Label(body, text="", font=(FONT, 9), bg=SURFACE, fg=RED)
        self.err_text.pack(anchor="w")

        btns = tk.Frame(body, bg=SURFACE)
        btns.pack(anchor="e", pady=(12, 0))
        ttk.Button(btns, text="Cancel", style="Secondary.TButton", command=self.destroy).pack(side="left", padx=6)
        ttk.Button(btns, text="Update review" if mine else "Submit review", style="Yellow.TButton",
                   command=self.submit).pack(side="left")
        self.bind("<Escape>", lambda e: self.destroy())

        self.update_idletasks()
        root = parent.winfo_toplevel()
        x = root.winfo_rootx() + (root.winfo_width() - self.winfo_width()) // 2
        y = root.winfo_rooty() + (root.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        self.after(60, self._grab)

    def _grab(self):
        try:
            self.grab_set()
            self.focus_set()
        except tk.TclError:
            pass

    def _rated(self, _):
        self.err_rating.configure(text="")

    def submit(self):
        rating = self.picker.value
        title, text = self.title_var.get().strip(), self.text.get("1.0", "end").strip()
        ok = True
        if rating == 0:
            self.err_rating.configure(text="Please choose a star rating.")
            ok = False
        if not title and not text:
            self.err_text.configure(text="Please add a headline or write a few words.")
            ok = False
        if not ok:
            return
        try:
            self.store.add_review(self.user, self.p["id"], rating, title, text)
        except StoreError as e:
            self.err_text.configure(text=str(e))
            return
        self.destroy()
        self.on_saved()
        self.screen.toast("Thanks for your review!")


class OrderHistoryTab(ttk.Frame):
    """Used by customers (own orders) and reused by admin (all orders)."""

    def __init__(self, master, store, user, admin=False, screen=None):
        super().__init__(master, padding=12)
        self.store, self.user, self.admin, self.screen = store, user, admin, screen
        cols = ("Order #", "Date", "Customer", "Total", "Status") if admin else ("Order #", "Date", "Total", "Status")
        widths = (80, 150, 120, 100, 100) if admin else (90, 170, 110, 110)
        compact = not admin and screen is not None      # customers: short table, roomy item panel
        wrap, self.tree = make_tree(self, cols, widths, height=5 if compact else None)
        wrap.pack(fill="x" if compact else "both", expand=not compact)
        self.tree.bind("<<TreeviewSelect>>", lambda _: self.show_details())

        if admin or screen is None:
            self.dscroll = None
            self.details = text_box(self, height=8)
            self.details.pack(fill="x", pady=10)
        else:                                     # customers get items with "Give review" buttons
            self.details = None
            holder = tk.Frame(self, bg=SURFACE, highlightthickness=1, highlightbackground=LINE)
            holder.pack(fill="both", expand=True, pady=10)
            self.dscroll = ScrollFrame(holder, bg=SURFACE, height=200)
            self.dscroll.pack(fill="both", expand=True)

        row = ttk.Frame(self)
        row.pack(fill="x")
        if admin:
            ttk.Label(row, text="Set status:").pack(side="left")
            self.status = tk.StringVar(value=ORDER_STATUSES[0])
            ttk.Combobox(row, textvariable=self.status, values=ORDER_STATUSES,
                         state="readonly", width=12).pack(side="left", padx=6)
            ttk.Button(row, text="Update", command=self.update_status).pack(side="left")
        else:
            ttk.Button(row, text="Cancel selected order", style="Secondary.TButton",
                       command=self.cancel).pack(side="left")

    def refresh(self):
        orders = self.store.list_orders(None if self.admin else self.user["username"])
        rows = []
        for o in orders:
            vals = [o["id"], o["date"]]
            if self.admin:
                vals.append(o["user"])
            vals += [money(o["total"]), o["status"]]
            rows.append((o["id"], vals))
        fill_tree(self.tree, rows)
        self.show_details()

    def show_details(self):
        oid = selected_id(self.tree)
        o = next((x for x in self.store.orders if x["id"] == oid), None)
        if self.dscroll is not None:
            return self.render_items(o)
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        if o:
            self.details.insert("1.0", order_details_text(o))
        self.details.configure(state="disabled")

    def render_items(self, o):
        inner = self.dscroll.inner
        for w in inner.winfo_children():
            w.destroy()
        if o is None:
            tk.Label(inner, text="Select an order to see its items.", font=(FONT, 10), bg=SURFACE,
                     fg=MUTED).pack(anchor="w", padx=14, pady=14)
            return
        delivered = o["status"] == "Delivered"
        if delivered:
            banner = tk.Frame(inner, bg="#EAF7F0", padx=12, pady=8)
            banner.pack(fill="x")
            tk.Label(banner, text="Delivered - how were your items? Click 'Give review' to tell other customers.",
                     font=(FONT, 10), bg="#EAF7F0", fg=GREEN).pack(anchor="w")
        elif o["status"] != "Cancelled":
            tk.Label(inner, text="You can review the items once this order is delivered.",
                     font=(FONT, 9), bg=SURFACE, fg=MUTED).pack(anchor="w", padx=14, pady=(8, 0))
        for name, price, qty, pid in o["items"]:
            p = self.store.products.get(pid)
            row = tk.Frame(inner, bg=SURFACE, padx=14, pady=6)
            row.pack(fill="x")
            if p:
                product_image(row, p, SMALL_IMG, self.screen.images,
                              command=lambda pid=pid: self.screen.show_product(pid)).pack(side="left")
            tk.Label(row, text=f"{name}\n{qty} x {money(price)}", font=(FONT, 10), bg=SURFACE, fg=TEXT,
                     justify="left").pack(side="left", padx=12)
            if delivered and p:
                mine = self.store.get_user_review(self.user["username"], pid)
                if mine:
                    tk.Label(row, text="\u2605" * mine["rating"], fg=STAR, bg=SURFACE,
                             font=(FONT, 11)).pack(side="right", padx=(8, 0))
                ttk.Button(row, text="Edit your review" if mine else "Give review",
                           style="Secondary.TButton" if mine else "Yellow.TButton",
                           command=lambda p=p: self.give_review(p)).pack(side="right")
        tk.Frame(inner, height=1, bg=LINE).pack(fill="x", padx=14, pady=6)
        extra = []
        if o["discount"]:
            extra.append(f"Discount: -{money(o['discount'])}")
        extra.append(f"Payment: {o.get('payment', '-')}")
        ship = o.get("ship_to")
        if ship:
            extra.append("Ship to: " + ", ".join(address_lines(ship)) + f"   Phone: {ship.get('phone', '')}")
        tk.Label(inner, text="\n".join(extra), font=(FONT, 9), bg=SURFACE, fg=MUTED, justify="left",
                 wraplength=760).pack(anchor="w", padx=14, pady=(0, 10))

    def give_review(self, product):
        ReviewDialog(self, self.screen, product, on_saved=self.show_details)

    def cancel(self):
        oid = selected_id(self.tree)
        if oid is None:
            return
        try:
            self.store.cancel_order(self.user["username"], oid)
            self.refresh()
        except StoreError as e:
            show_error(e)

    def update_status(self):
        oid = selected_id(self.tree)
        if oid is None:
            return messagebox.showinfo("Select an order", "Pick an order first.")
        try:
            self.store.set_status(oid, self.status.get())
            self.refresh()
        except StoreError as e:
            show_error(e)


class OrdersPage(tk.Frame):
    def __init__(self, master, screen):
        super().__init__(master, bg=BG, padx=16, pady=14)
        tk.Label(self, text="Your Orders", font=(HEAD, 18, "bold"), bg=BG, fg=TEXT).pack(anchor="w", pady=(0, 8))
        self.tab = OrderHistoryTab(self, screen.store, screen.user, screen=screen)
        self.tab.pack(fill="both", expand=True)
        self.tab.refresh()


# ----------------------------------------------------------------------------
# Customer screen: Amazon-style header + category bar + swappable pages
# ----------------------------------------------------------------------------
class CustomerScreen(tk.Frame):
    def __init__(self, master, store, user, on_logout, images):
        super().__init__(master, bg=BG)
        self.store, self.user, self.images = store, user, images
        self.category, self.query = "All", ""
        self.coupon, self.rate = "", 0.0
        self.page = None

        header = tk.Frame(self, bg=NAVY, padx=16, pady=10)
        header.pack(fill="x")
        logo(header, NAVY, command=lambda: self.go_home(reset=True)).pack(side="left")
        right = tk.Frame(header, bg=NAVY)
        right.pack(side="right")
        bold = (FONT, 10, "bold")
        link_label(right, f"Hello, {user['username']}", self.show_account, fg="#CCCCCC", bg=NAVY,
                   hover=STAR, font=(FONT, 9)).pack(side="left", padx=10)
        link_label(right, "Ask AI", self.show_assistant, fg="white", bg=NAVY,
                   hover=STAR, font=bold).pack(side="left", padx=10)
        link_label(right, "Orders", self.show_orders, fg="white", bg=NAVY, hover=STAR, font=bold).pack(side="left", padx=10)
        self.cart_link = link_label(right, "Cart (0)", self.show_cart, fg="white", bg=NAVY, hover=STAR, font=bold)
        self.cart_link.pack(side="left", padx=10)
        link_label(right, "Logout", on_logout, fg="white", bg=NAVY, hover=STAR, font=bold).pack(side="left", padx=10)

        mid = tk.Frame(header, bg=NAVY)
        mid.pack(side="left", fill="x", expand=True, padx=24)
        self.search = tk.StringVar()
        self.search_box = ttk.Combobox(mid, textvariable=self.search, font=(FONT, 11))
        self.search_box.pack(side="left", fill="x", expand=True, ipady=3)
        self.search_box.bind("<Return>", lambda e: self.do_search())
        self.search_box.bind("<<ComboboxSelected>>", lambda e: self.after_idle(self.do_search))
        ttk.Button(mid, text="Search", style="Orange.TButton", command=self.do_search).pack(side="left", padx=(6, 0))
        self.refresh_search_values()

        self.subbar = tk.Frame(self, bg=NAVY_2)
        self.subbar.pack(fill="x")
        self.content = tk.Frame(self, bg=BG)
        self.content.pack(fill="both", expand=True)
        self.update_cart_badge()
        self.show_home()

    # -- navigation -------------------------------------------------------------
    def _set(self, page):
        if self.page is not None:
            self.page.destroy()
        self.page = page
        page.pack(fill="both", expand=True)

    def _rebuild_subbar(self):
        for w in self.subbar.winfo_children():
            w.destroy()
        for c in ["All"] + self.store.categories():
            sel = c == self.category
            link_label(self.subbar, c, lambda c=c: self.set_category(c),
                       fg="white" if sel else "#C8CDD3", bg=NAVY_2, hover="white",
                       font=(FONT, 10, "bold" if sel else "normal")).pack(side="left", padx=12, pady=7)

    def show_home(self):
        self._rebuild_subbar()
        self._set(HomePage(self.content, self))

    def go_home(self, reset=False):
        if reset:
            self.query, self.category = "", "All"
            self.search.set("")
        self.show_home()

    def set_category(self, c):
        self.category = c
        self.show_home()

    def do_search(self):
        self.query = self.search.get().strip()
        if self.query:
            self.store.record_search(self.user["username"], self.query)
            self.refresh_search_values()
        self.show_home()

    def run_search(self, q):
        self.search.set(q)
        self.category = "All"
        self.do_search()

    def refresh_search_values(self):
        self.search_box.configure(values=[e["q"] for e in self.store.search_history(self.user["username"])])

    def show_product(self, pid, jump=False):
        self._set(ProductPage(self.content, self, pid, jump))

    def show_cart(self):
        self._set(CartPage(self.content, self))

    def show_checkout(self):
        self._set(CheckoutPage(self.content, self))

    def show_orders(self):
        self._set(OrdersPage(self.content, self))

    def show_assistant(self):
        self._set(AssistantPage(self.content, self))

    def show_account(self, edit=False, then=None):
        self._set(AccountPage(self.content, self, edit=edit, then=then))

    # -- shared actions ------------------------------------------------------------
    def update_cart_badge(self):
        self.cart_link.configure(text=f"Cart ({self.store.cart_count(self.user['username'])})")

    def add_to_cart(self, pid, qty=1):
        try:
            self.store.cart_add(self.user["username"], pid, qty)
        except StoreError as e:
            show_error(e)
            return False
        self.update_cart_badge()
        self.toast("Added to Cart")
        return True

    def toast(self, text):
        t = tk.Label(self, text=text, bg=NAVY_2, fg="white", font=(FONT, 10, "bold"), padx=18, pady=9)
        t.place(relx=0.5, y=116, anchor="n")
        t.lift()
        self.after(1700, t.destroy)


# ----------------------------------------------------------------------------
# Admin screens
# ----------------------------------------------------------------------------
class ProductAdminTab(ttk.Frame):
    FIELDS = ("Name", "Category", "Price", "Stock")

    def __init__(self, master, store, images):
        super().__init__(master, padding=14)
        self.store, self.images = store, images
        wrap, self.tree = make_tree(self, ("ID", "Name", "Category", "Price", "Stock", "Rating"),
                                    (50, 230, 110, 80, 60, 110))
        wrap.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda _: self.load_selected())

        form = ttk.Frame(self)
        form.pack(fill="x", pady=(14, 0))
        self.vars = {f: tk.StringVar() for f in self.FIELDS + ("Description", "Image")}
        for i, f in enumerate(self.FIELDS):
            ttk.Label(form, text=f).grid(row=0, column=i * 2, padx=(8, 2), pady=3)
            ttk.Entry(form, textvariable=self.vars[f], width=16).grid(row=0, column=i * 2 + 1, pady=3)
        ttk.Label(form, text="Description").grid(row=1, column=0, padx=(8, 8), pady=3, sticky="w")
        ttk.Entry(form, textvariable=self.vars["Description"]).grid(
            row=1, column=1, columnspan=7, sticky="ew", pady=3)
        ttk.Label(form, text="Image file").grid(row=2, column=0, padx=(8, 8), pady=3, sticky="w")
        ttk.Entry(form, textvariable=self.vars["Image"]).grid(
            row=2, column=1, columnspan=6, sticky="ew", pady=3)
        ttk.Button(form, text="Browse...", style="Secondary.TButton", command=self.browse).grid(
            row=2, column=7, padx=(6, 0))
        for c in range(1, 8):
            form.columnconfigure(c, weight=1)

        btns = ttk.Frame(form)
        btns.grid(row=3, columnspan=8, pady=(12, 0), sticky="w")
        for text, cmd, sty in (("Add", self.add, "TButton"), ("Update", self.update, "TButton"),
                               ("Delete", self.delete, "Secondary.TButton"),
                               ("Clear", self.clear, "Secondary.TButton"),
                               ("Import / Update CSV + Images", self.import_csv, "TButton")):
            ttk.Button(btns, text=text, command=cmd, style=sty).pack(side="left", padx=4)

    def _values(self):
        return [self.vars[f].get() for f in self.FIELDS + ("Description", "Image")]

    def browse(self):
        path = filedialog.askopenfilename(
            title="Choose product image",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.gif *.webp"), ("All files", "*.*")])
        if path:
            self.vars["Image"].set(path)

    def refresh(self):
        rows = []
        for p in self.store.list_products():
            r = self.store.rating_summary(p["id"])
            rating = f"{r['avg']:.1f} ({r['count']})" if r["count"] else "-"
            rows.append((p["id"], (p["id"], p["name"], p["category"], f"{p['price']:.2f}", p["stock"], rating)))
        fill_tree(self.tree, rows)

    def load_selected(self):
        pid = selected_id(self.tree)
        if pid in self.store.products:
            p = self.store.products[pid]
            for f, v in zip(self.FIELDS + ("Description", "Image"),
                            (p["name"], p["category"], p["price"], p["stock"], p["description"], p["image"])):
                self.vars[f].set(v)

    def clear(self):
        for v in self.vars.values():
            v.set("")
        self.tree.selection_remove(self.tree.selection())

    def add(self):
        try:
            self.store.add_product(*self._values())
            self.store.save_catalog_csv()
            self.clear()
            self.refresh()
        except StoreError as e:
            show_error(e)

    def update(self):
        pid = selected_id(self.tree)
        if pid is None:
            return messagebox.showinfo("Select a product", "Pick a product to update.")
        try:
            self.store.update_product(pid, *self._values())
            self.store.save_catalog_csv()
            self.refresh()
        except StoreError as e:
            show_error(e)

    def import_csv(self):
        csv_path = filedialog.askopenfilename(
            title="Select product catalog CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if not csv_path:
            return
        image_folder = filedialog.askdirectory(title="Select folder containing product images")
        if not image_folder:
            return
        try:
            with open(csv_path, "r", newline="", encoding="utf-8-sig") as catalog_file:
                reader = csv.DictReader(catalog_file)
                if not reader.fieldnames:
                    raise StoreError("The selected CSV is empty or has no header row.")
                normalized = {field.strip().lower() for field in reader.fieldnames if field}
                required = {"name", "category", "price", "stock"}
                missing = required - normalized
                if missing:
                    raise StoreError("CSV is missing required columns: " + ", ".join(sorted(missing)))
                rows = list(reader)
            if not rows:
                raise StoreError("The CSV contains no product rows.")
            added = updated = 0
            for row_number, raw_row in enumerate(rows, start=2):
                row = {(key or "").strip().lower(): (value or "").strip()
                       for key, value in raw_row.items()}
                try:
                    _, action = self.store.upsert_product_from_csv(row, image_folder)
                except (StoreError, ValueError) as error:
                    raise StoreError(f"CSV row {row_number}: {error}")
                if action == "added":
                    added += 1
                else:
                    updated += 1
            self.store.save_catalog_csv()
            self.refresh()
            self.images._cache.clear()
            destination = ("the backend database" if getattr(self.store, "backend_enabled", False)
                           else "database/products.csv")
            messagebox.showinfo(
                "Catalog import complete",
                f"Import finished successfully.\n\nProducts added: {added}\nProducts updated: {updated}\n\n"
                f"The catalog was saved to {destination} and images were copied into frontend/assets/images/.")
        except (OSError, csv.Error, StoreError) as error:
            show_error(error)

    def delete(self):
        pid = selected_id(self.tree)
        if pid is None:
            return
        if messagebox.askyesno("Delete", "Delete this product and its reviews?"):
            self.store.delete_product(pid)
            self.store.save_catalog_csv()
            self.clear()
            self.refresh()


class ReviewAdminTab(ttk.Frame):
    """Moderation: admins can read and remove customer reviews."""

    def __init__(self, master, store):
        super().__init__(master, padding=14)
        self.store = store
        wrap, self.tree = make_tree(self, ("ID", "Product", "Customer", "Rating", "Headline", "Date"),
                                    (50, 190, 110, 70, 230, 100))
        wrap.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda _: self.show_details())
        self.details = text_box(self, height=5)
        self.details.pack(fill="x", pady=10)
        ttk.Button(self, text="Delete selected review", style="Secondary.TButton",
                   command=self.delete).pack(anchor="w")

    def refresh(self):
        rows = []
        for r in self.store.list_all_reviews():
            p = self.store.products.get(r["pid"])
            rows.append((r["id"], (r["id"], p["name"] if p else "?", r["user"],
                                   "\u2605" * r["rating"], r["title"], r["date"])))
        fill_tree(self.tree, rows)
        self.show_details()

    def show_details(self):
        rid = selected_id(self.tree)
        rv = next((r for r in self.store.reviews if r["id"] == rid), None)
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        if rv:
            self.details.insert("1.0", rv["text"] or "(no written review)")
        self.details.configure(state="disabled")

    def delete(self):
        rid = selected_id(self.tree)
        if rid is not None and messagebox.askyesno("Delete", "Delete this review?"):
            self.store.delete_review(rid)
            self.refresh()


class ReportTab(ttk.Frame):
    def __init__(self, master, store):
        super().__init__(master, padding=14)
        self.store = store
        self.text = text_box(self, font=(MONO, 11))
        self.text.pack(fill="both", expand=True)
        ttk.Button(self, text="Refresh", style="Secondary.TButton", command=self.refresh).pack(
            anchor="e", pady=(10, 0))

    def refresh(self):
        r = self.store.report()
        lines = [
            "SALES SUMMARY",
            "-" * 40,
            f"Total orders  : {r['orders']}",
            f"Revenue       : {money(r['revenue'])}  (excludes cancelled)",
            f"Total reviews : {r['reviews']}",
            "",
            "Orders by status",
            *[f"  {s:<10} {n}" for s, n in r["by_status"].items()],
            "",
            "Revenue by payment method",
            *([f"  {m:<22} {money(a)}" for m, a in r["by_method"].items()] or ["  (no sales yet)"]),
            "",
            "Top products (units sold)",
            *([f"  {n:<28} {q}" for n, q in r["top"]] or ["  (no sales yet)"]),
            "",
            "Low stock (<= 10)",
            *([f"  {p['name']:<28} {p['stock']}" for p in r["low_stock"]] or ["  (none)"]),
            "",
            "FRAUD / ORDER-RISK REVIEW",
            "-" * 40,
            *fraud_lines(r["fraud_risks"], currency=CURRENCY),
            "",
            "DEMAND FORECAST",
            "-" * 40,
            *forecast_lines(r["forecast"]),
        ]
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", "\n".join(lines))
        self.text.configure(state="disabled")


class AdminScreen(tk.Frame):
    def __init__(self, master, store, user, on_logout, images):
        super().__init__(master, bg=BG)
        header = tk.Frame(self, bg=NAVY, padx=16, pady=10)
        header.pack(fill="x")
        logo(header, NAVY).pack(side="left")
        tk.Label(header, text=f"Seller Central  \u00b7  {user['username']}", bg=NAVY, fg="#CCCCCC",
                 font=(FONT, 10)).pack(side="left", padx=16)
        link_label(header, "Logout", on_logout, fg="white", bg=NAVY, hover=STAR,
                   font=(FONT, 10, "bold")).pack(side="right")

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=12, pady=(10, 12))
        self.nb.bind("<<NotebookTabChanged>>", self._tab_changed)
        self.nb.add(ProductAdminTab(self.nb, store, images), text="Products")
        self.nb.add(OrderHistoryTab(self.nb, store, user, admin=True), text="Orders")
        self.nb.add(ReviewAdminTab(self.nb, store), text="Reviews")
        self.nb.add(ReportTab(self.nb, store), text="Reports")
        self._tab_changed(None)

    def _tab_changed(self, _):
        tab = self.nametowidget(self.nb.select())
        if hasattr(tab, "refresh"):
            tab.refresh()


# ----------------------------------------------------------------------------
# App
# ----------------------------------------------------------------------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("NexusCart | Online Store")
        self.geometry("1120x740")
        self.minsize(920, 620)
        global FONT, HEAD, MONO
        FONT, HEAD, MONO = apply_style(self)
        ensure_images()
        self.store = DjangoStore() if os.getenv("NEXUSCART_API_URL") else MockStore()
        self.images = ImageCache()
        self._wheel_acc = 0.0
        handlers = [("<MouseWheel>", self._on_mousewheel), ("<Button-4>", self._on_button45),
                    ("<Button-5>", self._on_button45), ("<TouchpadScroll>", self._on_touchpad)]
        for seq, fn in handlers:
            try:                                          # <TouchpadScroll> only exists in Tk 8.7 / 9
                self.bind_all(seq, fn)
                for cls in ("Treeview", "Text"):          # replace their built-in scrolling so all paths agree
                    self.bind_class(cls, seq, fn)
            except tk.TclError:
                pass
        self.bind_all("<Prior>", lambda e: self._on_page_key(e, -1), add="+")    # Page Up / Page Down
        self.bind_all("<Next>", lambda e: self._on_page_key(e, 1), add="+")
        self.show_login()

    # ---- scrolling: mouse wheel, two-finger touchpad (all Tk versions), keyboard ---------
    @staticmethod
    def _decode_touchpad(delta):
        """Tk 8.7/9 'TouchpadScroll' packs (dx, dy) pixel deltas into one integer."""
        d = int(delta) & 0xFFFFFFFF
        dx, dy = (d >> 16) & 0xFFFF, d & 0xFFFF
        if dx >= 0x8000:
            dx -= 0x10000
        if dy >= 0x8000:
            dy -= 0x10000
        return dx, dy

    def _on_mousewheel(self, e):
        d = e.delta
        if sys.platform == "darwin" and abs(d) < 60:       # Tk 8.6 on macOS: small integer steps
            px = -d * 6.0
        else:                                              # Windows / Tk 8.7+: 120 per notch, touchpads smaller
            px = -d / 2.0
        return self._scroll(max(-240.0, min(240.0, px)), e)

    def _on_button45(self, e):                             # X11 wheel / touchpad ticks
        return self._scroll(-45.0 if e.num == 4 else 45.0, e)

    def _on_touchpad(self, e):
        _, dy = self._decode_touchpad(e.delta)
        return self._scroll(-float(dy), e)

    def _widget_under_pointer(self, e):
        try:
            x, y = self.winfo_pointerxy()
            w = self.winfo_containing(x, y)
            if w is not None:
                return w
        except (KeyError, tk.TclError):
            pass
        try:
            return self.winfo_containing(e.x_root, e.y_root)
        except (KeyError, tk.TclError):
            return None

    def _scroll(self, px, e):
        """Scroll whatever is under the pointer by `px` pixels (fractions are accumulated so
        slow touchpad swipes still move)."""
        if px == 0:
            return "break"
        w = self._widget_under_pointer(e)
        if px * self._wheel_acc < 0:                       # direction changed
            self._wheel_acc = 0.0
        self._wheel_acc += px
        target, kind, ww = None, None, w
        while ww is not None:
            canvas = getattr(ww, "scroll_canvas", None)
            if canvas is not None:
                target, kind = canvas, "px"
                break
            if isinstance(ww, (ttk.Treeview, tk.Text)):
                try:
                    lo, hi = ww.yview()
                except tk.TclError:
                    lo, hi = 0.0, 1.0
                if (lo, hi) != (0.0, 1.0):                 # this widget can scroll itself
                    target, kind = ww, "rows"
                    break
            ww = getattr(ww, "master", None)
        if target is None and (w is None or w.winfo_toplevel() is self):
            sf = ScrollFrame.visible_frame()               # fall back to the visible page
            if sf is not None:
                target, kind = sf.canvas, "px"
        if target is None:
            self._wheel_acc = 0.0
            return "break"
        if kind == "px":
            n = int(self._wheel_acc)
            self._wheel_acc -= n
        else:
            n = int(self._wheel_acc / 25.0)
            self._wheel_acc -= n * 25.0
        if n:
            target.yview_scroll(n, "units")
        return "break"

    def _on_page_key(self, e, direction):
        if isinstance(e.widget, (tk.Text, ttk.Treeview)):
            return None
        sf = ScrollFrame.visible_frame()
        if sf is not None:
            sf.canvas.yview_scroll(int(sf.canvas.winfo_height() * 0.9 * direction), "units")
        return None

    def _swap(self, frame):
        for w in self.winfo_children():
            if w is not frame:
                w.destroy()
        frame.pack(fill="both", expand=True)

    def show_login(self):
        self._swap(LoginFrame(self, self.store, self.on_login, self.show_register))

    def show_register(self):
        self._swap(RegisterFrame(self, self.store, self.on_registered, self.show_login))

    def on_registered(self, user):
        self.on_login(user, new=True)            # straight in - no second login

    def on_login(self, user, new=False):
        if user["role"] == "admin":
            return self._swap(AdminScreen(self, self.store, user, self.logout, self.images))

        def enter_store():
            self._swap(CustomerScreen(self, self.store, user, self.logout, self.images))

        try:
            if self.store.profile_complete(user["username"]):
                enter_store()
            else:                              # first login: collect delivery details
                self._swap(OnboardingScreen(self, self.store, user, enter_store, new=new))
        except StoreError as exc:
            show_error(exc)
            self.show_login()

    def logout(self):
        if getattr(self.store, "backend_enabled", False):
            try:
                self.store.logout()
            except StoreError as exc:
                show_error(exc)
        self.show_login()


if __name__ == "__main__":
    App().mainloop()