from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_nested import routers as nested_routers

from .views import (
    CartItemViewSet,
    CartViewSet,
    ClientViewSet,
    OrderItemViewSet,
    OrderPaymentProofViewSet,
    OrderViewSet,
)

app_name = 'shopping' 
# Top-level router
router = DefaultRouter()
router.register(r"clients", ClientViewSet, basename="client")
router.register(r"orders", OrderViewSet, basename="order")
router.register(r"carts", CartViewSet, basename="cart")

# Nested: /orders/{order_pk}/items/
order_router = nested_routers.NestedDefaultRouter(router, r"orders", lookup="order")
order_router.register(r"items", OrderItemViewSet, basename="order-items")
order_router.register(r"proofs", OrderPaymentProofViewSet, basename="order-proofs")

# Nested: /carts/{cart_pk}/items/
cart_router = nested_routers.NestedDefaultRouter(router, r"carts", lookup="cart")
cart_router.register(r"items", CartItemViewSet, basename="cart-items")

urlpatterns = [
    path("", include(router.urls)),
    path("", include(order_router.urls)),
    path("", include(cart_router.urls)),
]