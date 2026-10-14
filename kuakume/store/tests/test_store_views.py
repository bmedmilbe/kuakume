from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from shopping.models import Order
from shopping.tests.test_shopping_models import (
    _create_order_with_user_and_shop,
)

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
        user, _, _, _ = _create_order_with_user_and_shop()
        vendor = user.vendor_user
        vendor.account_number_pt="PT1"
        vendor.save()

        client = _auth_client(user)
        url = reverse("store:vendor-me")
        response = client.get(url)

        assert response.status_code == 200
        assert response.data["id"] == vendor.id
        assert response.data["account_number_pt"] == "PT1"
        assert "shops" in response.data

    def test_anonymous_user_gets_401(self):
        client = APIClient()
        url = reverse("store:vendor-me")
        response = client.get(url)

        assert response.status_code == 401

    def test_patch_account_fields(self):
        user, _, _, _ = _create_order_with_user_and_shop()
        vendor = user.vendor_user
        client = _auth_client(user)
        url = reverse("store:vendor-me")
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
        user, _, _, _ = _create_order_with_user_and_shop()
        
        client = _auth_client(user)
        url = reverse("store:vendor-me")
        response = getattr(client, method)(url)

        assert response.status_code == 405

    def test_vendor_list_is_404(self):
        """GET /vendors/ is completely inaccessible."""
        user = StoreUserFactory()
        VendorFactory(user=user, is_active=True)

        client = _auth_client(user)
        response = client.get("api/store/vendors/")

        assert response.status_code == status.HTTP_404_NOT_FOUND 
        


    def test_vendor_detail_by_id_is_404(self):
        """GET /vendors/{id}/ is completely inaccessible, even for own ID."""
        user = StoreUserFactory()
        vendor = VendorFactory(user=user, is_active=True)

        client = _auth_client(user)
        response = client.get(f"api/store/vendor/{vendor.id}")

        assert response.status_code == status.HTTP_404_NOT_FOUND


    def test_vendor_me_endpoint_remains_accessible(self):
        """GET /vendors/me/ functions perfectly as the sole entry point."""
        user, _, _, _ = _create_order_with_user_and_shop()
        vendor = user.vendor_user
        client = _auth_client(user)
        url = reverse("store:vendor-me")  
        response = client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["id"] == vendor.id


# =========================================================
# District
# =========================================================
@pytest.mark.django_db
class TestDistrictViewSet:

    def test_list_districts(self):
        user,_,_,_ = _create_order_with_user_and_shop()

        client = _auth_client(user)
        url = reverse("store:district-list")
        response = client.get(url)

        assert response.status_code == 200
        assert len(response.data) == 2

    def test_retrieve_district(self):
        user, _, _, _ = _create_order_with_user_and_shop()
        district = DistrictFactory(name="Central", city_name="Lisbon")

        client = _auth_client(user)
        url = reverse("store:district-detail", args=[district.id])
        response = client.get(url)

        assert response.status_code == 200
        assert response.data["name"] == "Central"
        assert response.data["city_name"] == "Lisbon"

    def test_anonymous_gets_401(self):
        client = APIClient()
        url = reverse("store:district-list")
        response = client.get(url)

        assert response.status_code == 401

    @pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
    def test_write_methods_return_405(self, method):
        user, _, _, _ = _create_order_with_user_and_shop()
        user.is_staff = True
        user.save()
        district = DistrictFactory()

        client = _auth_client(user)
        url = reverse("store:district-detail", args=[district.id])
        response = getattr(client, method)(url)

        assert response.status_code == 405


# =========================================================
# Street
# =========================================================
@pytest.mark.django_db
class TestStreetViewSet:

    def test_list_streets(self):
        user, _,_, _ = _create_order_with_user_and_shop()

        client = _auth_client(user)
        url = reverse("store:street-list")
        response = client.get(url)

        assert response.status_code == 200
        assert len(response.data) == 2

    def test_retrieve_street_includes_district_name(self):
        user, _, _, _ = _create_order_with_user_and_shop()
        district = DistrictFactory(name="Central")
        street = StreetFactory(name="Main", district=district)

        client = _auth_client(user)
        url = reverse("store:street-detail", args=[street.id])
        response = client.get(url)

        assert response.status_code == 200
        assert response.data["name"] == "Main"
        assert response.data["district"] == district.id
        assert response.data["district_name"] == "Central"

    def test_anonymous_gets_401(self):
        client = APIClient()
        url = reverse("store:street-list")
        response = client.get(url)

        assert response.status_code == 401


