from django.contrib.auth import get_user_model
from django.contrib.gis.geos import Point
from rest_framework import serializers
from store.models import Street

from .models import Deliver, DeliverData

User = get_user_model()


# =========================================================
# Street (read-only, nested)
# =========================================================
class StreetSerializer(serializers.ModelSerializer):
    """Lightweight read-only representation of a Street."""

    district_name = serializers.CharField(source="district.name", read_only=True)
    city_name = serializers.CharField(source="district.city_name", read_only=True)

    class Meta:
        model = Street
        fields = ["id", "name", "district", "district_name", "city_name"]
        read_only_fields = fields


# =========================================================
# Deliver — read
# =========================================================
class DeliverSerializer(serializers.ModelSerializer):
    """
    Read-only representation of a Deliver profile.

    GET /delivers/{id}/
    """

    username = serializers.CharField(source="user.username", read_only=True)
    street_detail = StreetSerializer(source="street", read_only=True)
    location = serializers.SerializerMethodField()

    class Meta:
        model = Deliver
        fields = [
            "id",
            "user",
            "username",
            "location",
            "street",
            "street_detail",
            "is_active",
        ]
        read_only_fields = fields

    def get_location(self, instance):
        """Serialize the GeoDjango Point as GeoJSON."""
        if not instance.location:
            return None
        return {
            "type": "Point",
            "coordinates": [instance.location.x, instance.location.y],
        }


# =========================================================
# Deliver — update (PATCH)
# =========================================================
class DeliverCreateSerializer(serializers.ModelSerializer):
    """
    Write serializer for Deliver.

    POST is intentionally disabled at the view layer (a Deliver row is
    provisioned automatically per User). Only PATCH is expected here.

    Accepts latitude/longitude as separate write-only fields and converts
    them to a PointField. The `user` FK is never writable — ownership is
    enforced by the view's queryset filter.
    """

    lon = serializers.FloatField(write_only=True, required=False)
    lat = serializers.FloatField(write_only=True, required=False)

    class Meta:
        model = Deliver
        fields = [
            "id",
            "location",
            "lon",
            "lat",
            "street",
            "is_active",
        ]
        read_only_fields = ["id", "location"]

    def validate(self, attrs):
        """Require lon and lat together; reject lone coordinates."""
        lon = attrs.get("lon")
        lat = attrs.get("lat")

        if (lon is None) != (lat is None):
            raise serializers.ValidationError(
                {"location": "Both 'lon' and 'lat' must be provided together."}
            )

        # Bounds check — WGS84 valid ranges.
        if lon is not None and not (-180.0 <= lon <= 180.0):
            raise serializers.ValidationError(
                {"lon": "Longitude must be between -180 and 180."}
            )
        if lat is not None and not (-90.0 <= lat <= 90.0):
            raise serializers.ValidationError(
                {"lat": "Latitude must be between -90 and 90."}
            )

        return attrs

    def _apply_coordinates(self, validated_data):
        """Pop lon/lat and, if both present, set `location` as a Point."""
        lon = validated_data.pop("lon", None)
        lat = validated_data.pop("lat", None)
        if lon is not None and lat is not None:
            validated_data["location"] = Point(lon, lat, srid=4326)
        return validated_data

    def create(self, validated_data):
        validated_data = self._apply_coordinates(validated_data)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data = self._apply_coordinates(validated_data)
        return super().update(instance, validated_data)


# =========================================================
# DeliverData — read
# =========================================================
class DeliverDataSerializer(serializers.ModelSerializer):
    """
    Read-only representation of a DeliverData record.

    GET /delivery-data/{id}/
    """

    deliver = DeliverSerializer(read_only=True)
    street = StreetSerializer(read_only=True)
    approved_by = serializers.SerializerMethodField()
    verification_status_display = serializers.CharField(
        source="get_verification_status_display",
        read_only=True,
    )

    class Meta:
        model = DeliverData
        fields = [
            "id",
            "deliver",
            "full_name",
            "date_of_birth",
            "residence",
            "street",
            "document_number",
            "id_front",
            "id_back",
            "verification_status",
            "verification_status_display",
            "approved_at",
            "approved_by",
        ]
        read_only_fields = fields

    def get_approved_by(self, instance):
        """Serialize the approving user compactly, or None."""
        if not instance.approved_by:
            return None
        return {
            "id": instance.approved_by.id,
            "username": instance.approved_by.username,
        }


