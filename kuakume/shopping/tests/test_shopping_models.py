import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db.utils import IntegrityError
from store.tests.factories import (
    ProductFactory,
    ShopVendorFactory,
    StoreUserFactory,
)

from ..models import Cart, CartItem, Order, OrderItem
from .factories import (
    CartFactory,
    CartItemFactory,
    ClientCartFactory,
    ClientFactory,
    OrderFactory,
    OrderItemFactory,
)


def _create_order(payment_status=Order.PaymentStatus.PENDING, delivery_status=Order.DeliveryStatus.PENDING):
    user_client = StoreUserFactory(phone="+123456789")
    client=user_client.clients
    
    user_vendor = StoreUserFactory(phone="+223456789")
    vendor=user_vendor.vendor_user
    
    user_deliver = StoreUserFactory(phone="+323456789")
    deliver=user_deliver.delivery_profile
    
    shop = ShopVendorFactory(vendor=vendor)
    product = ProductFactory(shop=shop)
    
    order = OrderFactory(client=client, shop=shop, deliver=deliver, payment_status=payment_status, delivery_status=delivery_status)
            
    return order, product
def _create_order_without_shop():
    user_client = StoreUserFactory(phone="+123456789")
    client=user_client.clients
        
    order = OrderFactory(client=client, shop=None, deliver=None)
            
    return order

# =========================================================
# Client
# =========================================================
@pytest.mark.django_db
class TestClientModel:

    def test_create_client(self):
        client = ClientFactory()
        assert client.pk is not None
        assert client.user is not None

    def test_client_str(self):
        client = ClientFactory()
        assert str(client) == f"Client: {client.user.username}"

    def test_client_user_is_one_to_one(self):
        ClientFactory()
        with pytest.raises(ValidationError):
            ClientFactory()

    def test_client_location_and_street_optional(self):
        client = ClientFactory(location=None, street=None)
        assert client.location is None
        assert client.street is None


# =========================================================
# Order
# =========================================================
@pytest.mark.django_db
class TestOrderModel:

    def test_create_order(self):
        order,_ = _create_order()
        assert order.pk is not None
        assert order.client is not None
        assert order.deliver is not None

    def test_order_default_statuses(self):
        order,_ = _create_order()
        assert order.delivery_status == Order.DeliveryStatus.PENDING
        assert order.payment_status == Order.PaymentStatus.PENDING

    def test_order_str(self):
        order,_ = _create_order()
        assert str(order) == f"Order #{order.id} - Client: {order.client.user.username}"

    def test_order_timestamps(self):
        order,_ = _create_order()
        assert order.created_at is not None
        assert order.updated_at is not None

    def test_total_zero_when_no_items(self):
        order,_ = _create_order()
        assert order.total == Decimal("0.00")

    def test_total_sums_items(self):
        order,product_a = _create_order()
        product_a.price=Decimal("5.00")
        product_a.save()
        # Two items on the same shop (same order):
        # product_a = ProductFactory(shop=order.shop, price=Decimal("5.00"))
        product_b = ProductFactory(shop=order.shop, price=Decimal("2.50"))

        OrderItemFactory(
            order=order,
            product=product_a,
            quantity=3,
            price_at_purchase=Decimal("5.00"),
        )
        OrderItemFactory(
            order=order,
            product=product_b,
            quantity=4,
            price_at_purchase=Decimal("2.50"),
        )

        expected = Decimal(3) * Decimal("5.00") + Decimal(4) * Decimal("2.50")
        assert order.total == expected

    def test_total_uses_price_at_purchase(self):
        order, product = _create_order()

        OrderItemFactory(
            order=order,
            product=product,
            quantity=2,
            price_at_purchase=Decimal("9.99"),
        )
        assert order.total == Decimal("19.98")

    @pytest.mark.parametrize(
        "delivery_status",
        [
            Order.DeliveryStatus.PENDING,
            Order.DeliveryStatus.DISPATCHED,
            Order.DeliveryStatus.DELIVERED,
            Order.DeliveryStatus.CANCELLED,
        ],
    )
    def test_delivery_status_choices(self, delivery_status):
        order, _ = _create_order(delivery_status=delivery_status)
        assert order.delivery_status == delivery_status

    @pytest.mark.parametrize(
        "payment_status",
        [
            Order.PaymentStatus.PENDING,
            Order.PaymentStatus.SENT,
            Order.PaymentStatus.PAID,
            Order.PaymentStatus.FAILED,
        ],
    )
    def test_payment_status_choices(self, payment_status):
        order, _ = _create_order(payment_status)
        # order = OrderFactory(payment_status=payment_status)
        assert order.payment_status == payment_status


