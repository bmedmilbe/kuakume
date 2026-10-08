from django.contrib.auth import get_user_model
from rest_framework import mixins, permissions, viewsets

from .models import (
    Category,
    Content,
    District,
    Product,
    ProductContent,
    ProductImages,
    ShopVendor,
    Street,
    Vendor,
)
from .serializers import (
    CategorySerializer,
    ContentSerializer,
    DistrictSerializer,
    ProductContentCreateOrUpdateSerializer,
    ProductContentSerializer,
    ProductCreateOrUpdateSerializer,
    ProductImagesCreateOrUpdateSerializer,
    ProductImagesSerializer,
    ProductSerializer,
    ShopVendorCreateOrUpdateSerializer,
    ShopVendorSerializer,
    StreetSerializer,
    VendorSerializer,
)

User = get_user_model()


# =========================================================
# Vendor
# =========================================================
from rest_framework.decorators import action
from rest_framework.response import Response


class VendorViewSet(viewsets.GenericViewSet):
    serializer_class = VendorSerializer
    permission_classes = [permissions.IsAuthenticated]
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self):
        """Restrict access to the authenticated user's vendor profile."""
        return Vendor.objects.select_related("user").filter(
            user=self.request.user
        )

    def get_serializer_context(self):
        """Propagate user id so nested serializers can enforce ownership."""
        ctx = super().get_serializer_context()
        ctx["user_pk"] = self.request.user.id
        return ctx

    def get_object(self):
        """
        Override get_object so it fetches the 'me' profile 
        when detail=False, otherwise fallback to the standard lookup.
        """
        if self.action == "me":
            try:
                return self.get_queryset().get()
            except Vendor.DoesNotExist:
                # DRF's Http404 automatically returns a standard 404 response
                from django.http import Http404
                raise Http404("Vendor profile not found.")
        return super().get_object()

    @action(detail=False, methods=["get", "patch"])
    def me(self, request):
        """
        GET /vendors/me/   -> Returns authenticated vendor profile
        PATCH /vendors/me/ -> Updates authenticated vendor profile
        """
        vendor = self.get_object()

        if request.method == "PATCH":
            # Using self.get_serializer ensures get_serializer_context() is executed safely
            serializer = self.get_serializer(vendor, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data)

        serializer = self.get_serializer(vendor)
        return Response(serializer.data)




# =========================================================
# District
# =========================================================
class DistrictViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Read-only access to districts."""

    queryset = District.objects.all().order_by("name")
    serializer_class = DistrictSerializer
    permission_classes = [permissions.IsAuthenticated]


# =========================================================
# Street
# =========================================================
class StreetViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Read-only access to streets."""

    queryset = Street.objects.select_related("district").order_by("name")
    serializer_class = StreetSerializer
    permission_classes = [permissions.IsAuthenticated]


# =========================================================
# ShopVendor (nested under Vendor)
# =========================================================
class ShopVendorViewSet(viewsets.ModelViewSet):
    """
    Full CRUD for shops, scoped to the authenticated vendor.

    Nested route: /vendors/{vendor_pk}/shops/

    Dynamic serializer:
      - GET              -> ShopVendorSerializer
      - POST/PUT/PATCH   -> ShopVendorCreateOrUpdateSerializer
    """

    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method in permissions.SAFE_METHODS:
            return ShopVendorSerializer
        return ShopVendorCreateOrUpdateSerializer

    def get_queryset(self):
        """Only return shops belonging to the authenticated vendor."""
        return (
            ShopVendor.objects
            .select_related("vendor__user", "street__district")
            .filter(vendor__user=self.request.user)
        )

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["user_pk"] = self.request.user.id
        return ctx

# =========================================================
# Category
# =========================================================
class CategoryViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Read-only access to categories."""

    queryset = Category.objects.all().order_by("name")
    serializer_class = CategorySerializer
    permission_classes = [permissions.IsAuthenticated]


# =========================================================
# Product
# =========================================================
class ProductViewSet(viewsets.ModelViewSet):
    """
    CRUD for products owned by the authenticated vendor.

    Dynamic serializer:
      - GET              -> ProductSerializer (nested shop, category, images)
      - POST/PUT/PATCH   -> ProductCreateOrUpdateSerializer
    """

    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method in permissions.SAFE_METHODS:
            return ProductSerializer
        return ProductCreateOrUpdateSerializer

    def get_queryset(self):
        """
        Restrict products to those whose shop belongs to the authenticated user.
        Also supports filtering by `shop_pk` when used as a nested route.
        """
        qs = (
            Product.objects
            .select_related("shop__vendor__user", "category")
            .prefetch_related("product_images")
            .filter(shop__vendor__user=self.request.user)
        )
        shop_pk = self.kwargs.get("shop_pk")
        if shop_pk is not None:
            qs = qs.filter(shop_id=shop_pk)
        return qs

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["user_pk"] = self.request.user.id
        ctx["shop_pk"] = self.kwargs.get("shop_pk")
        return ctx


# =========================================================
# ProductImages (nested under Product)
# =========================================================
class ProductImagesViewSet(viewsets.ModelViewSet):
    """
    CRUD for product images, scoped to the authenticated vendor.

    Nested route: /products/{product_pk}/images/

    Dynamic serializer:
      - GET              -> ProductImagesSerializer
      - POST/PUT/PATCH   -> ProductImagesCreateOrUpdateSerializer
    """

    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method in permissions.SAFE_METHODS:
            return ProductImagesSerializer
        return ProductImagesCreateOrUpdateSerializer

    def get_queryset(self):
        """Filter images by ownership and by the nested product_pk if present."""
        qs = (
            ProductImages.objects
            .select_related("product__shop__vendor__user")
            .filter(product__shop__vendor__user=self.request.user)
        )
        product_pk = self.kwargs.get("product_pk")
        if product_pk is not None:
            qs = qs.filter(product_id=product_pk)
        return qs

    def get_serializer_context(self):
        """
        Expose `product_pk` and `user_pk` to the serializer so it can
        enforce ownership and auto-assign the product on create.
        """
        ctx = super().get_serializer_context()
        ctx["user_pk"] = self.request.user.id
        ctx["product_pk"] = self.kwargs.get("product_pk")
        return ctx


# =========================================================
# Content
# =========================================================
class ContentViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Read-only access to content metadata."""

    queryset = Content.objects.all().order_by("name")
    serializer_class = ContentSerializer
    permission_classes = [permissions.IsAuthenticated]


# =========================================================
# ProductContent (nested under Product)
# =========================================================
class ProductContentViewSet(viewsets.ModelViewSet):
    """
    CRUD for product content, scoped to the authenticated vendor.

    Nested route: /products/{product_pk}/contents/

    Dynamic serializer:
      - GET              -> ProductContentSerializer
      - POST/PUT/PATCH   -> ProductContentCreateOrUpdateSerializer
    """

    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method in permissions.SAFE_METHODS:
            return ProductContentSerializer
        return ProductContentCreateOrUpdateSerializer

    def get_queryset(self):
        qs = (
            ProductContent.objects
            .select_related("product__shop__vendor__user", "content")
            .filter(product__shop__vendor__user=self.request.user)
        )
        product_pk = self.kwargs.get("product_pk")
        if product_pk is not None:
            qs = qs.filter(product_id=product_pk)
        return qs

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["user_pk"] = self.request.user.id
        ctx["product_pk"] = self.kwargs.get("product_pk")
        return ctx