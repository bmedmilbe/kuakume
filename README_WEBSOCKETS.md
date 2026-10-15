# Real-Time WebSocket Layer

Asynchronous communication fabric powering three Django applications (**Customer**, **Courier**, **Vendor**) through a unified **Django Channels** backbone.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Authentication](#authentication)
- [Message Contract](#message-contract)
- [Consumers](#consumers)
  - [ClientConsumer — Customer App](#clientconsumer--customer-app)
  - [DeliverConsumer — Courier App](#deliverconsumer--courier-app)
  - [StoreConsumer — Vendor App](#storeconsumer--vendor-app)
- [Channel Groups](#channel-groups)
- [Geospatial Features](#geospatial-features)
- [Testing](#testing)
- [Running the Server](#running-the-server)
- [Environment Requirements](#environment-requirements)

---

## Architecture Overview

The platform exposes a single ASGI application that multiplexes HTTP and WebSocket traffic. Every WebSocket route is wrapped in an application-specific JWT middleware stack and mounted through a shared `URLRouter`.

### ASGI Application Layout

- **ProtocolTypeRouter**
  - **"http"**: Django HTTP handler
  - **"websocket"**: AllowedHostsOriginValidator
    - **URLRouter**
      - `ws/shopping/` → ClientTokenAuthMiddlewareStack
      - `ws/shipping/` → ShippingAuthMiddlewareStack
      - `ws/store/` → VendorTokenAuthMiddlewareStack

Each route terminates in an `AsyncJsonWebsocketConsumer` dedicated to one domain.

### Route Mappings

- **Route**: `/ws/shopping/`
  - **Consumer**: `ClientConsumer`
  - **Domain**: Customer
- **Route**: `/ws/shipping/`
  - **Consumer**: `DeliverConsumer`
  - **Domain**: Courier
- **Route**: `/ws/store/`
  - **Consumer**: `StoreConsumer`
  - **Domain**: Vendor

---

## Authentication

Authentication is handled by **custom JWT middleware stacks** that intercept the WebSocket scope during the handshake.

- The access token is passed as a **query-string parameter**: `?token=<jwt>`.
- Middleware decodes the token using `rest_framework_simplejwt`.
- The resolved user is validated against its **profile** (`Client`, `Deliver`, or `Vendor`) and its `is_active` flag.
- On failure, the middleware injects an `AnonymousUser` and the consumer **closes the socket immediately** with code `4401` (unauthenticated) or `4403` (unauthorised profile).

### Middleware Stacks

- **Stack**: `ClientTokenAuthMiddlewareStack`
  - **App**: Shopping
  - **Resolves**: `Client` profile
- **Stack**: `ShippingAuthMiddlewareStack`
  - **App**: Shipping
  - **Resolves**: `Deliver` profile
- **Stack**: `VendorTokenAuthMiddlewareStack`
  - **App**: Store
  - **Resolves**: `Vendor` + shops

Each stack also wraps `CookieMiddleware` and `SessionMiddleware` to maintain parity with standard Django session handling.

---

## Message Contract

Every outbound WebSocket message follows a **strict envelope**:

```json
{
  "action": "<action_name>",
  "data": { ... }
}
```

Errors are folded into the same envelope, keeping the schema stable:

```json
{
  "action": "error",
  "data": { "error": "Unknown action." }
}
```

Inbound payloads follow the same convention:

```json
{
  "action": "<action_name>",
  "data": { ... }
}
```

---

## Consumers

### ClientConsumer — Customer App

- **Path**: `ws/shopping/?token=<jwt>`
- **Purpose**: Track live order states across all active purchases belonging to the authenticated client.
- **On connect**:
  - Resolve the Client profile from the JWT.
  - Fetch every active order (PENDING or DISPATCHED).
  - Join one channel group per order: `order_{order_id}`.
  - Emit a connected acknowledgement listing watched order IDs.
- **Inbound actions**:
  - `track_order`: returns the full state of an order owned by the client, including payment_status, delivery_status, and serialised `[longitude, latitude]` coordinates.
- **Outbound events**:
  - `connected`: handshake acknowledgement.
  - `track_order`: direct response to an inbound request.
  - `order_updated`: relay of any channel-layer event published to the order group (payment change, courier location, delivery completion, etc.).
  - `error`: structured error envelope.

#### Example outbound (broadcast relay)

```json
{
  "action": "order_updated",
  "data": {
    "order_id": 42,
    "payment_status": "PAID",
    "delivery_status": "DISPATCHED",
    "courier_location": [13.231, -8.829],
    "event": "courier_location_updated"
  }
}
```

### DeliverConsumer — Courier App

- **Path**: `ws/shipping/?token=<jwt>`
- **Purpose**: Receive delivery offers, publish live coordinate updates, and manage acceptance/delivery of orders.
- **On connect**:
  - Resolve the Deliver profile from the JWT.
  - Flip `is_online = True` in the database.
  - Join the global group `active_deliverers`.
- **On disconnect**:
  - Leave every joined group.
  - Flip `is_online = False` in the database.
- **Inbound actions**:
  - `update_location`: persist the courier's live coordinates.
  - `accept_order`: assign an order to the courier and mark it DISPATCHED.
  - `deliver_order`: mark an order as DELIVERED.
- **Outbound events**:
  - `connected`: handshake acknowledgement.
  - `new_order_available`: spatial offer pushed by StoreConsumer.
  - `order_updated`: relay of any order-group event.

### StoreConsumer — Vendor App

- **Path**: `ws/store/?token=<jwt>`
- **Purpose**: Multi-shop order management, payment confirmation, and proximity-based courier dispatch.
- **On connect**:
  - Resolve every ShopVendor owned by the authenticated vendor.
  - Fetch every active order across all owned shops.
  - Join one channel group per active order.
- **Inbound actions**:
  - `list_orders`: list orders across all owned shops (optionally filtered by `shop_id`).
  - `update_payment_status`: mark an order as PAID or FAILED, then broadcast the change to `order_{order_id}`.
  - `broadcast_to_deliverers`: scan live spatial data and push a `new_delivery_offer` to online couriers within 1 km of the shop.
- **Outbound events**:
  - `connected`: handshake acknowledgement listing owned shops and watched orders.
  - `list_orders`, `broadcast_to_deliverers`: direct responses.
  - `error`: structured error envelope.

---

## Channel Groups

Channel groups are the backbone of cross-app real-time communication. Each group is scoped to a single domain entity.

### Group Assignments

- **Group**: `order_{order_id}`
  - **Members**: ClientConsumer, StoreConsumer, DeliverConsumer
- **Group**: `active_deliverers`
  - **Members**: Every connected DeliverConsumer
- **Group**: `deliver_{user_id}`
  - **Members**: Single courier (targeted offers)

### Flow Example — Vendor Updates Payment Status

1. StoreConsumer handles `update_payment_status`.
2. Publishes to `order_{order_id}` via `channel_layer.group_send`.
3. ClientConsumer receives `order_event` and forwards it downstream as `order_updated`.
4. DeliverConsumer receives the same event and stays synchronised.

---

## Geospatial Features

Spatial operations are backed by PostGIS and accessed through GeoDjango lookups executed at the database level.

- Courier coordinates stored as `PointField(srid=4326)`.
- Shop coordinates stored as `PointField(srid=4326)`.
- Proximity filtering uses `D(m=1000)` combined with a Distance annotation.
- All spatial queries run inside `database_sync_to_async` workers.
- Coordinates are serialised to `[longitude, latitude]` arrays before being sent downstream.

### Example — Proximity Broadcast Query

```python
Deliver.objects.filter(
    is_active=True,
    is_online=True,
    location__isnull=False,
    location__distance_lte=(shop.location, D(m=1000)),
).annotate(
    distance=Distance("location", shop.location)
).order_by("distance")
```

---

## Testing

The WebSocket layer is covered by a comprehensive asynchronous pytest suite designed around rigid isolation principles.

### Principles

- No pytest fixtures, no setUp, no setup_method, no setup_class.
- Every test constructs its data locally inside the function body.
- All database setup uses `database_sync_to_async` to remain async-safe.
- Shared model helpers (from `shopping.tests.test_shopping_models`) are reused to enforce DRY at the test layer.
- The channel layer is always `InMemoryChannelLayer` — no external Redis dependency.

### Testing Tools Matrix

- **Concern**: Test runner
  - **Tool**: pytest
- **Concern**: Async support
  - **Tool**: pytest-asyncio
- **Concern**: DB isolation
  - **Tool**: `@pytest.mark.django_db(transaction=True)`
- **Concern**: WebSocket handshake
  - **Tool**: `channels.testing.WebsocketCommunicator`
- **Concern**: Channel layer
  - **Tool**: `channels.layers.InMemoryChannelLayer`
- **Concern**: ASGI application
  - **Tool**: `app.asgi.application`
- **Concern**: URL resolution
  - **Tool**: `django.urls.reverse("shopping:ws-shopping")`
- **Concern**: JWT generation
  - **Tool**: `rest_framework_simplejwt.tokens.AccessToken`

### Test Coverage Capabilities

The suite validates:

- Dynamic group joins on connect, one per active order.
- Rejection of missing or invalid tokens during handshake.
- Authorised order tracking, including serialised spatial coordinates.
- Cross-user leakage rejection with a structured error envelope.
- Channel-layer broadcast relay, forwarded as `order_updated`.
- Unknown action handling with a consistent error envelope.

### Example Test Invocation

```bash
pytest shopping/tests/test_shopping_websockets.py -v
```

---

## Running the Server

### Development Environment

```bash
daphne -b 0.0.0.0 -p 8000 app.asgi:application
```

Or, with Django's runserver (Channels 4.x):

```bash
python manage.py runserver
```

### Production Environment

Use any ASGI-compatible server:

- Daphne
- Uvicorn (`uvicorn app.asgi:application`)
- Hypercorn
- Gunicorn with uvicorn.workers.UvicornWorker

#### Example with Uvicorn

```bash
uvicorn app.asgi:application --host 0.0.0.0 --port 8000
```

### Channel Layer Configurations

#### Production Configuration (Redis-backed)

```python
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [("redis", 6379)],
        },
    },
}
```

#### Testing Configuration (In-memory layer)

```python
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    },
}
```

---

## Environment Requirements

### Dependencies

- **django**: Web framework
- **channels**: ASGI + WebSocket support
- **channels-redis**: Redis channel layer (production)
- **daphne**: ASGI server
- **djangorestframework**: Serializers and API views
- **djangorestframework-simplejwt**: JWT access token generation
- **psycopg2 / psycopg**: PostgreSQL driver
- **postgis (system)**: Spatial database engine
- **pytest**: Test runner
- **pytest-asyncio**: Async test support
- **pytest-django**: Django integration for pytest

### Required Django Settings

```python
INSTALLED_APPS += [
    "channels",
    "daphne",
    "rest_framework_simplejwt",
]

ASGI_APPLICATION = "app.asgi.application"

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",  # dev/test
    },
}
```

---

## Directory Reference

```text
shopping/
├── consumers.py           # ClientConsumer
├── middleware.py          # ClientTokenAuthMiddlewareStack
├── routing.py             # websocket_urlpatterns
└── tests/
    ├── test_shopping_models.py     # Shared model helpers
    └── test_shopping_websockets.py # ClientConsumer async suite

shipping/
├── consumers.py           # DeliverConsumer
├── middleware.py          # ShippingAuthMiddlewareStack
└── routing.py

store/
├── consumers.py           # StoreConsumer
├── middleware.py          # VendorTokenAuthMiddlewareStack
└── routing.py

app/
└── asgi.py                # ProtocolTypeRouter — mounts all routes
```

---

## Further Reading

- [Django Channels documentation](https://channels.readthedocs.io/)
- [Django Channels — Testing](https://channels.readthedocs.io/en/latest/topics/testing.html)
- [Django Channels — Channel Layers](https://channels.readthedocs.io/en/latest/topics/channel_layers.html)
- [GeoDjango documentation](https://docs.djangoproject.com/en/stable/ref/contrib/gis/)
- [PostGIS reference](https://postgis.net/documentation/)
- [djangorestframework-simplejwt](https://django-rest-framework-simplejwt.readthedocs.io/)
- [pytest-asyncio](https://github.com/pytest-dev/pytest-asyncio)
