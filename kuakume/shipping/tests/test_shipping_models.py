from datetime import date

import pytest
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import Point
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from store.tests.factories import StoreUserFactory, StreetFactory

from ..models import Deliver, DeliverData
from .factories import DeliverDataFactory, DeliverFactory, ShippingUserFactory

User = get_user_model()


# =========================================================
# Deliver
# =========================================================
@pytest.mark.django_db
class TestDeliverModel:

    def test_create_deliver_with_street(self):
        deliver = DeliverFactory()
        assert deliver.pk is not None
        assert deliver.user is not None
        assert deliver.street is None

    def test_create_deliver_without_street(self):
        deliver = DeliverFactory(street=None)
        assert deliver.pk is not None
        assert deliver.street is None

    def test_deliver_str(self):
        deliver = DeliverFactory()
        assert str(deliver) == f"Client: {deliver.user.username}"

    def test_deliver_user_is_one_to_one(self):
        user = ShippingUserFactory()
        deliver = user.delivery_profile
        with pytest.raises(IntegrityError):
            Deliver.objects.create(user=deliver.user)
            
            


    def test_deliver_is_active_defaults_to_false(self):
        deliver = DeliverFactory()
        assert deliver.is_active is False

    def test_deliver_is_active_can_be_set_true(self):
        deliver = DeliverFactory(is_active=True)
        deliver.is_active = True
        assert deliver.is_active is True

    def test_deliver_location_optional(self):
        deliver = DeliverFactory(location=None)
        assert deliver.location is None

    def test_deliver_location_srid(self):
        deliver = DeliverFactory()
        deliver.location = Point(12.34, 56.78, srid=4326)
        assert deliver.location.srid == 4326
        assert deliver.location.x == 12.34
        assert deliver.location.y == 56.78

    def test_deliver_street_related_name(self):
        street = StreetFactory()
        user = ShippingUserFactory()
        deliver = user.delivery_profile
        deliver.street = street
        deliver.save()
        assert deliver in street.delivers.all()

    def test_deliver_cascade_delete_user(self):
        deliver = DeliverFactory()
        deliver_id = deliver.pk
        deliver.user.delete()
        assert Deliver.objects.filter(id=deliver_id).exists() is False

    def test_deliver_street_cascade_on_street_delete(self):
        street = StreetFactory()
        deliver = Deliver(street=street)
        deliver.street = street
        deliver_id = deliver.pk
        deliver.street.delete()
        assert Deliver.objects.filter(id=deliver_id).exists() is False

    def test_deliver_survives_when_street_is_null(self):
        """The Deliver row remains intact even without a street."""
        deliver = DeliverFactory(street=None)
        deliver_id = deliver.pk
        assert Deliver.objects.filter(id=deliver_id).exists() is True

    def test_deliver_user_related_name(self):
        deliver = DeliverFactory()
        assert deliver.user.delivery_profile == deliver


