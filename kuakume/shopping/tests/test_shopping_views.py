import uuid

import pytest
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import Point
from django.urls import reverse
from rest_framework.test import APIClient
from store.tests.factories import (
    ProductFactory,
    ShopVendorFactory,
    StoreUserFactory,
)

from shopping.tests.test_shopping_models import (
    _create_order,
    _create_order_with_user,
    _create_product,
)

from ..models import CartItem, Order, OrderItem
from .factories import (
    CartFactory,
    CartItemFactory,
    ClientCartFactory,
    OrderItemFactory,
)

User = get_user_model()


# =========================================================
# Helpers — fresh APIClient per test, no fixtures
# =========================================================
def _auth_client(user):
    """Return an APIClient already authenticated as `user`."""
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _set_guest_cookie(client, cart):
    """Attach the guest cart token cookie to an APIClient."""
    client.cookies["guest_cart_token"] = str(cart.guest_token)
    return client


# =========================================================
# Client — /clients/me/
# =========================================================
@pytest.mark.django_db
class TestClientViewSet:

    def test_get_me_returns_own_client(self):
        user = StoreUserFactory()
        client_obj = user.clients

        api = _auth_client(user)
        response = api.get(reverse("client-me"))

        assert response.status_code == 200
        assert response.data["id"] == client_obj.id
        assert response.data["user"] == user.id
        assert response.data["username"] == user.username

    def test_get_me_anonymous_gets_401(self):
        api = APIClient()
        response = api.get(reverse("client-me"))

        assert response.status_code == 401

    def test_patch_me_updates_location(self):
        user = StoreUserFactory()

        api = _auth_client(user)
        response = api.patch(
            reverse("client-me"),
            data={"lon": 12.5, "lat": 34.5},
            format="json",
        )

        assert response.status_code == 200
        user.clients.refresh_from_db()
        assert user.clients.location.x == 12.5
        assert user.clients.location.y == 34.5

    def test_patch_me_only_lon_fails(self):
        user = StoreUserFactory()

        api = _auth_client(user)
        response = api.patch(
            reverse("client-me"),
            data={"lon": 12.5},
            format="json",
        )

        assert response.status_code == 400
        assert "location" in response.data

    @pytest.mark.parametrize("lon", [-200.0, 200.0])
    def test_patch_me_invalid_lon_rejected(self, lon):
        user = StoreUserFactory()

        api = _auth_client(user)
        response = api.patch(
            reverse("client-me"),
            data={"lon": lon, "lat": 0.0},
            format="json",
        )

        assert response.status_code == 400
        assert "lon" in response.data

    @pytest.mark.parametrize("lat", [-91.0, 91.0])
    def test_patch_me_invalid_lat_rejected(self, lat):
        user = StoreUserFactory()

        api = _auth_client(user)
        response = api.patch(
            reverse("client-me"),
            data={"lon": 0.0, "lat": lat},
            format="json",
        )

        assert response.status_code == 400
        assert "lat" in response.data

    def test_put_me_not_allowed(self):
        user = StoreUserFactory()
        api = _auth_client(user)
        response = api.put(reverse("client-me"), data={}, format="json")

        assert response.status_code == 405

    def test_delete_me_not_allowed(self):
        user = StoreUserFactory()
        api = _auth_client(user)
        response = api.delete(reverse("client-me"))

        assert response.status_code == 405

    def test_list_not_routed(self):
        user = StoreUserFactory()
        api = _auth_client(user)
        response = api.get("/api/shopping/clients")

        assert response.status_code == 404


