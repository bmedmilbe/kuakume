import uuid
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import Point
from rest_framework.test import APIClient
from shipping.tests.factories import DeliverFactory
from store.tests.factories import (
    ProductFactory,
    ShopVendorFactory,
    StoreUserFactory,
    StreetFactory,
)

from shopping.tests.test_shopping_models import (
    _create_order,
    _create_order_with_client,
    _create_product,
)

from ..models import Client, Order
from ..serializers import (
    CartCreateSerializer,
    CartItemCreateOrUpdateSerializer,
    CartItemSerializer,
    CartMergeSerializer,
    CartSerializer,
    CartUpdateSerializer,
    ClientSerializer,
    ClientUpdateSerializer,
    OrderCreateOrUpdateSerializer,
    OrderItemCreateOrUpdateSerializer,
    OrderItemSerializer,
    OrderSerializer,
)
from .factories import (
    CartFactory,
    CartItemFactory,
    ClientCartFactory,
    ClientFactory,
    OrderItemFactory,
)

User = get_user_model()


# =========================================================
# Helper — instantiate a fresh APIClient inside each test
# =========================================================
def _auth_client(user):
    """Return an APIClient already authenticated as `user`."""
    client = APIClient()
    client.force_authenticate(user=user)
    return client


# =========================================================
# ClientSerializer (read)
# =========================================================
@pytest.mark.django_db
class TestClientSerializer:

    def test_serialize_basic_fields(self):

        user = StoreUserFactory(phone="+6879879")

        client_obj = ClientFactory(user=user)

        data = ClientSerializer(client_obj).data

        assert data["id"] == client_obj.id
        assert data["user"] == client_obj.user_id
        assert data["username"] == client_obj.user.username

    def test_serialize_location_as_geojson(self):
        client_obj = ClientFactory()
        client_obj.location = Point(12.34, 56.78, srid=4326)
        data = ClientSerializer(client_obj).data

        assert data["location"] == {
            "type": "Point",
            "coordinates": [12.34, 56.78],
        }

    def test_serialize_location_none(self):
        client_obj = ClientFactory(location=None)

        data = ClientSerializer(client_obj).data

        assert data["location"] is None

    def test_serialize_nested_street(self):
        street = StreetFactory(name="Broadway")
        client_obj = ClientFactory()
        client_obj.street = street

        data = ClientSerializer(client_obj).data

        assert data["street"] == street.id
        assert data["street_detail"]["id"] == street.id
        assert data["street_detail"]["name"] == "Broadway"

    def test_all_fields_are_read_only(self):
        serializer = ClientSerializer(data={"street": 1})
        assert serializer.is_valid()
        for field in serializer.fields.values():
            assert field.read_only is True


# =========================================================
# ClientCreateOrUpdateSerializer (write)
# =========================================================
@pytest.mark.django_db
class TestClientCreateOrUpdateSerializer:

    def test_create_with_user_pk_fails(self):
        user = StoreUserFactory()

        serializer = ClientUpdateSerializer(
            data={"lon": 10.0, "lat": 20.0},
            context={"user_pk": user.id},
        )
        assert serializer.is_valid(), serializer.errors
        with pytest.raises(Exception):
            serializer.save()

    def test_update_location_from_lon_lat(self):
        client_obj = ClientFactory()

        serializer = ClientUpdateSerializer(
            client_obj,
            data={"lon": 45.0, "lat": 90.0},
            partial=True,
            context={"user_pk": client_obj.user_id},
        )
        assert serializer.is_valid(), serializer.errors
        updated = serializer.save()

        assert updated.location.x == 45.0
        assert updated.location.y == 90.0

    def test_update_with_only_lon_fails(self):
        client_obj = ClientFactory()

        serializer = ClientUpdateSerializer(
            client_obj,
            data={"lon": 45.0},
            partial=True,
            context={"user_pk": client_obj.user_id},
        )
        assert serializer.is_valid() is False
        assert "location" in serializer.errors

    @pytest.mark.parametrize("lon", [-200.0, 200.0, 999.0])
    def test_longitude_out_of_range_fails(self, lon):
        client_obj = ClientFactory()

        serializer = ClientUpdateSerializer(
            client_obj,
            data={"lon": lon, "lat": 0.0},
            partial=True,
            context={"user_pk": client_obj.user_id},
        )
        assert serializer.is_valid() is False
        assert "lon" in serializer.errors

    @pytest.mark.parametrize("lat", [-91.0, 91.0, 999.0])
    def test_latitude_out_of_range_fails(self, lat):
        client_obj = ClientFactory()

        serializer = ClientUpdateSerializer(
            client_obj,
            data={"lon": 0.0, "lat": lat},
            partial=True,
            context={"user_pk": client_obj.user_id},
        )
        assert serializer.is_valid() is False
        assert "lat" in serializer.errors

    def test_user_is_not_exposed(self):
        serializer = ClientUpdateSerializer()
        assert "user" not in serializer.fields


