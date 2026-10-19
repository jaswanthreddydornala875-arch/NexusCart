"""Personal recommendations for the signed-in user."""
from flask import Blueprint, jsonify, request

from app.ai.engines import demo_activity, get_engines

bp = Blueprint("recommendations", __name__)


@bp.get("/ping")
def ping():
    return jsonify(module="recommendations", status="not implemented yet")


@bp.post("/")
def recommend():
    """Body: {"purchases": [ids], "cart": [ids], "views": [ids], "searches": ["keyboard"], "liked": [ids]}.
    Stateless for now; once users exist in the database this reads their history itself."""
    activity = request.get_json(silent=True) or {}
    k = min(int(request.args.get("k", 6)), 20)
    return jsonify(get_engines().recommender.recommend(activity, k=k))


@bp.get("/demo/<int:user_number>")
def demo(user_number):
    """Recommendations for a synthetic demo shopper (1-90), handy for trying things out."""
    return jsonify(get_engines().recommender.recommend(demo_activity(user_number), k=6))
