# kuakume/shipping/tests/test_consumers.py
import random

import pytest
from asgiref.sync import sync_to_async
from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import Point
from kuakume.asgi import application
from rest_framework_simplejwt.tokens import AccessToken
from shopping.models import Order
from shopping.tests.test_shopping_models import (  # noqa: F401
    _create_order,
    _create_order_with_client,
    _create_order_with_shop,
    _create_order_with_user,
    _create_order_with_user_and_shop,
    _create_order_without_deliver,
    _create_order_without_shop,
    _create_product,
    _fake_number,
)
from store.tests.factories import ShopVendorFactory, StoreUserFactory

from shipping.models import Deliver

User = get_user_model()


# =========================================================
# Low-level helpers
# =========================================================
def _jwt_for(user):
    """Issue a SimpleJWT access token carrying the user id claim."""
    token = AccessToken.for_user(user)
    token["id"] = user.id
    return str(token)


async def _connect(token=None):
    """Open a WebsocketCommunicator against the shipping consumer."""
    path = "/ws/shipping/"
    if token is not None:
        path = f"{path}?token={token}"

    communicator = WebsocketCommunicator(application, path)
    connected, _ = await communicator.connect()
    return communicator, connected


async def _drain(communicator):
    """Return the next JSON message from the socket."""
    return await communicator.receive_json_from(timeout=1)


async def _open_courier_socket(courier_user, *, expect_ack=True):
    """
    Open + assert connect + (optionally) drain the ack.
    Returns the communicator so the test body only needs to send/assert.
    """
    communicator, connected = await _connect(token=_jwt_for(courier_user))
    assert connected is True
    if expect_ack:
        await _drain(communicator)
    return communicator


async def _send_and_receive(communicator, payload):
    """Send a JSON message and return the next received message."""
    await communicator.send_json_to(payload)
    return await _drain(communicator)


async def _assert_action_rejected(communicator, payload):
    """Send a payload and assert the response carries an error."""
    response = await _send_and_receive(communicator, payload)
    assert response["action"] == payload["action"]
    assert "error" in response["data"]
    return response


# =========================================================
# Sync setup helpers (invoked via sync_to_async)
# =========================================================
def _make_courier(phone=None, is_active=True, is_online=False, location=None):
    """Create a courier user with a Deliver profile."""
    phone = phone or f"+{random.randint(1000000000, 9999999999)}"
    user = StoreUserFactory(phone=phone)
    deliver = user.delivery_profile
    deliver.is_active = is_active
    deliver.is_online = is_online
    if location is not None:
        deliver.location = location
    deliver.save()
    return user, deliver


def _make_courier_with_order(
    *,
    phone=None,
    location=None,
    order_location=None,
):
    """
    Create a courier and one PENDING order (unassigned).

    Returns (courier_user, deliver, order).
    """
    courier_user, deliver = _make_courier(phone=phone, location=location)

    vendor_user, vendor = _make_active_vendor()
    shop = ShopVendorFactory(vendor=vendor)
    order, _ = _create_order_without_deliver(shop=shop)
    if order_location is not None:
        Order.objects.filter(id=order.id).update(location=order_location)
    else:
        Order.objects.filter(id=order.id).update(
            location=Point(0.0, 0.0, srid=4326),
            delivery_status=Order.DeliveryStatus.PENDING,
        )
    order.refresh_from_db()
    return courier_user, deliver, order


def _make_active_vendor(phone=None):
    """Create a StoreUser whose Vendor is active."""
    phone = phone or f"+{random.randint(1000000000, 9999999999)}"
    vendor_user = StoreUserFactory(phone=phone)
    vendor = vendor_user.vendor_user
    vendor.is_active = True
    vendor.save()
    return vendor_user, vendor


def _make_courier_assigned_to_order():
    """
    Create a courier assigned to an order (order.deliver == deliver).

    Returns (courier_user, deliver, order).
    """
    courier_user, deliver = _make_courier()
    vendor_user, vendor = _make_active_vendor()
    shop = ShopVendorFactory(vendor=vendor)
    order, _ = _create_order_with_shop(shop=shop)
    Order.objects.filter(id=order.id).update(
        deliver=deliver,
        delivery_status=Order.DeliveryStatus.DISPATCHED,
        location=Point(0.0, 0.0, srid=4326),
    )
    order.refresh_from_db()
    return courier_user, deliver, order