# =========================================================
# OrderItemSerializer (read)
# =========================================================
@pytest.mark.django_db
class TestOrderItemSerializer:

    def test_serialize_basic_fields(self):
        user = StoreUserFactory(phone="+7658674763")
        user_2 = StoreUserFactory(phone="+7658467476")
        deliver = DeliverFactory()
        client = ClientFactory(user=user_2)
        order,product = _create_order()
        
        # product = ProductFactory(shop=order.shop)
        item = OrderItemFactory(
            order=order,
            product=product,
            quantity=3,
            price_at_purchase=Decimal("5.00"),
        )

        data = OrderItemSerializer(item).data

        assert data["id"] == item.id
        assert data["order"] == order.id
        assert data["quantity"] == 3
        assert data["price_at_purchase"] == "5.00"

    def test_serialize_nested_product(self):
        order, product = _create_order(product_name="Apple")
        item = OrderItemFactory(order=order, product=product)

        data = OrderItemSerializer(item).data

        assert data["product"]["id"] == product.id
        assert data["product"]["name"] == "Apple"

    def test_total_price_is_serialised(self):
        order ,product = _create_order()
        item = OrderItemFactory(
            order=order,
            product=product,
            quantity=3,
            price_at_purchase=Decimal("4.50"),
        )

        data = OrderItemSerializer(item).data

        assert data["total_price"] == "13.50"

    def test_all_fields_read_only(self):
        serializer = OrderItemSerializer(data={"quantity": 1})
        assert serializer.is_valid()
        for field in serializer.fields.values():
            assert field.read_only is True


# =========================================================
# OrderItemCreateOrUpdateSerializer (write)
# =========================================================
@pytest.mark.django_db
class TestOrderItemCreateOrUpdateSerializer:

    def test_create_with_order_pk(self):
        order ,product = _create_order()

        serializer = OrderItemCreateOrUpdateSerializer(
            data={"product": product.id, "quantity": 2},
            context={"order_pk": order.id},
        )
        assert serializer.is_valid(), serializer.errors
        item = serializer.save()

        assert item.order_id == order.id
        assert item.product_id == product.id
        assert item.quantity == 2
        assert item.price_at_purchase == product.price

    def test_create_without_order_pk_fails(self):
        product = ProductFactory()

        serializer = OrderItemCreateOrUpdateSerializer(
            data={"product": product.id, "quantity": 1},
            context={},
        )
        assert serializer.is_valid() is False

    def test_create_with_invalid_order_pk_fails(self):
        product = ProductFactory()

        serializer = OrderItemCreateOrUpdateSerializer(
            data={"product": product.id, "quantity": 1},
            context={"order_pk": 999999},
        )
        assert serializer.is_valid() is False

    def test_product_from_different_shop_rejected(self):
        order, _ = _create_order()
        other_product = _create_product()

        serializer = OrderItemCreateOrUpdateSerializer(
            data={"product": other_product.id, "quantity": 1},
            context={"order_pk": order.id},
        )
        assert serializer.is_valid() is False
        assert "product" in serializer.errors

    def test_duplicate_product_is_auto_added(self):
        order, product = _create_order()
        OrderItemFactory(order=order, product=product)

        serializer = OrderItemCreateOrUpdateSerializer(
            data={"product": product.id, "quantity": 1},
            context={"order_pk": order.id},
        )
        assert serializer.is_valid() is True

    

    def test_update_own_item(self):
        order,product = _create_order()
        item = OrderItemFactory(order=order, product=product)

        serializer = OrderItemCreateOrUpdateSerializer(
            item,
            data={"quantity": 5},
            partial=True,
            context={"order_pk": order.id},
        )
        assert serializer.is_valid(), serializer.errors
        updated = serializer.save()

        assert updated.quantity == 5

    def test_price_snapshot_when_product_changes(self):
        order, product_a = _create_order()
        product_b = ProductFactory(shop=order.shop, price=Decimal("9.99"))
        item = OrderItemFactory(
            order=order,
            product=product_a,
            price_at_purchase=Decimal("1.00"),
        )

        serializer = OrderItemCreateOrUpdateSerializer(
            item,
            data={"product": product_b.id},
            partial=True,
            context={"order_pk": order.id},
        )
        assert serializer.is_valid(), serializer.errors
        updated = serializer.save()

        assert updated.price_at_purchase == Decimal("9.99")

    def test_quantity_must_be_positive(self):
        order, product =_create_order()

        serializer = OrderItemCreateOrUpdateSerializer(
            data={"product": product.id, "quantity": 0},
            context={"order_pk": order.id},
        )
        assert serializer.is_valid() is False
        assert "quantity" in serializer.errors

    def test_order_field_is_read_only(self):
        serializer = OrderItemCreateOrUpdateSerializer()
        assert serializer.fields["order"].read_only is True


