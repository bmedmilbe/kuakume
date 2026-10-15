
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.measure import D
from shipping.models import Deliver
from shopping.models import Order

from store.models import ShopVendor


# =========================================================
# Helpers — outbound envelope
# =========================================================
def _envelope(action, data=None, error=None):
    """
    Build the standard outbound WebSocket message.

    Envelope:
        {"action": "<name>", "data": {...}}

    `error` (if present) is folded into `data` to keep the schema stable.
    """
    payload = data or {}
    if error is not None:
        payload = {**payload, "error": error}
    return {"action": action, "data": payload}


def _point_to_list(point):
    """Serialise a PointField value as [lon, lat], or None."""
    if not point:
        return None
    return [point.x, point.y]


# =========================================================
# StoreConsumer — multi-shop aware
# =========================================================
class StoreConsumer(AsyncJsonWebsocketConsumer):
    """
    WebSocket consumer for authenticated vendors (store app).

    A vendor may own one or more ShopVendor rows. This consumer:

      * resolves every shop owned by the authenticated user at connect
        time;
      * joins one channel-group per active order across **all** of those
        shops (groups are named `order_{order_id}`, scoped per order, so
        there is no cross-shop leakage);
      * exposes per-shop write actions (`update_payment_status`,
        `broadcast_to_deliverers`) that verify the target shop belongs to
        the vendor before touching any data;
      * exposes a cross-shop read action (`list_orders`) that returns
        orders grouped by shop.

    Supported inbound actions:
        - list_orders                 (optional "shop_id" filter)
        - update_payment_status       (requires "shop_id" and "order_id")
        - broadcast_to_deliverers     (requires "shop_id" and "order_id")
    """

    # -----------------------------------------------------
    # Lifecycle — connect / disconnect
    # -----------------------------------------------------
    async def connect(self):
        """
        Authenticate, resolve every shop for the vendor, join all active
        per-order groups, then accept the socket.
        """
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            await self.close(code=4401)
            return

        # All shops owned by this vendor.
        shops = await self._get_vendor_shops(user.id)
        if not shops:
            await self.close(code=4403)
            return

        # Map shop_id -> shop summary so later actions don't re-query.
        self.shops = {s["id"]: s for s in shops}
        self.shop_ids = list(self.shops.keys())

        # One group per active order, across every shop.
        order_ids = await self._active_order_ids(self.shop_ids)
        self.groups_joined = []
        for order_id in order_ids:
            group_name = f"order_{order_id}"
            await self.channel_layer.group_add(group_name, self.channel_name)
            self.groups_joined.append(group_name)

        await self.accept()

        # Acknowledge with the vendor's full shop landscape.
        await self.send_json(
            _envelope(
                "connected",
                {
                    "shops": list(self.shops.values()),
                    "orders_watched": order_ids,
                },
            )
        )

    async def disconnect(self, close_code):
        """Leave every group the consumer joined."""
        for group_name in getattr(self, "groups_joined", []):
            await self.channel_layer.group_discard(group_name, self.channel_name)

    # -----------------------------------------------------
    # Dispatch
    # -----------------------------------------------------
    async def receive_json(self, content, **kwargs):
        """
        Route inbound JSON by its `action` key.

        Every response is wrapped in the standard envelope. Unknown
        actions return a structured error rather than raising.
        """
        action = content.get("action")
        payload = content.get("data") or {}

        handlers = {
            "list_orders": self._handle_list_orders,
            "update_payment_status": self._handle_update_payment_status,
            "broadcast_to_deliverers": self._handle_broadcast_to_deliverers,
        }

        handler = handlers.get(action)
        if handler is None:
            await self.send_json(
                _envelope("error", {"action": action}, error="Unknown action.")
            )
            return

        response = await handler(payload)
        if response is not None:
            await self.send_json(response)

    # -----------------------------------------------------
    # Group event handlers (from channel layer)
    # -----------------------------------------------------
    async def order_event(self, event):
        """
        Forward a channel-layer event to the connected client.

        Producers push:
            channel_layer.group_send(
                f"order_{order.id}",
                {"type": "order.event", "action": ..., "data": ...},
            )
        """
        await self.send_json(
            _envelope(event.get("action", "order_event"), event.get("data", {}))
        )

    # -----------------------------------------------------
    # Action — list_orders
    # -----------------------------------------------------
    async def _handle_list_orders(self, payload):
        """
        List orders across all owned shops, or a single shop if `shop_id`
        is provided and belongs to the vendor.
        """
        requested_shop_id = payload.get("shop_id")

        if requested_shop_id is not None:
            requested_shop_id = int(requested_shop_id)
            if requested_shop_id not in self.shops:
                return _envelope(
                    "list_orders",
                    {"shop_id": requested_shop_id},
                    error="Shop not found or not owned by this vendor.",
                )
            target_shop_ids = [requested_shop_id]
        else:
            target_shop_ids = self.shop_ids

        orders = await self._list_orders(target_shop_ids)
        return _envelope(
            "list_orders",
            {
                "shops": [self.shops[sid] for sid in target_shop_ids],
                "orders": orders,
            },
        )

    # -----------------------------------------------------
    # Action — update_payment_status
    # -----------------------------------------------------
    async def _handle_update_payment_status(self, payload):
        order_id = payload.get("order_id")
        shop_id = payload.get("shop_id")
        new_status = payload.get("payment_status")

        if order_id is None or shop_id is None or new_status is None:
            return _envelope(
                "update_payment_status",
                {"order_id": order_id, "shop_id": shop_id},
                error=(
                    "'shop_id', 'order_id', and 'payment_status' are all "
                    "required."
                ),
            )

        try:
            shop_id = int(shop_id)
            order_id = int(order_id)
        except (TypeError, ValueError):
            return _envelope(
                "update_payment_status",
                {},
                error="'shop_id' and 'order_id' must be integers.",
            )

        # Ownership check up-front, before touching the DB writer.
        if shop_id not in self.shops:
            return _envelope(
                "update_payment_status",
                {"shop_id": shop_id, "order_id": order_id},
                error="Shop not found or not owned by this vendor.",
            )

        updated, error = await self._update_payment_status(
            shop_id, order_id, new_status
        )
        if error:
            return _envelope(
                "update_payment_status",
                {"shop_id": shop_id, "order_id": order_id},
                error=error,
            )

        # Fan out to every consumer watching this order.
        await self.channel_layer.group_send(
            f"order_{order_id}",
            {
                "type": "order.event",
                "action": "payment_status_updated",
                "data": updated,
            },
        )
        return None

    # -----------------------------------------------------
    # Action — broadcast_to_deliverers
    # -----------------------------------------------------
    async def _handle_broadcast_to_deliverers(self, payload):
        order_id = payload.get("order_id")
        shop_id = payload.get("shop_id")

        if order_id is None or shop_id is None:
            return _envelope(
                "broadcast_to_deliverers",
                {"order_id": order_id, "shop_id": shop_id},
                error="'shop_id' and 'order_id' are required.",
            )

        try:
            shop_id = int(shop_id)
            order_id = int(order_id)
        except (TypeError, ValueError):
            return _envelope(
                "broadcast_to_deliverers",
                {},
                error="'shop_id' and 'order_id' must be integers.",
            )

        if shop_id not in self.shops:
            return _envelope(
                "broadcast_to_deliverers",
                {"shop_id": shop_id, "order_id": order_id},
                error="Shop not found or not owned by this vendor.",
            )

        # Verify the order belongs to the shop before fan-out.
        order_data = await self._order_for_shop(shop_id, order_id)
        if order_data is None:
            return _envelope(
                "broadcast_to_deliverers",
                {"shop_id": shop_id, "order_id": order_id},
                error="Order not found for this shop.",
            )

        # Spatial lookup — couriers within 1 km of this shop.
        courier_ids = await self._nearby_courier_user_ids(
            shop_id, radius_m=1000
        )

        shop_location = await self._shop_location(shop_id)

        for courier_id in courier_ids:
            await self.channel_layer.group_send(
                f"deliver_{courier_id}",
                {
                    "type": "deliver.offer",
                    "action": "new_delivery_offer",
                    "data": {
                        "order": order_data,
                        "shop": {
                            "id": shop_id,
                            "location": shop_location,
                        },
                    },
                },
            )

        return _envelope(
            "broadcast_to_deliverers",
            {
                "shop_id": shop_id,
                "order_id": order_id,
                "couriers_notified": len(courier_ids),
                "courier_user_ids": courier_ids,
            },
        )

    # -----------------------------------------------------
    # Synchronous ORM wrappers — all wrapped with database_sync_to_async
    # -----------------------------------------------------
    @database_sync_to_async
    def _get_vendor_shops(self, user_id):
        """
        Return a lightweight list of every ShopVendor owned by the user.

        Each entry is a JSON-safe dict so we can reuse it in messages
        without hitting the DB again.
        """
        shops = (
            ShopVendor.objects
            .filter(vendor__user_id=user_id)
            .select_related("street__district")
        )
        return [
            {
                "id": shop.id,
                "street_id": shop.street_id,
                "street_name": shop.street.name if shop.street else None,
                "city_name": (
                    shop.street.district.city_name
                    if shop.street and shop.street.district
                    else None
                ),
                "contact_number": shop.contact_number,
                "location": _point_to_list(shop.location),
            }
            for shop in shops
        ]

    @database_sync_to_async
    def _active_order_ids(self, shop_ids):
        """Active orders across a list of shops — grouped by their IDs."""
        return list(
            Order.objects
            .filter(
                shop_id__in=shop_ids,
                delivery_status__in=[
                    Order.DeliveryStatus.PENDING,
                    Order.DeliveryStatus.DISPATCHED,
                ],
            )
            .values_list("id", flat=True)
        )

    @database_sync_to_async
    def _list_orders(self, shop_ids):
        """Serialise every order for the given shops into JSON-able dicts."""
        orders = (
            Order.objects
            .filter(shop_id__in=shop_ids)
            .order_by("-created_at")
        )

        results = []
        for order in orders:
            results.append(
                {
                    "id": order.id,
                    "shop_id": order.shop_id,
                    "client_username": order.client.user.username,
                    "deliver_username": (
                        order.deliver.user.username if order.deliver else None
                    ),
                    "delivery_status": order.delivery_status,
                    "payment_status": order.payment_status,
                    "total": str(order.total),
                    "location": _point_to_list(order.location),
                    "street_id": order.street_id,
                    "created_at": order.created_at.isoformat(),
                    "updated_at": order.updated_at.isoformat(),
                    "items": [
                        {
                            "id": item.id,
                            "product_id": item.product_id,
                            "product_name": item.product.name,
                            "quantity": item.quantity,
                            "price_at_purchase": str(item.price_at_purchase),
                            "total_price": str(item.total_price),
                        }
                        for item in order.items.all()
                    ],
                }
            )
        return results

    @database_sync_to_async
    def _update_payment_status(self, shop_id, order_id, new_status):
        """
        Update the payment status of an order owned by `shop_id`.

        Allowed target statuses: PAID or FAILED.
        Returns (updated_payload, error_message).
        """
        allowed = {
            Order.PaymentStatus.PAID,
            Order.PaymentStatus.FAILED,
        }
        if new_status not in allowed:
            return None, (
                "'payment_status' must be one of: "
                f"{', '.join(sorted(allowed))}."
            )

        try:
            order = Order.objects.get(id=order_id, shop_id=shop_id)
        except Order.DoesNotExist:
            return None, "Order not found for this shop."

        order.payment_status = new_status
        order.save(update_fields=["payment_status", "updated_at"])

        return (
            {
                "shop_id": order.shop_id,
                "order_id": order.id,
                "payment_status": order.payment_status,
                "updated_at": order.updated_at.isoformat(),
            },
            None,
        )

    @database_sync_to_async
    def _order_for_shop(self, shop_id, order_id):
        """Fetch a compact order payload if it belongs to `shop_id`."""
        try:
            order = (
                Order.objects
                .select_related("client__user", "street")
                .get(id=order_id, shop_id=shop_id)
            )
        except Order.DoesNotExist:
            return None

        return {
            "id": order.id,
            "shop_id": order.shop_id,
            "client_username": order.client.user.username,
            "delivery_status": order.delivery_status,
            "payment_status": order.payment_status,
            "total": str(order.total),
            "location": _point_to_list(order.location),
            "street_id": order.street_id,
            "created_at": order.created_at.isoformat(),
        }

    @database_sync_to_async
    def _nearby_courier_user_ids(self, shop_id, radius_m=1000):
        """
        Return the user IDs of active couriers within `radius_m` metres of
        the given shop's location.

        Uses GeoDjango's `Distance` annotation and `D(m=...)` for a
        DB-level spatial filter (PostGIS `ST_DWithin`).
        """
        try:
            shop = ShopVendor.objects.only("location").get(id=shop_id)
        except ShopVendor.DoesNotExist:
            return []

        if not shop.location:
            return []

        couriers = (
            Deliver.objects
            .filter(
                is_active=True,
                location__isnull=False,
                location__distance_lte=(shop.location, D(m=radius_m)),
            )
            .annotate(distance=Distance("location", shop.location))
            .order_by("distance")
            .values_list("user_id", flat=True)
        )

        return list(couriers)

    @database_sync_to_async
    def _shop_location(self, shop_id):
        """Return the shop's location as [lon, lat] or None."""
        try:
            shop = ShopVendor.objects.only("location").get(id=shop_id)
        except ShopVendor.DoesNotExist:
            return None
        return _point_to_list(shop.location)