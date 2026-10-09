import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APIClient

from shipping.tests.test_shipping_serializers import _png

from ..models import Deliver, DeliverData
from .factories import (
    DeliverDataFactory,
    ShippingUserFactory,
)

User = get_user_model()


# =========================================================
# Helper — fresh APIClient inside each test
# =========================================================
def _auth_client(user):
    """Return an APIClient already authenticated as `user`."""
    client = APIClient()
    client.force_authenticate(user=user)
    return client




# =========================================================
# Deliver — /delivers/me/
# =========================================================
@pytest.mark.django_db
class TestDeliverMeEndpoint:

    def test_get_me_returns_own_profile(self):
        user = ShippingUserFactory(phone="+65768769871")
        deliver = user.delivery_profile

        client = _auth_client(user)
        response = client.get(reverse("deliver-me"))

        assert response.status_code == 200
        assert response.data["id"] == deliver.id
        assert response.data["user"] == user.id
        assert response.data["username"] == user.username

    def test_get_me_anonymous_gets_401(self):
        client = APIClient()
        response = client.get(reverse("deliver-me"))

        assert response.status_code == 401

    def test_get_me_without_deliver_returns_404(self):
        user = ShippingUserFactory(phone="+65768769871")
        Deliver.objects.filter(user=user).delete()

        client = _auth_client(user)
        response = client.get(reverse("deliver-me"))

        assert response.status_code == 404

    def test_patch_me_updates_location(self):
        user = ShippingUserFactory(phone="+65768769871")

        client = _auth_client(user)
        response = client.patch(
            reverse("deliver-me"),
            data={"lon": 33.0, "lat": 44.0},
            format="json",
        )

        assert response.status_code == 200
        user.delivery_profile.refresh_from_db()
        assert user.delivery_profile.location.x == 33.0
        assert user.delivery_profile.location.y == 44.0

    def test_patch_me_only_lon_fails(self):
        user = ShippingUserFactory(phone="+65768769871")

        client = _auth_client(user)
        response = client.patch(
            reverse("deliver-me"),
            data={"lon": 33.0},
            format="json",
        )

        assert response.status_code == 400
        assert "location" in response.data

    def test_patch_me_only_lat_fails(self):
        user = ShippingUserFactory(phone="+65768769871")

        client = _auth_client(user)
        response = client.patch(
            reverse("deliver-me"),
            data={"lat": 33.0},
            format="json",
        )

        assert response.status_code == 400
        assert "location" in response.data

    @pytest.mark.parametrize("lon", [-180.1, 180.1, 500.0])
    def test_patch_me_lon_out_of_range_fails(self, lon):
        user = ShippingUserFactory(phone="+65768769871")

        client = _auth_client(user)
        response = client.patch(
            reverse("deliver-me"),
            data={"lon": lon, "lat": 0.0},
            format="json",
        )

        assert response.status_code == 400
        assert "lon" in response.data

    @pytest.mark.parametrize("lat", [-90.1, 90.1, 500.0])
    def test_patch_me_lat_out_of_range_fails(self, lat):
        user = ShippingUserFactory(phone="+65768769871")

        client = _auth_client(user)
        response = client.patch(
            reverse("deliver-me"),
            data={"lon": 0.0, "lat": lat},
            format="json",
        )

        assert response.status_code == 400
        assert "lat" in response.data

    def test_patch_me_updates_is_active(self):
        user = ShippingUserFactory(phone="+65768769871")
        deliver = user.delivery_profile
        deliver.is_active = False
        deliver.save()

        client = _auth_client(user)
        response = client.patch(
            reverse("deliver-me"),
            data={"is_active": True},
            format="json",
        )

        assert response.status_code == 200
        deliver.refresh_from_db()
        assert deliver.is_active is True

    def test_patch_me_ignores_user_field(self):
        """`user` is not exposed → attempts to reassign are silently ignored."""
        user = ShippingUserFactory(phone="+65768769871")
        other_user = ShippingUserFactory(phone="+6954685685")

        client = _auth_client(user)
        response = client.patch(
            reverse("deliver-me"),
            data={"user": other_user.id},
            format="json",
        )

        assert response.status_code == 200
        user.delivery_profile.refresh_from_db()
        assert user.delivery_profile.user_id == user.id

    def test_put_me_not_allowed(self):
        user = ShippingUserFactory(phone="+65768769871")

        client = _auth_client(user)
        response = client.put(
            reverse("deliver-me"),
            data={"is_active": True},
            format="json",
        )

        assert response.status_code == 405

    def test_delete_me_not_allowed(self):
        user = ShippingUserFactory(phone="+65768769871")

        client = _auth_client(user)
        response = client.delete(reverse("deliver-me"))

        assert response.status_code == 405