def _make_order_for_another_courier():
    """
    Create an order assigned to a courier that is *not* the one under test.

    Returns (other_courier_user, other_deliver, order).
    """
    return _make_courier_assigned_to_order()


async def _refresh_deliver(user):
    """Fetch a fresh Deliver row from the database, async-safe."""
    return await sync_to_async(Deliver.objects.get)(user=user)


async def _refresh_order(order_id):
    """Fetch a fresh Order row from the database, async-safe."""
    return await sync_to_async(Order.objects.get)(id=order_id)


# =========================================================
# connect — state tracking & global group
# =========================================================
@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestConnect:

    async def test_connect_marks_courier_online(self):
        courier_user, _ = await sync_to_async(_make_courier)()

        communicator, connected = await _connect(token=_jwt_for(courier_user))
        assert connected is True

        ack = await _drain(communicator)
        assert ack["action"] == "connected"
        assert ack["data"]["is_online"] is True
        assert ack["data"]["group"] == "active_deliverers"

        deliver = await _refresh_deliver(courier_user)
        assert deliver.is_online is True

        await communicator.disconnect()

    async def test_connect_joins_global_active_deliverers_group(self):
        courier_user, _ = await sync_to_async(_make_courier)()

        communicator = await _open_courier_socket(courier_user)

        # Push a message into the global group. If the consumer has
        # joined, the socket will receive it.
        channel_layer = get_channel_layer()
        await channel_layer.group_send(
            "active_deliverers",
            {
                "type": "order.broadcast",
                "action": "new_order_available",
                "data": {"order_id": 999},
            },
        )

        payload = await _drain(communicator)
        assert payload["action"] == "new_order_available"
        assert payload["data"]["order_id"] == 999

        await communicator.disconnect()

    async def test_connect_without_token_is_closed(self):
        communicator, connected = await _connect(token=None)
        assert connected is False
        await communicator.disconnect()

    async def test_connect_with_invalid_token_is_closed(self):
        communicator, connected = await _connect(token="not-a-real-jwt")
        assert connected is False
        await communicator.disconnect()

    async def test_connect_with_user_without_deliver_profile_is_closed(self):
        def setup():
            user = StoreUserFactory()
            Deliver.objects.filter(user=user).delete()
            return user

        user = await sync_to_async(setup)()

        communicator, connected = await _connect(token=_jwt_for(user))
        assert connected is False
        await communicator.disconnect()


# =========================================================
# disconnect — state reversal
# =========================================================
@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestDisconnect:

    async def test_disconnect_marks_courier_offline(self):
        courier_user, _ = await sync_to_async(_make_courier)()

        communicator = await _open_courier_socket(courier_user)
        await communicator.disconnect()

        deliver = await _refresh_deliver(courier_user)
        assert deliver.is_online is False


# =========================================================
# update_location
# =========================================================
@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestUpdateLocationAction:

    async def test_update_location_persists_point(self):
        courier_user, _ = await sync_to_async(_make_courier)()

        communicator = await _open_courier_socket(courier_user)
        response = await _send_and_receive(
            communicator,
            {
                "action": "update_location",
                "data": {"location": [13.405, 52.52]},
            },
        )

        assert response["action"] == "update_location"
        assert response["data"]["location"] == [13.405, 52.52]

        deliver = await _refresh_deliver(courier_user)
        assert deliver.location.x == 13.405
        assert deliver.location.y == 52.52

        await communicator.disconnect()

    async def test_update_location_accepts_geojson_payload(self):
        courier_user, _ = await sync_to_async(_make_courier)()

        communicator = await _open_courier_socket(courier_user)
        response = await _send_and_receive(
            communicator,
            {
                "action": "update_location",
                "data": {
                    "location": {
                        "type": "Point",
                        "coordinates": [1.0, 2.0],
                    }
                },
            },
        )

        assert response["action"] == "update_location"
        assert response["data"]["location"] == [1.0, 2.0]

        deliver = await _refresh_deliver(courier_user)
        assert deliver.location.x == 1.0
        assert deliver.location.y == 2.0

        await communicator.disconnect()

    async def test_update_location_rejects_malformed_coordinates(self):
        courier_user, _ = await sync_to_async(_make_courier)()

        communicator = await _open_courier_socket(courier_user)
        await _assert_action_rejected(
            communicator,
            {
                "action": "update_location",
                "data": {"location": [1.0]},
            },
        )

        await communicator.disconnect()

    async def test_update_location_rejects_missing_payload(self):
        courier_user, _ = await sync_to_async(_make_courier)()

        communicator = await _open_courier_socket(courier_user)
        await _assert_action_rejected(
            communicator,
            {"action": "update_location", "data": {}},
        )

        await communicator.disconnect()