# =========================================================
# OrderSerializer (read)
# =========================================================
@pytest.mark.django_db
class TestOrderSerializer:

    def test_serialize_basic_fields(self):
        order,_ = _create_order()

        data = OrderSerializer(order).data

        assert data["id"] == order.id
        assert data["delivery_status"] == "PENDING"
        assert data["payment_status"] == "PENDING"

    def test_serialize_nested_client(self):
        order,_ = _create_order()

        data = OrderSerializer(order).data

        assert data["client"]["id"] == order.client_id

    def test_serialize_nested_deliver(self):
        order,_ = _create_order()

        data = OrderSerializer(order).data

        assert data["deliver"]["id"] == order.deliver_id

    def test_serialize_nested_shop(self):
        order,_ = _create_order()

        data = OrderSerializer(order).data

        assert data["shop"]["id"] == order.shop_id

    def test_serialize_items(self):
        order, product = _create_order()
        OrderItemFactory(order=order, product=product)

        data = OrderSerializer(order).data

        assert len(data["items"]) == 1
        assert data["items"][0]["product"]["id"] == product.id

    def test_total_is_serialised(self):
        order,product = _create_order(price=Decimal("5.00"))
        OrderItemFactory(
            order=order,
            product=product,
            quantity=2,
            price_at_purchase=Decimal("5.00"),
        )

        data = OrderSerializer(order).data

        assert data["total"] == "10.00"

    def test_location_is_geojson(self):
        order, _ = _create_order(location=Point(11.22, 33.44, srid=4326))

        data = OrderSerializer(order).data

        assert data["location"] == {
            "type": "Point",
            "coordinates": [11.22, 33.44],
        }

    def test_all_fields_read_only(self):
        serializer = OrderSerializer(data={"delivery_status": "PAID"})
        assert serializer.is_valid()
        for field in serializer.fields.values():
            assert field.read_only is True


