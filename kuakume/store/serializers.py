from django.contrib.auth import get_user_model
from django.contrib.gis.geos import Point
from rest_framework import serializers

from .models import (
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

# ---------------------------------------------------------
# District
# ---------------------------------------------------------
class DistrictSerializer(serializers.ModelSerializer):
    """Read-only district serializer."""

    class Meta:
        model = District
        fields = ['id', 'name', 'city_name']
        read_only_fields = fields


# ---------------------------------------------------------
# Street
# ---------------------------------------------------------
class StreetSerializer(serializers.ModelSerializer):
    """Read-only street serializer (with nested district name)."""
    district_name = serializers.CharField(source='district.name', read_only=True)

    class Meta:
        model = Street
        fields = ['id', 'name', 'district', 'district_name']
        read_only_fields = fields


# ---------------------------------------------------------
# ShopVendor
# ---------------------------------------------------------

class ShopVendorSerializer(serializers.ModelSerializer):
    """
    Read-only (GET) Serializer for ShopVendor.
    Formats spatial coordinates to GeoJSON and evaluates relation models cleanly.
    """
    vendor_username = serializers.CharField(source='vendor.user.username', read_only=True)
    street_name = serializers.CharField(source='street.name', read_only=True)  # Assumes your Street model has a 'name' field
    location = serializers.SerializerMethodField()
    
    class Meta:
        model = ShopVendor
        fields = [
            'id',
            'vendor',
            'vendor_username',
            'street',
            'street_name',
            'location',
            'contact_number',
        ]
        read_only_fields = fields

    def get_location(self, instance):
        """Converts the GeoDjango Point geometry directly into a GeoJSON structure."""
        if instance.location:
            return {
                'type': 'Point',
                'coordinates': [instance.location.x, instance.location.y],
            }
        return None

class ShopVendorCreateOrUpdateSerializer(serializers.ModelSerializer):
    """
    POST/PUT/PATCH for ShopVendor.
    Accepts latitude and longitude coordinates and converts them to a spatial Point.
    """
    lon = serializers.FloatField(write_only=True, required=False)
    lat = serializers.FloatField(write_only=True, required=False)

    class Meta:
        model = ShopVendor
        fields = [
            'id',
            'vendor',
            'street',
            'lon',
            'lat',
            'location',
            'contact_number',
        ]
        read_only_fields = ['id', 'location']

    def validate(self, attrs):
        """Ensure both coordinates are provided together if location is updated."""
        lon = attrs.get('lon')
        lat = attrs.get('lat')

        if (lon is not None and lat is None) or (lat is not None and lon is None):
            raise serializers.ValidationError(
                {"location": "Both 'lon' and 'lat' are required to update the location."}
            )
        return attrs

    def create(self, validated_data):
        lon = validated_data.pop('lon', None)
        lat = validated_data.pop('lat', None)
        
        if lon is not None and lat is not None:
            validated_data['location'] = Point(lon, lat, srid=4326)
            
        return super().create(validated_data)

    def update(self, instance, validated_data):
        lon = validated_data.pop('lon', None)
        lat = validated_data.pop('lat', None)

        if lon is not None and lat is not None:
            validated_data['location'] = Point(lon, lat, srid=4326)

        return super().update(instance, validated_data)
# ---------------------------------------------------------
# Vendor
# ---------------------------------------------------------
class VendorSerializer(serializers.ModelSerializer):
    """
    GET: full vendor details.
    PATCH: only `account_number_pt`, `account_number_stp`,
           `account_name_pt`, `account_name_stp` can be updated.
    """
    shops = ShopVendorSerializer(many=True, read_only=True)

    class Meta:
        model = Vendor
        fields = [
            'id',
            'account_number_pt',
            'account_number_stp',
            'account_name_pt',
            'account_name_stp',
            'shops',
        ]
        read_only_fields = ['id', 'shops']


# ---------------------------------------------------------
# Category
# ---------------------------------------------------------
class CategorySerializer(serializers.ModelSerializer):
    """Read-only category serializer."""
    picture = serializers.FileField(read_only=True)

    class Meta:
        model = Category
        fields = ['id', 'name', 'icon', 'picture']
        read_only_fields = fields





# ---------------------------------------------------------
# Product
# ---------------------------------------------------------

class ProductCreateOrUpdateSerializer(serializers.ModelSerializer):
    """POST / PUT / PATCH for Product with ownership validation and upsert handling."""

    class Meta:
        model = Product
        fields = ['id', 'shop', 'category', 'name', 'price']
        read_only_fields = ['id']

    def validate_price(self, value):
        if value < 0:
            raise serializers.ValidationError("Price must be non-negative.")
        return value

    def validate(self, attrs):
        
        user_pk = self.context.get('user_pk')

        if 'shop' in attrs:
            shop = attrs['shop']
            if shop.vendor.user.id != user_pk:
                raise serializers.ValidationError(
                    {"shop": "You do not have permission to add or modify products for this shop."}
                )

        elif self.instance:
            if self.instance.shop.vendor.user.id != user_pk:
                raise serializers.ValidationError(
                    "You do not have permission to modify this product."
                )

        return attrs

    def create(self, validated_data):
        """
        Handle upsert logic: If a product with the same shop, category, and name 
        already exists, update its price. Otherwise, create a new product.
        """
        shop = validated_data.get('shop')
        category = validated_data.get('category')
        name = validated_data.get('name')
        price = validated_data.get('price')

        instance, created = Product.objects.get_or_create(
            shop=shop,
            category=category,
            name=name,
            defaults={'price': price}
        )

        if not created:
            instance.price = price
            instance.save()

        return instance

    def update(self, instance, validated_data):
        """
        Standard update execution for handling individual PUT/PATCH actions.
        """
        instance.shop = validated_data.get('shop', instance.shop)
        instance.category = validated_data.get('category', instance.category)
        instance.name = validated_data.get('name', instance.name)
        instance.price = validated_data.get('price', instance.price)
        
        instance.save()
        return instance

# ---------------------------------------------------------
# ProductImages
# ---------------------------------------------------------
class ProductImagesSerializer(serializers.ModelSerializer):
    """GET for ProductImages."""

    class Meta:
        model = ProductImages
        fields = ['id', 'product', 'picture']
        read_only_fields = ['id']

class ProductSerializer(serializers.ModelSerializer):
    """GET for Product with shop ownership validation."""

    shop = VendorSerializer()
    category = CategorySerializer()
    product_images = ProductImagesSerializer(many=True)
    class Meta:
        model = Product
        fields = ['id', 'shop', 'category', 'name', 'price', 'product_images']
        read_only_fields = ['id']

class ProductImagesCreateOrUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating or updating product images within a nested API routing context.

    This serializer expects `product_pk` and `user_pk` to be explicitly passed via 
    the serializer's `context` dictionary from the view layer (e.g., `self.get_serializer_context()`).
    """
    class Meta:
        model = ProductImages
        fields = ['id', 'picture', 'product']
        read_only_fields = ['id','product']

    def validate(self, attrs):
        """
        Validate data payloads and enforce multi-layer shop ownership permissions.
        """
        product_pk = self.context.get('product_pk')
        user_pk = self.context.get('user_pk')
        
        if not self.instance:
            try:
                product = Product.objects.get(pk=product_pk)
            except Product.DoesNotExist:
                raise serializers.ValidationError("The specified product does not exist.")

            if product.shop.vendor.user.id != user_pk:
                raise serializers.ValidationError(
                    "You do not have permission to add images to this product."
                )

            attrs['product'] = product

        else:
            if self.instance.product.shop.vendor.user.id != user_pk:
                raise serializers.ValidationError(
                    "You do not have permission to modify this product image."
                )

        return attrs


# ---------------------------------------------------------
# Content
# ---------------------------------------------------------
class ContentSerializer(serializers.ModelSerializer):
    """Read-only content serializer."""

    class Meta:
        model = Content
        fields = ['id', 'name']
        read_only_fields = fields


# ---------------------------------------------------------
# ProductContent
# ---------------------------------------------------------
class ProductContentSerializer(serializers.ModelSerializer):
    """GET for ProductContent."""

    product = ProductSerializer()
    content = ContentSerializer()

    class Meta:
        model = ProductContent
        fields = ['id', 'product', 'content']
        read_only_fields = ['id']



class ProductContentCreateOrUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating or updating product content within a nested API routing context.
    If the content already exists on the product during creation, it returns that record.
    """
    class Meta:
        model = ProductContent
        fields = ['id', 'content', 'product']
        read_only_fields = ['id', 'product']

    def validate(self, attrs):
        """
        Validate data payloads and enforce multi-layer shop ownership permissions.
        """
        product_pk = self.context.get('product_pk')
        user_pk = self.context.get('user_pk')
        
        if not self.instance:
            try:
                product = Product.objects.get(pk=product_pk)
            except Product.DoesNotExist:
                raise serializers.ValidationError("The specified product does not exist.")

            if product.shop.vendor.user.id != user_pk:
                raise serializers.ValidationError(
                    "You do not have permission to add content to this product."
                )

            attrs['product'] = product
        else:
            product = self.instance.product
            if product.shop.vendor.user.id != user_pk:
                raise serializers.ValidationError(
                    "You do not have permission to modify this product content."
                )        

        return attrs

    def create(self, validated_data):
        """
        Handle upsert logic: If a record with this product and content already exists,
        return it. Otherwise, create a new one.
        """
        product = validated_data.get('product')
        content = validated_data.get('content')

        instance, created = ProductContent.objects.get_or_create(
            product=product,
            content=content,
            defaults=validated_data
        )
        return instance

    def update(self, instance, validated_data):
        """
        Standard update execution. Since product is read-only, it modifies the 
        content field value directly on the selected instance.
        """
        instance.content = validated_data.get('content', instance.content)
        instance.save()
        return instance

