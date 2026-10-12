import factory
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import Point
from factory.django import DjangoModelFactory
from shipping.tests.factories import DeliverFactory
from store.models import Product
from store.tests.factories import (
    ShopVendorFactory,
    StoreUserFactory,
    StreetFactory,
)

from ..models import Cart, CartItem, Client, Order, OrderItem

User = get_user_model()


# =========================================================
# Client
# =========================================================
class ClientFactory(DjangoModelFactory):
    class Meta:
        model = Client
        django_get_or_create=['user']

    user = factory.SubFactory(StoreUserFactory)
    street = factory.SubFactory(StreetFactory)
    location = factory.LazyFunction(lambda: Point(0.0, 0.0, srid=4326))


# =========================================================
# Order
# =========================================================
class OrderFactory(DjangoModelFactory):
    class Meta:
        model = Order

    client = factory.SubFactory(ClientFactory)
    deliver = factory.SubFactory(DeliverFactory)
    delivery_status = Order.DeliveryStatus.PENDING
    payment_status = Order.PaymentStatus.PENDING
    location = factory.LazyFunction(lambda: Point(0.0, 0.0, srid=4326))
    street = factory.SubFactory(StreetFactory)
    shop = factory.SubFactory(ShopVendorFactory)


# =========================================================
# OrderItem
# =========================================================
class OrderItemFactory(DjangoModelFactory):
    class Meta:
        model = OrderItem

    order = factory.SubFactory(OrderFactory)
    # product must belong to the order's shop to satisfy clean()
    product = factory.LazyAttribute(
        lambda o: Product.objects.create(
            shop=o.order.shop,
            category=__import__(
                "store.tests.factories", fromlist=["CategoryFactory"]
            ).CategoryFactory(),
            name=factory.Faker("word"),
            price="9.99",
        )
    )
    quantity = 1
    price_at_purchase = "9.99"



# =========================================================
# Cart
# =========================================================
class CartFactory(DjangoModelFactory):
    class Meta:
        model = Cart

    # Default to a guest cart — no client, a fresh token is generated
    # automatically by Cart.save().
    client = None
    guest_token = None
    shop = None
    location = factory.LazyFunction(lambda: Point(0.0, 0.0, srid=4326))
    street = factory.SubFactory(StreetFactory)
    is_active = True


class ClientCartFactory(DjangoModelFactory):
    """Convenience factory for an authenticated client's cart."""

    class Meta:
        model = Cart

    client = factory.SubFactory(ClientFactory)
    guest_token = None
    shop = None
    location = factory.LazyFunction(lambda: Point(0.0, 0.0, srid=4326))
    street = factory.SubFactory(StreetFactory)
    is_active = True


# =========================================================
# CartItem
# =========================================================
class CartItemFactory(DjangoModelFactory):
    class Meta:
        model = CartItem

    cart = factory.SubFactory(CartFactory)
    # Derive the product from the cart's shop when one is set; otherwise
    # generate a product on a fresh shop — the cart will lock onto it.
    product = factory.LazyAttribute(
        lambda o: Product.objects.create(
            shop=o.cart.shop
            or __import__(
                "store.tests.factories", fromlist=["ShopVendorFactory"]
            ).ShopVendorFactory(),
            category=__import__(
                "store.tests.factories", fromlist=["CategoryFactory"]
            ).CategoryFactory(),
            name=factory.Faker("word").generate(),
            price="9.99",
        )
    )
    quantity = 1
    # price_at_purchase is auto-filled from product.price in CartItem.save()
    price_at_purchase = None