# =========================================================
# Order — user-scoped CRUD
# =========================================================
@pytest.mark.django_db
class TestOrderViewSet:

    def test_list_only_own_orders(self):
        _,_,user_a = _create_order_with_user()
        _,_,_ = _create_order_with_user()

        api = _auth_client(user_a)
        response = api.get(reverse("order-list"))

        assert response.status_code == 200
        assert len(response.data) == 1

    def test_list_anonymous_gets_401(self):
        api = APIClient()
        response = api.get(reverse("order-list"))

        assert response.status_code == 401

    def test_retrieve_own_order(self):
        
        order,_, user =_create_order_with_user()

        api = _auth_client(user)
        response = api.get(reverse("order-detail", args=[order.id]))

        assert response.status_code == 200
        assert response.data["id"] == order.id
        assert response.data["delivery_status"] == "PENDING"

    def test_retrieve_other_users_order_404(self):
        user_a = StoreUserFactory()
        order_b, _, _ = _create_order_with_user()

        api = _auth_client(user_a)
        response = api.get(reverse("order-detail", args=[order_b.id]))

        assert response.status_code == 404

    def test_create_order_uses_client_location_fallback(self):
        user = StoreUserFactory()
        user.clients.location = Point(5.0, 6.0, srid=4326)
        user.clients.save()

        api = _auth_client(user)
        response = api.post(reverse("order-list"), data={}, format="json")

        assert response.status_code == 201
        order = Order.objects.get(id=response.data["id"])
        assert order.client_id == user.clients.id
        assert order.location.x == 5.0
        assert order.location.y == 6.0

    def test_create_order_with_explicit_location(self):
        user = StoreUserFactory()

        api = _auth_client(user)
        response = api.post(
            reverse("order-list"),
            data={"lon": 11.0, "lat": 22.0},
            format="json",
        )

        assert response.status_code == 201
        order = Order.objects.get(id=response.data["id"])
        assert order.location.x == 11.0
        assert order.location.y == 22.0

    def test_create_order_without_location_and_no_default_fails(self):
        user = StoreUserFactory()
        user.clients.location = None
        user.clients.save()

        api = _auth_client(user)
        response = api.post(reverse("order-list"), data={}, format="json")

        assert response.status_code == 400
        assert "location" in response.data

    def test_create_order_with_only_lon_fails(self):
        user = StoreUserFactory()

        api = _auth_client(user)
        response = api.post(
            reverse("order-list"),
            data={"lon": 11.0},
            format="json",
        )

        assert response.status_code == 400
        assert "location" in response.data

    def test_update_own_order(self):
        
        order,_,user = _create_order_with_user()

        api = _auth_client(user)
        response = api.patch(
            reverse("order-detail", args=[order.id]),
            data={"lon": 3.0, "lat": 4.0},
            format="json",
        )

        assert response.status_code == 200
        order.refresh_from_db()
        assert order.location.x == 3.0
        assert order.location.y == 4.0

    def test_update_other_users_order_404(self):
        user_a = StoreUserFactory()
        
        order_b,_,_ = _create_order_with_user()

        api = _auth_client(user_a)
        response = api.patch(
            reverse("order-detail", args=[order_b.id]),
            data={"lon": 3.0, "lat": 4.0},
            format="json",
        )

        assert response.status_code == 404

    def test_delete_own_order(self):
        order,_,user = _create_order_with_user()
        order_id = order.id

        api = _auth_client(user)
        response = api.delete(reverse("order-detail", args=[order_id]))

        assert response.status_code == 204
        assert Order.objects.filter(id=order_id).exists() is False

    def test_delete_other_users_order_404(self):
        user_a = StoreUserFactory()
        order_b,_,user_b = _create_order_with_user()

        api = _auth_client(user_a)
        response = api.delete(reverse("order-detail", args=[order_b.id]))

        
        api_b = _auth_client(user_b)
        response_b = api_b.delete(reverse("order-detail", args=[order_b.id]))

        assert response.status_code == 404
        assert response_b.status_code == 204

    def test_detach_shop_with_items_fails(self):
        
        order, product, user = _create_order_with_user()
        OrderItemFactory(order=order, product=product)

        api = _auth_client(user)
        response = api.patch(
            reverse("order-detail", args=[order.id]),
            data={"shop": None},
            format="json",
        )

        assert response.status_code == 400
        assert "shop" in response.data

    def test_delivery_status_is_read_only(self):
        order, _, user = _create_order_with_user()

        api = _auth_client(user)
        response = api.patch(
            reverse("order-detail", args=[order.id]),
            data={"delivery_status": Order.DeliveryStatus.CANCELLED,
                  "lon": 45.0, "lat": 90.0},
            format="json",
        )
        assert response.status_code == 200
        order.refresh_from_db()
        assert order.delivery_status == Order.DeliveryStatus.PENDING


