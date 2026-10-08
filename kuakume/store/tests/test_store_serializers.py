from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import Point
from django.core.files.uploadedfile import SimpleUploadedFile

from ..models import (
    Product,
    ProductContent,
)
from ..serializers import (
    CategorySerializer,
    ContentSerializer,
    DistrictSerializer,
    ProductContentCreateOrUpdateSerializer,
    ProductContentSerializer,
    ProductCreateOrUpdateSerializer,
    ProductImagesCreateOrUpdateSerializer,
    ProductImagesSerializer,
    ProductSerializer,
    ShopVendorCreateOrUpdateSerializer,
    ShopVendorSerializer,
    StreetSerializer,
    VendorSerializer,
)
from .factories import (
    CategoryFactory,
    ContentFactory,
    DistrictFactory,
    ProductContentFactory,
    ProductFactory,
    ProductImagesFactory,
    ShopVendorFactory,
    StoreUserFactory,
    StreetFactory,
    VendorFactory,
)

User = get_user_model()


# =========================================================
# DistrictSerializer
# =========================================================
@pytest.mark.django_db
class TestDistrictSerializer:
    def test_serialize_district(self):
        district = DistrictFactory(name='Central', city_name='Lisbon')
        data = DistrictSerializer(district).data
        assert data['id'] == district.id
        assert data['name'] == 'Central'
        assert data['city_name'] == 'Lisbon'

    def test_district_is_read_only(self):
        serializer = DistrictSerializer(
            data={'name': 'X', 'city_name': 'Y'}
        )
        assert serializer.is_valid()
        instance = serializer.save()
        # Since read_only_fields = fields, save() does nothing meaningful
        # but calling save() without an instance creates nothing.
        # We validate that fields are marked read-only.
        for field in serializer.fields.values():
            assert field.read_only is True


# =========================================================
# StreetSerializer
# =========================================================
@pytest.mark.django_db
class TestStreetSerializer:
    def test_serialize_street(self):
        street = StreetFactory(name='Main St')
        data = StreetSerializer(street).data
        assert data['id'] == street.id
        assert data['name'] == 'Main St'
        assert data['district'] == street.district.id
        assert data['district_name'] == street.district.name

    def test_street_is_read_only(self):
        serializer = StreetSerializer(data={'name': 'X', 'district': 1})
        assert serializer.is_valid()
        for field in serializer.fields.values():
            assert field.read_only is True


# =========================================================
# ShopVendorSerializer (read-only)
# =========================================================
@pytest.mark.django_db
class TestShopVendorSerializer:
    def test_serialize_shop_vendor(self):
        shop = ShopVendorFactory(location=Point(12.34, 56.78, srid=4326))
        data = ShopVendorSerializer(shop).data
        assert data['id'] == shop.id
        assert data['vendor'] == shop.vendor.id
        assert data['vendor_username'] == shop.vendor.user.username
        assert data['street'] == shop.street.id
        assert data['street_name'] == shop.street.name
        assert data['contact_number'] == shop.contact_number
        assert data['location'] == {
            'type': 'Point',
            'coordinates': [12.34, 56.78],
        }

    def test_location_none_returns_none(self):
        shop = ShopVendorFactory()
        shop.location = None
        data = ShopVendorSerializer(shop).data
        assert data['location'] is None

    def test_all_fields_read_only(self):
        serializer = ShopVendorSerializer(
            data={'vendor': 1, 'street': 1, 'contact_number': '123'}
        )
        assert serializer.is_valid()
        for field in serializer.fields.values():
            assert field.read_only is True