# =========================================================
# accept_order
# =========================================================
@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestAcceptOrderAction:

    async def test_accept_order_assigns_courier_and_joins_group(self):
        courier_user, deliver, order = await sync_to_async(
            _make_courier_with_order
        )()

        communicator = await _open_courier_socket(courier_user)
        response = await _send_and_receive(
            communicator,
            {"action": "accept_order", "data": {"order_id": order.id}},
        )
        print(response["data"])
        assert response["action"] == "accept_order"
        assert response["data"]["order_id"] == order.id
        assert response["data"]["delivery_status"] == Order.DeliveryStatus.DISPATCHED
        

        refreshed = await _refresh_order(order.id)
        assert refreshed.deliver_id == deliver.id
        assert refreshed.delivery_status == Order.DeliveryStatus.DISPATCHED

        await communicator.disconnect()

    async def test_accept_order_subscribes_to_order_group(self):
        courier_user, _, order = await sync_to_async(_make_courier_with_order)()

        communicator = await _open_courier_socket(courier_user)
        await _send_and_receive(
            communicator,
            {"action": "accept_order", "data": {"order_id": order.id}},
        )
        # The consumer also pushes an "order_accepted" broadcast into the
        # order group it just joined. Drain it.
        await _drain(communicator)

        channel_layer = get_channel_layer()
        await channel_layer.group_send(
            f"order_{order.id}",
            {
                "type": "order.event",
                "action": "payment_status_updated",
                "data": {"order_id": order.id, "payment_status": "PAID"},
            },
        )

        payload = await _drain(communicator)
        assert payload["action"] == "payment_status_updated"
        assert payload["data"]["order_id"] == order.id

        await communicator.disconnect()

    async def test_accept_order_rejects_already_assigned_to_another_courier(self):
        # Order is already dispatched to a different courier.
        other_courier, _, order = await sync_to_async(
            _make_courier_assigned_to_order
        )()

        # Under-test courier.
        courier_user, _ = await sync_to_async(_make_courier)()

        communicator = await _open_courier_socket(courier_user)
        await _assert_action_rejected(
            communicator,
            {"action": "accept_order", "data": {"order_id": order.id}},
        )

        refreshed = await _refresh_order(order.id)
        assert refreshed.deliver_id != courier_user.delivery_profile.id

        await communicator.disconnect()

    async def test_accept_order_rejects_missing_order_id(self):
        courier_user, _ = await sync_to_async(_make_courier)()

        communicator = await _open_courier_socket(courier_user)
        await _assert_action_rejected(
            communicator,
            {"action": "accept_order", "data": {}},
        )

        await communicator.disconnect()

    async def test_accept_order_rejects_unknown_order(self):
        courier_user, _ = await sync_to_async(_make_courier)()

        communicator = await _open_courier_socket(courier_user)
        await _assert_action_rejected(
            communicator,
            {"action": "accept_order", "data": {"order_id": 999999}},
        )

        await communicator.disconnect()