# =========================================================
# ShopVendor (nested under Vendor)
# =========================================================
@pytest.mark.django_db
class TestShopVendorViewSet:

    def test_list_only_own_shops(self):
        user_a, _, _, _ = _create_order_with_user_and_shop()
        _, _, _, _ = _create_order_with_user_and_shop()
        
        client = _auth_client(user_a)
        url = reverse("store:shop-list")
        response = client.get(url)

        assert response.status_code == 200
        assert len(response.data) == 1

    def test_create_shop_with_coordinates(self):
        user, shop, _, _ = _create_order_with_user_and_shop()
        street = StreetFactory()

        client = _auth_client(user)
        url = reverse("store:shop-list")
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
        assert shop.vendor_id == user.vendor_user.id
        assert shop.street_id == street.id
        assert shop.location.x == 10.5
        assert shop.location.y == 20.5
        assert shop.contact_number == "912345678"

    def test_create_shop_without_coordinates_fails(self):
        user = StoreUserFactory()
        street = StreetFactory()

        client = _auth_client(user)
        url = reverse("store:shop-list")
        response = client.post(
            url,
            data={"street": street.id, "contact_number": "912345678"},
            format="json",
        )

        assert response.status_code != 201

    def test_create_shop_with_only_lon_fails(self):
        user, _, _,_ = _create_order_with_user_and_shop()
        street = StreetFactory()

        client = _auth_client(user)
        url = reverse("store:shop-list")
        response = client.post(
            url,
            data={"street": street.id, "lon": 10.5, "contact_number": "912345678"},
            format="json",
        )

        assert response.status_code == 400

    def test_update_shop_location(self):
        user, shop, _, _ = _create_order_with_user_and_shop()
        client = _auth_client(user)
        url = reverse(
            "store:shop-detail",
            kwargs={ "pk": shop.id},
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
        user_a, _, _, _ = _create_order_with_user_and_shop()
        _,shop_b, _, _ = _create_order_with_user_and_shop()

        client = _auth_client(user_a)
        url = reverse(
            "store:shop-detail",
            kwargs={ "pk": shop_b.id},
        )
        response = client.get(url)

        assert response.status_code == 404

    def test_anonymous_gets_401(self):
        client = APIClient()
        url = reverse("store:shop-list")
        response = client.get(url)

        assert response.status_code == 401

    def test_delete_own_shop(self):
        user, shop, _, _ = _create_order_with_user_and_shop()
        shop_id = shop.id

        client = _auth_client(user)
        url = reverse(
           "store:shop-detail",
            kwargs={ "pk": shop_id},
        )
        response = client.delete(url)

        assert response.status_code == 204
        assert ShopVendor.objects.filter(id=shop_id).exists() is False

    def test_anonymous_user_cannot_access_shops(self):
            """
            Verify that unauthenticated network requests to the shop endpoint are 
            properly blocked by the permission architecture.
            """
            # Arrange
            client = APIClient()
            url = reverse("store:shop-list")
    
            # Act
            response = client.get(url)
    
            # Assert
            assert response.status_code == status.HTTP_401_UNAUTHORIZED
    
    def test_vendor_can_only_see_their_own_shops(self):
        """
        Verify that the custom get_queryset implementation successfully isolates 
        and limits records to those owned by the currently authenticated vendor.
        """
        # Arrange
        client = APIClient()
        
        user, owned_shop, _, _ = _create_order_with_user_and_shop()
        vendor_other = VendorFactory()
        
        client.force_authenticate(user)
        
        # Instantiate shops assigned across different owners
        ShopVendorFactory(vendor=vendor_other)
        
        url = reverse("store:shop-list")
    
        # Act
        response = client.get(url)
    
        # Assert
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0]["id"] == owned_shop.id
    
    def test_vendor_can_create_shop_successfully(self):
        """
        Verify that a POST request to the endpoint processes successfully,
        indicating the correct write-optimised serializer configuration is chosen.
        """
        # Arrange
        client = APIClient()
        user, _,_,_=_create_order_with_user_and_shop()
        client.force_authenticate(user=user)
        
        street = StreetFactory()
        url = reverse("store:shop-list")
        
        # Minimised geographic configuration payload for standard PointField mock strings
        payload = {
            "street": street.id,
            "lon": 45.0, "lat": 90.0,
            "contact_number": "+447123456789"
        }
    
        # Act
        response = client.post(url, data=payload, format="json")
    
        # Assert
        print(response.data)
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["contact_number"] == "+447123456789"


