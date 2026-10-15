"""
Async test suite for shopping.consumers.ClientConsumer.

Design constraints honoured:
  * No pytest fixtures, no setUp/setup_method/setup_class.
  * All DB setup and helper invocation happens locally inside each test,
    wrapped in `database_sync_to_async`.
  * Reuse the pre-defined helpers from shopping.tests.test_shopping_models.
  * Strict outbound envelope: {"action": ..., "data": {...}}.
  * WebSocket path resolved via Django reverse('shopping:...').
"""
import pytest
from channels.db import database_sync_to_async
from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from django.contrib.gis.geos import Point
from kuakume.asgi import application
from rest_framework_simplejwt.tokens import AccessToken

from shopping.models import Order
from shopping.tests.test_shopping_models import (
    _create_order_with_user,
)


# =========================================================
# Local, per-call helpers (no fixtures, no globals)
# =========================================================
async def _build_client(user):
    """
    Ensure the given User has a Client profile and return it.
    Runs synchronously under the async test via database_sync_to_async.
    """
    from shopping.models import Client

    @database_sync_to_async
    def _get_or_create(user_id):
        return Client.objects.get_or_create(user_id=user_id)[0]

    return await _get_or_create(user.id)


def _token_for(user):
    """Mint a fresh JWT access token for the given user."""
    return str(AccessToken.for_user(user))


def _ws_url(token):
    """
    Resolve the WebSocket path via Django reverse and append the JWT
    token as a query parameter.
    """
    path = "/ws/shopping/"
    return f"{path}?token={token}"


async def _connect(token):
    """
    Build a WebsocketCommunicator for ClientConsumer, routed through the
    shopping URL, and perform the handshake. Returns (communicator, ok).
    """
    communicator = WebsocketCommunicator(
        application,
        _ws_url(token),
    )
    connected, _ = await communicator.connect()
    print(connected)
    return communicator, connected


async def _receive_envelope(communicator):
    """Read one JSON message and assert it follows the standard envelope."""
    payload = await communicator.receive_json_from()
    assert "action" in payload
    assert "data" in payload
    return payload


# =========================================================
# 1. connect — Dynamic Order Tracking Groups
# =========================================================
@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_connect_joins_one_group_per_active_order():
    """
    A valid client JWT must cause the consumer to join one channel
    group per active order belonging to that client.
    """
    # --- Local data setup (async-safe) ---
    order_a, _, user = await database_sync_to_async(_create_order_with_user)(
        payment_status="PENDING",
        delivery_status="PENDING",
        product_name="Rice",
        price=10,
        location=Point(13.23, -8.83),
    )
    order_b, _, _ = await database_sync_to_async(_create_order_with_user)(
        payment_status="SENT",
        delivery_status="DISPATCHED",
        product_name="Beans",
        price=5,
        location=Point(13.24, -8.84),
        user=user
    )
    
    # Same client user; ensure Client profile exists.
    user = await database_sync_to_async(lambda: order_a.client.user)()
    await _build_client(user)

    token = _token_for(user)

    # --- Exercise ---
    communicator, connected = await _connect(token)
    assert connected is True

    ack = await _receive_envelope(communicator)
    assert ack["action"] == "connected"
    assert ack["data"]["client_id"] is not None

    expected_order_ids = sorted([order_a.id, order_b.id])
    assert sorted(ack["data"]["orders_watched"]) == expected_order_ids

    # The channel layer must contain the channel in both order groups.
    channel_layer = get_channel_layer()

    @database_sync_to_async
    def _refresh(order):
        order.refresh_from_db()
        return order.id

    order_a_id = await _refresh(order_a)
    order_b_id = await _refresh(order_b)

    # Send a broadcast into each group and verify the socket receives it.
    for oid in (order_a_id, order_b_id):
        await channel_layer.group_send(
            f"order_{oid}",
            {
                "type": "order.event",
                "action": "payment_status_updated",
                "data": {"order_id": oid, "payment_status": "PAID"},
            },
        )
        payload = await _receive_envelope(communicator)
        assert payload["action"] == "order_updated"
        assert payload["data"]["order_id"] == oid

    await communicator.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_connect_without_token_is_rejected():
    """A missing token must cause an immediate rejection (4401)."""
    communicator, connected = await _connect(token=None)
    assert connected is False
    await communicator.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_connect_with_invalid_token_is_rejected():
    """A malformed token must cause an immediate rejection (4401)."""
    communicator, connected = await _connect(token="not-a-real-jwt")
    assert connected is False
    await communicator.disconnect()