# =========================================================
# OrderItem
# =========================================================
@pytest.mark.django_db
class TestOrderItemModel:

    def test_create_order_item(self):
        order, product = _create_order()
        item = OrderItemFactory(order=order, product=product)
        assert item.pk is not None
        assert item.quantity == 1

    def test_order_item_str(self):
        order, product = _create_order()
        item = OrderItemFactory(order=order, product=product)
        expected = f"{item.quantity} x {item.product.name} (Order #{item.order.id})"
        assert str(item) == expected

    def test_total_price(self):
        order, product = _create_order()
        item = OrderItemFactory(
            order=order,
            product=product,
            quantity=3,
            price_at_purchase=Decimal("4.50"),
        )
        assert item.total_price == Decimal("13.50")

    def test_quantity_default_is_one(self):
        order, product = _create_order()
        item = OrderItemFactory(order=order, product=product)
        assert item.quantity == 1

    def test_unique_together_order_product(self):
        order, product = _create_order()
        item = OrderItemFactory(order=order, product=product)
        with pytest.raises(ValidationError):
            OrderItemFactory(order=item.order, product=item.product)

    def test_product_protected_from_deletion(self):
        order, product = _create_order()
        item = OrderItemFactory(order=order, product=product)
        with pytest.raises(Exception):
            item.product.delete()

    def test_cascade_delete_order_removes_items(self):
        order, product = _create_order()
        item = OrderItemFactory(order=order, product=product)
        item_id = item.pk
        item.order.delete()
        assert OrderItem.objects.filter(id=item_id).exists() is False

    # -----------------------------------------------------
    # Core business rule — single-shop-per-order
    # -----------------------------------------------------
    def test_order_shop_auto_assigned_from_product(self):
        """If the order has no shop, the first OrderItem assigns it."""
        order = _create_order_without_shop()
        product = ProductFactory(shop=ShopVendorFactory())

        item = OrderItemFactory(order=order, product=product)
        assert order.shop_id == product.shop_id
        assert item.product_id == product.id

    def test_same_shop_product_is_accepted(self):
        """A second item belonging to the same shop is accepted."""
        order, product = _create_order()

        first = OrderItemFactory(order=order, product=product)

        # Add a second product from the same shop
        second_product = ProductFactory(shop=order.shop)
        second = OrderItemFactory(order=order, product=second_product)

        assert first.order_id == order.id
        assert second.order_id == order.id
        assert OrderItem.objects.filter(order=order).count() == 2

    def test_product_from_different_shop_raises_validation_error(self):
        """Adding a product from another shop to an existing order must fail."""
        order, _ = _create_order()
        other_shop = ShopVendorFactory()
        other_product = ProductFactory(shop=other_shop)

        with pytest.raises(ValidationError) as excinfo:
            OrderItemFactory(order=order, product=other_product)

        assert "product" in excinfo.value.message_dict

    def test_cannot_mix_products_from_two_shops_in_one_order(self):
        """Explicit scenario: user tries to add two products from two shops."""

        order, product_a = _create_order()

        user_b = StoreUserFactory(phone="+123456782")
        shop_b = ShopVendorFactory(vendor=user_b.vendor_user)
        product_b = ProductFactory(shop=shop_b)

        # First item from shop A → OK
        OrderItemFactory(order=order, product=product_a)

        # Second item from shop B → ValidationError
        with pytest.raises(ValidationError):
            OrderItemFactory(order=order, product=product_b)

        assert OrderItem.objects.filter(order=order).count() == 1

    def test_validation_runs_on_manual_save(self):
        """`.save()` must invoke `.full_clean()` → invalid data raises."""
        order, _ = _create_order()
        other_shop = ShopVendorFactory()
        other_product = ProductFactory(shop=other_shop)

        item = OrderItem(
            order=order,
            product=other_product,
            quantity=1,
            price_at_purchase=Decimal("1.00"),
        )

        with pytest.raises(ValidationError):
            item.save()

        assert OrderItem.objects.filter(order=order).count() == 0
      

    def test_clean_without_order_raise(self):
        """`clean()` must not tolerate missing order/product."""
        item = OrderItem(quantity=1, price_at_purchase=Decimal("1.00"))
        # Should raise
        with pytest.raises(ObjectDoesNotExist):
            item.clean()
        

    @pytest.mark.parametrize("quantity", [1, 2, 5, 100])
    def test_total_price_parametrized(self, quantity):
        order, product = _create_order()
        
        item = OrderItemFactory(
            order=order,
            product=product,
            quantity=quantity,
            price_at_purchase=Decimal("2.00"),
        )
        assert item.total_price == Decimal(str(quantity)) * Decimal("2.00")