# =========================================================
# Category
# =========================================================
@pytest.mark.django_db
class TestCategoryViewSet:

    def test_list_categories(self):
        user,_,_,_ = _create_order_with_user_and_shop()
        CategoryFactory()

        client = _auth_client(user)
        url = reverse("store:category-list")
        response = client.get(url)

        assert response.status_code == 200
        assert len(response.data) == 2

    def test_retrieve_category(self):
        user, _, _, _ = _create_order_with_user_and_shop()
        category = CategoryFactory(name="Fruits")

        client = _auth_client(user)
        url = reverse("store:category-detail", args=[category.id])
        response = client.get(url)

        assert response.status_code == 200
        assert response.data["name"] == "Fruits"

    def test_anonymous_gets_401(self):
        client = APIClient()
        url = reverse("store:category-list")
        response = client.get(url)

        assert response.status_code == 401

    @pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
    def test_write_methods_return_405(self, method):
        user, _, _, _ = _create_order_with_user_and_shop()
        category = CategoryFactory()

        client = _auth_client(user)
        url = reverse("store:category-detail", args=[category.id])
        response = getattr(client, method)(url)

        assert response.status_code == 405


# =========================================================
# Product
# =========================================================
@pytest.mark.django_db
class TestProductViewSet:

    def test_list_only_own_products(self):
        user_a, shop_a, _, _ = _create_order_with_user_and_shop()
        _, _, _, _ = _create_order_with_user_and_shop()
        

        client = _auth_client(user_a)
        url = reverse("store:product-list")
        response = client.get(url)

        assert response.status_code == 200
        assert len(response.data) == 1
        assert response.data[0]["shop"]["id"] == shop_a.id

    def test_create_product_own_shop(self):
        user, shop, _, product = _create_order_with_user_and_shop()
        category = CategoryFactory()

        client = _auth_client(user)
        url = reverse("store:product-list")
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
        user_a, _, _, _ = _create_order_with_user_and_shop()
        _, shop_b, _, _ = _create_order_with_user_and_shop()
        category = CategoryFactory()

        client = _auth_client(user_a)
        url = reverse("store:product-list")
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
        user, shop, _, _ = _create_order_with_user_and_shop()
        category = CategoryFactory()

        client = _auth_client(user)
        url = reverse("store:product-list")
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
        user, shop, _, _ = _create_order_with_user_and_shop()
        category = CategoryFactory()
        existing = ProductFactory(
            shop=shop, category=category, name="Apple", price=Decimal("1.00")
        )

        client = _auth_client(user)
        url = reverse("store:product-list")
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
        user,_,_,product = _create_order_with_user_and_shop()

        client = _auth_client(user)
        url = reverse("store:product-detail", args=[product.id])
        response = client.patch(
            url,
            data={"price": "9.99"},
            format="json",
        )

        assert response.status_code == 200
        product.refresh_from_db()
        assert product.price == Decimal("9.99")

    def test_update_other_product_404(self):
        user_a, _, _,_ = _create_order_with_user_and_shop()
        user_b = StoreUserFactory(phone="+2457554457")
        vendor_b = VendorFactory(user=user_b)
        shop_b = ShopVendorFactory(vendor=vendor_b)
        product_b = ProductFactory(shop=shop_b)

        client = _auth_client(user_a)
        url = reverse("store:product-detail", args=[product_b.id])
        response = client.patch(
            url,
            data={"price": "9.99"},
            format="json",
        )

        assert response.status_code == 404

    def test_delete_own_product(self):
        user ,_,_,product = _create_order_with_user_and_shop()
        product_id = product.id

        client = _auth_client(user)
        url = reverse("store:product-detail", args=[product_id])
        response = client.delete(url)

        assert response.status_code == 204
        assert Product.objects.filter(id=product_id).exists() is False

    def test_anonymous_gets_401(self):
        client = APIClient()
        url = reverse("store:product-list")
        response = client.get(url)

        assert response.status_code == 401