# =========================================================
# DeliverData — create / update
# =========================================================
class DeliverDataCreateSerializer(serializers.ModelSerializer):
    """
    Write serializer for DeliverData.

    - `deliver` is read-only: the view assigns it from the authenticated
      user's Deliver profile (via `perform_create`).
    - `id_front` / `id_back` accept multipart file uploads.
    - `approved_by` / `approved_at` are read-only for regular users; staff
      approval flows should use a dedicated serializer/endpoint.
    - `document_number` is validated for uniqueness up-front so the client
      receives a clean 400 instead of a database IntegrityError.
    """

    class Meta:
        model = DeliverData
        fields = [
            "id",
            "deliver",
            "full_name",
            "date_of_birth",
            "residence",
            "street",
            "document_number",
            "id_front",
            "id_back",
            "verification_status",
            "approved_at",
            "approved_by",
        ]
        read_only_fields = [
            "id",
            "deliver",
            "verification_status",
            "approved_at",
            "approved_by",
        ]

    # -----------------------------------------------------
    # Field-level validation
    # -----------------------------------------------------
    def validate_full_name(self, value):
        """
        The model already carries MinLengthValidator and a non-blank
        RegexValidator. Reproduce them here so the API returns a clean
        400 instead of an uncaught ValidationError from full_clean().
        """
        stripped = value.strip()
        if len(stripped) < 5:
            raise serializers.ValidationError(
                "Full name must be at least 5 characters long."
            )
        if not stripped:
            raise serializers.ValidationError(
                "Full name cannot be empty or just spaces."
            )
        return stripped

    def validate_document_number(self, value):
        """
        Enforce uniqueness before hitting the DB constraint.
        Exclude the current instance on update.
        """
        qs = DeliverData.objects.filter(document_number=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                "A record with this document number already exists."
            )
        return value

    def validate_street(self, value):
        """Ensure the street exists (DRF already does this — kept explicit)."""
        if value is None:
            raise serializers.ValidationError("Street is required.")
        return value

    # -----------------------------------------------------
    # Object-level validation
    # -----------------------------------------------------
    def validate(self, attrs):
        """
        Cross-field and ownership checks.

        The view's `perform_create` assigns `deliver`, so we only need to
        ensure a nested `deliver_pk` in the URL (if present) matches the
        authenticated user's Deliver profile.
        """
        user_pk = self.context.get("user_pk")
        deliver_pk = self.context.get("deliver_pk")

        if user_pk is None:
            raise serializers.ValidationError(
                "Serializer must be given `user_pk` in its context."
            )

        # On update, ensure the record actually belongs to the user.
        if self.instance is not None:
            if self.instance.deliver.user_id != user_pk:
                raise serializers.ValidationError(
                    "You do not have permission to modify this record."
                )

        # On create via a nested route, ensure the URL deliver belongs to user.
        if deliver_pk is not None and self.instance is None:
            try:
                deliver = Deliver.objects.get(pk=deliver_pk)
            except Deliver.DoesNotExist:
                raise serializers.ValidationError("The specified deliver does not exist.")

            if deliver.user_id != user_pk:
                raise serializers.ValidationError(
                    "You do not have permission to create records for this deliver."
                )

        return attrs

    # -----------------------------------------------------
    # Create / Update
    # -----------------------------------------------------
    def create(self, validated_data):
        """
        `deliver` is normally supplied by the view's `perform_create`.
        If it wasn't (e.g. serializer used standalone), fall back to the
        authenticated user's Deliver.
        """
        if "deliver" not in validated_data:
            user_pk = self.context["user_pk"]
            try:
                validated_data["deliver"] = Deliver.objects.get(user_id=user_pk)
            except Deliver.DoesNotExist:
                raise serializers.ValidationError(
                    "You do not have a Deliver profile."
                )
        return super().create(validated_data)

    def update(self, instance, validated_data):
        """
        Prevent changing `deliver` — ownership must remain fixed.
        """
        validated_data.pop("deliver", None)
        return super().update(instance, validated_data)