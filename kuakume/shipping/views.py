from django.contrib.auth import get_user_model
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from .models import Deliver, DeliverData
from .serializers import (
    DeliverCreateSerializer,
    DeliverDataCreateSerializer,
    DeliverDataSerializer,
    DeliverSerializer,
)

User = get_user_model()


# =========================================================
# Deliver — singleton-per-user
# =========================================================
class DeliverViewSet(
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """
    Retrieve and update the authenticated user's Deliver profile.

    Routes:
        GET   /delivers/me/    -> read own Deliver profile
        PATCH /delivers/me/    -> partial update own Deliver profile

    A Deliver row is provisioned automatically per User (via signal), so
    a user always has exactly one. Because ownership is 1:1, the `/me/`
    action is the only endpoint exposed — no list, no detail-by-id.
    """

    permission_classes = [permissions.IsAuthenticated]
    http_method_names = ["get", "patch", "head", "options"]

    def get_serializer_class(self):
        if self.request.method in permissions.SAFE_METHODS:
            return DeliverSerializer
        return DeliverCreateSerializer

    def get_queryset(self):
        """Restrict to the Deliver row owned by the authenticated user."""
        return (
            Deliver.objects
            .select_related("user", "street__district")
            .filter(user=self.request.user)
        )

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["user_pk"] = self.request.user.id
        return ctx

    def _get_own_deliver(self):
        """Fetch the current user's Deliver or raise 404."""
        try:
            return Deliver.objects.select_related(
                "user", "street__district"
            ).get(user=self.request.user)
        except Deliver.DoesNotExist:
            raise NotFound("You do not have a Deliver profile.")

    @action(detail=False, methods=["get", "patch"], url_path="me")
    def me(self, request):
        """
        GET   /delivers/me/  -> read own Deliver
        PATCH /delivers/me/  -> update own Deliver (location, street, is_active)
        """
        deliver = self._get_own_deliver()

        if request.method == "GET":
            serializer = DeliverSerializer(
                deliver, context=self.get_serializer_context()
            )
            return Response(serializer.data)

        # PATCH
        serializer = DeliverCreateSerializer(
            deliver,
            data=request.data,
            partial=True,
            context=self.get_serializer_context(),
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)


# =========================================================
# DeliverData — one record per user (with me/ actions)
# =========================================================
class DeliverDataViewSet(viewsets.ModelViewSet):
    """
    CRUD for the authenticated user's DeliverData record.

    Routes:
        POST   /delivery-data/         -> create own record
        GET    /delivery-data/me/      -> read own record
        PUT    /delivery-data/me/      -> full update of own record
        PATCH  /delivery-data/me/      -> partial update of own record
        DELETE /delivery-data/me/      -> delete own record

    Because `DeliverData.deliver` is a OneToOneField, each user has at most
    one record. The `/me/` action is the only detail surface exposed — the
    generic detail routes (/{id}/) are intentionally not routed.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method in permissions.SAFE_METHODS:
            return DeliverDataSerializer
        return DeliverDataCreateSerializer

    def get_queryset(self):
        """Only rows whose parent Deliver belongs to the authenticated user."""
        return (
            DeliverData.objects
            .select_related(
                "deliver__user",
                "deliver__street",
                "street__district",
                "approved_by",
            )
            .filter(deliver__user=self.request.user)
        )

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["user_pk"] = self.request.user.id
        ctx["deliver_pk"] = None
        return ctx

    def create(self, request, *args, **kwargs):
        """
        POST /delivery-data/
        Refuse a second record — the user already has one.
        """
        if DeliverData.objects.filter(deliver__user=request.user).exists():
            return Response(
                {"detail": "You already have a DeliverData record. "
                           "Use PATCH /delivery-data/me/ to update it."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        """Force the FK to the authenticated user's Deliver profile."""
        deliver = Deliver.objects.get(user=self.request.user)
        serializer.save(deliver=deliver)

    def _get_own_record(self):
        """Fetch the current user's DeliverData or raise 404."""
        try:
            return DeliverData.objects.select_related(
                "deliver__user",
                "deliver__street",
                "street__district",
                "approved_by",
            ).get(deliver__user=self.request.user)
        except DeliverData.DoesNotExist:
            raise NotFound("You do not have a DeliverData record.")

    @action(
        detail=False,
        methods=["get", "put", "patch", "delete"],
        url_path="me",
    )
    def me(self, request):
        """
        GET    /delivery-data/me/  -> read own record
        PUT    /delivery-data/me/  -> full update
        PATCH  /delivery-data/me/  -> partial update
        DELETE /delivery-data/me/  -> delete own record
        """
        record = self._get_own_record()

        if request.method == "GET":
            serializer = DeliverDataSerializer(
                record, context=self.get_serializer_context()
            )
            return Response(serializer.data)

        if request.method == "DELETE":
            record.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)

        # PUT / PATCH
        partial = request.method == "PATCH"
        serializer = DeliverDataCreateSerializer(
            record,
            data=request.data,
            partial=partial,
            context=self.get_serializer_context(),
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)


# =========================================================
# DeliverDataApproval (optional, staff-only)
# =========================================================
class DeliverDataApprovalViewSet(
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """
    Staff-only endpoint for approving / rejecting DeliverData records.

    PATCH /delivery-data/{id}/approve/
    """

    permission_classes = [permissions.IsAdminUser]
    serializer_class = DeliverDataCreateSerializer
    http_method_names = ["patch", "head", "options"]

    def get_queryset(self):
        return DeliverData.objects.all()

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["user_pk"] = self.request.user.id
        return ctx