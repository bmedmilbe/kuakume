# Kuakume — Real-Time Multi-App Delivery Platform

A distributed, real-time delivery platform built with **Django 5**, **Django REST Framework**, **Django Channels 4**, and **GeoDjango**. Kuakume unifies three interacting user-facing applications — **Customer**, **Courier**, and **Vendor** — under a single asynchronous communication fabric, enabling live order coordination, spatial courier dispatch, and user-scoped data isolation across every role.

---

## Table of Contents

- [Overview](#overview)
- [Architecture & ASGI Layout](#architecture--asgi-layout)
- [Authentication Stack](#authentication-stack)
- [Core Features](#core-features)
- [Tech Stack & System Requirements](#tech-stack--system-requirements)
- [Project Directory Structure](#project-directory-structure)
- [Getting Started](#getting-started)
- [Environment Variables](#environment-variables)
- [Database & Migrations](#database--migrations)
- [Running the Application](#running-the-application)
- [WebSocket API & Message Contract](#websocket-api--message-contract)
- [REST API Overview](#rest-api-overview)
- [Testing Infrastructure](#testing-infrastructure)
- [Design Principles](#design-principles)
- [Roadmap](#roadmap)
- [Licence](#licence)

---

## Overview

Kuakume operates as a three-sided marketplace and real-time delivery management engine:

- **Customer app (`shopping`)** — Browses shops, builds shopping carts, places orders, and tracks live delivery status.
- **Courier app (`shipping`)** — Receives proximity-based delivery offers and pushes live coordinate updates.
- **Vendor app (`store`)** — Manages multi-shop order fulfilment pipelines and triggers courier broadcasts.

All three application domains share an asynchronous communication layer built upon a unified **Django Channels** infrastructure, utilising a strict JSON wrapper pattern and query-string resolved JWT handshakes.

---

## Architecture & ASGI Layout

The platform runs a single ASGI application entry point that transparently multiplexes HTTP and WebSocket traffic. WebSocket routes are isolated by custom middleware stacks and handled by targeted domain consumers.

### ASGI Application Layout

- **ProtocolTypeRouter**
  - **"http"**: Standard Django HTTP handler.
  - **"websocket"**: `AllowedHostsOriginValidator`
    - **URLRouter**
      - `ws/shopping/` → Wrapped by `ClientTokenAuthMiddlewareStack`.
      - `ws/shipping/` → Wrapped by `ShippingAuthMiddlewareStack`.
      - `ws/store/` → Wrapped by `VendorTokenAuthMiddlewareStack`.

### Consumer Map

- **Route**: `/ws/shopping/`
  - **Consumer**: `ClientConsumer`
  - **Domain**: Customer Application
- **Route**: `/ws/shipping/`
  - **Consumer**: `DeliverConsumer`
  - **Domain**: Courier Application
- **Route**: `/ws/store/`
  - **Consumer**: `StoreConsumer`
  - **Domain**: Vendor Application

### Channel Topology

```
                     ┌────────────────────────────────────┐
                     │           Django Channels          │
                     │   (Redis or InMemory channel layer)│
                     └──────────────┬─────────────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        │                           │                           │
┌───────▼─────────┐ ┌────────▼────────┐ ┌─────────▼───────┐
│ ClientConsumer │ │ DeliverConsumer │ │ StoreConsumer │
│ (shopping app) │ │ (shipping app) │ │ (store app) │
└───────┬─────────┘ └────────┬────────┘ └─────────┬───────┘
        │                    │                    │
        └──── groups: order_{id} ─────────┴──── groups: deliver_{user_id} ─┘
                             │
                  groups: active_deliverers
```

Every active consumer instance validates request ownership before performing database modifications, drops into `database_sync_to_async` worker execution threads for ORM queries, and communicates strictly through structured event wrappers.

---

## Authentication Stack

Authentication is handled via **custom JWT middleware stacks** that intercept the connection scope during the initial WebSocket handshake.

- The token is parsed from query parameters: `?token=<jwt>`.
- Scope tokens are decoded down via `rest_framework_simplejwt`.
- Resolved profile targets (`Client`, `Deliver`, or `Vendor`) are cross-referenced with `is_active` database state flags.
- Valid handshakes for the `VendorTokenAuthMiddlewareStack` resolve both the base `Vendor` object and related vendor shop ownership scopes.
- Failed handshakes automatically populate an `AnonymousUser` identity context and **terminate the socket connection** immediately with specific status codes: `4401` (Unauthenticated) or `4403` (Unauthorised Profile).

Middleware stacks additionally wrap standard `CookieMiddleware` and `SessionMiddleware` components to preserve session uniformity across operations.

---

## Core Features

### Real-Time Coordination

- **State Sync**: Push instant pipeline update triggers out to customers and vendor managers simultaneously.
- **Courier Lifecycle**: Instantly sets the courier's availability (`is_online = True/False`) within the database upon matching socket connection lifecycle events.

### Geospatial Processing

- **Spatial Architecture**: Leverages database-backed **PostGIS** operations exposed via GeoDjango engine APIs.
- **Field Mappings**: Standardised `PointField(srid=4326)` structures model courier coordinates and static shop fronts.
- **Proximity Search**: Proximity searches combine distance annotations with database filters executing `location__distance_lte=(shop.location, D(m=1000))`.

### Vendor-Triggered Broadcasts

- Vendor managers trigger a localized search via the `broadcast_to_deliverers` payload action.
- Scans for matching couriers within a **1 km** geographic radius who maintain active status indicators (`is_active=True`, `is_online=True`).
- Eligible couriers are messaged via targeted `deliver_{user_id}` group entries, returning telemetry detailing total notification numbers and the corresponding targets.

### User-Scoped Isolation

- Core viewset components filter object states down by checking `client__user`, `vendor__user`, or `deliver__user` relationships.
- Broken or cross-tenant operations throw clear **404 Not Found** errors instead of revealing state existence metrics.

### Guest Checkout

- Anonymous users receive tracking hashes down using a dedicated `guest_token` cookie string.
- System logins trigger a cart resolution flow that merges guest items back into primary profiles via `Cart.attach_to_client()` execution routines.

---

## Tech Stack & System Requirements

### Platform Components

- **Language Layer**: Python 3.11+
- **Core Framework**: Django 5.x
- **API Engine**: Django REST Framework
- **Async Fabric**: Django Channels 4
- **Broker Storage**: Redis 7+
- **Spatial Mapping**: GeoDjango + PostGIS
- **Auth Component**: SimpleJWT
- **Routing Layer**: `drf-nested-routers`
- **Database Backend**: PostgreSQL 14+
- **Testing Drivers**: pytest, pytest-django, pytest-asyncio

### Environment Dependencies

- `django` & `channels`: Base application frameworks.
- `channels-redis`: Redis engine adapter layer (Production).
- `daphne` & `uvicorn`: ASGI server components.
- `djangorestframework` & `djangorestframework-simplejwt`: Serialization, views, and auth tokens.
- `psycopg` / `psycopg2`: Primary PostgreSQL database connectors.
- `pytest-django` & `pytest-asyncio`: Automated test isolation infrastructure.

---

## Project Directory Structure

```text
kuakume/                            # Main project repository root
├── kuakume/                        # Central system configuration
│   ├── asgi.py                     # Asynchronous application route mounting
│   ├── settings/                   # Modular settings environment files
│   └── urls.py                     # Root HTTP endpoints mapping configuration
├── store/                          # Vendor App domain logic
│   ├── consumers.py                # StoreConsumer implementation
│   ├── middleware.py               # VendorTokenAuthMiddlewareStack
│   ├── models.py                   # Shop, Product, Vendor entity schemas
│   ├── serializers.py              # Vendor-centric request parsing logic
│   ├── views.py                    # Scoped merchant endpoint handlers
│   └── tests/                      # Automated domain validation code
├── shopping/                       # Customer App domain logic
│   ├── consumers.py                # ClientConsumer implementation
│   ├── models.py                   # Order, Cart, Client entity schemas
│   ├── serializers.py              # Order layout payload validation rules
│   ├── views.py                    # Customer API endpoints
│   └── tests/                      # Core customer functional tests
├── shipping/                       # Courier App domain logic
│   ├── consumers.py                # DeliverConsumer implementation
│   ├── middleware.py               # ShippingAuthMiddlewareStack
│   ├── models.py                   # Deliver, DeliverData geospatial entities
│   └── views.py                    # Fleet telemetry API viewsets
├── core/                           # Shared library utilities (Base Managers, User overrides)
├── docker-compose.yml              # Multi-container orchestration definition
└── Dockerfile                      # Application server image build manifest
```

---

## Getting Started

### 1. Environment Activation

```bash
git clone https://github.com/bmedmilbe/kuakume.git
cd kuakume

# Setup Python environment
python -m venv .venv
source .venv/bin/activate       # Linux / macOS
.venv\Scripts\activate          # Windows
```

_(Pipenv users can alternatively run `pipenv install --dev && pipenv shell` to stand up requirements)._

### 2. Dependency Resolution

```bash
pip install -r requirements.txt
```

### 3. Environment Variable Provisioning

```bash
cp .env.example .env
```

Ensure configurations in `.env` align with your target system components.

---

## Environment Variables

The application references these key variables for infrastructure connections:

```ini
# Django Configuration
DJANGO_SECRET_KEY=change-me-in-production-environments
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1

# Database Backend Configuration
DB_NAME=kuakume
DB_USER=kuakume
DB_PASSWORD=kuakume
DB_HOST=localhost
DB_PORT=5432

# Channel Broker Configuration
CHANNEL_LAYER_BACKEND=channels_redis.core.RedisChannelLayer
CHANNEL_LAYER_HOST=127.0.0.1
CHANNEL_LAYER_PORT=6379

# JSON Web Token Lifespans
JWT_ACCESS_TOKEN_LIFETIME_MINUTES=60
JWT_REFRESH_TOKEN_LIFETIME_DAYS=7

# System File Directories
MEDIA_ROOT=/var/media/kuakume
STATIC_ROOT=/var/static/kuakume
```

---

## Database & Migrations

Database operations require an active PostGIS geospatial extension instance. Connect to your PostgreSQL database instance and activate the driver:

```sql
CREATE EXTENSION IF NOT EXISTS postgis;
```

Execute migrations and bootstrap structural records into place using application data seeds:

```bash
python manage.py makemigrations
python manage.py migrate

# Inject database fixtures
python manage.py loaddata store/fixtures/districts.json
python manage.py loaddata store/fixtures/categories.json
```

---

## Running the Application

### Development (ASGI Server Stack)

Start the asynchronous environment directly via Daphne:

```bash
daphne -b 0.0.0.0 -p 8000 kuakume.asgi:application
```

Alternatively, execute via manage scripts:

```bash
python manage.py runserver
```

_(With `channels` included inside `INSTALLED_APPS`, the default dev server overrides standard WSGI threads to run an ASGI loop automatically)._

### Multi-Container Provisioning

```bash
docker compose up --build
```

This orchestrates the operational database engine (PostGIS), the broker cache layer (Redis), and the Daphne web application image concurrently.

### Production Deployment

Production setups should decouple traffic management across standardized infrastructure topologies:

- **Reverse Proxy**: Stand up Nginx in front of application streams to manage TLS termination and direct incoming WebSocket upgrade actions.
- **Process Worker Engines**: Run mixed production pools via Uvicorn components managed by Gunicorn (`gunicorn kuakume.asgi:application -k uvicorn.workers.UvicornWorker`).
- **Channel Layer Backend**: Wire settings up to use `channels_redis.core.RedisChannelLayer` to allow the cluster to scale horizontally across multiple application nodes.

---

## WebSocket API & Message Contract

### Envelope Contract

All payloads transmitted across active sockets follow a rigid structural wrapper contract:

_Inbound / Outbound Data Formats_

```json
{
  "action": "<action_name>",
  "data": { "...": "..." }
}
```

_Error Wrapper Structure_

```json
{
  "action": "error",
  "data": { "error": "Descriptive machine-readable reason string." }
}
```

### Application Client Actions (`ClientConsumer`)

- **Endpoint Path**: `ws/shopping/?token=<jwt>`
- **Lifecycle Connections**: Resolves user context, scans for `PENDING` or `DISPATCHED` state entries, signs the connection onto `order_{order_id}` channel entries, and returns confirmation parameters.
- **Inbound Payloads**:
  - `track_order`: Retrieves live attributes including serialised coordinate vectors `[longitude, latitude]`.
- **Outbound Broadcast Relays**:
  - `order_updated`: Fires out real-time alerts whenever state changes occur within the target order channel.

### Courier Fleet Actions (`DeliverConsumer`)

- **Endpoint Path**: `ws/shipping/?token=<jwt>`
- **Lifecycle Connections**: Assigns online flags (`is_online = True`) and registers the socket instance to the global `active_deliverers` group. Disconnection automatically reverses the presence flags.
- **Inbound Payloads**:
  - `update_location`: Persists active coordinates down to backend data stores.
  - `accept_order`: Pairs the target order to the courier identity and marks status trackers as `DISPATCHED`.
  - `deliver_order`: Transitions order pipelines cleanly to `DELIVERED` status indicators.
- **Outbound Event Emits**:
  - `new_order_available`: Relays nearby broadcast notifications pushed down by merchant updates.

### Merchant Vendor Actions (`StoreConsumer`)

- **Endpoint Path**: `ws/store/?token=<jwt>`
- **Lifecycle Connections**: Map all physical `ShopVendor` relationships, check for active orders, and map paths into target order group keys.
- **Inbound Payloads**:
  - `list_orders`: Returns matching transaction logs, optionally filtered down using `shop_id` variables.
  - `update_payment_status`: Updates specific target profiles to `PAID` or `FAILED` states, broadcasting updates to `order_{order_id}` channels.
  - `broadcast_to_deliverers`: Leverages geographic calculations to identify active nearby couriers within a 1 km boundary.

---

## REST API Overview

All HTTP endpoints mandate operational authentication verification states (`IsAuthenticated`) unless explicitly noted.

### Merchant Pipelines (`store`)

- `/api/store/vendors/me/` — Retrieve or patch profile parameters for the active vendor.
- `/api/store/vendors/{vendor_pk}/shops/` — Manage individual retail operations (Nested).
- `/api/store/products/` — Master catalogue product configuration management.
- `/api/store/products/{product_pk}/images/` — Upload or manage item graphics data assets (Nested).

### Consumer Shopping (`shopping`)

- `/api/shopping/clients/me/` — Manage profile states for the active client.
- `/api/shopping/orders/` — View history records, submit checkouts, or inspect transactions.
- `/api/shopping/carts/` — Active shopping basket item manipulation (Guest state cookies supported).
- `/api/shopping/carts/merge/` — Merges anonymous guest items back into authenticated user sessions.

### Fleet Operations (`shipping`)

- `/api/shipping/delivers/me/` — Access profile information for the authenticated courier.
- `/api/shipping/delivery-data/` — Instantiate underlying operational metadata tracking parameters.
- `/api/shipping/delivery-data/me/` — Complete CRUD management of self-owned delivery attributes.

---

## Testing Infrastructure

Automated quality verification loops manage regressions via `pytest`, executing tasks asynchronously under strict data isolation logic.

### Operational Testing Guidelines

- **Zero Fixture Usage**: Tests construct data dependencies locally within the execution body to maintain total clarity.
- **No Global Hook Setups**: Avoids common `setUp`, `setup_method`, or `setup_class` configurations entirely.
- **Data Factory Blueprints**: Employs discrete `DjangoModelFactory` representations driven by Factory Boy parameters.
- **Async Safety Enforcements**: Consumer validations utilize `@pytest.mark.django_db(transaction=True)` annotations.
- **Isolated Channel Sandboxing**: Execution contexts override settings to use an in-memory communications broker (`InMemoryChannelLayer`) to decouple tests from external system dependencies.

### Infrastructure Components Mapping

- **Execution Runner**: `pytest`
- **Async Event Handling**: `pytest-asyncio`
- **Socket Handshake Testing**: `channels.testing.WebsocketCommunicator`
- **Target Path Resolution**: `django.urls.reverse("shopping:ws-shopping")`
- **Mock Auth Generation**: `rest_framework_simplejwt.tokens.AccessToken`

### Command Execution Execution

```bash
# Execute suite
DJANGO_SETTINGS_MODULE=kuakume.settings_test pytest -v

# Generate local test coverage reporting maps
pytest --cov=. --cov-report=html
```

---

## Design Principles

- **Non-Blocking Architecture**: Consumers avoid blocking event loops by routing synchronous engine executions through async task wrappers (`database_sync_to_async`).
- **Hermetic Tenant Isolation**: System querysets apply automated authorization scoping constraints at the ORM layer, throwing 404 targets to defend against data sniffing vectors.
- **Invariants in Depth**: Multi-shop shopping cart conflicts or single courier assignments are defended against by constraints enforced concurrently across models, serializers, and the database schema.

---

## Roadmap

- [ ] Integrated alternative payment provider webhook gateways.
- [ ] Implement push notification fallback tracking integrations for offline couriers.
- [ ] Establish operational support for multi-currency product valuation structures.
- [ ] Deploy rich analytical visual reporting tools for active platform merchants.
- [ ] Package mobile SDK layout interfaces for native Android and iOS client implementations.

---

## Licence

Distributed under the terms of the **MIT Licence**. See the project `LICENSE` metadata file for details.

---

## Acknowledgements

Special appreciation is extended to the open-source engineering groups who maintain the foundations of this architecture:

- **Django Project** and **Django REST Framework**
- **Django Channels Infrastructure** and the **channels-redis** team
- **GeoDjango Components**, **PostGIS Extension**, and upstream **GEOS** spatial developers

---

**Project Maintainer Link:** [Edmilbe Ramos](https://github.com/bmedmilbe)