# =========================================================
# ShopVendorCreateOrUpdateSerializer
# =========================================================
@pytest.mark.django_db
class TestShopVendorCreateOrUpdateSerializer:
    def test_create_with_coordinates(self):
        vendor = VendorFactory()
        street = StreetFactory()
        serializer = ShopVendorCreateOrUpdateSerializer(
            data={
            'vendor': vendor.id,
            'street': street.id,
            'lon': 10.5,
            'lat': 20.5,
            'contact_number': '123456789'
        },
        context={'user_pk': vendor.user.id}
        )
        assert serializer.is_valid(), serializer.errors
        shop = serializer.save()
        assert shop.location.x == 10.5
        assert shop.location.y == 20.5
        assert shop.location.srid == 4326

    def test_create_without_coordinates_fails(self):
        vendor = VendorFactory()
        street = StreetFactory()
        serializer = ShopVendorCreateOrUpdateSerializer(data={
            'vendor': vendor.id,
            'street': street.id,
            'contact_number': '123456789',
        })
        assert not serializer.is_valid(), serializer.errors
        with pytest.raises(Exception):
            serializer.save()

    def test_validate_only_lon_provided(self):
        serializer = ShopVendorCreateOrUpdateSerializer(data={
            'vendor': 1, 'street': 1, 'contact_number': '1',
            'lon': 10.0,
        })
        assert not serializer.is_valid()

    def test_validate_only_lat_provided(self):
        serializer = ShopVendorCreateOrUpdateSerializer(data={
            'vendor': 1, 'street': 1, 'contact_number': '1',
            'lat': 10.0,
        })
        assert not serializer.is_valid()

    def test_update_with_coordinates(self):
        shop = ShopVendorFactory(location=Point(0, 0, srid=4326))
        serializer = ShopVendorCreateOrUpdateSerializer(
            shop,
            data={'lon': 99.0, 'lat': 88.0},
            context={'user_pk': shop.vendor.user.id},
            partial=True,
        )
        assert serializer.is_valid(), serializer.errors
        shop = serializer.save()
        assert shop.location.x == 99.0
        assert shop.location.y == 88.0

    def test_update_without_coordinates(self):
        shop = ShopVendorFactory()
        original_location = shop.location
        serializer = ShopVendorCreateOrUpdateSerializer(
            shop,
            data={'contact_number': '000'},
            context={'user_pk': shop.vendor.user.id},
            partial=True,
        )
        assert not serializer.is_valid(), serializer.errors
        with pytest.raises(Exception):
            serializer.save()
        
# =========================================================
# VendorSerializer
# =========================================================
@pytest.mark.django_db
class TestVendorSerializer:
    def test_serialize_vendor_with_shops(self):
        vendor = VendorFactory()
        shop = ShopVendorFactory(vendor=vendor)
        data = VendorSerializer(vendor).data
        assert data['id'] == vendor.id
        assert data['account_number_pt'] == vendor.account_number_pt
        assert len(data['shops']) == 1
        assert data['shops'][0]['id'] == shop.id

    def test_patch_account_fields(self):
        vendor = VendorFactory()
        serializer = VendorSerializer(
            vendor,
            data={'account_number_pt': 'NEW123', 'account_name_pt': 'New Name'},
            partial=True,
        )
        assert serializer.is_valid(), serializer.errors
        vendor = serializer.save()
        assert vendor.account_number_pt == 'NEW123'
        assert vendor.account_name_pt == 'New Name'

    def test_shops_is_read_only(self):
        vendor = VendorFactory()
        ShopVendorFactory(vendor=vendor)
        serializer = VendorSerializer(
            vendor,
            data={'shops': []},
            partial=True,
        )
        assert serializer.is_valid()
        vendor = serializer.save()
        # shops untouched
        assert vendor.shops.count() == 1


# =========================================================
# CategorySerializer
# =========================================================
@pytest.mark.django_db
class TestCategorySerializer:
    def test_serialize_category(self):
        category = CategoryFactory(name='Fruits')
        data = CategorySerializer(category).data
        assert data['id'] == category.id
        assert data['name'] == 'Fruits'
        assert 'picture' in data

    def test_all_fields_read_only(self):
        serializer = CategorySerializer(data={'name': 'X'})
        assert serializer.is_valid()
        for field in serializer.fields.values():
            assert field.read_only is True


# =========================================================
# ProductCreateOrUpdateSerializer
# =========================================================
@pytest.mark.django_db
class TestProductCreateOrUpdateSerializer:
    def test_create_product_with_permission(self):
        vendor = VendorFactory()
        shop = ShopVendorFactory(vendor=vendor)
        category = CategoryFactory()

        serializer = ProductCreateOrUpdateSerializer(
            data={
                'shop': shop.id,
                'category': category.id,
                'name': 'Apple',
                'price': '1.50',
            },
            context={'user_pk': vendor.user.id},
        )
        assert serializer.is_valid(), serializer.errors
        product = serializer.save()
        assert product.name == 'Apple'
        assert product.price == Decimal('1.50')

    def test_create_product_without_permission(self):
        shop = ShopVendorFactory()
        category = CategoryFactory()
        other_user = StoreUserFactory(phone="+5455846568")

        serializer = ProductCreateOrUpdateSerializer(
            data={
                'shop': shop.id,
                'category': category.id,
                'name': 'Apple',
                'price': '1.50',
            },
            context={'user_pk': other_user.id},
        )
        assert not serializer.is_valid()
        assert 'shop' in serializer.errors

    def test_negative_price_rejected(self):
        vendor = VendorFactory()
        shop = ShopVendorFactory(vendor=vendor)
        category = CategoryFactory()

        serializer = ProductCreateOrUpdateSerializer(
            data={
                'shop': shop.id,
                'category': category.id,
                'name': 'Apple',
                'price': '-1.00',
            },
            context={'user_pk': vendor.user.id},
        )
        assert not serializer.is_valid()
        assert 'price' in serializer.errors

    def test_upsert_updates_price_when_product_exists(self):
        vendor = VendorFactory()
        shop = ShopVendorFactory(vendor=vendor)
        category = CategoryFactory()
        existing = ProductFactory(shop=shop, category=category, name='Apple', price=Decimal('1.00'))

        serializer = ProductCreateOrUpdateSerializer(
            data={
                'shop': shop.id,
                'category': category.id,
                'name': 'Apple',
                'price': '2.50',
            },
            context={'user_pk': vendor.user.id},
        )
        assert serializer.is_valid(), serializer.errors
        product = serializer.save()
        assert product.id == existing.id
        assert product.price == Decimal('2.50')
        assert Product.objects.filter(shop=shop, category=category, name='Apple').count() == 1

    def test_update_without_permission(self):
        shop = ShopVendorFactory()
        product = ProductFactory(shop=shop)
        other_user = StoreUserFactory(phone="+55846849854")

        serializer = ProductCreateOrUpdateSerializer(
            product,
            data={'price': '5.00'},
            partial=True,
            context={'user_pk': other_user.id},
        )
        assert not serializer.is_valid()
        assert 'non_field_errors' in serializer.errors

    def test_update_with_permission(self):
        vendor = VendorFactory()
        shop = ShopVendorFactory(vendor=vendor)
        product = ProductFactory(shop=shop, price=Decimal('1.00'))

        serializer = ProductCreateOrUpdateSerializer(
            product,
            data={'price': '9.99'},
            partial=True,
            context={'user_pk': vendor.user.id},
        )
        assert serializer.is_valid(), serializer.errors
        product = serializer.save()
        assert product.price == Decimal('9.99')


