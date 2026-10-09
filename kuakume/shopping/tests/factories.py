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

from ..models import Client, Order, OrderItem

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