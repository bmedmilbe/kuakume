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
from shopping.tests.test_shopping_models import (
    _create_order_with_shop,
)

from store.models import Vendor
from store.tests.factories import ShopVendorFactory, StoreUserFactory

User = get_user_model()


# =========================================================
# Low-level helpers (async)
# =========================================================
def _jwt_for(user):
    """Issue a SimpleJWT access token carrying the user id claim."""
    token = AccessToken.for_user(user)
    token["id"] = user.id
    return str(token)


async def _connect(token=None):
    """Open a WebsocketCommunicator against the store consumer."""
    path = "/ws/store/"
    if token is not None:
        path = f"{path}?token={token}"

    communicator = WebsocketCommunicator(application, path)
    connected, _ = await communicator.connect()
    return communicator, connected


async def _drain(communicator):
    """Return the next JSON message from the socket."""
    return await communicator.receive_json_from(timeout=1)


async def _open_vendor_socket(vendor_user, *, expect_ack=True):
    """
    Open + assert connect + (optionally) drain the ack.

    Returns the communicator so the test body only needs to send
    and assert. Caller is responsible for `.disconnect()`.
    """
    communicator, connected = await _connect(token=_jwt_for(vendor_user))
    assert connected is True
    if expect_ack:
        await _drain(communicator)
    return communicator


# =========================================================
# Sync setup helpers (run inside sync_to_async)
# =========================================================
def _make_active_vendor(phone=None):
    """Create a StoreUser and ensure its Vendor is active."""
    kwargs = {}
    if phone is not None:
        kwargs["phone"] = phone

    vendor_user = StoreUserFactory(**kwargs)
    vendor = vendor_user.vendor_user
    vendor.is_active = True
    vendor.save()
    return vendor_user, vendor


def _activate_order(order, status=Order.DeliveryStatus.PENDING):
    """Force an order into a given delivery status."""
    Order.objects.filter(id=order.id).update(delivery_status=status)
    return order


def _vendor_with_shops(num_shops=1, phone=None, shop_point=None):
    """
    Create an active vendor with N shops. Returns (vendor_user, [shops]).
    """
    vendor_user, vendor = _make_active_vendor(phone=phone)
    shops = []
    for _ in range(num_shops):
        kwargs = {"vendor": vendor}
        if shop_point is not None:
            kwargs["location"] = shop_point
        shops.append(ShopVendorFactory(**kwargs))
    return vendor_user, shops


def _vendor_with_active_order(shop_point=None, phone=None):
    """
    Create an active vendor, a shop, and one active PENDING order.

    Returns (vendor_user, shop, order).
    """
    vendor_user, vendor = _make_active_vendor(phone=phone)
    kwargs = {"vendor": vendor}
    if shop_point is not None:
        kwargs["location"] = shop_point
    shop = ShopVendorFactory(**kwargs)
    order, _ = _create_order_with_shop(shop=shop)
    _activate_order(order)
    return vendor_user, shop, order


def _vendor_with_three_shops_and_orders():
    """
    Vendor with 3 shops, each with a PENDING order.

    Returns (vendor_user, order_a, order_b, order_c).
    """
    vendor_user, shops = _vendor_with_shops(num_shops=3)
    order_a, _ = _create_order_with_shop(shop=shops[0])
    order_b, _ = _create_order_with_shop(shop=shops[1])
    order_c, _ = _create_order_with_shop(shop=shops[2])
    for o in (order_a, order_b, order_c):
        _activate_order(o)
    return vendor_user, order_a, order_b, order_c


def _vendor_with_orders_by_delivery_status():
    """
    Vendor with 4 orders, each at a different delivery status.

    Returns (vendor_user, active, dispatched, delivered, cancelled).
    """
    vendor_user, shop, active = _vendor_with_active_order()
    dispatched, _ = _create_order_with_shop(shop=shop)
    delivered, _ = _create_order_with_shop(shop=shop)
    cancelled, _ = _create_order_with_shop(shop=shop)

    _activate_order(dispatched, Order.DeliveryStatus.DISPATCHED)
    _activate_order(delivered, Order.DeliveryStatus.DELIVERED)
    _activate_order(cancelled, Order.DeliveryStatus.CANCELLED)

    return vendor_user, active, dispatched, delivered, cancelled