# =========================================================
# ProductSerializer (read)
# =========================================================
@pytest.mark.django_db
class TestProductSerializer:
    def test_serialize_product(self):
        product = ProductFactory(name='Apple', price=Decimal('2.50'))
        ProductImagesFactory(product=product)

        data = ProductSerializer(product).data
        assert data['id'] == product.id
        assert data['name'] == 'Apple'
        assert data['price'] == '2.50'
        assert 'shop' in data
        assert 'category' in data
        assert isinstance(data['shop'], dict)
        assert isinstance(data['category'], dict)


# =========================================================
# ProductImagesSerializer (read)
# =========================================================
@pytest.mark.django_db
class TestProductImagesSerializer:
    def test_serialize_product_image(self):
        image = ProductImagesFactory()
        data = ProductImagesSerializer(image).data
        assert data['id'] == image.id
        assert data['product'] == image.product.id
        assert 'picture' in data


# =========================================================
# ProductImagesCreateOrUpdateSerializer
# =========================================================
@pytest.mark.django_db
class TestProductImagesCreateOrUpdateSerializer:
    def test_create_with_permission(self):
        vendor = VendorFactory()
        shop = ShopVendorFactory(vendor=vendor)
        product = ProductFactory(shop=shop)

        upload = SimpleUploadedFile('test.png', b'filecontent', content_type='image/png')

        serializer = ProductImagesCreateOrUpdateSerializer(
            data={'picture': upload},
            context={'product_pk': product.id, 'user_pk': vendor.user.id},
        )
        assert serializer.is_valid(), serializer.errors
        image = serializer.save()
        assert image.product == product
        assert image.picture is not None

    def test_create_without_permission(self):
        shop = ShopVendorFactory()
        product = ProductFactory(shop=shop)
        other_user = StoreUserFactory(phone="+55846849854")

        upload = SimpleUploadedFile('test.png', b'filecontent', content_type='image/png')

        serializer = ProductImagesCreateOrUpdateSerializer(
            data={'picture': upload},
            context={'product_pk': product.id, 'user_pk': other_user.id},
        )
        assert not serializer.is_valid()
        assert 'non_field_errors' in serializer.errors

    def test_create_with_invalid_product(self):
        other_user = StoreUserFactory(phone="+546849854")
        upload = SimpleUploadedFile('test.png', b'filecontent', content_type='image/png')

        serializer = ProductImagesCreateOrUpdateSerializer(
            data={'picture': upload},
            context={'product_pk': 999999, 'user_pk': other_user.id},
        )
        assert not serializer.is_valid()
        assert 'non_field_errors' in serializer.errors

    def test_update_with_permission(self):
        vendor = VendorFactory()
        shop = ShopVendorFactory(vendor=vendor)
        product = ProductFactory(shop=shop)
        image = ProductImagesFactory(product=product)

        new_upload = SimpleUploadedFile('new.png', b'newcontent', content_type='image/png')

        serializer = ProductImagesCreateOrUpdateSerializer(
            image,
            data={'picture': new_upload},
            partial=True,
            context={'user_pk': vendor.user.id},
        )
        assert serializer.is_valid(), serializer.errors
        image = serializer.save()
        assert image.picture is not None

    def test_update_without_permission(self):
        shop = ShopVendorFactory()
        product = ProductFactory(shop=shop)
        image = ProductImagesFactory(product=product)
        other_user = StoreUserFactory(phone="+55366849854")

        new_upload = SimpleUploadedFile('new.png', b'newcontent', content_type='image/png')

        serializer = ProductImagesCreateOrUpdateSerializer(
            image,
            data={'picture': new_upload},
            partial=True,
            context={'user_pk': other_user.id},
        )
        assert not serializer.is_valid()
        assert 'non_field_errors' in serializer.errors