# =========================================================
# Deliver — not-routed routes
# =========================================================
@pytest.mark.django_db
class TestDeliverNotRouted:

    def test_get_deliver_list_not_routed(self):
        user = ShippingUserFactory(phone="+65768769871")
        client = _auth_client(user)
        # `/api/delivers/` is not registered — literal path is intentional.
        response = client.get("/api/delivers/")

        assert response.status_code == 404

    def test_get_deliver_detail_not_routed(self):
        user = ShippingUserFactory(phone="+65768769871")
        deliver = user.delivery_profile
        client = _auth_client(user)
        response = client.get(f"/api/delivers/{deliver.id}/")

        assert response.status_code == 404


# =========================================================
# DeliverData — POST /delivery-data/
# =========================================================
@pytest.mark.django_db
class TestDeliverDataCreateEndpoint:

    def test_post_creates_record(self):
        user = ShippingUserFactory(phone="+65768769871")

        client = _auth_client(user)
        response = client.post(
            reverse("deliver-data-list"),
            data={
                "full_name": "Valid Name",
                "date_of_birth": "1990-05-20",
                "residence": "Addr",
                "street": __import__(
                    "store.tests.factories", fromlist=["StreetFactory"]
                ).StreetFactory().id,
                "document_number": "DOC-HTTP-001",
                "id_front": _png("f.png"),
                "id_back": _png("b.png"),
            },
            format="multipart",
        )
        assert response.status_code == 201
        assert response.data["full_name"] == "Valid Name"
        assert response.data["document_number"] == "DOC-HTTP-001"
        assert response.data["verification_status"] == "PENDING"

        user.delivery_profile.refresh_from_db()
        assert DeliverData.objects.filter(deliver__user=user).count() == 1

    def test_post_with_short_full_name_fails(self):
        user = ShippingUserFactory(phone="+65768769871")
        from store.tests.factories import StreetFactory

        client = _auth_client(user)
        response = client.post(
            reverse("deliver-data-list"),
            data={
                "full_name": "Ali",
                "date_of_birth": "1990-05-20",
                "residence": "Addr",
                "street": StreetFactory().id,
                "document_number": "DOC-SHORT-NAME",
                "id_front": _png(),
                "id_back": _png(),
            },
            format="multipart",
        )

        assert response.status_code == 400
        assert "full_name" in response.data

    def test_post_with_duplicate_document_number_fails(self):
        user = ShippingUserFactory(phone="+65768769871")
        other_user = ShippingUserFactory(phone="+6954685685")
        from store.tests.factories import StreetFactory

        # create an existing record on another user with the same document_number
        DeliverDataFactory(
            deliver=other_user.delivery_profile,
            document_number="DOC-DUP",
        )

        client = _auth_client(user)
        response = client.post(
            reverse("deliver-data-list"),
            data={
                "full_name": "Valid Name",
                "date_of_birth": "1990-05-20",
                "residence": "Addr",
                "street": StreetFactory().id,
                "document_number": "DOC-DUP",
                "id_front": _png(),
                "id_back": _png(),
            },
            format="multipart",
        )

        assert response.status_code == 400
        assert "document_number" in response.data

    def test_post_twice_returns_400(self):
        user = ShippingUserFactory(phone="+65768769871")
        from store.tests.factories import StreetFactory

        DeliverDataFactory(deliver=user.delivery_profile)

        client = _auth_client(user)
        response = client.post(
            reverse("deliver-data-list"),
            data={
                "full_name": "Another Name",
                "date_of_birth": "1990-05-20",
                "residence": "Addr",
                "street": StreetFactory().id,
                "document_number": "DOC-DUPLICATE-POST",
                "id_front": _png(),
                "id_back": _png(),
            },
            format="multipart",
        )

        assert response.status_code == 400
        assert "detail" in response.data

    def test_post_anonymous_gets_401(self):
        client = APIClient()
        response = client.post(reverse("deliver-data-list"), data={})

        assert response.status_code == 401


