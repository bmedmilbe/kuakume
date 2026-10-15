# kuakume/shipping/consumers.py
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.contrib.gis.geos import Point
from shopping.models import Order

from shipping.models import Deliver


# =========================================================
# Helpers — outbound envelope and point (de)serialisation
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


def _list_to_point(coords):
    """
    Convert [lon, lat] (or a GeoJSON {"type": "Point", "coordinates": [...]})
    into a GeoDjango Point with SRID 4326. Raises ValueError on malformed input.
    """
    if isinstance(coords, dict):
        coords = coords.get("coordinates")

    if not isinstance(coords, (list, tuple)) or len(coords) != 2:
        raise ValueError("Coordinates must be a [lon, lat] pair.")

    lon, lat = float(coords[0]), float(coords[1])
    if not (-180.0 <= lon <= 180.0):
        raise ValueError("Longitude must be between -180 and 180.")
    if not (-90.0 <= lat <= 90.0):
        raise ValueError("Latitude must be between -90 and 90.")

    return Point(lon, lat, srid=4326)


# =========================================================
# DeliverConsumer
# =========================================================
class DeliverConsumer(AsyncJsonWebsocketConsumer):
    """
    WebSocket consumer for authenticated deliverers (shipping app).

    Each courier connects with their JWT via the query string. On connect:

      * their `Deliver` row is resolved;
      * `is_online` is set to True;
      * they join the global `active_deliverers` group so system-wide
        broadcasts (offers, service notices) can reach them.

    On disconnect, `is_online` is flipped back to False and all groups
    the socket joined are left cleanly.

    Supported inbound actions:
        - update_location    ({"data": {"location": [lon, lat]}})
        - accept_order       ({"data": {"order_id": <id>}})
        - deliver_order      ({"data": {"order_id": <id>}})

    Supported inbound channel-layer events:
        - order_broadcast    -> forwarded to the client as
                                {"action": "new_order_available", "data": {...}}
        - order_event        -> forwarded as-is from the order group
    """

    GLOBAL_GROUP = "active_deliverers"

    # -----------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------
    async def connect(self):
        """
        Authenticate, mark the courier online, join the global group,
        then accept the socket.
        """
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            await self.close(code=4401)
            return

        deliver = await self._get_deliver(user.id)
        if deliver is None:
            await self.close(code=4403)
            return

        self.deliver_id = deliver["id"]
        self.deliver_user_id = user.id
        self.groups_joined = []

        # Mark courier online and join the global group.
        await self._set_online(user.id, True)
        await self._join_group(self.GLOBAL_GROUP)

        await self.accept()

        await self.send_json(
            _envelope(
                "connected",
                {
                    "deliver_id": self.deliver_id,
                    "is_online": True,
                    "group": self.GLOBAL_GROUP,
                },
            )
        )

    async def disconnect(self, close_code):
        """
        Leave every group the socket joined and mark the courier offline.
        Runs safely even when the connect phase failed early.
        """
        for group_name in getattr(self, "groups_joined", []):
            await self.channel_layer.group_discard(group_name, self.channel_name)

        user_id = getattr(self, "deliver_user_id", None)
        if user_id is not None:
            await self._set_online(user_id, False)

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
            "update_location": self._handle_update_location,
            "accept_order": self._handle_accept_order,
            "deliver_order": self._handle_deliver_order,
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
    # Inbound action — update_location
    # -----------------------------------------------------
    async def _handle_update_location(self, payload):
        coords = payload.get("location") or payload.get("coordinates")
        if coords is None:
            return _envelope(
                "update_location",
                {},
                error="'location' must be a [lon, lat] pair.",
            )

        try:
            point = _list_to_point(coords)
        except (TypeError, ValueError) as exc:
            return _envelope("update_location", {}, error=str(exc))

        await self._save_location(self.deliver_user_id, point)

        return _envelope(
            "update_location",
            {"location": _point_to_list(point)},
        )

    # -----------------------------------------------------
    # Inbound action — accept_order
    # -----------------------------------------------------
    async def _handle_accept_order(self, payload):
        order_id = payload.get("order_id")
        if order_id is None:
            return _envelope(
                "accept_order", {}, error="'order_id' is required."
            )

        try:
            order_id = int(order_id)
        except (TypeError, ValueError):
            return _envelope(
                "accept_order", {}, error="'order_id' must be an integer."
            )

        ok, order_data, error = await self._assign_order(
            self.deliver_user_id, order_id
        )
        if not ok:
            return _envelope(
                "accept_order", {"order_id": order_id}, error=error
            )

        # Join the order group so all parties stay in sync.
        await self._join_group(f"order_{order_id}")

        # Notify the other participants (vendor + client).
        await self._broadcast_to_group(
            f"order_{order_id}",
            event_type="order.event",
            action="order_accepted",
            data={
                "order_id": order_id,
                "deliver_id": self.deliver_id,
                "deliver_username": order_data["deliver_username"],
            },
        )

        return _envelope("accept_order", order_data)

    # -----------------------------------------------------
    # Inbound action — deliver_order
    # -----------------------------------------------------
    async def _handle_deliver_order(self, payload):
        order_id = payload.get("order_id")
        if order_id is None:
            return _envelope(
                "deliver_order", {}, error="'order_id' is required."
            )

        try:
            order_id = int(order_id)
        except (TypeError, ValueError):
            return _envelope(
                "deliver_order", {}, error="'order_id' must be an integer."
            )

        ok, order_data, error = await self._complete_order(
            self.deliver_user_id, order_id
        )
        if not ok:
            return _envelope(
                "deliver_order", {"order_id": order_id}, error=error
            )

        # Fan out to the order group.
        await self._broadcast_to_group(
            f"order_{order_id}",
            event_type="order.event",
            action="order_delivered",
            data=order_data,
        )

        # Leave the order group — this courier's work on it is done.
        await self._leave_group(f"order_{order_id}")

        return _envelope("order_delivered", order_data)

    # -----------------------------------------------------
    # Channel-layer event handlers
    # -----------------------------------------------------
    async def order_broadcast(self, event):
        """
        Receive a spatial offer pushed by StoreConsumer's
        `broadcast_to_deliverers` and forward it to the courier's app.
        """
        await self.send_json(
            _envelope("new_order_available", event.get("data", {}))
        )

    async def order_event(self, event):
        """
        Receive an event from an order group (accept, payment update,
        delivery completed, ...) and forward it verbatim.
        """
        await self.send_json(
            _envelope(event.get("action", "order_event"), event.get("data", {}))
        )

    # -----------------------------------------------------
    # Internal helpers — group management
    # -----------------------------------------------------
    async def _join_group(self, group_name):
        """Join a channel-layer group and record it for later cleanup."""
        await self.channel_layer.group_add(group_name, self.channel_name)
        if group_name not in self.groups_joined:
            self.groups_joined.append(group_name)

    async def _leave_group(self, group_name):
        """Leave a channel-layer group and drop it from the cleanup list."""
        await self.channel_layer.group_discard(group_name, self.channel_name)
        if group_name in self.groups_joined:
            self.groups_joined.remove(group_name)

    async def _broadcast_to_group(self, group_name, *, event_type, action, data):
        """
        DRY helper — push one event to a channel-layer group with the
        standard envelope payload inside.
        """
        await self.channel_layer.group_send(
            group_name,
            {"type": event_type, "action": action, "data": data},
        )

    # -----------------------------------------------------
    # ORM helpers — all wrapped with database_sync_to_async
    # -----------------------------------------------------
    @database_sync_to_async
    def _get_deliver(self, user_id):
        """
        Resolve the Deliver profile for a courier.

        Returns a JSON-safe dict or None if the user is not a courier.
        """
        try:
            deliver = (
                Deliver.objects
                .select_related("user", "street__district")
                .get(user_id=user_id)
            )
        except Deliver.DoesNotExist:
            return None

        return {
            "id": deliver.id,
            "is_active": deliver.is_active,
            "is_online": deliver.is_online,
            "location": _point_to_list(deliver.location),
        }

    @database_sync_to_async
    def _set_online(self, user_id, is_online):
        """Flip the courier's is_online flag."""
        Deliver.objects.filter(user_id=user_id).update(is_online=is_online)

    @database_sync_to_async
    def _save_location(self, user_id, point):
        """Persist a courier's current position."""
        Deliver.objects.filter(user_id=user_id).update(location=point)

    @database_sync_to_async
    def _assign_order(self, user_id, order_id):
        """
        Assign an order to a courier.

        Only orders that are PENDING and not already tied to a deliverer
        can be accepted. Returns (ok, payload, error).
        """
        try:
            order = (
                Order.objects
                .select_related("client__user", "shop__vendor__user", "street")
                .get(id=order_id)
            )
        except Order.DoesNotExist:
            return False, None, "Order not found."

        if order.deliver_id is not None and order.deliver.user_id != user_id:
            return False, None, "Order already assigned to another courier."

        try:
            deliver = Deliver.objects.get(user_id=user_id)
        except Deliver.DoesNotExist:
            return False, None, "Deliver profile not found."

        order.deliver = deliver
        order.delivery_status = Order.DeliveryStatus.DISPATCHED
        order.save(update_fields=["deliver", "delivery_status", "updated_at"])

        return (
            True,
            {
                "order_id": order.id,
                "delivery_status": order.delivery_status,
                "deliver_username": deliver.user.username,
                "client_username": order.client.user.username,
                "shop_id": order.shop_id,
                "total": str(order.total),
                "location": _point_to_list(order.location),
            },
            None,
        )

    @database_sync_to_async
    def _complete_order(self, user_id, order_id):
        """
        Mark an order as DELIVERED.

        Only the courier currently assigned to the order may complete it.
        Returns (ok, payload, error).
        """
        try:
            order = (
                Order.objects
                .select_related("deliver__user", "client__user", "shop__vendor__user")
                .get(id=order_id)
            )
        except Order.DoesNotExist:
            return False, None, "Order not found."

        if order.deliver_id is None:
            return False, None, "Order has no assigned courier."

        if order.deliver.user_id != user_id:
            return False, None, "You are not the courier assigned to this order."

        order.delivery_status = Order.DeliveryStatus.DELIVERED
        order.save(update_fields=["delivery_status", "updated_at"])

        return (
            True,
            {
                "order_id": order.id,
                "delivery_status": order.delivery_status,
                "deliver_username": order.deliver.user.username,
                "client_username": order.client.user.username,
                "shop_id": order.shop_id,
                "updated_at": order.updated_at.isoformat(),
            },
            None,
        )