def _other_vendor_with_shop(phone=None):
    """
    A second, unrelated vendor with one shop and one order.

    Returns (other_vendor_user, other_shop, other_order).
    """
    phone = phone or f"+{random.randint(1000000000, 9999999999)}"
    other_vendor_user, vendor = _make_active_vendor(phone=phone)
    other_shop = ShopVendorFactory(vendor=vendor)
    other_order, _ = _create_order_with_shop(shop=other_shop)
    _activate_order(other_order)
    return other_vendor_user, other_shop, other_order


def _courier_near(point, phone=None):
    """Create an active courier at `point`. Returns the courier's user."""
    phone = phone or f"+{random.randint(1000000000, 9999999999)}"
    courier_user = StoreUserFactory(phone=phone)
    deliver = courier_user.delivery_profile
    deliver.location = point
    deliver.is_active = True
    deliver.is_online = True
    deliver.save()
    return courier_user


# =========================================================
# Shared payload helpers (avoid dict literals in tests)
# =========================================================
def _list_orders_payload(shop_id=None):
    data = {}
    if shop_id is not None:
        data["shop_id"] = shop_id
    return {"action": "list_orders", "data": data}


def _update_payment_payload(shop_id, order_id, new_status):
    return {
        "action": "update_payment_status",
        "data": {
            "shop_id": shop_id,
            "order_id": order_id,
            "payment_status": new_status,
        },
    }


def _broadcast_payload(shop_id=None, order_id=None):
    return {
        "action": "broadcast_to_deliverers",
        "data": {"shop_id": shop_id, "order_id": order_id},
    }


async def _send_and_receive(communicator, payload):
    """Send a JSON message and return the next received message."""
    await communicator.send_json_to(payload)
    return await _drain(communicator)


async def _assert_update_rejected(communicator, payload):
    """Send an update payload and assert the response carries an error."""
    response = await _send_and_receive(communicator, payload)
    assert response["action"] == payload["action"]
    assert "error" in response["data"]
    return response


# =========================================================
# Connect — valid JWT
# =========================================================
@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestConnectValidToken:

    async def test_connect_with_valid_token_single_shop(self):
        """Vendor with one shop and two active orders sees both in the ack."""

        def setup():
            vendor_user, shop, order_a = _vendor_with_active_order()
            order_b, _ = _create_order_with_shop(shop=shop)
            _activate_order(order_b)
            return vendor_user, shop, order_a, order_b

        vendor_user, shop, order_a, order_b = await sync_to_async(setup)()

        communicator, connected = await _connect(token=_jwt_for(vendor_user))
        assert connected is True

        ack = await _drain(communicator)
        assert ack["action"] == "connected"
        assert ack["data"]["orders_watched"] == [order_a.id, order_b.id]
        assert ack["data"]["shops"][0]["id"] == shop.id

        await communicator.disconnect()

    async def test_connect_with_multiple_shops_joins_all_orders(self):
        """Vendor with three shops joins every active per-order group."""
        vendor_user, order_a, order_b, order_c = await sync_to_async(
            _vendor_with_three_shops_and_orders
        )()

        communicator, connected = await _connect(token=_jwt_for(vendor_user))
        assert connected is True

        ack = await _drain(communicator)
        assert ack["action"] == "connected"
        assert len(ack["data"]["shops"]) == 3
        assert sorted(ack["data"]["orders_watched"]) == sorted(
            [order_a.id, order_b.id, order_c.id]
        )

        # Verify group membership by pushing one event per order group.
        channel_layer = get_channel_layer()
        for order_id in (order_a.id, order_b.id, order_c.id):
            await channel_layer.group_send(
                f"order_{order_id}",
                {
                    "type": "order.event",
                    "action": "payment_status_updated",
                    "data": {"order_id": order_id},
                },
            )

        received = set()
        for _ in range(3):
            msg = await _drain(communicator)
            assert msg["action"] == "payment_status_updated"
            received.add(msg["data"]["order_id"])

        assert received == {order_a.id, order_b.id, order_c.id}

        await communicator.disconnect()

    async def test_connect_skips_delivered_and_cancelled_orders(self):
        """DELIVERED and CANCELLED orders are not joined at connect."""
        data = await sync_to_async(_vendor_with_orders_by_delivery_status)()
        vendor_user, active, dispatched, delivered, cancelled = data

        communicator, connected = await _connect(token=_jwt_for(vendor_user))
        assert connected is True

        ack = await _drain(communicator)
        watched = ack["data"]["orders_watched"]

        assert active.id in watched
        assert dispatched.id in watched
        assert delivered.id not in watched
        assert cancelled.id not in watched

        await communicator.disconnect()