# =========================================================
# OrderItem — nested under Order
# =========================================================
@pytest.mark.django_db
class TestOrderItemViewSet:

    def test_list_only_own_items(self):
        order_a, product_a, user_a = _create_order_with_user()
        order_b, product_b = _create_order()
        OrderItemFactory(order=order_a, product=product_a)
        OrderItemFactory(order=order_b, product=product_b)

        api = _auth_client(user_a)
        response = api.get(
            reverse("order-items-list", kwargs={"order_pk": order_a.id})
        )

        assert response.status_code == 200
        assert len(response.data) == 1

    def test_list_anonymous_gets_401(self):
        order,_ = _create_order()
        api = APIClient()
        response = api.get(
            reverse("order-items-list", kwargs={"order_pk": order.id})
        )

        assert response.status_code == 401

    def test_create_item_in_own_order(self):
        
        order, product, user = _create_order_with_user()

        api = _auth_client(user)
        response = api.post(
            reverse("order-items-list", kwargs={"order_pk": order.id}),
            data={"product": product.id, "quantity": 2},
            format="json",
        )

        assert response.status_code == 201
        item = OrderItem.objects.get(id=response.data["id"])
        assert item.order_id == order.id
        assert item.product_id == product.id
        assert item.quantity == 2

    def test_create_item_for_other_users_order_404(self):
        order_a, _, _ = _create_order_with_user()
        _, product, user_a = _create_order_with_user()

        api = _auth_client(user_a)
        response = api.post(
            reverse("order-items-list", kwargs={"order_pk": order_a.id}),
            data={"product": product.id, "quantity": 1},
            format="json",
        )

        assert response.status_code in (400, 404)

    def test_create_item_from_different_shop_rejected(self):
        order,_,user=_create_order_with_user()
        other_product = _create_product()

        api = _auth_client(user)
        response = api.post(
            reverse("order-items-list", kwargs={"order_pk": order.id}),
            data={"product": other_product.id, "quantity": 1},
            format="json",
        )

        assert response.status_code == 400
        assert "product" in response.data

    def test_duplicate_product_are_auto_added(self):
        order, product, user = _create_order_with_user()
        product = ProductFactory(shop=order.shop)
        OrderItemFactory(order=order, product=product)

        api = _auth_client(user)
        response = api.post(
            reverse("order-items-list", kwargs={"order_pk": order.id}),
            data={"product": product.id, "quantity": 1},
            format="json",
        )

        assert response.status_code == 201
        assert "product" in response.data

    @pytest.mark.parametrize("quantity", [0, -1])
    def test_invalid_quantity_rejected(self, quantity):
        order, product, user = _create_order_with_user()

        api = _auth_client(user)
        response = api.post(
            reverse("order-items-list", kwargs={"order_pk": order.id}),
            data={"product": product.id, "quantity": quantity},
            format="json",
        )

        assert response.status_code == 400
        assert "quantity" in response.data

    def test_update_own_item(self):
        order, product, user = _create_order_with_user()
        item = OrderItemFactory(order=order, product=product)

        api = _auth_client(user)
        response = api.patch(
            reverse(
                "order-items-detail",
                kwargs={"order_pk": order.id, "pk": item.id},
            ),
            data={"quantity": 7},
            format="json",
        )

        assert response.status_code == 200
        item.refresh_from_db()
        assert item.quantity == 7

    def test_delete_own_item(self):
        order, product, user = _create_order_with_user()
        item = OrderItemFactory(order=order, product=product)
        item_id = item.id

        api = _auth_client(user)
        response = api.delete(
            reverse(
                "order-items-detail",
                kwargs={"order_pk": order.id, "pk": item_id},
            )
        )

        assert response.status_code == 204
        assert OrderItem.objects.filter(id=item_id).exists() is False


