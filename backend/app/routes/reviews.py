"""List and write reviews (Give review after Delivered)."""
from flask import Blueprint, jsonify

from app.ai.engines import get_engines

bp = Blueprint("reviews", __name__)


@bp.get("/ping")
def ping():
    return jsonify(module="reviews", status="not implemented yet")


@bp.get("/sentiment/<int:product_id>")
def sentiment(product_id):
    """What customers praise / complain about, plus reviews whose stars disagree with the words."""
    e = get_engines()
    product = e.products.get(product_id)
    if product is None:
        return jsonify(error="Product not found"), 404
    reviews = [r for r in e.reviews if r["product_id"] == product_id]
    return jsonify(product=product["name"], **e.sentiment.summarize(reviews, product["name"]))