# =========================================================
# Connect — rejected paths
# =========================================================
@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestConnectRejected:

    async def test_connect_without_token_is_closed(self):
        communicator, connected = await _connect(token=None)
        assert connected is False
        await communicator.disconnect()

    async def test_connect_with_invalid_token_is_closed(self):
        communicator, connected = await _connect(token="not-a-real-jwt")
        assert connected is False
        await communicator.disconnect()

    async def test_connect_with_user_without_vendor_is_closed(self):
        def setup():
            user = StoreUserFactory()
            Vendor.objects.filter(user=user).delete()
            return user

        user = await sync_to_async(setup)()

        communicator, connected = await _connect(token=_jwt_for(user))
        assert connected is False
        await communicator.disconnect()

    async def test_connect_with_vendor_without_shop_is_closed(self):
        vendor_user, _ = await sync_to_async(_make_active_vendor)()

        communicator, connected = await _connect(token=_jwt_for(vendor_user))
        assert connected is False
        await communicator.disconnect()

    async def test_connect_with_inactive_vendor_is_closed(self):
        def setup():
            user = StoreUserFactory()
            # Ensure the vendor exists but is not active.
            vendor = user.vendor_user
            vendor.is_active = False
            vendor.save()
            ShopVendorFactory(vendor=vendor)
            return user

        vendor_user = await sync_to_async(setup)()

        communicator, connected = await _connect(token=_jwt_for(vendor_user))
        assert connected is False
        await communicator.disconnect()


# =========================================================
# list_orders
# =========================================================
@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestListOrdersAction:

    async def test_list_orders_returns_own_orders_only(self):
        def setup():
            vendor_user, shops = _vendor_with_shops(num_shops=3)
            orders = [
                _activate_order(_create_order_with_shop(shop=s)[0])
                for s in shops
            ]
            # Add a foreign vendor whose orders must never appear.
            _other_vendor_with_shop()
            return vendor_user, orders

        vendor_user, orders = await sync_to_async(setup)()
        expected_ids = {o.id for o in orders}

        communicator = await _open_vendor_socket(vendor_user)
        payload = await _send_and_receive(communicator, _list_orders_payload())

        assert payload["action"] == "list_orders"
        assert {o["id"] for o in payload["data"]["orders"]} == expected_ids

        await communicator.disconnect()

    async def test_list_orders_scoped_by_shop_id(self):
        def setup():
            vendor_user, shops = _vendor_with_shops(num_shops=2)
            order_a = _activate_order(
                _create_order_with_shop(shop=shops[0])[0]
            )
            _activate_order(_create_order_with_shop(shop=shops[1])[0])
            return vendor_user, shops[0], order_a

        vendor_user, shop_a, order_a = await sync_to_async(setup)()

        communicator = await _open_vendor_socket(vendor_user)
        payload = await _send_and_receive(
            communicator, _list_orders_payload(shop_id=shop_a.id)
        )

        assert payload["action"] == "list_orders"
        assert {o["id"] for o in payload["data"]["orders"]} == {order_a.id}

        await communicator.disconnect()

    async def test_list_orders_rejects_other_vendors_shop(self):
        def setup():
            vendor_user, _ = _vendor_with_shops(num_shops=1)
            _, other_shop, _ = _other_vendor_with_shop()
            return vendor_user, other_shop

        vendor_user, other_shop = await sync_to_async(setup)()

        communicator = await _open_vendor_socket(vendor_user)
        response = await _assert_update_rejected(
            communicator, _list_orders_payload(shop_id=other_shop.id)
        )

        assert response["data"]["shop_id"] == other_shop.id
        assert "orders" not in response["data"]

        await communicator.disconnect()