# =========================================================
# Cart — guest + authenticated
# =========================================================
@pytest.mark.django_db
class TestCartViewSet:

    def test_guest_can_create_cart(self):
        api = APIClient()
        response = api.post(reverse("cart-list"), data={}, format="json")

        assert response.status_code == 201
        assert response.data["guest_token"] is not None
        assert "guest_cart_token" in response.cookies

    def test_guest_create_twice_returns_400(self):
        api = APIClient()
        first = api.post(reverse("cart-list"), data={}, format="json")
        assert first.status_code == 201

        token = first.cookies["guest_cart_token"].value
        api.cookies["guest_cart_token"] = token

        second = api.post(reverse("cart-list"), data={}, format="json")
        assert second.status_code == 400
        assert "detail" in second.data

    def test_authenticated_create_cart(self):
        user = StoreUserFactory()

        api = _auth_client(user)
        response = api.post(reverse("cart-list"), data={}, format="json")

        assert response.status_code == 201
        assert response.data["client"] is not None
        assert response.data["guest_token"] is None

    def test_get_own_cart_authenticated(self):
        user = StoreUserFactory()
        cart = ClientCartFactory(client=user.clients)

        api = _auth_client(user)
        response = api.get(reverse("cart-detail", args=[cart.id]))

        assert response.status_code == 200
        assert response.data["id"] == cart.id

    def test_get_own_cart_guest(self):
        cart = CartFactory()

        api = APIClient()
        _set_guest_cookie(api, cart)
        response = api.get(reverse("cart-detail", args=[cart.id]))

        assert response.status_code == 200
        assert response.data["id"] == cart.id

    def test_get_cart_without_cookie_404(self):
        cart = CartFactory()

        api = APIClient()
        response = api.get(reverse("cart-detail", args=[cart.id]))

        assert response.status_code == 404

    def test_patch_own_cart_location(self):
        user = StoreUserFactory()
        ClientCartFactory(client=user.clients)

        api = _auth_client(user)
        response = api.patch(
            reverse("cart-detail", args=[user.clients.carts.first().id]),
            data={"lon": 5.0, "lat": 6.0},
            format="json",
        )

        assert response.status_code == 200
        user.clients.carts.first().refresh_from_db()
        assert user.clients.carts.first().location.x == 5.0
        assert user.clients.carts.first().location.y == 6.0

    def test_delete_own_cart_soft_deletes(self):
        user = StoreUserFactory()
        cart = ClientCartFactory(client=user.clients)
        cart_id = cart.id

        api = _auth_client(user)
        response = api.delete(reverse("cart-detail", args=[cart_id]))

        assert response.status_code == 204
        cart.refresh_from_db()
        assert cart.is_active is False

    def test_guest_delete_clears_cookie(self):
        cart = CartFactory()

        api = APIClient()
        _set_guest_cookie(api, cart)
        response = api.delete(reverse("cart-detail", args=[cart.id]))

        assert response.status_code == 204
        assert response.cookies["guest_cart_token"].value == ""

    # -----------------------------------------------------
    # Merge endpoint
    # -----------------------------------------------------
    def test_merge_guest_cart_into_client_cart(self):
        user = StoreUserFactory()
        guest_cart = CartFactory()

        api = _auth_client(user)
        response = api.post(
            reverse("cart-merge"),
            data={"guest_token": str(guest_cart.guest_token)},
            format="json",
        )

        assert response.status_code == 200
        assert response.data["client"] is not None
        assert response.data["guest_token"] is None

    def test_merge_anonymous_gets_401(self):
        guest_cart = CartFactory()

        api = APIClient()
        response = api.post(
            reverse("cart-merge"),
            data={"guest_token": str(guest_cart.guest_token)},
            format="json",
        )

        assert response.status_code == 401

    def test_merge_invalid_token_returns_400(self):
        user = StoreUserFactory()

        api = _auth_client(user)
        response = api.post(
            reverse("cart-merge"),
            data={"guest_token": str(uuid.uuid4())},
            format="json",
        )

        assert response.status_code == 400
        assert "guest_token" in response.data