# =========================================================
# OrderCreateOrUpdateSerializer (write)
# =========================================================
@pytest.mark.django_db
class TestOrderCreateOrUpdateSerializer:

    def test_create_derives_client_from_user_pk(self):
        user = StoreUserFactory()
        client_obj = user.clients

        serializer = OrderCreateOrUpdateSerializer(
            data={"lon": 1.0, "lat": 2.0},
            context={"user_pk": user.id},
        )
        assert serializer.is_valid(), serializer.errors
        order = serializer.save()

        assert order.client_id == client_obj.id
        assert order.location.x == 1.0
        assert order.location.y == 2.0

    def test_create_without_user_pk_fails(self):
        serializer = OrderCreateOrUpdateSerializer(
            data={"lon": 1.0, "lat": 2.0},
            context={},
        )
        assert serializer.is_valid() is False

    def test_create_falls_back_to_client_location(self):
        user = StoreUserFactory()
        client_obj = user.clients
        client_obj.location = Point(9.0, 9.0, srid=4326)
        client_obj.save()

        serializer = OrderCreateOrUpdateSerializer(
            data={},
            context={"user_pk": user.id},
        )
        assert serializer.is_valid(), serializer.errors
        order = serializer.save()

        assert order.location.x == 9.0
        assert order.location.y == 9.0

    def test_create_without_location_or_default_fails(self):
        user = StoreUserFactory()
        client_obj = user.clients
        client_obj.location = None
        client_obj.save()

        serializer = OrderCreateOrUpdateSerializer(
            data={},
            context={"user_pk": user.id},
        )
        assert serializer.is_valid() is False
        assert "location" in serializer.errors

    def test_update_without_permission_fails(self):
        user_a = StoreUserFactory()
        user_b = StoreUserFactory(phone="+6546846")
        order, _ = _create_order_with_client(client=user_b.clients)

        serializer = OrderCreateOrUpdateSerializer(
            order,
            data={"deliver": None},
            partial=True,
            context={"user_pk": user_a.id},
        )
        assert serializer.is_valid() is False

    def test_update_with_permission(self):
        user = StoreUserFactory()
        order,_ = _create_order_with_client(client=user.clients)

        serializer = OrderCreateOrUpdateSerializer(
            order,
            data={"lon": 3.0, "lat": 4.0},
            partial=True,
            context={"user_pk": user.id},
        )
        assert serializer.is_valid(), serializer.errors
        updated = serializer.save()

        assert updated.location.x == 3.0
        assert updated.location.y == 4.0

    def test_detach_shop_with_items_fails(self):
        user = StoreUserFactory()
        order, product = _create_order_with_client(client=user.clients)
        OrderItemFactory(order=order, product=product)

        serializer = OrderCreateOrUpdateSerializer(
            order,
            data={"shop": None},
            partial=True,
            context={"user_pk": user.id},
        )
        assert serializer.is_valid() is False
        assert "shop" in serializer.errors

    def test_delivery_status_is_read_only(self):
        user = StoreUserFactory()
        client = ClientFactory(user=user)
        client.location = Point(7.0, 8.0, srid=4326)
        client.save()
        order, _ = _create_order_with_client(client=user.clients)

        serializer = OrderCreateOrUpdateSerializer(
            order,
            data={"delivery_status": Order.DeliveryStatus.CANCELLED},
            partial=True,
            context={"user_pk": user.id},
        )
        assert serializer.is_valid(), serializer.errors
        updated = serializer.save()

        assert updated.delivery_status == Order.DeliveryStatus.PENDING

    @pytest.mark.parametrize("lon", [-200.0, 200.0])
    def test_invalid_longitude_rejected(self, lon):
        user = StoreUserFactory()

        serializer = OrderCreateOrUpdateSerializer(
            data={"lon": lon, "lat": 0.0},
            context={"user_pk": user.id},
        )
        assert serializer.is_valid() is False
        assert "lon" in serializer.errors


# =========================================================
# CartItemSerializer (read)
# =========================================================
@pytest.mark.django_db
class TestCartItemSerializer:

    def test_serialize_basic_fields(self):
        cart = CartFactory()
        product = ProductFactory(shop=ShopVendorFactory())
        item = CartItemFactory(
            cart=cart,
            product=product,
            quantity=2,
            price_at_purchase=Decimal("4.00"),
        )

        data = CartItemSerializer(item).data

        assert data["id"] == item.id
        assert data["cart"] == cart.id
        assert data["quantity"] == 2
        assert data["price_at_purchase"] == "4.00"

    def test_total_price_serialised(self):
        cart = CartFactory()
        product = ProductFactory(shop=ShopVendorFactory())
        item = CartItemFactory(
            cart=cart,
            product=product,
            quantity=3,
            price_at_purchase=Decimal("4.50"),
        )

        data = CartItemSerializer(item).data

        assert data["total_price"] == "13.50"

    def test_nested_product_present(self):
        cart = CartFactory()
        product = ProductFactory(shop=ShopVendorFactory(), name="Apple")
        item = CartItemFactory(cart=cart, product=product)

        data = CartItemSerializer(item).data

        assert data["product"]["id"] == product.id
        assert data["product"]["name"] == "Apple"

    def test_all_fields_read_only(self):
        serializer = CartItemSerializer(data={"quantity": 1})
        assert serializer.is_valid()
        for field in serializer.fields.values():
            assert field.read_only is True


