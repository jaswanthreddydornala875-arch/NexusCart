"""
Demand forecasting: how fast is each product selling, and when will the stock run out?

Two simple, explainable time-series methods (no training data or libraries needed):
  * weighted moving average (WMA)  - recent days count more than old days
  * Holt's linear trend method     - double exponential smoothing: tracks the level AND the trend,
                                     so a product that is speeding up is forecast higher

With little history only the WMA is used; once a product has sold on enough different days the two
are averaged.  Every row also says how much to trust it (confidence) and when stock runs out.

Orders are plain dicts:  {"date": "YYYY-MM-DD HH:MM", "status": ..., "items": [(name, price, qty, product_id)]}
"""
import math
from collections import defaultdict
from datetime import date, datetime, timedelta


def _order_day(o):
    try:
        return datetime.strptime(str(o["date"])[:10], "%Y-%m-%d").date()
    except (ValueError, KeyError):
        return None


def daily_sales(orders, window=30, today=None):
    """{product_id: [units sold per day]} for the last `window` days, oldest first, today last.
    Cancelled orders are ignored.  Handy for drawing a sales chart."""
    today = today or date.today()
    series = defaultdict(lambda: [0] * window)
    for o in orders:
        if o.get("status") == "Cancelled":
            continue
        d = _order_day(o)
        if d is None:
            continue
        age = (today - d).days
        if 0 <= age < window:
            for _name, _price, qty, pid in o["items"]:
                series[pid][window - 1 - age] += qty
    return series


def holt_forecast(series, horizon=7, alpha=0.4, beta=0.2):
    """Holt's linear trend method.  Returns the expected units for each of the next `horizon` days
    (never negative).  alpha smooths the level, beta smooths the trend."""
    if not series:
        return [0.0] * horizon
    level, trend = float(series[0]), 0.0
    for x in series[1:]:
        previous = level
        level = alpha * x + (1 - alpha) * (level + trend)
        trend = beta * (level - previous) + (1 - beta) * trend
    return [max(0.0, level + trend * h) for h in range(1, horizon + 1)]


def _weighted_rate(series, decay):
    """Weighted moving average of units per day (the newest day has weight 1, older days less)."""
    n = len(series)
    weights = [decay ** (n - 1 - i) for i in range(n)]
    return sum(x * w for x, w in zip(series, weights)) / sum(weights)


def forecast_demand(orders, products, today=None, window=30, horizon=7, decay=0.94, cover_days=21):
    """One row per product, most urgent first:
       product, units_30d, per_day, days_left, predicted (units in the next `horizon` days),
       trend (Rising / Steady / Falling), status, suggest (units to reorder for `cover_days` of cover),
       confidence (High / Medium / Low), stockout (expected date or None)."""
    today = today or date.today()
    series = daily_sales(orders, window, today)
    rows = []
    for p in products:
        s = series.get(p["id"], [0] * window)
        total = sum(s)
        active_days = sum(1 for x in s if x)
        rate = _weighted_rate(s, decay)
        if active_days >= 8:                                   # enough history: blend in the trend method
            holt = sum(holt_forecast(s, horizon)) / horizon
            rate = 0.5 * rate + 0.5 * min(holt, 3 * max(rate, 0.1))      # cap so one spike cannot run away
        recent, before = sum(s[-7:]), sum(s[-14:-7])
        trend = "Rising" if recent >= 3 and recent > before * 1.3 else \
                "Falling" if before >= 3 and before > recent * 1.3 else "Steady"
        days_left = p["stock"] / rate if rate > 0 else None
        if p["stock"] <= 0:
            status = "Out of stock"
        elif rate <= 0:
            status = "No recent sales"
        elif days_left < 7:
            status = "Restock now"
        elif days_left < 14:
            status = "Restock soon"
        else:
            status = "OK"
        confidence = "High" if active_days >= 10 else "Medium" if active_days >= 4 else "Low"
        stockout = today + timedelta(days=int(days_left)) if days_left is not None else None
        rows.append({"product": p, "units_30d": total, "per_day": rate, "days_left": days_left,
                     "predicted": rate * horizon, "trend": trend, "status": status,
                     "suggest": max(0, math.ceil(rate * cover_days - p["stock"])) if rate > 0 else 0,
                     "confidence": confidence, "stockout": stockout})
    order = {"Out of stock": 0, "Restock now": 1, "Restock soon": 2, "OK": 3, "No recent sales": 4}
    rows.sort(key=lambda r: (order[r["status"]], r["days_left"] if r["days_left"] is not None else 1e9))
    return rows


def forecast_summary(rows):
    """Headline numbers for a dashboard."""
    return {"expected_units": round(sum(r["predicted"] for r in rows)),
            "restock_now": sum(r["status"] == "Restock now" for r in rows),
            "restock_soon": sum(r["status"] == "Restock soon" for r in rows),
            "out_of_stock": sum(r["status"] == "Out of stock" for r in rows),
            "rising": sum(r["trend"] == "Rising" for r in rows)}


def forecast_lines(rows, limit=8):
    """Text lines for the admin report."""
    if not any(r["units_30d"] for r in rows):
        return ["  Not enough sales history yet - place orders or press 'Load demo sales data'."]
    sm = forecast_summary(rows)
    lines = [f"  Expected demand next 7 days: {sm['expected_units']} units   |   restock now: "
             f"{sm['restock_now']}   soon: {sm['restock_soon']}   out of stock: {sm['out_of_stock']}"]
    need = [r for r in rows if r["status"] in ("Out of stock", "Restock now", "Restock soon")
            and (r["units_30d"] or r["status"] == "Out of stock")]
    if not need:
        return lines + ["  Every product has enough stock for the next two weeks."]
    for r in need[:limit]:
        left = "-" if r["days_left"] is None else f"{r['days_left']:.0f} days"
        lines.append(f"  {r['product']['name'][:24]:<24} stock {r['product']['stock']:>3}  "
                     f"{r['per_day']:>4.1f}/day  {left:>8}  {r['status']:<12} {r['trend']:<8} "
                     f"order ~{r['suggest']:<3} ({r['confidence'].lower()} confidence)")
    return lines
