from decimal import Decimal

import pytest
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from store.tests.factories import (
    ProductFactory,
    ShopVendorFactory,
    StoreUserFactory,
)

from ..models import Order, OrderItem
from .factories import (
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