# =========================================================
# ContentSerializer
# =========================================================
@pytest.mark.django_db
class TestContentSerializer:
    def test_serialize_content(self):
        content = ContentFactory(name='Ingredients')
        data = ContentSerializer(content).data
        assert data['id'] == content.id
        assert data['name'] == 'Ingredients'

    def test_all_fields_read_only(self):
        serializer = ContentSerializer(data={'name': 'X'})
        assert serializer.is_valid()
        for field in serializer.fields.values():
            assert field.read_only is True


# =========================================================
# ProductContentSerializer (read)
# =========================================================
@pytest.mark.django_db
class TestProductContentSerializer:
    def test_serialize_product_content(self):
        pc = ProductContentFactory()
        data = ProductContentSerializer(pc).data
        assert data['id'] == pc.id
        assert data['product']['id'] == pc.product.id
        assert data['content']['id'] == pc.content.id


# =========================================================
# ProductContentCreateOrUpdateSerializer
# =========================================================
@pytest.mark.django_db
class TestProductContentCreateOrUpdateSerializer:
    def test_create_with_permission(self):
        vendor = VendorFactory()
        shop = ShopVendorFactory(vendor=vendor)
        product = ProductFactory(shop=shop)
        content = ContentFactory()

        serializer = ProductContentCreateOrUpdateSerializer(
            data={'content': content.id},
            context={'product_pk': product.id, 'user_pk': vendor.user.id},
        )
        assert serializer.is_valid(), serializer.errors
        pc = serializer.save()
        assert pc.product == product
        assert pc.content == content

    def test_create_without_permission(self):
        shop = ShopVendorFactory()
        product = ProductFactory(shop=shop)
        content = ContentFactory()
        other_user = StoreUserFactory(phone="+55846631854")

        serializer = ProductContentCreateOrUpdateSerializer(
            data={'content': content.id},
            context={'product_pk': product.id, 'user_pk': other_user.id},
        )
        assert not serializer.is_valid()
        assert 'non_field_errors' in serializer.errors

    def test_create_with_invalid_product(self):
        content = ContentFactory()
        other_user = StoreUserFactory(phone="+5583254854")

        serializer = ProductContentCreateOrUpdateSerializer(
            data={'content': content.id},
            context={'product_pk': 999999, 'user_pk': other_user.id},
        )
        assert not serializer.is_valid()
        assert 'non_field_errors' in serializer.errors

    def test_upsert_returns_existing_on_duplicate(self):
        vendor = VendorFactory()
        shop = ShopVendorFactory(vendor=vendor)
        product = ProductFactory(shop=shop)
        content = ContentFactory()

        existing = ProductContentFactory(product=product, content=content)

        serializer = ProductContentCreateOrUpdateSerializer(
            data={'content': content.id},
            context={'product_pk': product.id, 'user_pk': vendor.user.id},
        )
        assert serializer.is_valid(), serializer.errors
        pc = serializer.save()
        assert pc.id == existing.id
        assert ProductContent.objects.filter(product=product, content=content).count() == 1

    def test_update_with_permission(self):
        vendor = VendorFactory()
        shop = ShopVendorFactory(vendor=vendor)
        product = ProductFactory(shop=shop)
        content_a = ContentFactory()
        content_b = ContentFactory()
        pc = ProductContentFactory(product=product, content=content_a)

        serializer = ProductContentCreateOrUpdateSerializer(
            pc,
            data={'content': content_b.id},
            partial=True,
            context={'user_pk': vendor.user.id},
        )
        assert serializer.is_valid(), serializer.errors
        pc = serializer.save()
        assert pc.content == content_b

    def test_update_without_permission(self):
        shop = ShopVendorFactory()
        product = ProductFactory(shop=shop)
        content_a = ContentFactory()
        content_b = ContentFactory()
        pc = ProductContentFactory(product=product, content=content_a)
        other_user = StoreUserFactory(phone="+5586569854")

        serializer = ProductContentCreateOrUpdateSerializer(
            pc,
            data={'content': content_b.id},
            partial=True,
            context={'user_pk': other_user.id},
        )
        assert not serializer.is_valid()
        assert 'non_field_errors' in serializer.errors