# =========================================================
# CartItem — nested under Cart
# =========================================================
@pytest.mark.django_db
class TestCartItemViewSet:

    def test_authenticated_list_own_items(self):
        _,_, user = _create_order_with_user()
        cart = ClientCartFactory(client=user.clients)
        product = ProductFactory(shop=ShopVendorFactory())
        CartItemFactory(cart=cart, product=product)

        api = _auth_client(user)
        response = api.get(
            reverse("cart-items-list", kwargs={"cart_pk": cart.id})
        )

        assert response.status_code == 200
        assert len(response.data) == 1

    def test_guest_list_with_cookie(self):
        cart = CartFactory()
        product = ProductFactory(shop=ShopVendorFactory())
        CartItemFactory(cart=cart, product=product)

        api = APIClient()
        _set_guest_cookie(api, cart)
        response = api.get(
            reverse("cart-items-list", kwargs={"cart_pk": cart.id})
        )

        assert response.status_code == 200
        assert len(response.data) == 1

    def test_guest_list_without_cookie_empty(self):
        cart = CartFactory()
        product = ProductFactory(shop=ShopVendorFactory())
        CartItemFactory(cart=cart, product=product)

        api = APIClient()
        response = api.get(
            reverse("cart-items-list", kwargs={"cart_pk": cart.id})
        )

        assert response.status_code == 200
        assert len(response.data) == 0

    def test_authenticated_add_item(self):
        _ , _ , user = _create_order_with_user()
        cart = ClientCartFactory(client=user.clients)
        product = ProductFactory(shop=ShopVendorFactory())

        api = _auth_client(user)
        response = api.post(
            reverse("cart-items-list", kwargs={"cart_pk": cart.id}),
            data={"product": product.id, "quantity": 2},
            format="json",
        )

        assert response.status_code == 201
        assert response.data["quantity"] == 2
        assert response.data["product"] == product.id

    def test_add_product_from_different_shop_rejected(self):
        _, first_product, user = _create_order_with_user()
        cart = ClientCartFactory(client=user.clients)
        CartItemFactory(cart=cart, product=first_product)
        cart.refresh_from_db()

        other_product = _create_product()

        api = _auth_client(user)
        response = api.post(
            reverse("cart-items-list", kwargs={"cart_pk": cart.id}),
            data={"product": other_product.id, "quantity": 1},
            format="json",
        )

        assert response.status_code == 400
        assert "product" in response.data

    def test_duplicate_product_is_increased(self):
        _, product, user = _create_order_with_user()
        cart = ClientCartFactory(client=user.clients)
        
        CartItemFactory(cart=cart, product=product)

        api = _auth_client(user)
        response = api.post(
            reverse("cart-items-list", kwargs={"cart_pk": cart.id}),
            data={"product": product.id, "quantity": 1},
            format="json",
        )

        assert response.status_code == 201
        assert "product" in response.data
        assert  response.data["quantity"] == 2

    @pytest.mark.parametrize("quantity", [0, -1])
    def test_invalid_quantity_rejected(self, quantity):
        _, product, user = _create_order_with_user()
        cart = ClientCartFactory(client=user.clients)
        

        api = _auth_client(user)
        response = api.post(
            reverse("cart-items-list", kwargs={"cart_pk": cart.id}),
            data={"product": product.id, "quantity": quantity},
            format="json",
        )

        assert response.status_code == 400
        assert "quantity" in response.data

    def test_update_quantity(self):
        _, product, user = _create_order_with_user()
        cart = ClientCartFactory(client=user.clients)
        item = CartItemFactory(cart=cart, product=product)

        api = _auth_client(user)
        response = api.patch(
            reverse(
                "cart-items-detail",
                kwargs={"cart_pk": cart.id, "pk": item.id},
            ),
            data={"quantity": 9},
            format="json",
        )

        assert response.status_code == 200
        item.refresh_from_db()
        assert item.quantity == 9

    def test_delete_own_item(self):
        _, product, user = _create_order_with_user()
        cart = ClientCartFactory(client=user.clients)
        item = CartItemFactory(cart=cart, product=product)
        item_id = item.id

        api = _auth_client(user)
        response = api.delete(
            reverse(
                "cart-items-detail",
                kwargs={"cart_pk": cart.id, "pk": item_id},
            )
        )

        assert response.status_code == 204
        assert CartItem.objects.filter(id=item_id).exists() is False

    def test_guest_cannot_touch_other_guests_items(self):
        cart_a = CartFactory()
        cart_b = CartFactory()
        product = ProductFactory(shop=ShopVendorFactory())
        item_b = CartItemFactory(cart=cart_b, product=product)

        api = APIClient()
        _set_guest_cookie(api, cart_a)
        response = api.get(
            reverse(
                "cart-items-detail",
                kwargs={"cart_pk": cart_b.id, "pk": item_b.id},
            )
        )

        assert response.status_code == 404


# =========================================================
# Ownership isolation across all views
# =========================================================
@pytest.mark.django_db
class TestCrossUserIsolation:

    def test_user_a_cannot_read_user_b_order(self):
        user_a = StoreUserFactory()
        order_b, _, _ =_create_order_with_user()

        api = _auth_client(user_a)
        response = api.get(reverse("order-detail", args=[order_b.id]))

        assert response.status_code == 404

    def test_user_a_cannot_read_user_b_cart(self):
        user_a = StoreUserFactory()
        user_b = StoreUserFactory(phone="+5768768868")
        ClientCartFactory(client=user_b.clients)

        api = _auth_client(user_a)
        # user_a has no cart → 404 regardless of the ID sent
        response = api.get(reverse("cart-detail", args=[1]))

        assert response.status_code == 404

    def test_user_a_cannot_read_user_b_cart_items(self):
        user_a = StoreUserFactory()
        user_b = StoreUserFactory(phone="+57876875")
        cart_b = ClientCartFactory(client=user_b.clients)
        product = _create_product()
        CartItemFactory(cart=cart_b, product=product)

        api = _auth_client(user_a)
        response = api.get(
            reverse("cart-items-list", kwargs={"cart_pk": cart_b.id})
        )

        assert response.status_code == 200
        assert len(response.data) == 0