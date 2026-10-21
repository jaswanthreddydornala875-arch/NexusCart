"""Catalog item (table: products).

`sku` is the stable key the bulk importer matches on, so importing the same file again updates
products instead of duplicating them. `image_path` is relative to frontend/assets/images,
e.g. "electronics/wireless-mouse.png".
"""
from datetime import datetime, timezone

from app.extensions import db


def _now():
    return datetime.now(timezone.utc)


class Product(db.Model):
    __tablename__ = "products"
    __table_args__ = (db.CheckConstraint("price >= 0", name="ck_products_price"),
                      db.CheckConstraint("stock >= 0", name="ck_products_stock"))

    id = db.Column(db.BigInteger().with_variant(db.Integer, "sqlite"), primary_key=True)
    sku = db.Column(db.String(40), nullable=False, unique=True)
    name = db.Column(db.String(150), nullable=False)
    category = db.Column(db.String(60), nullable=False, index=True)
    brand = db.Column(db.String(80))
    price = db.Column(db.Numeric(10, 2), nullable=False)
    stock = db.Column(db.Integer, nullable=False, default=0)
    description = db.Column(db.Text, nullable=False, default="")
    image_path = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    def to_dict(self):
        return {"id": self.id, "sku": self.sku, "name": self.name, "category": self.category,
                "brand": self.brand, "price": float(self.price), "stock": self.stock,
                "description": self.description, "image_path": self.image_path, "is_active": self.is_active}