# =========================================================
# ProductImages (nested under Product)
# =========================================================
@pytest.mark.django_db
class TestProductImagesViewSet:

    def test_list_only_own_product_images(self):
        user_a, _, _, product_a = _create_order_with_user_and_shop()
        _, _, _, product_b = _create_order_with_user_and_shop()
        ProductImagesFactory(product=product_a)
        ProductImagesFactory(product=product_b)

        client = _auth_client(user_a)
        url = reverse("store:product-images-list", kwargs={"product_pk": product_a.id})
        response = client.get(url)

        assert response.status_code == 200
        assert len(response.data) == 1

    def test_create_image_for_own_product(self):
        user, _, _, product = _create_order_with_user_and_shop()

        upload = SimpleUploadedFile(
            "test.png", b"file-content", content_type="image/png"
        )

        client = _auth_client(user)
        url = reverse("store:product-images-list", kwargs={"product_pk": product.id})
        response = client.post(
            url,
            data={"picture": upload},
            format="multipart",
        )

        assert response.status_code == 201
        image = ProductImages.objects.get(id=response.data["id"])
        assert image.product_id == product.id

    def test_create_image_for_other_product_404(self):
        user_a, _, _, _ = _create_order_with_user_and_shop()

        _, _, _, product_b = _create_order_with_user_and_shop()

        upload = SimpleUploadedFile(
            "test.png", b"file-content", content_type="image/png"
        )

        client = _auth_client(user_a)
        url = reverse("store:product-images-list", kwargs={"product_pk": product_b.id})
        response = client.post(
            url,
            data={"picture": upload},
            format="multipart",
        )

        assert response.status_code in (400, 404)

    def test_delete_own_image(self):
        user, _,_, product = _create_order_with_user_and_shop()
        image = ProductImagesFactory(product=product)
        image_id = image.id

        client = _auth_client(user)
        url = reverse(
            "store:product-images-detail",
            kwargs={"product_pk": product.id, "pk": image_id},
        )
        response = client.delete(url)

        assert response.status_code == 204
        assert ProductImages.objects.filter(id=image_id).exists() is False

    def test_anonymous_gets_401(self):
        product = ProductFactory()
        client = APIClient()
        url = reverse("store:product-images-list", kwargs={"product_pk": product.id})
        response = client.get(url)

        assert response.status_code == 401


# =========================================================
# Content
# =========================================================
@pytest.mark.django_db
class TestContentViewSet:

    def test_list_contents(self):
        user,_,_,_ = _create_order_with_user_and_shop()
        ContentFactory()
        ContentFactory()

        client = _auth_client(user)
        url = reverse("store:content-list")
        response = client.get(url)

        assert response.status_code == 200
        assert len(response.data) == 2

    def test_retrieve_content(self):
        user,_,_,_ = _create_order_with_user_and_shop()
        content = ContentFactory(name="Ingredients")

        client = _auth_client(user)
        url = reverse("store:content-detail", args=[content.id])
        response = client.get(url)

        assert response.status_code == 200
        assert response.data["name"] == "Ingredients"

    def test_anonymous_gets_401(self):
        client = APIClient()
        url = reverse("store:content-list")
        response = client.get(url)

        assert response.status_code == 401

    @pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
    def test_write_methods_return_405(self, method):
        user, _,_,_ = _create_order_with_user_and_shop()
        content = ContentFactory()

        client = _auth_client(user)
        url = reverse("store:content-detail", args=[content.id])
        response = getattr(client, method)(url)

        assert response.status_code == 405


