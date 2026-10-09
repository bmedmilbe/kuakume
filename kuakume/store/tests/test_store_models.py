from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import Point
from django.db import IntegrityError

from ..models import (
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
from .factories import (
    CategoryFactory,
    ContentFactory,
    DistrictFactory,
    ProductContentFactory,
    ProductFactory,
    ProductImagesFactory,
    ShopVendorFactory,
    StreetFactory,
    VendorFactory,
)

User = get_user_model()

@pytest.mark.django_db
class TestVendorModel:
    def test_create_vendor(self):
        vendor = VendorFactory()
        assert vendor.pk is not None
        assert isinstance(vendor.user, User)

    def test_vendor_str(self):
        vendor = VendorFactory()
        assert str(vendor) == f"Vendor: {vendor.user.phone}"

    def test_vendor_one_to_one_with_user(self):
        vendor = VendorFactory()
        with pytest.raises(IntegrityError):
            Vendor.objects.create(user=vendor.user)

    def test_vendor_optional_fields(self):
        vendor = VendorFactory(
            account_number_pt=None,
            account_number_stp=None,
            account_name_pt=None,
            account_name_stp=None,
        )
        assert vendor.account_number_pt is None
        assert vendor.account_number_stp is None
        assert vendor.account_name_pt is None
        assert vendor.account_name_stp is None


@pytest.mark.django_db
class TestDistrictModel:
    def test_create_district(self):
        district = DistrictFactory()
        assert district.pk is not None
        assert district.name is not None
        assert district.city_name is not None


@pytest.mark.django_db
class TestStreetModel:
    def test_create_street(self):
        street = StreetFactory()
        assert street.pk is not None
        assert isinstance(street.district, District)

    def test_street_name_unique(self):
        street = StreetFactory(name='Unique Street')
        with pytest.raises(IntegrityError):
            StreetFactory(name='Unique Street')

    def test_street_related_name(self):
        district = DistrictFactory()
        street = StreetFactory(district=district)
        assert street in district.street.all()


@pytest.mark.django_db
class TestShopVendorModel:
    def test_create_shop_vendor(self):
        shop = ShopVendorFactory()
        assert shop.pk is not None
        assert isinstance(shop.vendor, Vendor)
        assert isinstance(shop.street, Street)
        assert isinstance(shop.location, Point)

    def test_shop_str(self):
        shop = ShopVendorFactory()
        assert str(shop) == f"Shop of {shop.vendor.user.username}"


    def test_shop_location_srid(self):
        shop = ShopVendorFactory(location=Point(12.34, 56.78, srid=4326))
        assert shop.location.srid == 4326
        assert shop.location.x == 12.34
        assert shop.location.y == 56.78

    def test_shop_related_name_on_vendor(self):
        vendor = VendorFactory()
        shops = ShopVendorFactory(vendor=vendor)
        assert shops in vendor.shops.all()

    def test_shop_related_name_on_street(self):
        street = StreetFactory()
        shops = ShopVendorFactory(street=street)
        assert shops in street.shops.all()


@pytest.mark.django_db
class TestCategoryModel:
    def test_create_category(self):
        category = CategoryFactory()
        assert category.pk is not None
        assert category.name is not None
        assert category.picture is not None

    def test_category_icon_optional(self):
        category = CategoryFactory(icon=None)
        assert category.icon is None


@pytest.mark.django_db
class TestProductModel:
    def test_create_product(self):
        product = ProductFactory()
        assert product.pk is not None
        assert isinstance(product.shop, ShopVendor)
        assert isinstance(product.category, Category)

    def test_product_str(self):
        product = ProductFactory(name='Test Product')
        assert str(product) == 'Test Product'

    def test_product_price_decimal(self):
        product = ProductFactory(price=Decimal('99.99'))
        assert product.price == Decimal('99.99')

    def test_product_related_name_on_shop(self):
        shop = ShopVendorFactory()
        product = ProductFactory(shop=shop)
        assert product in shop.products.all()

    def test_product_related_name_on_category(self):
        category = CategoryFactory()
        product = ProductFactory(category=category)
        assert product in category.products.all()

    def test_product_cascade_delete_on_shop(self):
        product = ProductFactory()
        product_id = product.pk
        product.shop.delete()
        assert not Product.objects.filter(pk=product_id).exists()


@pytest.mark.django_db
class TestProductImagesModel:
    def test_create_product_image(self):
        image = ProductImagesFactory()
        assert image.pk is not None
        assert isinstance(image.product, Product)
        assert image.picture is not None

    def test_product_images_related_name(self):
        product = ProductFactory()
        image = ProductImagesFactory(product=product)
        assert image in product.product_images.all()

    def test_product_images_cascade_delete(self):
        image = ProductImagesFactory()
        image_id = image.pk
        image.product.delete()
        assert not ProductImages.objects.filter(pk=image_id).exists()


@pytest.mark.django_db
class TestContentModel:
    def test_create_content(self):
        content = ContentFactory()
        assert content.pk is not None
        assert content.name is not None


@pytest.mark.django_db
class TestProductContentModel:
    def test_create_product_content(self):
        pc = ProductContentFactory()
        assert pc.pk is not None
        assert isinstance(pc.product, Product)
        assert isinstance(pc.content, Content)

    def test_product_content_str(self):
        product = ProductFactory(name='My Product')
        content = ContentFactory(name='Ingredients')
        pc = ProductContentFactory(product=product, content=content)
        assert str(pc) == 'My Product - Ingredients'

    def test_product_content_unique_together(self):
        pc = ProductContentFactory()
        with pytest.raises(IntegrityError):
            ProductContentFactory(product=pc.product, content=pc.content)

    def test_product_content_cascade_delete_product(self):
        pc = ProductContentFactory()
        pc_id = pc.pk
        pc.product.delete()
        assert not ProductContent.objects.filter(pk=pc_id).exists()

    def test_product_content_cascade_delete_content(self):
        pc = ProductContentFactory()
        pc_id = pc.pk
        pc.content.delete()
        assert not ProductContent.objects.filter(pk=pc_id).exists()