# =========================================================
# Cart
# =========================================================
@pytest.mark.django_db
class TestCartModel:

    def test_create_guest_cart(self):
        cart = CartFactory(client = None)
        assert cart.pk is not None
        assert cart.client is None
        assert cart.guest_token is not None

    def test_guest_token_is_uuid(self):
        import uuid as uuid_module

        cart = CartFactory(client = None)
        assert isinstance(cart.guest_token, uuid_module.UUID)

    def test_guest_token_unique(self):
        cart_a = CartFactory(client = None)
        cart_b = CartFactory(client = None)
        assert cart_a.guest_token != cart_b.guest_token

    def test_create_client_cart(self):
        cart = ClientCartFactory()
        assert cart.pk is not None
        assert cart.client is not None
        assert cart.guest_token is None

    def test_cart_str_for_guest(self):
        cart = CartFactory(client=None)
        assert str(cart) == f"Cart #{cart.id} (guest:{cart.guest_token})"

    def test_cart_str_for_client(self):
        cart = ClientCartFactory()
        expected_username = cart.client.user.username
        assert str(cart) == f"Cart #{cart.id} (client:{expected_username})"

    def test_cart_default_is_active(self):
        cart = CartFactory()
        assert cart.is_active is True

    def test_cart_timestamps(self):
        cart = CartFactory()
        assert cart.created_at is not None
        assert cart.updated_at is not None

    def test_cart_shop_optional(self):
        cart = CartFactory(shop=None)
        assert cart.shop is None

    def test_cart_location_optional(self):
        cart = CartFactory(location=None)
        assert cart.location is None

    def test_cart_street_optional(self):
        cart = CartFactory(street=None)
        assert cart.street is None

    # -----------------------------------------------------
    # Ownership XOR constraint
    # -----------------------------------------------------
    def test_cart_cannot_have_both_client_and_guest_token(self):
        client = ClientFactory()
        with pytest.raises(IntegrityError):
            Cart.objects.create(client=client, guest_token=uuid.uuid4())

    def test_cart_cannot_have_neither_client_nor_guest_token(self):
        """
        `Cart.save()` auto-fills guest_token if neither owner is present,
        so this only fails if you bypass save and call clean() directly.
        """
        cart = Cart(client=None, guest_token=None)
        with pytest.raises(ValidationError):
            cart.clean()

    # -----------------------------------------------------
    # Defaults
    # -----------------------------------------------------
    def test_total_zero_when_no_items(self):
        cart = CartFactory()
        assert cart.total == Decimal("0.00")

    def test_item_count_zero_when_no_items(self):
        cart = CartFactory()
        assert cart.item_count == 0

    def test_total_sums_items(self):
        shop = ShopVendorFactory()
        cart = CartFactory()
        product_a = ProductFactory(shop=shop)  
        # cart.shop becomes product_a.shop
        cart.refresh_from_db()
        product_b = ProductFactory(shop=shop)

        CartItemFactory(
            cart=cart,
            product=product_a,
            quantity=3,
            price_at_purchase=Decimal("5.00"),
        )
        CartItemFactory(
            cart=cart,
            product=product_b,
            quantity=4,
            price_at_purchase=Decimal("2.50"),
        )

        expected = Decimal(3) * Decimal("5.00") + Decimal(4) * Decimal("2.50")
        assert cart.total == expected


    def test_item_count_counts_items(self):
        shop = ShopVendorFactory()
        cart = CartFactory()
        product_a = ProductFactory(shop=shop)
        cart.refresh_from_db()
        product_b = ProductFactory(shop=shop)

        CartItemFactory(cart=cart, product=product_a)
        CartItemFactory(cart=cart, product=product_b)

        assert cart.item_count == 2

    # -----------------------------------------------------
    # Single-shop rule — Cart.clean()
    # -----------------------------------------------------
    def test_cart_clean_rejects_items_from_other_shop(self):
        """
        Bypass CartItem.save() (which would raise earlier) by inserting
        directly with the ORM, then call Cart.clean() to check the
        aggregate validation.
        """
        cart = CartFactory()
        product_a = ProductFactory(shop=ShopVendorFactory())
        CartItemFactory(cart=cart, product=product_a)
        cart.refresh_from_db()

        user = StoreUserFactory(phone="+547465498")
        other_shop = ShopVendorFactory(vendor=user.vendor_user)
        other_product = ProductFactory(shop=other_shop)

        # Force-insert a mismatched item, bypassing CartItem.clean().
        CartItem.objects.bulk_create(
            [
                CartItem(
                    cart=cart,
                    product=other_product,
                    quantity=1,
                    price_at_purchase=Decimal("1.00"),
                )
            ]
        )

        with pytest.raises(ValidationError) as excinfo:
            cart.clean()

        assert "shop" in excinfo.value.message_dict
    # -----------------------------------------------------
    # attach_to_client — merge guest cart into client cart
    # -----------------------------------------------------
    def test_attach_to_client_no_existing_cart(self):
        """Guest cart with no client cart → just reassign to the client."""
        client = ClientFactory()
        cart = CartFactory()
        guest_token_before = cart.guest_token

        result = cart.attach_to_client(client)

        assert result.id == cart.id
        assert result.client_id == client.id
        assert result.guest_token is None
        assert guest_token_before is not None

    def test_attach_to_client_merges_items(self):
        """Guest cart has items; client cart has same product → quantities sum."""
        user = StoreUserFactory(phone="+687684984")
        client = ClientFactory()
        existing_cart = ClientCartFactory(client=client)
        shop = ShopVendorFactory(vendor=user.vendor_user)
        existing_cart.shop = shop
        existing_cart.save()

        product = ProductFactory(shop=shop)

        # Seed the client cart with 2 of the product.
        CartItemFactory(
            cart=existing_cart,
            product=product,
            quantity=2,
            price_at_purchase=Decimal("9.99"),
        )

        # Guest cart with 3 of the same product.
        guest_cart = CartFactory()
        guest_cart.shop = shop
        guest_cart.save()
        CartItemFactory(
            cart=guest_cart,
            product=product,
            quantity=3,
            price_at_purchase=Decimal("9.99"),
        )

        result = guest_cart.attach_to_client(client)

        assert result.id == existing_cart.id
        merged = CartItem.objects.get(cart=existing_cart, product=product)
        assert merged.quantity == 5

    def test_attach_to_client_moves_items_for_different_products(self):
        """Guest cart has a product not in client cart → item moves."""
        user = StoreUserFactory(phone="+989889491")
        client = ClientFactory()
        existing_cart = ClientCartFactory(client=client)
        shop = ShopVendorFactory(vendor=user.vendor_user)
        existing_cart.shop = shop
        existing_cart.save()

        product_a = ProductFactory(shop=shop)
        CartItemFactory(
            cart=existing_cart,
            product=product_a,
            quantity=1,
            price_at_purchase=Decimal("5.00"),
        )

        guest_cart = CartFactory()
        guest_cart.shop = shop
        guest_cart.save()
        product_b = ProductFactory(shop=shop)
        CartItemFactory(
            cart=guest_cart,
            product=product_b,
            quantity=2,
            price_at_purchase=Decimal("3.00"),
        )

        guest_cart.attach_to_client(client)

        assert CartItem.objects.filter(cart=existing_cart).count() == 2
        assert CartItem.objects.filter(cart=guest_cart).count() == 0

    def test_attach_to_client_marks_guest_cart_inactive(self):
        client = ClientFactory()
        ClientCartFactory(client=client)
        guest_cart = CartFactory()

        guest_cart.attach_to_client(client)
        guest_cart.refresh_from_db()

        assert guest_cart.is_active is False

    def test_attach_to_client_different_shops_raises(self):
        user = StoreUserFactory(phone="+65879879")
        user = StoreUserFactory(phone="+65879872")
        client = ClientFactory()
        existing_cart = ClientCartFactory(client=client)
        existing_shop = ShopVendorFactory(vendor=user.vendor_user)
        existing_cart.shop = existing_shop
        existing_cart.save()

        guest_cart = CartFactory()
        guest_cart.shop = ShopVendorFactory(vendor=user.vendor_user)
        guest_cart.save()

        with pytest.raises(ValidationError):
            guest_cart.attach_to_client(client)

    def test_attach_to_client_already_attached_raises(self):
        user = StoreUserFactory(phone="+65879879")
        client_a = ClientFactory()
        client_b = ClientFactory(user=user)
        cart = ClientCartFactory(client=client_a)

        with pytest.raises(ValidationError):
            cart.attach_to_client(client_b)