# =========================================================
# deliver_order
# =========================================================
@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestDeliverOrderAction:

    async def test_deliver_order_completes_and_broadcasts(self):
        courier_user, _, order = await sync_to_async(
            _make_courier_assigned_to_order
        )()

        # Join the order group by accepting first — mirrors the real flow.
        communicator = await _open_courier_socket(courier_user)
        await _send_and_receive(
            communicator,
            {"action": "accept_order", "data": {"order_id": order.id}},
        )
        await _drain(communicator)  # drain order_accepted fan-out

        response = await _send_and_receive(
            communicator,
            {"action": "deliver_order", "data": {"order_id": order.id}},
        )

        # Because `deliver_order` broadcasts into the same order group the
        # socket belongs to, the ack is delivered as an "order_delivered"
        # event rather than an "deliver_order" envelope.
        assert response["action"] == "order_delivered"
        assert response["data"]["order_id"] == order.id
        assert response["data"]["delivery_status"] == Order.DeliveryStatus.DELIVERED

        refreshed = await _refresh_order(order.id)
        assert refreshed.delivery_status == Order.DeliveryStatus.DELIVERED

        await communicator.disconnect()

    async def test_deliver_order_rejects_unauthorised_courier(self):
        # Order assigned to courier A.
        courier_a, _, order = await sync_to_async(_make_courier_assigned_to_order)()

        # Courier B is a different courier.
        courier_b, _ = await sync_to_async(_make_courier)()

        communicator = await _open_courier_socket(courier_b)
        await _assert_action_rejected(
            communicator,
            {"action": "deliver_order", "data": {"order_id": order.id}},
        )

        refreshed = await _refresh_order(order.id)
        assert refreshed.delivery_status != Order.DeliveryStatus.DELIVERED

        await communicator.disconnect()

    async def test_deliver_order_rejects_unassigned_order(self):
        courier_user, _, order = await sync_to_async(_make_courier_with_order)()

        communicator = await _open_courier_socket(courier_user)
        await _assert_action_rejected(
            communicator,
            {"action": "deliver_order", "data": {"order_id": order.id}},
        )

        refreshed = await _refresh_order(order.id)
        assert refreshed.delivery_status != Order.DeliveryStatus.DELIVERED

        await communicator.disconnect()

    async def test_deliver_order_rejects_missing_order_id(self):
        courier_user, _ = await sync_to_async(_make_courier)()

        communicator = await _open_courier_socket(courier_user)
        await _assert_action_rejected(
            communicator,
            {"action": "deliver_order", "data": {}},
        )

        await communicator.disconnect()


# =========================================================
# order_broadcast event
# =========================================================
@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestOrderBroadcastEvent:

    async def test_order_broadcast_is_relayed_as_new_order_available(self):
        courier_user, _ = await sync_to_async(_make_courier)()

        communicator = await _open_courier_socket(courier_user)

        # Mock a vendor broadcast landing on the consumer's group.
        channel_layer = get_channel_layer()
        await channel_layer.group_send(
            "active_deliverers",
            {
                "type": "order.broadcast",
                "action": "new_order_available",
                "data": {
                    "order": {
                        "id": 42,
                        "client_username": "alice",
                        "total": "45.00",
                        "location": [13.405, 52.52],
                    },
                    "shop": {"id": 7, "location": [13.401, 52.518]},
                },
            },
        )

        payload = await _drain(communicator)
        assert payload["action"] == "new_order_available"
        assert payload["data"]["order"]["id"] == 42
        assert payload["data"]["shop"]["id"] == 7

        await communicator.disconnect()

    async def test_order_broadcast_with_empty_data(self):
        courier_user, _ = await sync_to_async(_make_courier)()

        communicator = await _open_courier_socket(courier_user)

        channel_layer = get_channel_layer()
        await channel_layer.group_send(
            "active_deliverers",
            {
                "type": "order.broadcast",
                "action": "new_order_available",
                "data": {},
            },
        )

        payload = await _drain(communicator)
        assert payload["action"] == "new_order_available"
        assert payload["data"] == {}

        await communicator.disconnect()


# =========================================================
# unknown action
# =========================================================
@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestUnknownAction:

    async def test_unknown_action_returns_error_envelope(self):
        courier_user, _ = await sync_to_async(_make_courier)()

        communicator = await _open_courier_socket(courier_user)
        response = await _send_and_receive(
            communicator,
            {"action": "do_something_else", "data": {}},
        )

        assert response["action"] == "error"
        assert response["data"]["action"] == "do_something_else"
        assert response["data"]["error"] == "Unknown action."

        await communicator.disconnect()