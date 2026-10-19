"""Flask application factory for the NexusCart backend."""
from flask import Flask

from app.routes.products import bp as products_bp
from app.routes.recommendations import bp as recommendations_bp
from app.routes.reviews import bp as reviews_bp


def create_app(config=None):
    app = Flask(__name__)
    if config:
        app.config.update(config)
    app.register_blueprint(products_bp, url_prefix="/api/products")
    app.register_blueprint(recommendations_bp, url_prefix="/api/recommendations")
    app.register_blueprint(reviews_bp, url_prefix="/api/reviews")
    return app
