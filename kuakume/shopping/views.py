# kuakume/shopping/views.py
from django.contrib.auth import get_user_model
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from shopping.models import OrderPaymentProof

from .models import Cart, CartItem, Client, Order, OrderItem
from .permissions import IsClientActive
from .serializers import (
    CartCreateSerializer,
    CartItemCreateOrUpdateSerializer,
    CartItemSerializer,
    CartMergeSerializer,
    CartSerializer,
    CartUpdateSerializer,
    ClientSerializer,
    ClientUpdateSerializer,
    OrderCreateOrUpdateSerializer,
    OrderItemCreateOrUpdateSerializer,
    OrderItemSerializer,
    OrderPaymentProofCreateSerializer,
    OrderPaymentProofSerializer,
    OrderSerializer,
)

User = get_user_model()


# =========================================================
# Cart resolution helper
# =========================================================
def _resolve_cart(request):
    """
    Return the active cart tied to the current request.

    - Authenticated users: their Client's active cart.
    - Guests: an active guest cart whose `guest_token` matches the
      `guest_cart_token` cookie.

    Returns `None` when no cart exists yet.
    """
    if request.user.is_authenticated:
        return (
            Cart.objects
            .filter(client__user=request.user, is_active=True)
            .select_related("client__user", "shop", "street__district")
            .first()
        )

    token = request.COOKIES.get("guest_cart_token")
    if not token:
        return None
    return (
        Cart.objects
        .filter(guest_token=token, is_active=True)
        .select_related("shop", "street__district")
        .first()
    )


# =========================================================
# Custom permission — guest-aware cart ownership
# =========================================================
class IsCartOwnerOrReadOnly(permissions.BasePermission):
    """
    Cart owner permission that supports anonymous guests.

    - GET/HEAD/OPTIONS are allowed for anyone with a valid cart token.
    - Write methods require the request to match the cart's owner:
        * authenticated user → cart.client.user == request.user
        * guest → cart.guest_token == request.COOKIES["guest_cart_token"]
    """

    def has_object_permission(self, request, view, obj):
        cart = obj if isinstance(obj, Cart) else getattr(obj, "cart", None)
        if cart is None:
            return False

        if request.user.is_authenticated:
            return cart.client_id is not None and cart.client.user_id == request.user.id

        token = request.COOKIES.get("guest_cart_token")
        if not token:
            return False
        return str(cart.guest_token) == str(token)