# =========================================================
# CartItemCreateOrUpdateSerializer (write)
# =========================================================
@pytest.mark.django_db
class TestCartItemCreateOrUpdateSerializer:

    def test_create_with_cart_pk(self):
        cart = CartFactory()
        product = ProductFactory(shop=ShopVendorFactory())

        serializer = CartItemCreateOrUpdateSerializer(
            data={"product": product.id, "quantity": 2},
            context={"cart_pk": cart.id},
        )
        assert serializer.is_valid(), serializer.errors
        item = serializer.save()

        assert item.cart_id == cart.id
        assert item.product_id == product.id
        assert item.quantity == 2
        assert item.price_at_purchase == product.price

    def test_create_without_cart_pk_fails(self):
        product = ProductFactory()

        serializer = CartItemCreateOrUpdateSerializer(
            data={"product": product.id, "quantity": 1},
            context={},
        )
        assert serializer.is_valid() is False

    def test_create_with_invalid_cart_pk_fails(self):
        product = ProductFactory()

        serializer = CartItemCreateOrUpdateSerializer(
            data={"product": product.id, "quantity": 1},
            context={"cart_pk": 999999},
        )
        assert serializer.is_valid() is False

    def test_product_from_different_shop_rejected(self):
        cart = CartFactory()
        first_product = ProductFactory(shop=ShopVendorFactory())
        CartItemFactory(cart=cart, product=first_product)
        cart.refresh_from_db()

        other_product = _create_product()

        serializer = CartItemCreateOrUpdateSerializer(
            data={"product": other_product.id, "quantity": 1},
            context={"cart_pk": cart.id},
        )
        assert serializer.is_valid() is False
        assert "product" in serializer.errors

    def test_duplicate_product_not_rejected(self):
        cart = CartFactory()
        product = ProductFactory(shop=ShopVendorFactory())
        CartItemFactory(cart=cart, product=product)

        serializer = CartItemCreateOrUpdateSerializer(
            data={"product": product.id, "quantity": 1},
            context={"cart_pk": cart.id},
        )
        assert serializer.is_valid() is True

    def test_cart_shop_locked_on_create(self):
        cart = CartFactory(shop=None)
        product = ProductFactory(shop=ShopVendorFactory())

        serializer = CartItemCreateOrUpdateSerializer(
            data={"product": product.id, "quantity": 1},
            context={"cart_pk": cart.id},
        )
        assert serializer.is_valid(), serializer.errors
        serializer.save()

        cart.refresh_from_db()
        assert cart.shop_id == product.shop_id

    def test_update_quantity(self):
        cart = CartFactory()
        product = ProductFactory(shop=ShopVendorFactory())
        item = CartItemFactory(cart=cart, product=product)

        serializer = CartItemCreateOrUpdateSerializer(
            item,
            data={"quantity": 5},
            partial=True,
            context={"cart_pk": cart.id},
        )
        assert serializer.is_valid(), serializer.errors
        updated = serializer.save()

        assert updated.quantity == 5

    def test_quantity_must_be_positive(self):
        cart = CartFactory()
        product = ProductFactory(shop=ShopVendorFactory())

        serializer = CartItemCreateOrUpdateSerializer(
            data={"product": product.id, "quantity": 0},
            context={"cart_pk": cart.id},
        )
        assert serializer.is_valid() is False
        assert "quantity" in serializer.errors

    def test_cart_field_is_read_only(self):
        serializer = CartItemCreateOrUpdateSerializer()
        assert serializer.fields["cart"].read_only is True


