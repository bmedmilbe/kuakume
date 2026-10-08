from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import Point
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from store.models import (
    Product,
    ProductContent,
    ProductImages,
    ShopVendor,
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
# Helper — instantiate a fresh APIClient inside each test
# =========================================================
def _auth_client(user):
    """Return an APIClient already authenticated as `user`."""
    client = APIClient()
    client.force_authenticate(user=user)
    return client


# =========================================================
# Vendor
# =========================================================
@pytest.mark.django_db
class TestVendorViewSet:

    def test_get_vendor_returns_own_profile(self):
        user = StoreUserFactory()
        vendor = VendorFactory(user=user, account_number_pt="PT1")

        client = _auth_client(user)
        url = reverse("vendor-me")
        response = client.get(url)

        assert response.status_code == 200
        assert response.data["id"] == vendor.id
        assert response.data["account_number_pt"] == "PT1"
        assert "shops" in response.data

    def test_anonymous_user_gets_401(self):
        vendor = VendorFactory()
        client = APIClient()
        url = reverse("vendor-me")
        response = client.get(url)

        assert response.status_code == 401

    def test_patch_account_fields(self):
        user = StoreUserFactory()
        vendor = VendorFactory(user=user)

        client = _auth_client(user)
        url = reverse("vendor-me")
        response = client.patch(
            url,
            data={"account_number_pt": "NEW-PT", "account_name_pt": "New Name"},
            format="json",
        )

        assert response.status_code == 200
        assert response.data["account_number_pt"] == "NEW-PT"
        assert response.data["account_name_pt"] == "New Name"

        vendor.refresh_from_db()
        assert vendor.account_number_pt == "NEW-PT"

    @pytest.mark.parametrize("method", ["post", "put", "delete"])
    def test_unsupported_methods_return_405(self, method):
        user = StoreUserFactory()
        vendor = VendorFactory(user=user)

        client = _auth_client(user)
        url = reverse("vendor-me")
        response = getattr(client, method)(url)

        assert response.status_code == 405

    def test_vendor_list_is_404(self):
        """GET /vendors/ is completely inaccessible."""
        user = StoreUserFactory()
        VendorFactory(user=user)

        client = _auth_client(user)
        response = client.get("api/store/vendors/")

        assert response.status_code == status.HTTP_404_NOT_FOUND 
        


    def test_vendor_detail_by_id_is_404(self):
        """GET /vendors/{id}/ is completely inaccessible, even for own ID."""
        user = StoreUserFactory()
        vendor = VendorFactory(user=user)

        client = _auth_client(user)
        response = client.get(f"api/store/vendor/{vendor.id}")

        assert response.status_code == status.HTTP_404_NOT_FOUND


    def test_vendor_me_endpoint_remains_accessible(self):
        """GET /vendors/me/ functions perfectly as the sole entry point."""
        user = StoreUserFactory()
        vendor = VendorFactory(user=user)

        client = _auth_client(user)
        url = reverse("vendor-me")  
        response = client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["id"] == vendor.id


# =========================================================
# District
# =========================================================
@pytest.mark.django_db
class TestDistrictViewSet:

    def test_list_districts(self):
        user = StoreUserFactory()
        DistrictFactory(name="A")
        DistrictFactory(name="B")

        client = _auth_client(user)
        url = reverse("district-list")
        response = client.get(url)

        assert response.status_code == 200
        assert len(response.data) == 2

    def test_retrieve_district(self):
        user = StoreUserFactory()
        district = DistrictFactory(name="Central", city_name="Lisbon")

        client = _auth_client(user)
        url = reverse("district-detail", args=[district.id])
        response = client.get(url)

        assert response.status_code == 200
        assert response.data["name"] == "Central"
        assert response.data["city_name"] == "Lisbon"

    def test_anonymous_gets_401(self):
        client = APIClient()
        url = reverse("district-list")
        response = client.get(url)

        assert response.status_code == 401

    @pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
    def test_write_methods_return_405(self, method):
        user = StoreUserFactory()
        district = DistrictFactory()

        client = _auth_client(user)
        url = reverse("district-detail", args=[district.id])
        response = getattr(client, method)(url)

        assert response.status_code == 405


# =========================================================
# Street
# =========================================================
@pytest.mark.django_db
class TestStreetViewSet:

    def test_list_streets(self):
        user = StoreUserFactory()
        StreetFactory()
        StreetFactory()

        client = _auth_client(user)
        url = reverse("street-list")
        response = client.get(url)

        assert response.status_code == 200
        assert len(response.data) == 2

    def test_retrieve_street_includes_district_name(self):
        user = StoreUserFactory()
        district = DistrictFactory(name="Central")
        street = StreetFactory(name="Main", district=district)

        client = _auth_client(user)
        url = reverse("street-detail", args=[street.id])
        response = client.get(url)

        assert response.status_code == 200
        assert response.data["name"] == "Main"
        assert response.data["district"] == district.id
        assert response.data["district_name"] == "Central"

    def test_anonymous_gets_401(self):
        client = APIClient()
        url = reverse("street-list")
        response = client.get(url)

        assert response.status_code == 401


# =========================================================
# ShopVendor (nested under Vendor)
# =========================================================
@pytest.mark.django_db
class TestShopVendorViewSet:

    def test_list_only_own_shops(self):
        user_a = StoreUserFactory()
        user_b = StoreUserFactory(phone="+2457554457")
        vendor_a = VendorFactory(user=user_a)
        vendor_b = VendorFactory(user=user_b)
        ShopVendorFactory(vendor=vendor_a)
        ShopVendorFactory(vendor=vendor_b)

        client = _auth_client(user_a)
        url = reverse("vendor-shops-list", kwargs={"vendor_pk": vendor_a.id})
        response = client.get(url)

        assert response.status_code == 200
        assert len(response.data) == 1

    def test_create_shop_with_coordinates(self):
        user = StoreUserFactory()
        vendor = VendorFactory(user=user)
        street = StreetFactory()

        client = _auth_client(user)
        url = reverse("vendor-shops-list", kwargs={"vendor_pk": vendor.id})
        response = client.post(
            url,
            data={
                "street": street.id,
                "lon": 10.5,
                "lat": 20.5,
                "contact_number": "912345678",
            },
            format="json",
        )

        assert response.status_code == 201
        shop = ShopVendor.objects.get(id=response.data["id"])
        assert shop.vendor_id == vendor.id
        assert shop.street_id == street.id
        assert shop.location.x == 10.5
        assert shop.location.y == 20.5
        assert shop.contact_number == "912345678"

    def test_create_shop_without_coordinates_fails(self):
        user = StoreUserFactory()
        vendor = VendorFactory(user=user)
        street = StreetFactory()

        client = _auth_client(user)
        url = reverse("vendor-shops-list", kwargs={"vendor_pk": vendor.id})
        response = client.post(
            url,
            data={"street": street.id, "contact_number": "912345678"},
            format="json",
        )

        assert response.status_code != 201

    def test_create_shop_with_only_lon_fails(self):
        user = StoreUserFactory()
        vendor = VendorFactory(user=user)
        street = StreetFactory()

        client = _auth_client(user)
        url = reverse("vendor-shops-list", kwargs={"vendor_pk": vendor.id})
        response = client.post(
            url,
            data={"street": street.id, "lon": 10.5, "contact_number": "912345678"},
            format="json",
        )

        assert response.status_code == 400

    def test_update_shop_location(self):
        user = StoreUserFactory()
        vendor = VendorFactory(user=user)
        shop = ShopVendorFactory(vendor=vendor, location=Point(0, 0, srid=4326))

        client = _auth_client(user)
        url = reverse(
            "vendor-shops-detail",
            kwargs={"vendor_pk": vendor.id, "pk": shop.id},
        )
        response = client.patch(
            url,
            data={"lon": 45.0, "lat": 90.0},
            format="json",
        )

        assert response.status_code == 200
        shop.refresh_from_db()
        assert shop.location.x == 45.0
        assert shop.location.y == 90.0

    def test_cannot_access_other_vendors_shop(self):
        user_a = StoreUserFactory()
        user_b = StoreUserFactory(phone="+2457554457")
        vendor_a = VendorFactory(user=user_a)
        vendor_b = VendorFactory(user=user_b)
        shop_b = ShopVendorFactory(vendor=vendor_b)

        client = _auth_client(user_a)
        url = reverse(
            "vendor-shops-detail",
            kwargs={"vendor_pk": vendor_a.id, "pk": shop_b.id},
        )
        response = client.get(url)

        assert response.status_code == 404

    def test_anonymous_gets_401(self):
        vendor = VendorFactory()
        client = APIClient()
        url = reverse("vendor-shops-list", kwargs={"vendor_pk": vendor.id})
        response = client.get(url)

        assert response.status_code == 401

    def test_delete_own_shop(self):
        user = StoreUserFactory()
        vendor = VendorFactory(user=user)
        shop = ShopVendorFactory(vendor=vendor)
        shop_id = shop.id

        client = _auth_client(user)
        url = reverse(
            "vendor-shops-detail",
            kwargs={"vendor_pk": vendor.id, "pk": shop_id},
        )
        response = client.delete(url)

        assert response.status_code == 204
        assert ShopVendor.objects.filter(id=shop_id).exists() is False


# =========================================================
# Category
# =========================================================
@pytest.mark.django_db
class TestCategoryViewSet:

    def test_list_categories(self):
        user = StoreUserFactory()
        CategoryFactory()
        CategoryFactory()

        client = _auth_client(user)
        url = reverse("category-list")
        response = client.get(url)

        assert response.status_code == 200
        assert len(response.data) == 2

    def test_retrieve_category(self):
        user = StoreUserFactory()
        category = CategoryFactory(name="Fruits")

        client = _auth_client(user)
        url = reverse("category-detail", args=[category.id])
        response = client.get(url)

        assert response.status_code == 200
        assert response.data["name"] == "Fruits"

    def test_anonymous_gets_401(self):
        client = APIClient()
        url = reverse("category-list")
        response = client.get(url)

        assert response.status_code == 401

    @pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
    def test_write_methods_return_405(self, method):
        user = StoreUserFactory()
        category = CategoryFactory()

        client = _auth_client(user)
        url = reverse("category-detail", args=[category.id])
        response = getattr(client, method)(url)

        assert response.status_code == 405


# =========================================================
# Product
# =========================================================
@pytest.mark.django_db
class TestProductViewSet:

    def test_list_only_own_products(self):
        user_a = StoreUserFactory()
        user_b = StoreUserFactory(phone="+2457554457")
        vendor_a = VendorFactory(user=user_a)
        vendor_b = VendorFactory(user=user_b)
        shop_a = ShopVendorFactory(vendor=vendor_a)
        shop_b = ShopVendorFactory(vendor=vendor_b)
        ProductFactory(shop=shop_a)
        ProductFactory(shop=shop_b)

        client = _auth_client(user_a)
        url = reverse("product-list")
        response = client.get(url)

        assert response.status_code == 200
        assert len(response.data) == 1
        assert response.data[0]["shop"]["id"] == shop_a.id

    def test_create_product_own_shop(self):
        user = StoreUserFactory()
        vendor = VendorFactory(user=user)
        shop = ShopVendorFactory(vendor=vendor)
        category = CategoryFactory()

        client = _auth_client(user)
        url = reverse("product-list")
        response = client.post(
            url,
            data={
                "shop": shop.id,
                "category": category.id,
                "name": "Apple",
                "price": "2.50",
            },
            format="json",
        )

        assert response.status_code == 201
        product = Product.objects.get(id=response.data["id"])
        assert product.name == "Apple"
        assert product.price == Decimal("2.50")

    def test_create_product_other_shop_forbidden(self):
        user_a = StoreUserFactory()
        user_b = StoreUserFactory(phone="+2457554457")
        vendor_b = VendorFactory(user=user_b)
        shop_b = ShopVendorFactory(vendor=vendor_b)
        category = CategoryFactory()

        client = _auth_client(user_a)
        url = reverse("product-list")
        response = client.post(
            url,
            data={
                "shop": shop_b.id,
                "category": category.id,
                "name": "Apple",
                "price": "2.50",
            },
            format="json",
        )

        assert response.status_code == 400
        assert "shop" in response.data

    @pytest.mark.parametrize("price", ["-1.00", "-0.01"])
    def test_create_product_negative_price_rejected(self, price):
        user = StoreUserFactory()
        vendor = VendorFactory(user=user)
        shop = ShopVendorFactory(vendor=vendor)
        category = CategoryFactory()

        client = _auth_client(user)
        url = reverse("product-list")
        response = client.post(
            url,
            data={
                "shop": shop.id,
                "category": category.id,
                "name": "Apple",
                "price": price,
            },
            format="json",
        )

        assert response.status_code == 400
        assert "price" in response.data

    def test_upsert_updates_existing_price(self):
        user = StoreUserFactory()
        vendor = VendorFactory(user=user)
        shop = ShopVendorFactory(vendor=vendor)
        category = CategoryFactory()
        existing = ProductFactory(
            shop=shop, category=category, name="Apple", price=Decimal("1.00")
        )

        client = _auth_client(user)
        url = reverse("product-list")
        response = client.post(
            url,
            data={
                "shop": shop.id,
                "category": category.id,
                "name": "Apple",
                "price": "5.00",
            },
            format="json",
        )

        assert response.status_code == 201
        existing.refresh_from_db()
        assert existing.price == Decimal("5.00")
        assert (
            Product.objects.filter(shop=shop, category=category, name="Apple").count()
            == 1
        )

    def test_update_own_product(self):
        user = StoreUserFactory()
        vendor = VendorFactory(user=user)
        shop = ShopVendorFactory(vendor=vendor)
        product = ProductFactory(shop=shop, price=Decimal("1.00"))

        client = _auth_client(user)
        url = reverse("product-detail", args=[product.id])
        response = client.patch(
            url,
            data={"price": "9.99"},
            format="json",
        )

        assert response.status_code == 200
        product.refresh_from_db()
        assert product.price == Decimal("9.99")

    def test_update_other_product_404(self):
        user_a = StoreUserFactory()
        user_b = StoreUserFactory(phone="+2457554457")
        vendor_b = VendorFactory(user=user_b)
        shop_b = ShopVendorFactory(vendor=vendor_b)
        product_b = ProductFactory(shop=shop_b)

        client = _auth_client(user_a)
        url = reverse("product-detail", args=[product_b.id])
        response = client.patch(
            url,
            data={"price": "9.99"},
            format="json",
        )

        assert response.status_code == 404

    def test_delete_own_product(self):
        user = StoreUserFactory()
        vendor = VendorFactory(user=user)
        shop = ShopVendorFactory(vendor=vendor)
        product = ProductFactory(shop=shop)
        product_id = product.id

        client = _auth_client(user)
        url = reverse("product-detail", args=[product_id])
        response = client.delete(url)

        assert response.status_code == 204
        assert Product.objects.filter(id=product_id).exists() is False

    def test_anonymous_gets_401(self):
        client = APIClient()
        url = reverse("product-list")
        response = client.get(url)

        assert response.status_code == 401


# =========================================================
# ProductImages (nested under Product)
# =========================================================
@pytest.mark.django_db
class TestProductImagesViewSet:

    def test_list_only_own_product_images(self):
        user_a = StoreUserFactory()
        user_b = StoreUserFactory(phone="+2457554457")
        vendor_a = VendorFactory(user=user_a)
        vendor_b = VendorFactory(user=user_b)
        shop_a = ShopVendorFactory(vendor=vendor_a)
        shop_b = ShopVendorFactory(vendor=vendor_b)
        product_a = ProductFactory(shop=shop_a)
        product_b = ProductFactory(shop=shop_b)
        ProductImagesFactory(product=product_a)
        ProductImagesFactory(product=product_b)

        client = _auth_client(user_a)
        url = reverse("product-images-list", kwargs={"product_pk": product_a.id})
        response = client.get(url)

        assert response.status_code == 200
        assert len(response.data) == 1

    def test_create_image_for_own_product(self):
        user = StoreUserFactory()
        vendor = VendorFactory(user=user)
        shop = ShopVendorFactory(vendor=vendor)
        product = ProductFactory(shop=shop)

        upload = SimpleUploadedFile(
            "test.png", b"file-content", content_type="image/png"
        )

        client = _auth_client(user)
        url = reverse("product-images-list", kwargs={"product_pk": product.id})
        response = client.post(
            url,
            data={"picture": upload},
            format="multipart",
        )

        assert response.status_code == 201
        image = ProductImages.objects.get(id=response.data["id"])
        assert image.product_id == product.id

    def test_create_image_for_other_product_404(self):
        user_a = StoreUserFactory()
        user_b = StoreUserFactory(phone="+2457554457")
        vendor_b = VendorFactory(user=user_b)
        shop_b = ShopVendorFactory(vendor=vendor_b)
        product_b = ProductFactory(shop=shop_b)

        upload = SimpleUploadedFile(
            "test.png", b"file-content", content_type="image/png"
        )

        client = _auth_client(user_a)
        url = reverse("product-images-list", kwargs={"product_pk": product_b.id})
        response = client.post(
            url,
            data={"picture": upload},
            format="multipart",
        )

        assert response.status_code in (400, 404)

    def test_delete_own_image(self):
        user = StoreUserFactory()
        vendor = VendorFactory(user=user)
        shop = ShopVendorFactory(vendor=vendor)
        product = ProductFactory(shop=shop)
        image = ProductImagesFactory(product=product)
        image_id = image.id

        client = _auth_client(user)
        url = reverse(
            "product-images-detail",
            kwargs={"product_pk": product.id, "pk": image_id},
        )
        response = client.delete(url)

        assert response.status_code == 204
        assert ProductImages.objects.filter(id=image_id).exists() is False

    def test_anonymous_gets_401(self):
        product = ProductFactory()
        client = APIClient()
        url = reverse("product-images-list", kwargs={"product_pk": product.id})
        response = client.get(url)

        assert response.status_code == 401


# =========================================================
# Content
# =========================================================
@pytest.mark.django_db
class TestContentViewSet:

    def test_list_contents(self):
        user = StoreUserFactory()
        ContentFactory()
        ContentFactory()

        client = _auth_client(user)
        url = reverse("content-list")
        response = client.get(url)

        assert response.status_code == 200
        assert len(response.data) == 2

    def test_retrieve_content(self):
        user = StoreUserFactory()
        content = ContentFactory(name="Ingredients")

        client = _auth_client(user)
        url = reverse("content-detail", args=[content.id])
        response = client.get(url)

        assert response.status_code == 200
        assert response.data["name"] == "Ingredients"

    def test_anonymous_gets_401(self):
        client = APIClient()
        url = reverse("content-list")
        response = client.get(url)

        assert response.status_code == 401

    @pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
    def test_write_methods_return_405(self, method):
        user = StoreUserFactory()
        content = ContentFactory()

        client = _auth_client(user)
        url = reverse("content-detail", args=[content.id])
        response = getattr(client, method)(url)

        assert response.status_code == 405


# =========================================================
# ProductContent (nested under Product)
# =========================================================
@pytest.mark.django_db
class TestProductContentViewSet:

    def test_list_only_own_product_contents(self):
        user_a = StoreUserFactory()
        user_b = StoreUserFactory(phone="+2457554457")
        vendor_a = VendorFactory(user=user_a)
        vendor_b = VendorFactory(user=user_b)
        shop_a = ShopVendorFactory(vendor=vendor_a)
        shop_b = ShopVendorFactory(vendor=vendor_b)
        product_a = ProductFactory(shop=shop_a)
        product_b = ProductFactory(shop=shop_b)
        ProductContentFactory(product=product_a)
        ProductContentFactory(product=product_b)

        client = _auth_client(user_a)
        url = reverse("product-contents-list", kwargs={"product_pk": product_a.id})
        response = client.get(url)

        assert response.status_code == 200
        assert len(response.data) == 1

    def test_create_content_for_own_product(self):
        user = StoreUserFactory()
        vendor = VendorFactory(user=user)
        shop = ShopVendorFactory(vendor=vendor)
        product = ProductFactory(shop=shop)
        content = ContentFactory()

        client = _auth_client(user)
        url = reverse("product-contents-list", kwargs={"product_pk": product.id})
        response = client.post(
            url,
            data={"content": content.id},
            format="json",
        )

        assert response.status_code == 201
        pc = ProductContent.objects.get(id=response.data["id"])
        assert pc.product_id == product.id
        assert pc.content_id == content.id

    def test_create_duplicate_content_returns_existing(self):
        user = StoreUserFactory()
        vendor = VendorFactory(user=user)
        shop = ShopVendorFactory(vendor=vendor)
        product = ProductFactory(shop=shop)
        content = ContentFactory()
        existing = ProductContentFactory(product=product, content=content)

        client = _auth_client(user)
        url = reverse("product-contents-list", kwargs={"product_pk": product.id})
        response = client.post(
            url,
            data={"content": content.id},
            format="json",
        )

        assert response.status_code == 201
        assert response.data["id"] == existing.id
        assert (
            ProductContent.objects.filter(product=product, content=content).count() == 1
        )

    def test_create_content_for_other_product_rejected(self):
        user_a = StoreUserFactory()
        user_b = StoreUserFactory(phone="+2457554457")
        vendor_b = VendorFactory(user=user_b)
        shop_b = ShopVendorFactory(vendor=vendor_b)
        product_b = ProductFactory(shop=shop_b)
        content = ContentFactory()

        client = _auth_client(user_a)
        url = reverse("product-contents-list", kwargs={"product_pk": product_b.id})
        response = client.post(
            url,
            data={"content": content.id},
            format="json",
        )

        assert response.status_code in (400, 404)

    def test_update_own_product_content(self):
        user = StoreUserFactory()
        vendor = VendorFactory(user=user)
        shop = ShopVendorFactory(vendor=vendor)
        product = ProductFactory(shop=shop)
        content_a = ContentFactory()
        content_b = ContentFactory()
        pc = ProductContentFactory(product=product, content=content_a)

        client = _auth_client(user)
        url = reverse(
            "product-contents-detail",
            kwargs={"product_pk": product.id, "pk": pc.id},
        )
        response = client.patch(
            url,
            data={"content": content_b.id},
            format="json",
        )

        assert response.status_code == 200
        pc.refresh_from_db()
        assert pc.content_id == content_b.id

    def test_delete_own_product_content(self):
        user = StoreUserFactory()
        vendor = VendorFactory(user=user)
        shop = ShopVendorFactory(vendor=vendor)
        product = ProductFactory(shop=shop)
        pc = ProductContentFactory(product=product)
        pc_id = pc.id

        client = _auth_client(user)
        url = reverse(
            "product-contents-detail",
            kwargs={"product_pk": product.id, "pk": pc_id},
        )
        response = client.delete(url)

        assert response.status_code == 204
        assert ProductContent.objects.filter(id=pc_id).exists() is False

    def test_anonymous_gets_401(self):
        product = ProductFactory()
        client = APIClient()
        url = reverse("product-contents-list", kwargs={"product_pk": product.id})
        response = client.get(url)

        assert response.status_code == 401