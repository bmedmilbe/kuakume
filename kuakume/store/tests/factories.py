import factory
from core.tests.factories import UserFactory
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import Point
from factory.django import DjangoModelFactory

from store.models import (
    Category,
    Content,
    District,
    Product,
    ProductContent,
    ProductImages,
    ShopVendor,
    Street,
    Vendor,
)

User = get_user_model()

class StoreUserFactory(UserFactory):
    class Meta:
        model = User
    phone = "+35945755755"

class VendorFactory(DjangoModelFactory):
    class Meta:
        model = Vendor
        django_get_or_create = ['user']

    user = factory.SubFactory(StoreUserFactory)
    account_number_pt = factory.Faker('bban')
    account_number_stp = factory.Faker('bban')
    account_name_pt = factory.Faker('name')
    account_name_stp = factory.Faker('name')
    is_active=True


class DistrictFactory(DjangoModelFactory):
    class Meta:
        model = District

    name = factory.Faker('city_suffix')
    city_name = factory.Faker('city')


class StreetFactory(DjangoModelFactory):
    class Meta:
        model = Street

    name = factory.Sequence(lambda n: f'Street {n}')
    district = factory.SubFactory(DistrictFactory)


class ShopVendorFactory(DjangoModelFactory):
    class Meta:
        model = ShopVendor

    vendor = factory.SubFactory(VendorFactory)
    street = factory.SubFactory(StreetFactory)
    location = factory.LazyFunction(lambda: Point(0.0, 0.0, srid=4326))
    contact_number = factory.Faker('numerify', text='############')


class CategoryFactory(DjangoModelFactory):
    class Meta:
        model = Category

    name = factory.Faker('word')
    icon = factory.Faker('word')
    picture = factory.django.FileField(filename='category.png')


class ProductFactory(DjangoModelFactory):
    class Meta:
        model = Product

    shop = factory.SubFactory(ShopVendorFactory)
    category = factory.SubFactory(CategoryFactory)
    name = factory.Faker('word')
    price = factory.Faker('pydecimal', left_digits=6, right_digits=2, positive=True)


class ProductImagesFactory(DjangoModelFactory):
    class Meta:
        model = ProductImages

    product = factory.SubFactory(ProductFactory)
    picture = factory.django.FileField(filename='product.png')


class ContentFactory(DjangoModelFactory):
    class Meta:
        model = Content

    name = factory.Sequence(lambda n: f"product-word-{n}")


class ProductContentFactory(DjangoModelFactory):
    class Meta:
        model = ProductContent

    product = factory.SubFactory(ProductFactory)
    content = factory.SubFactory(ContentFactory)