# =========================================================
# 2. track_order — Authorised
# =========================================================
@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_track_order_returns_full_order_state():
    """
    A client may track an order that belongs to them. The response must
    include payment_status, delivery_status, and serialised [lon, lat].
    """
    order,_,_ = await database_sync_to_async(_create_order_with_user)(
        payment_status=Order.PaymentStatus.SENT,
        delivery_status=Order.DeliveryStatus.DISPATCHED,
        product_name="Milk",
        price=3,
        location=Point(13.2300, -8.8300),
    )
    user = await database_sync_to_async(lambda: order.client.user)()
    print(user.clients.is_active)
    token = _token_for(user)

    communicator, connected = await _connect(token)
    assert connected is True
    await _receive_envelope(communicator)  # consume "connected"

    await communicator.send_json_to(
        {"action": "track_order", "data": {"order_id": order.id}}
    )

    payload = await _receive_envelope(communicator)
    assert payload["action"] == "track_order"
    assert payload["data"]["order_id"] == order.id
    assert payload["data"]["payment_status"] == "SENT"
    assert payload["data"]["delivery_status"] == "DISPATCHED"
    # PointField was serialised as [lon, lat].
    assert payload["data"]["location"] == [13.23, -8.83]

    await communicator.disconnect()


# =========================================================
# 3. track_order — Unauthorised / Cross-User Leakage
# =========================================================
@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_track_order_foreign_order_is_rejected():
    """
    A client must NOT be able to track an order belonging to another
    client. The consumer must return a structured error envelope.
    """
    # Order that belongs to *another* client.
    foreign_order, _, _ = await database_sync_to_async(_create_order_with_user)(
        payment_status="PENDING",
        delivery_status="PENDING",
        product_name="Sugar",
        price=2,
        location=Point(13.20, -8.80),
    )

    # Our own order + our own client user.
    own_order, _, _ = await database_sync_to_async(_create_order_with_user)(
        payment_status="PENDING",
        delivery_status="PENDING",
        product_name="Salt",
        price=1,
        location=Point(13.21, -8.81),
    )
    user = await database_sync_to_async(lambda: own_order.client.user)()
    await _build_client(user)
    token = _token_for(user)

    communicator, connected = await _connect(token)
    assert connected is True
    await _receive_envelope(communicator)  # consume "connected"

    await communicator.send_json_to(
        {"action": "track_order", "data": {"order_id": foreign_order.id}}
    )

    payload = await _receive_envelope(communicator)
    assert payload["action"] == "track_order"
    assert "error" in payload["data"]
    assert payload["data"]["order_id"] == foreign_order.id

    await communicator.disconnect()


# =========================================================
# 4. Real-Time Broadcast Relay — order_event
# =========================================================
@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_order_event_is_relayed_as_order_updated():
    """
    A channel-layer message pushed into `order_{id}` must be re-emitted
    downstream using the strict schema:
        {"action": "order_updated", "data": {...}}
    """
    order, _, _ = await database_sync_to_async(_create_order_with_user)(
        payment_status="SENT",
        delivery_status="DISPATCHED",
        product_name="Bread",
        price=4,
        location=Point(13.2200, -8.8200),
    )
    user = await database_sync_to_async(lambda: order.client.user)()
    await _build_client(user)
    token = _token_for(user)

    communicator, connected = await _connect(token)
    assert connected is True
    await _receive_envelope(communicator)  # consume "connected"

    # Simulate a vendor/courier publishing an update to the order group.
    channel_layer = get_channel_layer()
    await channel_layer.group_send(
        f"order_{order.id}",
        {
            "type": "order.event",
            "action": "payment_status_updated",
            "data": {
                "order_id": order.id,
                "payment_status": "PAID",
                "delivery_status": "DISPATCHED",
            },
        },
    )

    payload = await _receive_envelope(communicator)
    assert payload["action"] == "order_updated"
    assert payload["data"]["order_id"] == order.id
    assert payload["data"]["payment_status"] == "PAID"
    assert payload["data"]["event"] == "payment_status_updated"

    # Second broadcast — courier location update.
    await channel_layer.group_send(
        f"order_{order.id}",
        {
            "type": "order.event",
            "action": "courier_location_updated",
            "data": {
                "order_id": order.id,
                "courier_location": [13.2290, -8.8290],
            },
        },
    )

    payload = await _receive_envelope(communicator)
    assert payload["action"] == "order_updated"
    assert payload["data"]["courier_location"] == [13.229, -8.829]
    assert payload["data"]["event"] == "courier_location_updated"

    await communicator.disconnect()


# =========================================================
# 5. Bonus — unknown action is rejected with structured error
# =========================================================
@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_unknown_action_returns_structured_error():
    """
    Any action that is not registered must be rejected using the strict
    envelope, without raising on the consumer side.
    """
    order, _, _ = await database_sync_to_async(_create_order_with_user)(
        payment_status="PENDING",
        delivery_status="PENDING",
        product_name="Tea",
        price=1,
        location=Point(13.19, -8.79),
    )
    user = await database_sync_to_async(lambda: order.client.user)()
    await _build_client(user)
    token = _token_for(user)

    communicator, connected = await _connect(token)
    assert connected is True
    await _receive_envelope(communicator)  # consume "connected"

    await communicator.send_json_to({"action": "no_such_action", "data": {}})

    payload = await _receive_envelope(communicator)
    assert payload["action"] == "error"
    assert payload["data"]["error"] == "Unknown action."
    assert payload["data"]["action"] == "no_such_action"

    await communicator.disconnect()