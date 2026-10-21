"""
Fraud / risk detection for orders and payments  -  rule-based + statistics, offline, explainable.

Each order gets a risk score from 0 to 100 and a list of plain-English reasons, so an admin can
see WHY an order looks odd.  Nothing is blocked automatically: this is a review queue for humans.

Signals (points are added up and capped at 100):
  * order value far above the store's normal orders        (robust z-score using the median / MAD)
  * order value far above THIS customer's own history, or a first order that is unusually large
  * bulk quantity of a single item
  * many orders in a short time (velocity)
  * many cancelled orders in a row
  * the same delivery address / phone used by several accounts, disposable e-mail addresses
  * big order placed in the middle of the night, high-value cash on delivery
  * payment problems: amount differs from the order total, repeated failed payments

Orders are plain dicts:  {"id", "user", "date": "YYYY-MM-DD HH:MM", "items": [(name, price, qty, pid)],
"total", "status", "payment", "ship_to": {...}}.  Payments: {"order_id", "method", "amount", "status", "date"}.
"""
import re
import statistics
from datetime import datetime

DISPOSABLE_DOMAINS = {"mailinator.com", "tempmail.com", "10minutemail.com", "guerrillamail.com",
                      "yopmail.com", "trashmail.com", "getnada.com", "sharklasers.com",
                      "dispostable.com", "throwawaymail.com"}
LEVELS = ((60, "High"), (30, "Medium"), (0, "Low"))


def _when(value):
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(value)[:16 if fmt.endswith("M") else 10], fmt)
        except ValueError:
            pass
    return None


def _level(score):
    return next(name for floor, name in LEVELS if score >= floor)


def _robust_z(x, values):
    """How many 'typical deviations' x is above the median (median absolute deviation based, so a few
    huge orders do not hide each other).  Falls back to a ratio when every value is identical."""
    med = statistics.median(values)
    mad = statistics.median(abs(v - med) for v in values)
    if mad > 0:
        return 0.6745 * (x - med) / mad
    return (x / med - 1) * 3 if med > 0 else 0.0


def _address_key(ship):
    line, postal = str(ship.get("address_line1", "")).lower().strip(), str(ship.get("postal_code", "")).lower().strip()
    return (re.sub(r"\W+", " ", line), postal) if line and postal else None


def _digits(text):
    return re.sub(r"\D", "", str(text or ""))


def assess_order(order, all_orders, payments=(), now=None):
    """Risk assessment of ONE order.  `all_orders` should include every order in the store (it may include
    this one).  Returns {"order_id", "user", "total", "score", "level", "reasons"}."""
    user, total = order.get("user"), float(order.get("total", 0))
    when = _when(order.get("date"))
    others = [o for o in all_orders if o.get("id") != order.get("id")]
    live = [o for o in others if o.get("status") != "Cancelled"]
    found = []                                               # (points, reason)

    # 1. how big is it compared with the rest of the store?
    store_totals = [o["total"] for o in live]
    if len(store_totals) >= 5:
        z = _robust_z(total, store_totals)
        if z >= 3.5:
            found.append((25, f"order value {total:,.2f} is far above the store's usual orders"))
        elif z >= 2.5:
            found.append((12, f"order value {total:,.2f} is well above the store's usual orders"))

    # 2. ... and compared with this customer's own history
    mine = [o["total"] for o in live if o.get("user") == user]
    if len(mine) >= 2 and total > 3 * statistics.median(mine):
        found.append((20, "much larger than this customer's usual orders"))
    elif not mine and len(store_totals) >= 5 and total >= sorted(store_totals)[int(0.9 * (len(store_totals) - 1))]:
        found.append((15, "first order from this customer and unusually large"))

    # 3. bulk quantity
    biggest = max((it[2] for it in order.get("items", [])), default=0)
    if biggest >= 5:
        found.append((15, f"bulk quantity ({biggest} of one item)"))

    # 4. velocity: many orders from the same customer close together
    if when:
        gaps = [abs((_when(o.get("date")) - when).total_seconds()) / 60
                for o in others if o.get("user") == user and _when(o.get("date"))]
        within_hour = sum(g <= 60 for g in gaps)
        within_day = sum(g <= 24 * 60 for g in gaps)
        if within_hour >= 2:
            found.append((30, f"{within_hour + 1} orders within one hour"))
        elif within_day >= 4:
            found.append((15, f"{within_day + 1} orders within 24 hours"))

    # 5. cancellation habit (last five earlier orders of the customer)
    history = sorted((o for o in others if o.get("user") == user), key=lambda o: str(o.get("date")))[-5:]
    if sum(o.get("status") == "Cancelled" for o in history) >= 3:
        found.append((15, "this customer cancelled most of their recent orders"))

    # 6. shared identity details across accounts
    ship = order.get("ship_to") or {}
    key = _address_key(ship)
    if key:
        shared = {o.get("user") for o in others if _address_key(o.get("ship_to") or {}) == key} - {user}
        if len(shared) >= 2:
            found.append((25, f"same delivery address used by {len(shared)} other accounts"))
    phone = _digits(ship.get("phone"))
    if len(phone) >= 7:
        shared = {o.get("user") for o in others if _digits((o.get("ship_to") or {}).get("phone")) == phone} - {user}
        if len(shared) >= 2:
            found.append((15, f"same phone number used by {len(shared)} other accounts"))
    domain = str(ship.get("email", "")).rsplit("@", 1)[-1].lower()
    if domain in DISPOSABLE_DOMAINS:
        found.append((10, f"disposable e-mail address ({domain})"))

    # 7. timing and payment method
    typical = statistics.median(store_totals) if store_totals else 0
    if when and when.hour < 5 and typical and total >= typical:
        found.append((5, "placed in the middle of the night"))
    if order.get("payment") == "Cash on Delivery" and typical and total >= 3 * typical:
        found.append((10, "high-value cash on delivery"))

    # 8. payment records
    owner = {o.get("id"): o.get("user") for o in all_orders}
    mine_pay = [p for p in payments if p.get("order_id") == order.get("id")]
    if any(abs(float(p.get("amount", 0)) - total) > 0.01 for p in mine_pay):
        found.append((40, "payment amount does not match the order total"))
    if when:
        failed = [p for p in payments if p.get("status") == "Failed" and owner.get(p.get("order_id")) == user
                  and _when(p.get("date")) and abs((_when(p.get("date")) - when).total_seconds()) <= 3600]
        if len(failed) >= 3:
            found.append((25, f"{len(failed)} failed payments within an hour"))

    score = min(100, sum(points for points, _ in found))
    found.sort(key=lambda t: -t[0])
    return {"order_id": order.get("id"), "user": user, "total": total, "score": score,
            "level": _level(score), "reasons": [text for _, text in found]}


def scan_orders(orders, payments=(), min_score=30):
    """Assess every non-cancelled order and return those at or above `min_score`, riskiest first."""
    results = [assess_order(o, orders, payments) for o in orders if o.get("status") != "Cancelled"]
    return sorted((r for r in results if r["score"] >= min_score), key=lambda r: (-r["score"], -r["order_id"]))


def fraud_lines(results, currency="$", limit=8):
    """Text lines for the admin report."""
    if not results:
        return ["  No risky orders found."]
    lines = []
    for r in results[:limit]:
        lines.append(f"  #{r['order_id']:<5} {str(r['user'])[:14]:<14} {currency}{r['total']:>9,.2f}  "
                     f"{r['level']:<6} {r['score']:>3}/100")
        lines.extend(f"        - {reason}" for reason in r["reasons"][:3])
    if len(results) > limit:
        lines.append(f"  ... and {len(results) - limit} more")
    return lines
