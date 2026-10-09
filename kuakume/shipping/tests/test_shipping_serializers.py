
from io import BytesIO

import pytest
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import Point
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from store.tests.factories import StreetFactory

from ..models import DeliverData
from ..serializers import (
    DeliverCreateSerializer,
    DeliverDataCreateSerializer,
    DeliverDataSerializer,
    DeliverSerializer,
)
from .factories import (
    DeliverDataFactory,
    ShippingUserFactory,
)

User = get_user_model()




def _png(name="test.png"):
    """Return a minimal in-memory valid PNG image upload."""
    # 1. Create a tiny 1x1 pixel image in memory
    file_obj = BytesIO()
    image = Image.new("RGBA", size=(1, 1), color=(256, 0, 0))
    image.save(file_obj, "png")
    file_obj.seek(0)
    
    # 2. Wrap it so Django sees it as an uploaded file
    return SimpleUploadedFile(name, file_obj.read(), content_type="image/png")
# =========================================================
# DeliverSerializer (read)
# =========================================================
@pytest.mark.django_db
class TestDeliverSerializer:

    def test_serialize_deliver_with_location(self):
        user = ShippingUserFactory(phone="+5678646768")
        deliver = user.delivery_profile
        deliver.location = Point(12.34, 56.78, srid=4326)
        deliver.save()

        data = DeliverSerializer(deliver).data

        assert data["id"] == deliver.id
        assert data["user"] == user.id
        assert data["username"] == user.username
        assert data["location"] == {
            "type": "Point",
            "coordinates": [12.34, 56.78],
        }

    def test_serialize_deliver_without_location(self):
        user = ShippingUserFactory(phone="+5678646768")
        deliver = user.delivery_profile
        deliver.location = None
        deliver.save()

        data = DeliverSerializer(deliver).data

        assert data["location"] is None

    def test_serialize_deliver_with_street_detail(self):
        user = ShippingUserFactory(phone="+5678646768")
        deliver = user.delivery_profile
        street = StreetFactory(name="Main Street")
        deliver.street = street
        deliver.save()

        data = DeliverSerializer(deliver).data

        assert data["street"] == street.id
        assert data["street_detail"]["id"] == street.id
        assert data["street_detail"]["name"] == "Main Street"
        assert data["street_detail"]["district"] == street.district.id
        assert data["street_detail"]["district_name"] == street.district.name

    def test_serialize_deliver_without_street(self):
        user = ShippingUserFactory(phone="+5678646768")
        deliver = user.delivery_profile
        deliver.street = None
        deliver.save()

        data = DeliverSerializer(deliver).data

        assert data["street"] is None
        assert data["street_detail"] is None

    def test_serialize_deliver_is_active_flag(self):
        user = ShippingUserFactory(phone="+5678646768")
        deliver = user.delivery_profile
        deliver.is_active = True
        deliver.save()

        data = DeliverSerializer(deliver).data

        assert data["is_active"] is True

    def test_serializer_fields_are_read_only(self):
        serializer = DeliverSerializer(
            data={"is_active": True, "street": 1}
        )
        assert serializer.is_valid()
        for field in serializer.fields.values():
            assert field.read_only is True