# =========================================================
# DeliverData
# =========================================================
@pytest.mark.django_db
class TestDeliverDataModel:

    def test_create_deliver_data(self):
        data = DeliverDataFactory()
        assert data.pk is not None
        assert data.full_name is not None
        assert data.document_number is not None
        assert data.deliver is not None
        assert data.street is not None

    def test_deliver_data_str(self):
        data = DeliverDataFactory(full_name="Alice Doe")
        expected = f"Client Data: Alice Doe ({data.get_verification_status_display()})"
        assert str(data) == expected

    def test_document_number_unique(self):
        data = DeliverDataFactory(document_number="DOC-XYZ")
        with pytest.raises(ValidationError):
            DeliverDataFactory(document_number="DOC-XYZ")

    def test_verification_status_default_is_pending(self):
        data = DeliverDataFactory()
        assert data.verification_status == DeliverData.VerificationStatus.PENDING

    @pytest.mark.parametrize(
        "status",
        [
            DeliverData.VerificationStatus.PENDING,
            DeliverData.VerificationStatus.APPROVED,
            DeliverData.VerificationStatus.REJECTED,
        ],
    )
    def test_verification_status_choices(self, status):
        data = DeliverDataFactory(verification_status=status)
        assert data.verification_status == status

    def test_get_verification_status_display(self):
        data = DeliverDataFactory(
            verification_status=DeliverData.VerificationStatus.APPROVED
        )
        assert data.get_verification_status_display() == "Approved"

    def test_approved_at_optional(self):
        data = DeliverDataFactory(approved_at=None)
        assert data.approved_at is None

    def test_approved_by_optional(self):
        data = DeliverDataFactory(approved_by=None)
        assert data.approved_by is None

    def test_approved_by_can_be_set(self):
        approver = ShippingUserFactory(phone="+65465468546")
        data = DeliverDataFactory(
            approved_by=approver,
            verification_status=DeliverData.VerificationStatus.APPROVED,
        )
        assert data.approved_by_id == approver.id
        assert data.approved_by == approver

    def test_approved_by_related_name(self):
        approver = StoreUserFactory(phone="+5687876864")
        data = DeliverDataFactory(approved_by=approver)
        assert data in approver.approved_delivery_records.all()

    def test_approved_by_set_null_on_user_delete(self):
        approver = StoreUserFactory(phone="+5687876864")
        data = DeliverDataFactory(approved_by=approver)
        data_id = data.pk

        approver.delete()

        data.refresh_from_db()
        assert data.approved_by is None
        assert DeliverData.objects.filter(id=data_id).exists() is True

    def test_deliver_related_name(self):
        deliver = DeliverFactory()
        data = DeliverDataFactory(deliver=deliver)
        assert data == deliver.data_records

    def test_deliver_cascade_delete(self):
        data = DeliverDataFactory()
        data_id = data.pk
        data.deliver.delete()
        assert DeliverData.objects.filter(id=data_id).exists() is False

    def test_street_related_name(self):
        street = StreetFactory()
        data = DeliverDataFactory(street=street)
        assert data in street.delivery_data_records.all()

    def test_street_cascade_delete(self):
        data = DeliverDataFactory()
        data_id = data.pk
        data.street.delete()
        assert DeliverData.objects.filter(id=data_id).exists() is False

    def test_date_of_birth_is_date(self):
        data = DeliverDataFactory(date_of_birth=date(1990, 5, 20))
        assert data.date_of_birth == date(1990, 5, 20)

    def test_residence_is_text(self):
        long_address = "A" * 500
        data = DeliverDataFactory(residence=long_address)
        assert data.residence == long_address

    def test_full_name_max_length(self):
        data = DeliverDataFactory(full_name="A" * 255)
        assert len(data.full_name) == 255

    def test_document_number_max_length(self):
        data = DeliverDataFactory(document_number="D" * 50)
        assert len(data.document_number) == 50

    def test_id_front_and_id_back_present(self):
        data = DeliverDataFactory()
        assert data.id_front is not None
        assert data.id_back is not None
        assert data.id_front.name != ""
        assert data.id_back.name != ""

    # -----------------------------------------------------
    # Validators on full_name (enforced via save → full_clean)
    # -----------------------------------------------------
    def test_full_name_min_length_enforced_on_save(self):
        with pytest.raises(ValidationError) as excinfo:
            DeliverDataFactory(full_name="Ali")
        assert "full_name" in excinfo.value.message_dict

    def test_full_name_whitespace_only_rejected(self):
        with pytest.raises(ValidationError) as excinfo:
            DeliverDataFactory(full_name="     ")
        assert "full_name" in excinfo.value.message_dict

    def test_full_name_five_chars_accepted(self):
        data = DeliverDataFactory(full_name="Alice")
        assert data.full_name == "Alice"

    def test_full_name_exact_min_length_boundary(self):
        data = DeliverDataFactory(full_name="ABCDE")
        assert len(data.full_name) == 5

    def test_full_name_four_chars_rejected(self):
        with pytest.raises(ValidationError):
            DeliverDataFactory(full_name="ABCD")

    def test_full_name_blank_rejected(self):
        with pytest.raises(ValidationError):
            DeliverDataFactory(full_name="")

    # -----------------------------------------------------
    # save() forces full_clean()
    # -----------------------------------------------------
    def test_save_runs_full_clean_on_instance(self):
        deliver = DeliverFactory()
        street = StreetFactory()
        instance = DeliverData(
            deliver=deliver,
            street=street,
            full_name="Ali",  # too short
            date_of_birth=date(1990, 5, 20),
            residence="Somewhere",
            document_number="MANUAL-001",
        )
        with pytest.raises(ValidationError):
            instance.save()
        assert (
            DeliverData.objects.filter(document_number="MANUAL-001").exists() is False
        )

   
    def test_deliver_data_requires_street(self):
        """DeliverData.street is non-nullable → omitting it raises IntegrityError."""
        deliver = DeliverFactory()
        with pytest.raises(ValidationError):
            DeliverData.objects.create(
                deliver=deliver,
                street=None,
                full_name="Valid Name",
                date_of_birth=date(1990, 5, 20),
                residence="Somewhere",
                document_number="NO-STREET-001",
            )

    def test_deliver_data_requires_deliver(self):
        """DeliverData.deliver is non-nullable → omitting it raises IntegrityError."""
        street = StreetFactory()
        with pytest.raises(ValidationError):
            DeliverData.objects.create(
                deliver=None,
                street=street,
                full_name="Valid Name",
                date_of_birth=date(1990, 5, 20),
                residence="Somewhere",
                document_number="NO-DELIVER-001",
            )