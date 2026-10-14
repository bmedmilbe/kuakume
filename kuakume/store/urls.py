from django.urls import include, path
from rest_framework_nested import routers

from .views import (
    CategoryViewSet,
    ContentViewSet,
    DistrictViewSet,
    ProductContentViewSet,
    ProductImagesViewSet,
    ProductViewSet,
    ShopOrderViewSet,
    ShopVendorViewSet,
    StreetViewSet,
    VendorViewSet,
)

app_name = 'store' 

# Top-level router
router = routers.DefaultRouter()
router.register(r"vendors", VendorViewSet, basename="vendor")
router.register(r"districts", DistrictViewSet, basename="district")
router.register(r"streets", StreetViewSet, basename="street")
router.register(r"categories", CategoryViewSet, basename="category")
router.register(r"contents", ContentViewSet, basename="content")
router.register(r"products", ProductViewSet, basename="product")
router.register(r"shops", ShopVendorViewSet, basename="shop")



# Nested: /shops/{shop_pk}/shops/
shop_router = routers.NestedDefaultRouter(router, r"shops", lookup="shop")
shop_router.register(r"orders", ShopOrderViewSet, basename="shop-orders")

# Nested: /products/{product_pk}/images/ and /products/{product_pk}/contents/
product_router = routers.NestedDefaultRouter(router, r"products", lookup="product")
product_router.register(r"images", ProductImagesViewSet, basename="product-images")
product_router.register(r"contents", ProductContentViewSet, basename="product-contents")

urlpatterns = [
    path("", include(router.urls)),
    path("", include(shop_router.urls)),
    path("", include(product_router.urls)),
]