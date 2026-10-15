# kuakume/shopping/consumers.py
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from shopping.models import Client, Order


# =========================================================
# Helpers — outbound envelope and point serialisation (DRY)
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
# ClientConsumer
# =========================================================
class ClientConsumer(AsyncJsonWebsocketConsumer):
    """
    WebSocket consumer for authenticated clients (shopping app).

    Authentication is performed by a JWT middleware that resolves
    `scope["user"]` from a `?token=<access_token>` query parameter.

    On connect:
      * every active order belonging to the authenticated client is
        fetched asynchronously;
      * the client's channel is added to each order's unique group
        (`order_{order.id}`), so a single socket receives updates for
        all of their pending orders at once;
      * an acknowledgement envelope ("connected") is sent downstream.

    Supported inbound actions:
        - track_order   ({"data": {"order_id": <id>}})

    Supported inbound channel-layer events:
        - order_event   -> forwarded to the client as
                           {"action": "order_updated", "data": {...}}
    """

    # -----------------------------------------------------
    # Lifecycle — connect / disconnect
    # -----------------------------------------------------
    async def connect(self):
        """
        Authenticate, resolve the client profile, join one group per
        active order, then accept the socket.
        """
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            await self.close(code=4401)
            return

        # Resolve the Client profile for this user.
        client = await self._get_client(user.id)
        if client is None:
            await self.close(code=4403)
            return

        self.client_id = client["id"]
        self.client_user_id = user.id
        self.groups_joined = []

        # Dynamically join one group per active order.
        active_order_ids = await self._active_order_ids(self.client_id)
        for order_id in active_order_ids:
            await self._join_group(f"order_{order_id}")

        await self.accept()

        await self.send_json(
            _envelope(
                "connected",
                {
                    "client_id": self.client_id,
                    "orders_watched": active_order_ids,
                },
            )
        )

    async def disconnect(self, close_code):
        """
        Leave every group the socket joined. Safe to call even if the
        connect phase exited early.
        """
        for group_name in getattr(self, "groups_joined", []):
            await self.channel_layer.group_discard(group_name, self.channel_name)

    # -----------------------------------------------------
    # Dispatch
    # -----------------------------------------------------
    async def receive_json(self, content, **kwargs):
        """
        Route inbound JSON by its `action` key. Unknown actions return a
        structured error instead of raising.
        """
        action = content.get("action")
        payload = content.get("data") or {}

        handlers = {
            "track_order": self._handle_track_order,
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
    # Inbound action — track_order
    # -----------------------------------------------------
    async def _handle_track_order(self, payload):
        """
        Return the full current state of a single order owned by the
        authenticated client. Includes payment_status, delivery_status,
        and the live courier location if a deliver is assigned.
        """
        order_id = payload.get("order_id")
        if order_id is None:
            return _envelope(
                "track_order", {}, error="'order_id' is required."
            )

        try:
            order_id = int(order_id)
        except (TypeError, ValueError):
            return _envelope(
                "track_order", {}, error="'order_id' must be an integer."
            )

        order_data = await self._order_for_client(self.client_id, order_id)
        if order_data is None:
            return _envelope(
                "track_order",
                {"order_id": order_id},
                error="Order not found or not owned by this client.",
            )

        # Ensure the socket is listening to this order's group, so future
        # updates are pushed automatically (idempotent).
        await self._join_group(f"order_{order_id}")

        return _envelope("track_order", order_data)

    # -----------------------------------------------------
    # Channel-layer event handler — order_event
    # -----------------------------------------------------
    async def order_event(self, event):
        """
        Forward a channel-layer event to the connected client.

        Producers push:
            channel_layer.group_send(
                f"order_{order.id}",
                {"type": "order.event", "action": ..., "data": ...},
            )

        The strict outbound schema is always:
            {"action": "order_updated", "data": {...}}
        """
        # Internal `action` (payment_status_updated, order_delivered,
        # courier_location_updated, ...) is preserved inside `data` so
        # the frontend can branch on it, while the top-level action
        # stays uniform for the client consumer.
        data = dict(event.get("data") or {})
        internal_action = event.get("action")
        if internal_action:
            data.setdefault("event", internal_action)

        await self.send_json(_envelope("order_updated", data))

    # -----------------------------------------------------
    # Internal helpers — group management (DRY)
    # -----------------------------------------------------
    async def _join_group(self, group_name):
        """Join a channel-layer group and record it for later cleanup."""
        await self.channel_layer.group_add(group_name, self.channel_name)
        if group_name not in self.groups_joined:
            self.groups_joined.append(group_name)

    # -----------------------------------------------------
    # ORM helpers — all wrapped with database_sync_to_async
    # -----------------------------------------------------
    @database_sync_to_async
    def _get_client(self, user_id):
        """
        Resolve the Client profile for this user. Returns a JSON-safe
        dict or None if the user is not a client.
        """
        try:
            client = (
                Client.objects
                .select_related("user", "street__district")
                .get(user_id=user_id, is_active=True)
            )
        except Client.DoesNotExist:
            return None

        return {
            "id": client.id,
            "username": client.user.username,
            "location": _point_to_list(client.location),
        }

    @database_sync_to_async
    def _active_order_ids(self, client_id):
        """
        Return the IDs of every active order for the client. Active means
        the order is still moving through the delivery pipeline.
        """
        return list(
            Order.objects
            .filter(
                client_id=client_id,
                delivery_status__in=[
                    Order.DeliveryStatus.PENDING,
                    Order.DeliveryStatus.DISPATCHED,
                ],
            )
            .values_list("id", flat=True)
        )

    @database_sync_to_async
    def _order_for_client(self, client_id, order_id):
        """
        Fetch a single order and serialize it, but only if it belongs to
        `client_id`. Returns a JSON-safe dict, or None on mismatch.
        """
        try:
            order = (
                Order.objects
                .select_related(
                    "client__user",
                    "shop__vendor__user",
                    "deliver__user",
                    "street",
                )
                .prefetch_related("items__product")
                .get(id=order_id, client_id=client_id)
            )
        except Order.DoesNotExist:
            return None

        return self._serialize_order(order, include_items=True)

    # -----------------------------------------------------
    # Serialisation helpers (DRY)
    # -----------------------------------------------------
    @staticmethod
    def _serialize_order(order, *, include_items=False):
        """
        Build a JSON-safe representation of an Order.

        Spatial fields (Order.location, Deliver.location) are converted
        from GeoDjango PointField to [lon, lat] arrays. When a courier is
        assigned, its live location is embedded so clients can track the
        delivery in real time.
        """
        data = {
            "order_id": order.id,
            "shop_id": order.shop_id,
            "client_username": order.client.user.username,
            "deliver_username": (
                order.deliver.user.username if order.deliver_id else None
            ),
            "delivery_status": order.delivery_status,
            "payment_status": order.payment_status,
            "total": str(order.total),
            "location": _point_to_list(order.location),
            "street_id": order.street_id,
            "created_at": order.created_at.isoformat(),
            "updated_at": order.updated_at.isoformat(),
            "courier_location": (
                _point_to_list(order.deliver.location)
                if order.deliver_id and order.deliver.location
                else None
            ),
        }

        if include_items:
            data["items"] = [
                {
                    "id": item.id,
                    "product_id": item.product_id,
                    "product_name": item.product.name,
                    "quantity": item.quantity,
                    "price_at_purchase": str(item.price_at_purchase),
                    "total_price": str(item.total_price),
                }
                for item in order.items.all()
            ]

        return data