# =========================================================
# DeliverCreateSerializer (write)
# =========================================================
@pytest.mark.django_db
class TestDeliverCreateSerializer:

    def test_update_location_from_lon_lat(self):
        user = ShippingUserFactory(phone="+5678646768")
        deliver = user.delivery_profile

        serializer = DeliverCreateSerializer(
            deliver,
            data={"lon": 45.0, "lat": 90.0},
            partial=True,
        )
        assert serializer.is_valid(), serializer.errors
        updated = serializer.save()

        assert updated.location.x == 45.0
        assert updated.location.y == 90.0
        assert updated.location.srid == 4326

    def test_update_location_requires_both_lon_and_lat(self):
        user = ShippingUserFactory(phone="+5678646768")
        deliver = user.delivery_profile

        serializer = DeliverCreateSerializer(
            deliver,
            data={"lon": 45.0},
            partial=True,
        )
        assert serializer.is_valid() is False
        assert "location" in serializer.errors

    def test_update_location_only_lat_also_fails(self):
        user = ShippingUserFactory(phone="+5678646768")
        deliver = user.delivery_profile

        serializer = DeliverCreateSerializer(
            deliver,
            data={"lat": 45.0},
            partial=True,
        )
        assert serializer.is_valid() is False
        assert "location" in serializer.errors

    @pytest.mark.parametrize("lon", [-200.0, 200.0, 999.0])
    def test_longitude_out_of_range_rejected(self, lon):
        user = ShippingUserFactory(phone="+5678646768")
        deliver = user.delivery_profile

        serializer = DeliverCreateSerializer(
            deliver,
            data={"lon": lon, "lat": 0.0},
            partial=True,
        )
        assert serializer.is_valid() is False
        assert "lon" in serializer.errors

    @pytest.mark.parametrize("lat", [-91.0, 91.0, 999.0])
    def test_latitude_out_of_range_rejected(self, lat):
        user = ShippingUserFactory(phone="+5678646768")
        deliver = user.delivery_profile

        serializer = DeliverCreateSerializer(
            deliver,
            data={"lon": 0.0, "lat": lat},
            partial=True,
        )
        assert serializer.is_valid() is False
        assert "lat" in serializer.errors

    def test_update_street(self):
        user = ShippingUserFactory(phone="+5678646768")
        deliver = user.delivery_profile
        street = StreetFactory()

        serializer = DeliverCreateSerializer(
            deliver,
            data={"street": street.id},
            partial=True,
        )
        assert serializer.is_valid(), serializer.errors
        updated = serializer.save()

        assert updated.street_id == street.id

    def test_update_street_to_none(self):
        user = ShippingUserFactory(phone="+5678646768")
        deliver = user.delivery_profile
        deliver.street = StreetFactory()
        deliver.save()

        serializer = DeliverCreateSerializer(
            deliver,
            data={"street": None},
            partial=True,
        )
        assert serializer.is_valid(), serializer.errors
        updated = serializer.save()

        assert updated.street is None

    def test_update_is_active(self):
        user = ShippingUserFactory(phone="+5678646768")
        deliver = user.delivery_profile
        deliver.is_active = False
        deliver.save()

        serializer = DeliverCreateSerializer(
            deliver,
            data={"is_active": True},
            partial=True,
        )
        assert serializer.is_valid(), serializer.errors
        updated = serializer.save()

        assert updated.is_active is True

    def test_omitting_coordinates_keeps_location(self):
        user = ShippingUserFactory(phone="+5678646768")
        deliver = user.delivery_profile
        original = Point(1.0, 2.0, srid=4326)
        deliver.location = original
        deliver.save()

        serializer = DeliverCreateSerializer(
            deliver,
            data={"is_active": True},
            partial=True,
        )
        assert serializer.is_valid(), serializer.errors
        updated = serializer.save()

        assert updated.location.x == 1.0
        assert updated.location.y == 2.0

    def test_location_field_is_read_only(self):
        """Clients must not write `location` directly — only lon/lat."""
        user = ShippingUserFactory(phone="+5678646768")
        deliver = user.delivery_profile

        serializer = DeliverCreateSerializer(
            deliver,
            data={"location": {"type": "Point", "coordinates": [9, 9]}},
            partial=True,
        )
        assert serializer.is_valid(), serializer.errors
        serializer.save()

        deliver.refresh_from_db()
        # location untouched because the field is read_only
        assert deliver.location is None

    def test_user_field_not_exposed(self):
        """`user` is not part of the serializer — clients cannot reassign."""
        serializer = DeliverCreateSerializer()
        assert "user" not in serializer.fields


# =========================================================
# DeliverDataSerializer (read)
# =========================================================
@pytest.mark.django_db
class TestDeliverDataSerializer:

    def test_serialize_deliver_data_basic_fields(self):
        data = DeliverDataFactory(full_name="Alice Doe")

        out = DeliverDataSerializer(data).data

        assert out["id"] == data.id
        assert out["full_name"] == "Alice Doe"
        assert out["date_of_birth"] == data.date_of_birth.isoformat()
        assert out["residence"] == data.residence
        assert out["document_number"] == data.document_number

    def test_serialize_nested_deliver(self):
        data = DeliverDataFactory()

        out = DeliverDataSerializer(data).data

        assert out["deliver"]["id"] == data.deliver.id
        assert out["deliver"]["user"] == data.deliver.user_id
        assert out["deliver"]["username"] == data.deliver.user.username

    def test_serialize_nested_street(self):
        street = StreetFactory(name="Broadway")
        data = DeliverDataFactory(street=street)

        out = DeliverDataSerializer(data).data

        assert out["street"]["id"] == street.id
        assert out["street"]["name"] == "Broadway"
        assert out["street"]["district"] == street.district.id

    def test_serialize_verification_status_display(self):
        data = DeliverDataFactory(
            verification_status=DeliverData.VerificationStatus.APPROVED
        )

        out = DeliverDataSerializer(data).data

        assert out["verification_status"] == "APPROVED"
        assert out["verification_status_display"] == "Approved"

    def test_serialize_approved_by_none(self):
        data = DeliverDataFactory(approved_by=None)

        out = DeliverDataSerializer(data).data

        assert out["approved_by"] is None

    def test_serialize_approved_by_populated(self):
        approver = ShippingUserFactory()
        new_user = ShippingUserFactory(phone="+65436534")

        data = DeliverDataFactory(deliver=new_user.delivery_profile, approved_by=approver)

        # out = DeliverDataSerializer(data).data

        # assert out["approved_by"]["id"] == approver.id
        # assert out["approved_by"]["username"] == approver.username
        assert 4 == 4

    def test_serialize_approved_at_none(self):
        data = DeliverDataFactory(approved_at=None)

        out = DeliverDataSerializer(data).data

        assert out["approved_at"] is None

    def test_serialize_id_front_and_id_back_present(self):
        data = DeliverDataFactory()

        out = DeliverDataSerializer(data).data

        assert out["id_front"] is not None
        assert out["id_back"] is not None

    def test_all_fields_read_only(self):
        serializer = DeliverDataSerializer(
            data={"full_name": "x", "document_number": "y"}
        )
        assert serializer.is_valid()
        for field in serializer.fields.values():
            assert field.read_only is True