# =========================================================
# update_payment_status
# =========================================================
@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestUpdatePaymentStatusAction:

    @pytest.mark.parametrize(
        "new_status",
        [Order.PaymentStatus.PAID, Order.PaymentStatus.FAILED],
    )
    async def test_update_payment_status_valid_transitions(self, new_status):
        vendor_user, shop, order = await sync_to_async(
            _vendor_with_active_order
        )()

        communicator = await _open_vendor_socket(vendor_user)
        event = await _send_and_receive(
            communicator,
            _update_payment_payload(shop.id, order.id, new_status),
        )

        assert event["action"] == "payment_status_updated"
        assert event["data"]["order_id"] == order.id
        assert event["data"]["payment_status"] == new_status

        refreshed = await sync_to_async(Order.objects.get)(id=order.id)
        assert refreshed.payment_status == new_status

        await communicator.disconnect()

    async def test_update_payment_status_rejects_unknown_status(self):
        vendor_user, shop, order = await sync_to_async(
            _vendor_with_active_order
        )()

        communicator = await _open_vendor_socket(vendor_user)
        await _assert_update_rejected(
            communicator,
            _update_payment_payload(shop.id, order.id, "UNKNOWN"),
        )

        refreshed = await sync_to_async(Order.objects.get)(id=order.id)
        assert refreshed.payment_status == Order.PaymentStatus.PENDING

        await communicator.disconnect()

    async def test_update_payment_status_requires_shop_id(self):
        vendor_user, _, order = await sync_to_async(
            _vendor_with_active_order
        )()

        communicator = await _open_vendor_socket(vendor_user)
        # Deliberately omit shop_id.
        await _assert_update_rejected(
            communicator,
            {
                "action": "update_payment_status",
                "data": {
                    "order_id": order.id,
                    "payment_status": Order.PaymentStatus.PAID,
                },
            },
        )

        await communicator.disconnect()

    async def test_update_payment_status_rejects_other_vendors_shop(self):
        def setup():
            vendor_user, _, _ = _vendor_with_active_order()
            _, other_shop, other_order = _other_vendor_with_shop()
            return vendor_user, other_shop, other_order

        vendor_user, other_shop, other_order = await sync_to_async(setup)()

        communicator = await _open_vendor_socket(vendor_user)
        await _assert_update_rejected(
            communicator,
            _update_payment_payload(
                other_shop.id,
                other_order.id,
                Order.PaymentStatus.PAID,
            ),
        )

        refreshed = await sync_to_async(Order.objects.get)(id=other_order.id)
        assert refreshed.payment_status == Order.PaymentStatus.PENDING

        await communicator.disconnect()


# =========================================================
# broadcast_to_deliverers
# =========================================================
@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestBroadcastToDeliverersAction:

    async def test_broadcast_reaches_only_couriers_within_1km(self):
        def setup():
            shop_point = Point(0.0, 0.0, srid=4326)
            vendor_user, shop, order = _vendor_with_active_order(
                shop_point=shop_point
            )
            # Courier A — ~500 m east (inside the 1 km radius).
            courier_a = _courier_near(Point(0.0045, 0.0, srid=4326))
            # Courier B — ~2 km east (outside the 1 km radius).
            courier_b = _courier_near(Point(0.018, 0.0, srid=4326))
            return vendor_user, shop, order, courier_a, courier_b

        data = await sync_to_async(setup)()
        vendor_user, shop, order, courier_a, courier_b = data

        channel_layer = get_channel_layer()
        courier_a_group = f"deliver_{courier_a.id}"
        courier_b_group = f"deliver_{courier_b.id}"

        await channel_layer.group_add(courier_a_group, "test.channel.a")
        await channel_layer.group_add(courier_b_group, "test.channel.b")

        communicator = await _open_vendor_socket(vendor_user)
        response = await _send_and_receive(
            communicator, _broadcast_payload(shop_id=shop.id, order_id=order.id)
        )

        assert response["action"] == "broadcast_to_deliverers"
        assert response["data"]["couriers_notified"] == 1
        assert response["data"]["courier_user_ids"] == [courier_a.id]

        msg_a = await channel_layer.receive("test.channel.a")
        assert msg_a["type"] == "deliver.offer"
        assert msg_a["action"] == "new_delivery_offer"
        assert msg_a["data"]["order"]["id"] == order.id

        # Courier B's channel must remain untouched.
        with pytest.raises(Exception):
            await channel_layer.receive("test.channel.b", timeout=0.1)

        await communicator.disconnect()

    async def test_broadcast_requires_shop_and_order_ids(self):
        vendor_user, _, _ = await sync_to_async(_vendor_with_active_order)()

        communicator = await _open_vendor_socket(vendor_user)
        await _assert_update_rejected(communicator, _broadcast_payload())

        await communicator.disconnect()

    async def test_broadcast_rejects_other_vendors_shop(self):
        def setup():
            vendor_user, _, _ = _vendor_with_active_order()
            _, other_shop, other_order = _other_vendor_with_shop()
            return vendor_user, other_shop, other_order

        vendor_user, other_shop, other_order = await sync_to_async(setup)()

        communicator = await _open_vendor_socket(vendor_user)
        await _assert_update_rejected(
            communicator,
            _broadcast_payload(shop_id=other_shop.id, order_id=other_order.id),
        )

        await communicator.disconnect()