# =========================================================
# CartItem
# =========================================================
@pytest.mark.django_db
class TestCartItemModel:

    def test_create_cart_item(self):
        cart = CartFactory()
        product = ProductFactory(shop=ShopVendorFactory())
        item = CartItemFactory(cart=cart, product=product)
        assert item.pk is not None
        assert item.quantity == 1

    def test_cart_item_str(self):
        cart = CartFactory()
        product = ProductFactory(shop=ShopVendorFactory())
        item = CartItemFactory(cart=cart, product=product)
        expected = f"{item.quantity} x {item.product.name} (Cart #{item.cart_id})"
        assert str(item) == expected

    def test_quantity_default_is_one(self):
        cart = CartFactory()
        product = ProductFactory(shop=ShopVendorFactory())
        item = CartItemFactory(cart=cart, product=product)
        assert item.quantity == 1

    def test_price_at_purchase_snapshots_product_price(self):
        cart = CartFactory()
        product = ProductFactory(shop=ShopVendorFactory(), price=Decimal("7.77"))
        item = CartItemFactory(cart=cart, product=product, price_at_purchase=None)
        assert item.price_at_purchase == Decimal("7.77")

    def test_total_price(self):
        cart = CartFactory()
        product = ProductFactory(shop=ShopVendorFactory())
        item = CartItemFactory(
            cart=cart,
            product=product,
            quantity=3,
            price_at_purchase=Decimal("4.50"),
        )
        assert item.total_price == Decimal("13.50")

    @pytest.mark.parametrize("quantity", [1, 2, 5, 100])
    def test_total_price_parametrized(self, quantity):
        cart = CartFactory()
        product = ProductFactory(shop=ShopVendorFactory())
        item = CartItemFactory(
            cart=cart,
            product=product,
            quantity=quantity,
            price_at_purchase=Decimal("2.00"),
        )
        assert item.total_price == Decimal(str(quantity)) * Decimal("2.00")

    def test_unique_together_cart_product(self):
        cart = CartFactory()
        product = ProductFactory(shop=ShopVendorFactory())
        item = CartItemFactory(cart=cart, product=product)

        with pytest.raises(ValidationError):
            CartItemFactory(cart=item.cart, product=item.product)

    def test_product_protected_from_deletion(self):
        cart = CartFactory()
        product = ProductFactory(shop=ShopVendorFactory())
        CartItemFactory(cart=cart, product=product)

        with pytest.raises(Exception):
            product.delete()

    def test_cascade_delete_cart_removes_items(self):
        cart = CartFactory()
        product = ProductFactory(shop=ShopVendorFactory())
        item = CartItemFactory(cart=cart, product=product)
        item_id = item.pk

        cart.delete()
        assert CartItem.objects.filter(id=item_id).exists() is False

    # -----------------------------------------------------
    # Single-shop rule — CartItem.clean()
    # -----------------------------------------------------
    def test_first_item_locks_cart_shop(self):
        cart = CartFactory(shop=None)
        product = ProductFactory(shop=ShopVendorFactory())

        CartItemFactory(cart=cart, product=product)
        cart.refresh_from_db()

        assert cart.shop_id == product.shop_id

    def test_same_shop_product_is_accepted(self):
        cart = CartFactory()
        product_a = ProductFactory(shop=ShopVendorFactory())
        CartItemFactory(cart=cart, product=product_a)
        cart.refresh_from_db()

        product_b = ProductFactory(shop=cart.shop)
        item = CartItemFactory(cart=cart, product=product_b)

        assert item.pk is not None
        assert CartItem.objects.filter(cart=cart).count() == 2

    def test_product_from_different_shop_raises_validation_error(self):
        cart = CartFactory()
        product_a = ProductFactory(shop=ShopVendorFactory())
        CartItemFactory(cart=cart, product=product_a)
        cart.refresh_from_db()

        user = StoreUserFactory(phone="+6964849684")
        other_product = ProductFactory(shop=ShopVendorFactory(vendor=user.vendor_user))

        with pytest.raises(ValidationError) as excinfo:
            CartItemFactory(cart=cart, product=other_product)

        assert "product" in excinfo.value.message_dict

    def test_cannot_mix_products_from_two_shops_in_one_cart(self):
        cart = CartFactory()
        product_a = ProductFactory(shop=ShopVendorFactory())
        CartItemFactory(cart=cart, product=product_a)
        cart.refresh_from_db()
        user = StoreUserFactory(phone="+6964849684")

        product_b = ProductFactory(shop=ShopVendorFactory(vendor=user.vendor_user))

        with pytest.raises(ValidationError):
            CartItemFactory(cart=cart, product=product_b)

        assert CartItem.objects.filter(cart=cart).count() == 1

    def test_validation_runs_on_manual_save(self):
        cart = CartFactory()
        product_a = ProductFactory(shop=ShopVendorFactory())
        CartItemFactory(cart=cart, product=product_a)
        cart.refresh_from_db()

        user = StoreUserFactory(phone="+6964849684")
        
        
        other_product = ProductFactory(shop=ShopVendorFactory(vendor=user.vendor_user))

        item = CartItem(
            cart=cart,
            product=other_product,
            quantity=1,
            price_at_purchase=Decimal("1.00"),
        )

        with pytest.raises(ValidationError):
            item.save()

        assert CartItem.objects.filter(cart=cart).count() == 1

    # -----------------------------------------------------
    # merge_into
    # -----------------------------------------------------
    def test_merge_into_existing_product_sums_quantities(self):
        shop = ShopVendorFactory()
        product = ProductFactory(shop=shop)

        target_cart = CartFactory()
        target_cart.shop = shop
        target_cart.save()

        source_cart = CartFactory()
        source_cart.shop = shop
        source_cart.save()

        CartItemFactory(
            cart=target_cart,
            product=product,
            quantity=2,
            price_at_purchase=Decimal("1.00"),
        )
        source_item = CartItemFactory(
            cart=source_cart,
            product=product,
            quantity=3,
            price_at_purchase=Decimal("1.00"),
        )

        source_item.merge_into(target_cart)

        merged = CartItem.objects.get(cart=target_cart, product=product)
        assert merged.quantity == 5
        assert CartItem.objects.filter(cart=source_cart).count() == 0

    def test_merge_into_new_product_moves_item(self):
        shop = ShopVendorFactory()
        product_a = ProductFactory(shop=shop)
        product_b = ProductFactory(shop=shop)

        target_cart = CartFactory()
        target_cart.shop = shop
        target_cart.save()

        source_cart = CartFactory()
        source_cart.shop = shop
        source_cart.save()

        CartItemFactory(
            cart=target_cart,
            product=product_a,
            quantity=1,
            price_at_purchase=Decimal("1.00"),
        )
        source_item = CartItemFactory(
            cart=source_cart,
            product=product_b,
            quantity=2,
            price_at_purchase=Decimal("1.00"),
        )

        source_item.merge_into(target_cart)

        assert CartItem.objects.filter(cart=target_cart).count() == 2
        assert CartItem.objects.filter(cart=source_cart).count() == 0

    def test_merge_into_different_shop_raises(self):
        user = StoreUserFactory(phone="+6964849684")
                        
        product_a = ProductFactory(shop=ShopVendorFactory())
        product_b = ProductFactory(shop=ShopVendorFactory(vendor=user.vendor_user))

        target_cart = CartFactory()
        target_cart.shop = product_a.shop
        target_cart.save()

        source_cart = CartFactory()
        source_cart.shop = product_b.shop
        source_cart.save()

        source_item = CartItemFactory(
            cart=source_cart,
            product=product_b,
            quantity=1,
            price_at_purchase=Decimal("1.00"),
        )

        with pytest.raises(ValidationError):
            source_item.merge_into(target_cart)

