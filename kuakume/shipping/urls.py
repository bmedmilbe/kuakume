# shipping/urls.py
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    DeliverDataApprovalViewSet,
    DeliverDataViewSet,
    DeliverViewSet,
)

router = DefaultRouter()
router.register(r"delivers", DeliverViewSet, basename="deliver")
router.register(r"delivery-data", DeliverDataViewSet, basename="deliver-data")
router.register(
    r"delivery-data-approval",
    DeliverDataApprovalViewSet,
    basename="deliver-data-approval",
)

urlpatterns = [
    path("", include(router.urls)),
]