# =========================================================
# DeliverData — /delivery-data/me/
# =========================================================
@pytest.mark.django_db
class TestDeliverDataMeEndpoint:

    def test_get_me_returns_record(self):
        user = ShippingUserFactory(phone="+65768769871")
        record = DeliverDataFactory(deliver=user.delivery_profile)

        client = _auth_client(user)
        response = client.get(reverse("deliver-data-me"))

        assert response.status_code == 200
        assert response.data["id"] == record.id
        assert response.data["full_name"] == record.full_name
        assert response.data["verification_status"] == "PENDING"
        assert response.data["verification_status_display"] == "Pending Verification"

    def test_get_me_anonymous_gets_401(self):
        client = APIClient()
        response = client.get(reverse("deliver-data-me"))

        assert response.status_code == 401

    def test_get_me_without_record_returns_404(self):
        user = ShippingUserFactory(phone="+65768769871")
        DeliverData.objects.filter(deliver__user=user).delete()

        client = _auth_client(user)
        response = client.get(reverse("deliver-data-me"))

        assert response.status_code == 404

    def test_patch_me_updates_full_name(self):
        user = ShippingUserFactory(phone="+65768769871")
        record = DeliverDataFactory(deliver=user.delivery_profile)

        client = _auth_client(user)
        response = client.patch(
            reverse("deliver-data-me"),
            data={"full_name": "New Name"},
            format="json",
        )

        assert response.status_code == 200
        record.refresh_from_db()
        assert record.full_name == "New Name"

    def test_patch_me_updates_residence(self):
        user = ShippingUserFactory(phone="+65768769871")
        record = DeliverDataFactory(deliver=user.delivery_profile)

        client = _auth_client(user)
        response = client.patch(
            reverse("deliver-data-me"),
            data={"residence": "New Residence"},
            format="json",
        )

        assert response.status_code == 200
        record.refresh_from_db()
        assert record.residence == "New Residence"

    def test_patch_me_does_not_change_deliver(self):
        user = ShippingUserFactory(phone="+65768769871")
        record = DeliverDataFactory(deliver=user.delivery_profile)
        original_deliver_id = record.deliver_id

        client = _auth_client(user)
        response = client.patch(
            reverse("deliver-data-me"),
            data={"deliver": 999999},
            format="json",
        )

        assert response.status_code == 200
        record.refresh_from_db()
        assert record.deliver_id == original_deliver_id

    def test_patch_me_does_not_change_verification_status(self):
        user = ShippingUserFactory(phone="+65768769871")
        record = DeliverDataFactory(deliver=user.delivery_profile)

        client = _auth_client(user)
        response = client.patch(
            reverse("deliver-data-me"),
            data={"verification_status": "APPROVED"},
            format="json",
        )

        assert response.status_code == 200
        record.refresh_from_db()
        assert record.verification_status == DeliverData.VerificationStatus.PENDING

    

    def test_delete_me_removes_record(self):
        user = ShippingUserFactory(phone="+65768769871")
        record = DeliverDataFactory(deliver=user.delivery_profile)
        record_id = record.id

        client = _auth_client(user)
        response = client.delete(reverse("deliver-data-me"))

        assert response.status_code == 204
        assert DeliverData.objects.filter(id=record_id).exists() is False

    def test_delete_me_anonymous_gets_401(self):
        client = APIClient()
        response = client.delete(reverse("deliver-data-me"))

        assert response.status_code == 401

    def test_post_me_not_allowed(self):
        user = ShippingUserFactory(phone="+65768769871")

        client = _auth_client(user)
        response = client.post(reverse("deliver-data-me"), data={})

        assert response.status_code == 405


# =========================================================
# DeliverData — not-routed routes
# =========================================================
@pytest.mark.django_db
class TestDeliverDataNotRouted:

    def test_get_list_not_routed(self):
        user = ShippingUserFactory(phone="+65768769871")
        client = _auth_client(user)
        response = client.get("/api/delivery-data/")

        assert response.status_code == 404

    def test_get_detail_by_id_not_routed(self):
        user = ShippingUserFactory(phone="+65768769871")
        record = DeliverDataFactory(deliver=user.delivery_profile)
        client = _auth_client(user)
        response = client.get(f"/api/delivery-data/{record.id}/")

        assert response.status_code == 404


# =========================================================
# Cross-user isolation
# =========================================================
@pytest.mark.django_db
class TestCrossUserIsolation:

    def test_user_a_cannot_read_user_b_record_via_me(self):
        user_a = ShippingUserFactory()
        user_b = ShippingUserFactory(phone="+6546876854")
        DeliverDataFactory(deliver=user_b.delivery_profile)

        client = _auth_client(user_a)
        response = client.get(reverse("deliver-data-me"))

        assert response.status_code == 404

    def test_user_a_me_returns_own_record_not_b(self):
        user_a = ShippingUserFactory()
        user_b = ShippingUserFactory(phone="+6546876854")
        DeliverDataFactory(
            deliver=user_a.delivery_profile,
            full_name="User A Name",
        )
        DeliverDataFactory(
            deliver=user_b.delivery_profile,
            full_name="User B Name",
        )

        client = _auth_client(user_a)
        response = client.get(reverse("deliver-data-me"))

        assert response.status_code == 200
        assert response.data["full_name"] == "User A Name"


# =========================================================
# DeliverDataApproval — staff-only
# =========================================================
@pytest.mark.django_db
class TestDeliverDataApprovalEndpoint:

    def test_anonymous_gets_401(self):
        client = APIClient()
        record = DeliverDataFactory()
        url = reverse("deliver-data-approval-detail", args=[record.id])
        response = client.patch(url, data={}, format="json")

        assert response.status_code == 401

    def test_non_staff_gets_403(self):
        user = ShippingUserFactory(phone="+65768769871")
        record = DeliverDataFactory()

        client = _auth_client(user)
        url = reverse("deliver-data-approval-detail", args=[record.id])
        response = client.patch(url, data={}, format="json")

        assert response.status_code == 403

    def test_staff_can_patch(self):        
        record = DeliverDataFactory()
        user = record.deliver.user
        user.is_staff=True
        user.save()
        client = _auth_client(user)
        url = reverse("deliver-data-approval-detail", args=[record.id])
        response = client.patch(url, data={"full_name": "Approved Name"}, format="json")

        assert response.status_code == 200
        record.refresh_from_db()
        assert record.full_name == "Approved Name"