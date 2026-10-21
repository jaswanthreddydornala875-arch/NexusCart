"""Flask application factory for the NexusCart backend."""
from flask import Flask

from app.config import Config
from app.extensions import db
from app.routes.products import bp as products_bp
from app.routes.recommendations import bp as recommendations_bp
from app.routes.reviews import bp as reviews_bp


def create_app(config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if config:
        if isinstance(config, dict):
            app.config.update(config)
        else:
            app.config.from_object(config)
    db.init_app(app)
    from app.models import product  # noqa: F401

    app.register_blueprint(products_bp, url_prefix="/api/products")
    app.register_blueprint(recommendations_bp, url_prefix="/api/recommendations")
    app.register_blueprint(reviews_bp, url_prefix="/api/reviews")
    return app
