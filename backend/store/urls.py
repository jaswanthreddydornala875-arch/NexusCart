"""NexusCart - urls.py : the API map the frontend developer needs."""
from django.urls import path
from . import views
 
urlpatterns = [
    # auth
    path("csrf/", views.csrf),
    path("auth/register/", views.register),
    path("auth/login/", views.login_view),
    path("auth/logout/", views.logout_view),
    path("profile/", views.profile),
    path("activity/", views.activity),
    # products
    path("products/", views.product_collection),            # GET all | POST (admin)
    path("products/<int:pk>/", views.product_detail),       # GET | PATCH (admin) | DELETE (admin, soft)
    path("products/search/", views.product_search),
    path("products/<int:product_id>/reviews/", views.product_reviews),
    path("products/<int:product_id>/sentiment/", views.review_sentiment),
    path("recommendations/", views.product_recommendations),
    path("reviews/", views.review_collection),
    path("reviews/<int:review_id>/", views.review_delete),
    # cart
    path("cart/", views.cart_detail),
    path("cart/add/", views.cart_add),
    path("cart/update/", views.cart_update),
    path("cart/remove/", views.cart_remove),
    # checkout, payment, orders
    path("checkout/", views.checkout),
    path("payments/confirm/", views.payment_confirm),
    path("orders/", views.order_list),
    path("orders/<int:pk>/", views.order_detail),
    path("orders/<int:pk>/cancel/", views.order_cancel),
    path("orders/<int:pk>/status/", views.order_update_status),  # admin
]
 