# =========================================================
# CartSerializer (read)
# =========================================================
@pytest.mark.django_db
class TestCartSerializer:

    def test_serialize_guest_cart(self):
        cart = CartFactory()

        data = CartSerializer(cart).data

        assert data["id"] == cart.id
        assert data["client"] is None
        assert data["guest_token"] is not None

    def test_serialize_client_cart(self):
        cart = ClientCartFactory()

        data = CartSerializer(cart).data

        assert data["client"]["id"] == cart.client_id
        assert data["guest_token"] is None

    def test_serialize_nested_items(self):
        cart = CartFactory()
        product = ProductFactory(shop=ShopVendorFactory())
        CartItemFactory(cart=cart, product=product)

        data = CartSerializer(cart).data

        assert len(data["items"]) == 1
        assert data["items"][0]["product"]["id"] == product.id

    def test_total_is_serialised(self):
        cart = CartFactory()
        product = ProductFactory(shop=ShopVendorFactory())
        CartItemFactory(
            cart=cart,
            product=product,
            quantity=2,
            price_at_purchase=Decimal("3.00"),
        )

        data = CartSerializer(cart).data

        assert data["total"] == "6.00"

    def test_item_count_is_serialised(self):
        cart = CartFactory()
        product_a = ProductFactory(shop=ShopVendorFactory())
        CartItemFactory(cart=cart, product=product_a)
        cart.refresh_from_db()

        product_b = ProductFactory(shop=cart.shop)
        CartItemFactory(cart=cart, product=product_b)

        data = CartSerializer(cart).data

        assert data["item_count"] == 2

    def test_location_is_geojson(self):
        cart = CartFactory(location=Point(7.0, 8.0, srid=4326))

        data = CartSerializer(cart).data

        assert data["location"] == {
            "type": "Point",
            "coordinates": [7.0, 8.0],
        }

    def test_all_fields_read_only(self):
        serializer = CartSerializer(data={"is_active": False})
        assert serializer.is_valid()
        for field in serializer.fields.values():
            assert field.read_only is True


# =========================================================
# CartCreateSerializer (write)
# =========================================================
@pytest.mark.django_db
class TestCartCreateSerializer:

    def test_create_guest_cart_without_user_pk(self):
        serializer = CartCreateSerializer(data={}, context={})
        assert serializer.is_valid(), serializer.errors
        cart = serializer.save()

        assert cart.client is None
        assert cart.guest_token is not None

    def test_create_client_cart_with_user_pk(self):
        user = StoreUserFactory()

        serializer = CartCreateSerializer(
            data={},
            context={"user_pk": user.id},
        )
        assert serializer.is_valid(), serializer.errors
        cart = serializer.save()

        assert cart.client_id == user.clients.id
        assert cart.guest_token is None

    def test_create_with_user_pk_but_no_client_fails(self):
        # A user that has no Client profile — remove the signal-created one.
        user = StoreUserFactory()
        Client.objects.filter(user=user).delete()

        serializer = CartCreateSerializer(
            data={},
            context={"user_pk": user.id},
        )
        assert serializer.is_valid() is False

    def test_create_with_location(self):
        serializer = CartCreateSerializer(
            data={"lon": 12.0, "lat": 34.0},
            context={},
        )
        assert serializer.is_valid(), serializer.errors
        cart = serializer.save()

        assert cart.location.x == 12.0
        assert cart.location.y == 34.0

    def test_create_with_only_lon_fails(self):
        serializer = CartCreateSerializer(
            data={"lon": 12.0},
            context={},
        )
        assert serializer.is_valid() is False
        assert "location" in serializer.errors

    @pytest.mark.parametrize("lon", [-200.0, 200.0])
    def test_invalid_longitude_rejected(self, lon):
        serializer = CartCreateSerializer(
            data={"lon": lon, "lat": 0.0},
            context={},
        )
        assert serializer.is_valid() is False
        assert "lon" in serializer.errors

    @pytest.mark.parametrize("lat", [-91.0, 91.0])
    def test_invalid_latitude_rejected(self, lat):
        serializer = CartCreateSerializer(
            data={"lon": 0.0, "lat": lat},
            context={},
        )
        assert serializer.is_valid() is False
        assert "lat" in serializer.errors


