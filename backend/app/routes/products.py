"""List, search, view, and admin add/update/delete products."""
from flask import Blueprint, jsonify, request

from app.ai.engines import get_engines

bp = Blueprint("products", __name__)


@bp.get("/ping")
def ping():
    return jsonify(module="products", status="not implemented yet")


@bp.get("/search")
def search():
    """Smart search. Examples: /api/products/search?q=wireles mouse   ?q=earphones under 50
    Uses the demo catalog until the products table is connected."""
    q = request.args.get("q", "")
    limit = min(int(request.args.get("limit", 10)), 50)
    result = get_engines().search.search(q, limit=limit, category=request.args.get("category"),
                                         in_stock_only=request.args.get("in_stock") == "1")
    return jsonify(result)