# =========================================================
# ProductContent (nested under Product)
# =========================================================
@pytest.mark.django_db
class TestProductContentViewSet:

    def test_list_only_own_product_contents(self):
        user_a, _, _, product_a = _create_order_with_user_and_shop()
        user_b = StoreUserFactory(phone="+2457554457")
        vendor_b = VendorFactory(user=user_b)
        shop_b = ShopVendorFactory(vendor=vendor_b)
        product_b = ProductFactory(shop=shop_b)
        ProductContentFactory(product=product_a)
        ProductContentFactory(product=product_b)

        client = _auth_client(user_a)
        url = reverse("store:product-contents-list", kwargs={"product_pk": product_a.id})
        response = client.get(url)

        assert response.status_code == 200
        assert len(response.data) == 1

    def test_create_content_for_own_product(self):
        user, _, _, product = _create_order_with_user_and_shop()
        content = ContentFactory()
        client = _auth_client(user)
        url = reverse("store:product-contents-list", kwargs={"product_pk": product.id})
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
        user, _, _, product = _create_order_with_user_and_shop()
        content = ContentFactory()
        existing = ProductContentFactory(product=product, content=content)

        client = _auth_client(user)
        url = reverse("store:product-contents-list", kwargs={"product_pk": product.id})
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
        user_a, _,_,_ = _create_order_with_user_and_shop()
        user_b = StoreUserFactory(phone="+2457554457")
        vendor_b = VendorFactory(user=user_b)
        shop_b = ShopVendorFactory(vendor=vendor_b)
        product_b = ProductFactory(shop=shop_b)
        content = ContentFactory()

        client = _auth_client(user_a)
        url = reverse("store:product-contents-list", kwargs={"product_pk": product_b.id})
        response = client.post(
            url,
            data={"content": content.id},
            format="json",
        )

        assert response.status_code in (400, 404)

    def test_update_own_product_content(self):
        user, _,_, product = _create_order_with_user_and_shop()
        content_a = ContentFactory()
        content_b = ContentFactory()
        pc = ProductContentFactory(product=product, content=content_a)

        client = _auth_client(user)
        url = reverse(
            "store:product-contents-detail",
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
        user, _, _, product = _create_order_with_user_and_shop()
        pc = ProductContentFactory(product=product)
        pc_id = pc.id

        client = _auth_client(user)
        url = reverse(
            "store:product-contents-detail",
            kwargs={"product_pk": product.id, "pk": pc_id},
        )
        response = client.delete(url)

        assert response.status_code == 204
        assert ProductContent.objects.filter(id=pc_id).exists() is False

    def test_anonymous_gets_401(self):
        product = ProductFactory()
        client = APIClient()
        url = reverse("store:product-contents-list", kwargs={"product_pk": product.id})
        response = client.get(url)

        assert response.status_code == 401

# ============================================================================
# ShopOrderViewSet Tests (Nested via drf-nested-routers)
# ============================================================================

@pytest.mark.django_db
class TestShopOrderViewSet:

    def test_non_vendor_user_triggers_permission_denied_exception(self):
        """
        Verify that a standard authenticated user who is not categorised as a Vendor 
        is explicitly restricted from accessing shop order indices.
        """
        # Arrange
        client = APIClient()
        standard_user = StoreUserFactory(phone="+987984984")
        client.force_authenticate(user=standard_user)
        
        # Set up a generic target shop index mapping context
        shop = ShopVendorFactory()
        url = reverse("store:shop-orders-list", kwargs={"shop_pk": shop.pk})

        # Act
        response = client.get(url)

        # Assert
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_vendor_can_list_orders_nested_under_their_own_shop(self):
        """
        Verify that an authenticated vendor can pull records matching the explicitly 
        nested shop lookup parameter when ownership credentials are valid.
        """
        # Arrange
        client = APIClient()

        # Build an order assigned to the active vendor's shop
        user,owned_shop,target_order,_ = _create_order_with_user_and_shop()
        client.force_authenticate(user=user)
        
        
        
        # Build a cross-contamination scenario with a separate shop and order
        _,_,_,_ = _create_order_with_user_and_shop()
        
        url = reverse("store:shop-orders-list", kwargs={"shop_pk": owned_shop.pk})

        # Act
        response = client.get(url)

        # Assert
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0]["id"] == target_order.id

    def test_vendor_cannot_view_orders_nested_under_another_vendors_shop(self):
        """
        Verify that the query filter layer rejects data leaks by hiding listings 
        if a vendor targets a shop primary key that they do not own.
        """
        # Arrange
        client = APIClient()
        vendor_rogue, _,_,_ = _create_order_with_user_and_shop()
        client.force_authenticate(user=vendor_rogue)
        
        # Shop and order belonging entirely to an independent vendor workspace
        user,legit_shop,_,_ = _create_order_with_user_and_shop()
        vendor_legit = user.vendor_user
        legit_shop = ShopVendorFactory(vendor=vendor_legit)
        
        url = reverse("store:shop-orders-list", kwargs={"shop_pk": legit_shop.pk})

        # Act
        response = client.get(url)

        # Assert
        assert response.status_code == status.HTTP_200_OK
        # Returns an empty list array because strict matching filters out unowned items
        assert len(response.data) == 0

    @pytest.mark.parametrize("target_status", [
        Order.PaymentStatus.PAID,
        Order.PaymentStatus.FAILED
    ])
    def test_vendor_can_patch_payment_status_successfully(self, target_status):
        """
        Verify that data mutation operations targeting unsafe HTTP methods successfully 
        authorise the alternate write serializer to process administrative status modifications.
        """
        # Arrange
        client = APIClient()
        
        user, shop, order,_ = _create_order_with_user_and_shop(payment_status=Order.PaymentStatus.SENT)
        client.force_authenticate(user=user)
        vendor = user.vendor_user
        vendor.is_active = True
        vendor.save()
                
        url = reverse("store:shop-orders-detail", kwargs={"shop_pk": shop.pk, "pk": order.pk})
        print(url)
        payload = {"payment_status": target_status}

        # Act
        response = client.patch(url, data=payload, format="json")
        order.refresh_from_db()

        # Assert
        print(response.data)
        assert response.status_code == status.HTTP_200_OK
        assert order.payment_status == target_status