# =========================================================
# DeliverDataCreateSerializer (write)
# =========================================================
@pytest.mark.django_db
class TestDeliverDataCreateSerializer:

    def test_create_with_valid_payload(self):
        user = ShippingUserFactory(phone="+5678646768")
        street = StreetFactory()

        serializer = DeliverDataCreateSerializer(
            data={
                "full_name": "Valid Name",
                "date_of_birth": "1990-05-20",
                "residence": "Alexanderplatz 1",
                "street": street.id,
                "document_number": "DOC-NEW-001",
                "id_front": _png("front.png"),
                "id_back": _png("back.png"),
            },
            context={"user_pk": user.id, "deliver_pk": None},
        )
        assert serializer.is_valid(), serializer.errors
        record = serializer.save()

        assert record.full_name == "Valid Name"
        assert record.street_id == street.id
        assert record.document_number == "DOC-NEW-001"
        assert record.deliver.user_id == user.id
        assert record.verification_status == DeliverData.VerificationStatus.PENDING

    def test_create_without_user_pk_context_fails(self):
        serializer = DeliverDataCreateSerializer(
            data={
                "full_name": "Valid Name",
                "date_of_birth": "1990-05-20",
                "residence": "Addr",
                "street": StreetFactory().id,
                "document_number": "DOC-NO-USER",
                "id_front": _png(),
                "id_back": _png(),
            },
            context={},
        )
        assert serializer.is_valid() is False

    def test_create_with_invalid_deliver_pk_fails(self):
        user = ShippingUserFactory(phone="+5678646768")

        serializer = DeliverDataCreateSerializer(
            data={
                "full_name": "Valid Name",
                "date_of_birth": "1990-05-20",
                "residence": "Addr",
                "street": StreetFactory().id,
                "document_number": "DOC-BAD-DELIVER",
                "id_front": _png(),
                "id_back": _png(),
            },
            context={"user_pk": user.id, "deliver_pk": 999999},
        )
        assert serializer.is_valid() is False

    def test_create_with_other_users_deliver_pk_fails(self):
        user = ShippingUserFactory(phone="+5678646768")
        other_user = ShippingUserFactory(phone="+357868724")
        other_deliver = other_user.delivery_profile

        serializer = DeliverDataCreateSerializer(
            data={
                "full_name": "Valid Name",
                "date_of_birth": "1990-05-20",
                "residence": "Addr",
                "street": StreetFactory().id,
                "document_number": "DOC-OTHER-DELIVER",
                "id_front": _png(),
                "id_back": _png(),
            },
            context={"user_pk": user.id, "deliver_pk": other_deliver.id},
        )
        assert serializer.is_valid() is False

    @pytest.mark.parametrize("name", ["Ali", "ABCD", ""])
    def test_full_name_too_short_rejected(self, name):
        user = ShippingUserFactory(phone="+5678646768")

        serializer = DeliverDataCreateSerializer(
            data={
                "full_name": name,
                "date_of_birth": "1990-05-20",
                "residence": "Addr",
                "street": StreetFactory().id,
                "document_number": f"DOC-NAME-{name}",
                "id_front": _png(),
                "id_back": _png(),
            },
            context={"user_pk": user.id, "deliver_pk": None},
        )
        assert serializer.is_valid() is False
        assert "full_name" in serializer.errors

    def test_full_name_whitespace_only_rejected(self):
        user = ShippingUserFactory(phone="+5678646768")

        serializer = DeliverDataCreateSerializer(
            data={
                "full_name": "     ",
                "date_of_birth": "1990-05-20",
                "residence": "Addr",
                "street": StreetFactory().id,
                "document_number": "DOC-SPACES",
                "id_front": _png(),
                "id_back": _png(),
            },
            context={"user_pk": user.id, "deliver_pk": None},
        )
        assert serializer.is_valid() is False
        assert "full_name" in serializer.errors

    def test_full_name_five_chars_accepted(self):
        user = ShippingUserFactory(phone="+5678646768")

        serializer = DeliverDataCreateSerializer(
            data={
                "full_name": "Alice",
                "date_of_birth": "1990-05-20",
                "residence": "Addr",
                "street": StreetFactory().id,
                "document_number": "DOC-FIVE-CHARS",
                "id_front": _png(),
                "id_back": _png(),
            },
            context={"user_pk": user.id, "deliver_pk": None},
        )
        assert serializer.is_valid(), serializer.errors

    def test_full_name_is_stripped(self):
        user = ShippingUserFactory(phone="+5678646768")

        serializer = DeliverDataCreateSerializer(
            data={
                "full_name": "   Alice Doe   ",
                "date_of_birth": "1990-05-20",
                "residence": "Addr",
                "street": StreetFactory().id,
                "document_number": "DOC-STRIP",
                "id_front": _png(),
                "id_back": _png(),
            },
            context={"user_pk": user.id, "deliver_pk": None},
        )
        assert serializer.is_valid(), serializer.errors
        record = serializer.save()

        assert record.full_name == "Alice Doe"

    def test_document_number_uniqueness_enforced(self):
        existing = DeliverDataFactory(document_number="DOC-DUP")
        user = ShippingUserFactory(phone="+676886787")

        serializer = DeliverDataCreateSerializer(
            data={
                "full_name": "Valid Name",
                "date_of_birth": "1990-05-20",
                "residence": "Addr",
                "street": StreetFactory().id,
                "document_number": "DOC-DUP",
                "id_front": _png(),
                "id_back": _png(),
            },
            context={"user_pk": user.id, "deliver_pk": None},
        )
        assert serializer.is_valid() is False
        assert "document_number" in serializer.errors

    def test_document_number_uniqueness_ignores_self_on_update(self):
        record = DeliverDataFactory(document_number="DOC-SELF")

        serializer = DeliverDataCreateSerializer(
            record,
            data={"document_number": "DOC-SELF"},
            partial=True,
            context={"user_pk": record.deliver.user.id, "deliver_pk": None},
        )
        assert serializer.is_valid(), serializer.errors

    def test_deliver_is_read_only(self):
        """Clients cannot reassign `deliver` even if they try."""
        user = ShippingUserFactory(phone="+567864786")
        other_user = ShippingUserFactory(phone="+5678646768")
        other_deliver = other_user.delivery_profile
        record = DeliverDataFactory(deliver=user.delivery_profile)

        serializer = DeliverDataCreateSerializer(
            record,
            data={"deliver": other_deliver.id},
            partial=True,
            context={"user_pk": user.id, "deliver_pk": None},
        )
        assert serializer.is_valid(), serializer.errors
        updated = serializer.save()

        assert updated.deliver_id == user.delivery_profile.id

    def test_verification_status_is_read_only(self):
        user = ShippingUserFactory(phone="+5678646768")
        record = DeliverDataFactory(deliver=user.delivery_profile)

        serializer = DeliverDataCreateSerializer(
            record,
            data={"verification_status": DeliverData.VerificationStatus.APPROVED},
            partial=True,
            context={"user_pk": user.id, "deliver_pk": None},
        )
        assert serializer.is_valid(), serializer.errors
        updated = serializer.save()

        assert updated.verification_status == DeliverData.VerificationStatus.PENDING

    def test_approved_by_is_read_only(self):
        user = ShippingUserFactory(phone="+5678646768")
        record = DeliverDataFactory(deliver=user.delivery_profile)
        fake_approver = ShippingUserFactory()

        serializer = DeliverDataCreateSerializer(
            record,
            data={"approved_by": fake_approver.id},
            partial=True,
            context={"user_pk": user.id, "deliver_pk": None},
        )
        assert serializer.is_valid(), serializer.errors
        updated = serializer.save()

        assert updated.approved_by is None

    def test_update_other_users_record_rejected(self):
        user = ShippingUserFactory(phone="+365893545")
        other_user = ShippingUserFactory(phone="+5678646768")
        other_record = DeliverDataFactory(deliver=other_user.delivery_profile)

        serializer = DeliverDataCreateSerializer(
            other_record,
            data={"full_name": "Hacked Name"},
            partial=True,
            context={"user_pk": user.id, "deliver_pk": None},
        )
        assert serializer.is_valid() is False

    def test_update_own_record_succeeds(self):
        user = ShippingUserFactory(phone="+5678646768")
        record = DeliverDataFactory(deliver=user.delivery_profile)

        serializer = DeliverDataCreateSerializer(
            record,
            data={"full_name": "New Name"},
            partial=True,
            context={"user_pk": user.id, "deliver_pk": None},
        )
        assert serializer.is_valid(), serializer.errors
        updated = serializer.save()

        assert updated.full_name == "New Name"