# =========================================================
# CartUpdateSerializer (write)
# =========================================================
@pytest.mark.django_db
class TestCartUpdateSerializer:

    def test_update_location(self):
        cart = CartFactory()

        serializer = CartUpdateSerializer(
            cart,
            data={"lon": 5.0, "lat": 6.0},
            partial=True,
        )
        assert serializer.is_valid(), serializer.errors
        updated = serializer.save()

        assert updated.location.x == 5.0
        assert updated.location.y == 6.0

    def test_update_is_active(self):
        cart = CartFactory(is_active=True)

        serializer = CartUpdateSerializer(
            cart,
            data={"is_active": False},
            partial=True,
        )
        assert serializer.is_valid(), serializer.errors
        updated = serializer.save()

        assert updated.is_active is False

    def test_cannot_change_client(self):
        cart = ClientCartFactory()
        user = StoreUserFactory(phone="+6567876")
        other_client = ClientFactory(user=user)

        serializer = CartUpdateSerializer(
            cart,
            data={"client": other_client.id},
            partial=True,
        )
        assert serializer.is_valid(), serializer.errors
        updated = serializer.save()

        # `client` is not in `fields`, so DRF silently drops it.
        assert updated.client_id == cart.client_id

    def test_cannot_change_guest_token(self):
        cart = CartFactory()
        original_token = cart.guest_token

        serializer = CartUpdateSerializer(
            cart,
            data={"guest_token": str(uuid.uuid4())},
            partial=True,
        )
        assert serializer.is_valid(), serializer.errors
        updated = serializer.save()

        assert updated.guest_token == original_token

    def test_only_lon_fails(self):
        cart = CartFactory()

        serializer = CartUpdateSerializer(
            cart,
            data={"lon": 5.0},
            partial=True,
        )
        assert serializer.is_valid() is False
        assert "location" in serializer.errors


# =========================================================
# CartMergeSerializer
# =========================================================
@pytest.mark.django_db
class TestCartMergeSerializer:

    def test_merge_guest_cart_into_client_cart(self):
        user = StoreUserFactory()
        guest_cart = CartFactory()
        guest_token = guest_cart.guest_token

        serializer = CartMergeSerializer(
            data={"guest_token": str(guest_token)},
            context={"user_pk": user.id},
        )
        assert serializer.is_valid(), serializer.errors
        result = serializer.save()

        assert result.client_id == user.clients.id
        assert result.guest_token is None

    def test_merge_with_invalid_token_fails(self):
        user = StoreUserFactory()

        serializer = CartMergeSerializer(
            data={"guest_token": str(uuid.uuid4())},
            context={"user_pk": user.id},
        )
        assert serializer.is_valid() is False
        assert "guest_token" in serializer.errors

    def test_merge_without_user_pk_fails(self):
        guest_cart = CartFactory()

        serializer = CartMergeSerializer(
            data={"guest_token": str(guest_cart.guest_token)},
            context={},
        )
        # Validation of the token passes but save() raises.
        assert serializer.is_valid(), serializer.errors
        with pytest.raises(Exception):
            serializer.save()

    def test_merge_into_different_shop_raises(self):
        user_shopper_1 = StoreUserFactory(phone="+6542746")
        shop = ShopVendorFactory(vendor=user_shopper_1.vendor_user)
        
        user = StoreUserFactory(phone="+654658746")
        _ = ClientCartFactory(client=user.clients, shop=shop)

        user_shopper_2 = StoreUserFactory(phone="+6546582746")
        guest_cart = CartFactory(shop=ShopVendorFactory(vendor=user_shopper_2.vendor_user))

        serializer = CartMergeSerializer(
            data={"guest_token": str(guest_cart.guest_token)},
            context={"user_pk": user.id},
        )
        assert serializer.is_valid(), serializer.errors
        with pytest.raises(Exception):
            serializer.save()

    def test_merge_requires_guest_token(self):
        user = StoreUserFactory()

        serializer = CartMergeSerializer(
            data={},
            context={"user_pk": user.id},
        )
        assert serializer.is_valid() is False
        assert "guest_token" in serializer.errors