# =========================================================
# Client — /clients/me/
# =========================================================
class ClientViewSet(
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """
    Retrieve and update the authenticated user's Client profile.

    Routes:
        GET   /clients/me/    -> read own Client
        PATCH /clients/me/    -> update own Client (location, street)
    """

    permission_classes = [IsClientActive]
    http_method_names = ["get", "patch", "head", "options"]

    def get_serializer_class(self):
        if self.request.method in permissions.SAFE_METHODS:
            return ClientSerializer
        return ClientUpdateSerializer

    def get_queryset(self):
        return (
            Client.objects
            .select_related("user", "street__district")
            .filter(user=self.request.user)
        )

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["user_pk"] = self.request.user.id
        return ctx

    def _get_own_client(self):
        try:
            return Client.objects.select_related(
                "user", "street__district"
            ).get(user=self.request.user)
        except Client.DoesNotExist:
            raise NotFound("You do not have a Client profile.")

    @action(detail=False, methods=["get", "patch"], url_path="me")
    def me(self, request):
        """GET /clients/me/ — read.  PATCH /clients/me/ — update."""
        client_obj = self._get_own_client()

        if request.method == "GET":
            serializer = ClientSerializer(
                client_obj, context=self.get_serializer_context()
            )
            return Response(serializer.data)

        serializer = ClientUpdateSerializer(
            client_obj,
            data=request.data,
            partial=True,
            context=self.get_serializer_context(),
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)


# =========================================================
# Order — user-scoped CRUD
# =========================================================
class OrderViewSet(viewsets.ModelViewSet):
    """
    CRUD for orders owned by the authenticated user's Client.

    Routes:
        GET    /orders/            -> list own orders
        POST   /orders/            -> create a new order
        GET    /orders/{id}/       -> retrieve own order
        PUT    /orders/{id}/       -> full update
        PATCH  /orders/{id}/       -> partial update
        DELETE /orders/{id}/       -> delete own order

    Dynamic serializer:
        GET              -> OrderSerializer (nested items + totals)
        POST/PUT/PATCH   -> OrderCreateOrUpdateSerializer
    """

    permission_classes = [IsClientActive]

    def get_serializer_class(self):
        if self.request.method in permissions.SAFE_METHODS:
            return OrderSerializer
        return OrderCreateOrUpdateSerializer

    def get_queryset(self):
        """
        Restrict to the authenticated user's Client's orders.

        Because the queryset is filtered at the ORM level, retrieval of
        another user's order naturally returns 404, not 403 — the standard
        isolation pattern.
        """
        return (
            Order.objects
            .select_related(
                "client__user",
                "deliver__user",
                "shop__vendor__user",
                "street__district",
            )
            .prefetch_related(
                "items__product__shop",
                "items__product__category",
            )
            .filter(client__user=self.request.user)
        )

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["user_pk"] = self.request.user.id
        return ctx

    def perform_create(self, serializer):
        """
        `client` is resolved inside the serializer from `user_pk`; the
        view does nothing extra beyond delegating to `.save()`.
        """
        serializer.save()


# =========================================================
# OrderItem — nested under Order
# =========================================================
class OrderItemViewSet(viewsets.ModelViewSet):
    """
    CRUD for items within an Order owned by the authenticated user.

    Nested route: /orders/{order_pk}/items/

    Dynamic serializer:
        GET              -> OrderItemSerializer
        POST/PUT/PATCH   -> OrderItemCreateOrUpdateSerializer
    """

    permission_classes = [IsClientActive]

    def get_serializer_class(self):
        if self.request.method in permissions.SAFE_METHODS:
            return OrderItemSerializer
        return OrderItemCreateOrUpdateSerializer

    def get_queryset(self):
        """
        Filter by ownership and, when nested, by the parent `order_pk`.
        """
        qs = (
            OrderItem.objects
            .select_related(
                "order__client__user",
                "order__shop__vendor__user",
                "product__shop",
                "product__category",
            )
            .filter(order__client__user=self.request.user)
        )

        order_pk = self.kwargs.get("order_pk")
        if order_pk is not None:
            qs = qs.filter(order_id=order_pk)

        return qs

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["user_pk"] = self.request.user.id
        ctx["order_pk"] = self.kwargs.get("order_pk")
        return ctx

    def perform_create(self, serializer):
        """The serializer resolves the parent order from `order_pk`."""
        serializer.save()


# =========================================================
# Cart — guest + authenticated
# =========================================================
class CartViewSet(viewsets.ModelViewSet):
    """
    CRUD for the current cart.

    Guests are supported: an anonymous request creates a guest cart and
    receives its `guest_token`, which the client stores in a cookie.
    Authenticated users get their Client's cart.

    Routes:
        POST   /carts/            -> create (guest or client cart)
        GET    /carts/{id}/       -> read cart
        PATCH  /carts/{id}/       -> partial update
        DELETE /carts/{id}/       -> soft-delete (is_active=False)
        POST   /carts/merge/      -> merge a guest cart into the caller's

    Dynamic serializer:
        POST             -> CartCreateSerializer
        PATCH/PUT        -> CartUpdateSerializer
        GET              -> CartSerializer
    """

    # Guests must be able to create and read their cart.
    permission_classes = [permissions.AllowAny]

    def get_serializer_class(self):
        if self.action == "create":
            return CartCreateSerializer
        if self.action in ("update", "partial_update"):
            return CartUpdateSerializer
        if self.action == "merge":
            return CartMergeSerializer
        return CartSerializer

    def get_queryset(self):
        """Return only the caller's cart (authenticated or guest)."""
        return Cart.objects.filter(is_active=True)

    def get_object(self):
        """
        Bypass the default PK lookup and return the caller's cart.

        The `/me/` and nested routes are the only supported access patterns;
        numeric IDs are intentionally not exposed for carts, to prevent
        enumeration.
        """
        cart = _resolve_cart(self.request)
        if cart is None:
            raise NotFound("No active cart found for this request.")
        self.check_object_permissions(self.request, cart)
        return cart

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        if self.request.user.is_authenticated:
            ctx["user_pk"] = self.request.user.id
        return ctx

    # -----------------------------------------------------
    # HTTP methods
    # -----------------------------------------------------
    def create(self, request, *args, **kwargs):
        """
        Refuse a second active cart for the same owner; otherwise create.
        """
        if _resolve_cart(request) is not None:
            return Response(
                {"detail": "You already have an active cart."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        cart = serializer.save()

        response = Response(
            CartSerializer(cart, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )
        # Guests must receive their token so the client can persist it.
        if cart.client_id is None:
            response.set_cookie(
                "guest_cart_token",
                str(cart.guest_token),
                httponly=True,
                samesite="Lax",
            )
        return response

    def destroy(self, request, *args, **kwargs):
        """Soft-delete: mark `is_active=False` and clear the guest cookie."""
        cart = self.get_object()
        cart.is_active = False
        cart.save(update_fields=["is_active"])

        response = Response(status=status.HTTP_204_NO_CONTENT)
        response.delete_cookie("guest_cart_token")
        return response

    @action(detail=False, methods=["post"], url_path="merge",
            permission_classes=[permissions.IsAuthenticated])
    def merge(self, request):
        """
        Merge the guest cart identified by `guest_token` into the caller's
        client cart.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        cart = serializer.save()
        return Response(
            CartSerializer(cart, context=self.get_serializer_context()).data,
            status=status.HTTP_200_OK,
        )


# =========================================================
# CartItem — nested under Cart
# =========================================================
class CartItemViewSet(viewsets.ModelViewSet):
    """
    CRUD for items within the caller's cart.

    Nested route: /carts/{cart_pk}/items/

    Dynamic serializer:
        GET              -> CartItemSerializer
        POST/PUT/PATCH   -> CartItemCreateOrUpdateSerializer
    """

    permission_classes = [permissions.AllowAny]

    def get_serializer_class(self):
        if self.request.method in permissions.SAFE_METHODS:
            return CartItemSerializer
        return CartItemCreateOrUpdateSerializer

    def get_queryset(self):
        """
        Filter items by the caller's cart.

        - Authenticated: cart belongs to the user's Client.
        - Guest: cart's `guest_token` matches the cookie.
        """
        qs = CartItem.objects.select_related(
            "cart__client__user",
            "cart__shop",
            "product__shop",
            "product__category",
        )

        cart_pk = self.kwargs.get("cart_pk")
        if cart_pk is not None:
            qs = qs.filter(cart_id=cart_pk)

        if self.request.user.is_authenticated:
            return qs.filter(cart__client__user=self.request.user)

        token = self.request.COOKIES.get("guest_cart_token")
        if not token:
            return qs.none()
        return qs.filter(cart__guest_token=token)

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        if self.request.user.is_authenticated:
            ctx["user_pk"] = self.request.user.id
        ctx["cart_pk"] = self.kwargs.get("cart_pk")
        return ctx

    def perform_create(self, serializer):
        """The serializer resolves the parent cart from `cart_pk`."""
        serializer.save()





class OrderPaymentProofViewSet(
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet
):
    permission_classes = [IsClientActive]
    
    def get_queryset(self):
        order_pk = self.kwargs.get('order_pk')
        return OrderPaymentProof.objects.filter(order_id=order_pk)

    def get_serializer_class(self):
        if self.request.method in permissions.SAFE_METHODS:
            return OrderPaymentProofSerializer
        return OrderPaymentProofCreateSerializer

    def get_serializer_context(self):
        """
        Overrides context generation to inject 'order_pk' from 
        drf-nested-routers directly into the serializer instance.
        """
        context = super().get_serializer_context()
        context['order_pk'] = self.kwargs.get('order_pk')
        return context
