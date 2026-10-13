from django.contrib.auth import get_user_model
from django.contrib.gis.geos import Point
from rest_framework import serializers
from shipping.models import Deliver
from store.models import Product, ShopVendor, Street

from .models import Cart, CartItem, Client, Order, OrderItem

User = get_user_model()


# =========================================================
# Shared nested read-only serializers
# =========================================================
class StreetSerializer(serializers.ModelSerializer):
    """Lightweight read-only Street representation."""

    district_name = serializers.CharField(source="district.name", read_only=True)
    city_name = serializers.CharField(source="district.city_name", read_only=True)

    class Meta:
        model = Street
        fields = ["id", "name", "district", "district_name", "city_name"]
        read_only_fields = fields


class ShopVendorBriefSerializer(serializers.ModelSerializer):
    """Compact ShopVendor representation for nested output."""

    vendor_username = serializers.CharField(
        source="vendor.user.username", read_only=True
    )
    street_name = serializers.CharField(source="street.name", read_only=True)

    class Meta:
        model = ShopVendor
        fields = ["id", "vendor", "vendor_username", "street", "street_name"]
        read_only_fields = fields


class DeliverBriefSerializer(serializers.ModelSerializer):
    """Compact Deliver representation for nested output."""

    username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = Deliver
        fields = ["id", "user", "username", "is_active"]
        read_only_fields = fields


class ProductBriefSerializer(serializers.ModelSerializer):
    """Compact Product representation for nested output."""

    shop_name = serializers.CharField(source="shop.__str__", read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True)

    class Meta:
        model = Product
        fields = ["id", "name", "price", "shop", "shop_name", "category", "category_name"]
        read_only_fields = fields


# =========================================================
# Client
# =========================================================
class ClientSerializer(serializers.ModelSerializer):
    """Read-only Client representation (with nested street)."""

    username = serializers.CharField(source="user.username", read_only=True)
    street_detail = StreetSerializer(source="street", read_only=True)
    location = serializers.SerializerMethodField()

    class Meta:
        model = Client
        fields = [
            "id",
            "user",
            "username",
            "location",
            "street",
            "street_detail",
        ]
        read_only_fields = fields

    def get_location(self, instance):
        if not instance.location:
            return None
        return {
            "type": "Point",
            "coordinates": [instance.location.x, instance.location.y],
        }


class ClientUpdateSerializer(serializers.ModelSerializer):
    """
    Write serializer for Client.

    - `user` is never writable; the view supplies `user_pk` via context.
    - `location` is set via `lon`/`lat` write-only fields.
    """

    lon = serializers.FloatField(write_only=True, required=False)
    lat = serializers.FloatField(write_only=True, required=False)

    class Meta:
        model = Client
        fields = ["id", "location", "lon", "lat", "street"]
        read_only_fields = ["id", "location"]

    def validate(self, attrs):
        lon = attrs.get("lon")
        lat = attrs.get("lat")
        if (lon is None) != (lat is None):
            raise serializers.ValidationError(
                {"location": "Both 'lon' and 'lat' must be provided together."}
            )
        if lon is not None and not (-180.0 <= lon <= 180.0):
            raise serializers.ValidationError(
                {"lon": "Longitude must be between -180 and 180."}
            )
        if lat is not None and not (-90.0 <= lat <= 90.0):
            raise serializers.ValidationError(
                {"lat": "Latitude must be between -90 and 90."}
            )
        return attrs

    def _apply_coordinates(self, validated_data):
        lon = validated_data.pop("lon", None)
        lat = validated_data.pop("lat", None)
        if lon is not None and lat is not None:
            validated_data["location"] = Point(lon, lat, srid=4326)
        return validated_data

    def update(self, instance, validated_data):
        validated_data = self._apply_coordinates(validated_data)
        validated_data.pop("user", None)  # never reassign
        return super().update(instance, validated_data)


# =========================================================
# OrderItem
# =========================================================
class OrderItemSerializer(serializers.ModelSerializer):
    """Read-only OrderItem representation."""

    product = ProductBriefSerializer(read_only=True)
    total_price = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )

    class Meta:
        model = OrderItem
        fields = [
            "id",
            "order",
            "product",
            "quantity",
            "price_at_purchase",
            "total_price",
        ]
        read_only_fields = fields


class OrderItemCreateOrUpdateSerializer(serializers.ModelSerializer):
    """
    Write serializer for OrderItem.

    Context:
        order_pk : parent Order id (used at create; instance on update)
    """

    class Meta:
        model = OrderItem
        fields = ["id", "order", "product", "quantity", "price_at_purchase"]
        read_only_fields = ["id", "order"]
        extra_kwargs = {
            "quantity": {"min_value": 1},
            "price_at_purchase": {"required": False},
        }

    def validate(self, attrs):
        order_pk = self.context.get("order_pk")
        product = attrs.get("product") or getattr(self.instance, "product", None)

        # Resolve parent order.
        if self.instance is not None:
            order = self.instance.order
        else:
            if order_pk is None:
                raise serializers.ValidationError(
                    "Serializer must be given `order_pk` in its context."
                )
            try:
                order = Order.objects.get(pk=order_pk)
            except Order.DoesNotExist:
                raise serializers.ValidationError(
                    "The specified order does not exist."
                )

        # Single-shop rule.
        if product is not None and order.shop_id is not None:
            if product.shop_id != order.shop_id:
                raise serializers.ValidationError(
                    {"product": "This product belongs to a different shop than the order."}
                )

        # unique_together(order, product).
        if product is not None:
            qs = OrderItem.objects.filter(order=order, product=product)
            if self.instance is not None:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(
                    {"product": "This product is already part of the order."}
                )

        return attrs

    def create(self, validated_data):
        order_pk = self.context.get("order_pk")
        try:
            order = Order.objects.get(pk=order_pk)
        except Order.DoesNotExist:
            raise serializers.ValidationError("The specified order does not exist.")

        product = validated_data.get("product")

        # Lazy shop assignment — mirrors OrderItem.clean().
        if order.shop_id is None and product is not None:
            order.shop = product.shop
            order.save(update_fields=["shop"])

        # Auto-fill price from product if not provided.
        if not validated_data.get("price_at_purchase"):
            validated_data["price_at_purchase"] = product.price

        validated_data["order"] = order
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data.pop("order", None)  # never reassign
        if "product" in validated_data and not validated_data.get("price_at_purchase"):
            validated_data["price_at_purchase"] = validated_data["product"].price
        return super().update(instance, validated_data)


# =========================================================
# Order
# =========================================================
class OrderSerializer(serializers.ModelSerializer):
    """Read-only Order representation with nested items and computed total."""

    client = ClientSerializer(read_only=True)
    deliver = DeliverBriefSerializer(read_only=True)
    shop = ShopVendorBriefSerializer(read_only=True)
    street = StreetSerializer(read_only=True)
    items = OrderItemSerializer(many=True, read_only=True)
    total = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    location = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "id",
            "client",
            "deliver",
            "delivery_status",
            "payment_status",
            "created_at",
            "updated_at",
            "location",
            "street",
            "shop",
            "items",
            "total",
        ]
        read_only_fields = fields

    def get_location(self, instance):
        if not instance.location:
            return None
        return {
            "type": "Point",
            "coordinates": [instance.location.x, instance.location.y],
        }


class OrderCreateOrUpdateSerializer(serializers.ModelSerializer):
    """
    Write serializer for Order.

    Context:
        user_pk : authenticated user id (Client is derived from it).
    """

    lon = serializers.FloatField(write_only=True, required=False)
    lat = serializers.FloatField(write_only=True, required=False)
    class Meta:
        model = Order
        fields = [
            "id",
            "deliver",
            "delivery_status",
            "payment_status",
            "location",
            "lon",
            "lat",
            "street",
            "shop",
        ]
        read_only_fields = ["id", "location", "delivery_status", "payment_status"]

    def validate(self, attrs):
        lon = attrs.get("lon")
        lat = attrs.get("lat")
       
        
        if (lon is None) != (lat is None):
            raise serializers.ValidationError(
                {"location": "Both 'lon' and 'lat' must be provided together."}
            )
        if lon is not None and not (-180.0 <= lon <= 180.0):
            raise serializers.ValidationError(
                {"lon": "Longitude must be between -180 and 180."}
            )
        if lat is not None and not (-90.0 <= lat <= 90.0):
            raise serializers.ValidationError(
                {"lat": "Latitude must be between -90 and 90."}
            )

        user_pk = self.context.get("user_pk")
        if user_pk is None:
            raise serializers.ValidationError(
                "You do not have permission to modify this order."
            )
        elif self.instance is not None and user_pk is not None:
            if self.instance.client.user_id != user_pk:
                raise serializers.ValidationError(
                    "You do not have permission to modify this order."
                )

        try:
            client = Client.objects.get(user_id=user_pk)
        except Client.DoesNotExist:
            raise serializers.ValidationError("You do not have a Client profile.")
        
        location = attrs.get("location")
        if location is None and lat is None and lon is None:
            if not client.location:
                raise serializers.ValidationError(
                {"location": "Location is required and no client default exists."}
            )

        return attrs

    def validate_shop(self, value):
        if value is None and self.instance is not None and self.instance.shop_id:
            if self.instance.items.exists():
                raise serializers.ValidationError(
                    "Cannot detach shop from an order that already has items."
                )
        return value

    def _apply_coordinates(self, validated_data):
        lon = validated_data.pop("lon", None)
        lat = validated_data.pop("lat", None)
        if lon is not None and lat is not None:
            validated_data["location"] = Point(lon, lat, srid=4326)
        return validated_data

    def create(self, validated_data):
        validated_data = self._apply_coordinates(validated_data)
        user_pk = self.context.get("user_pk")
        if user_pk is None:
            raise serializers.ValidationError(
                "Serializer must be given `user_pk` in its context."
            )
        try:
            client = Client.objects.get(user_id=user_pk)
        except Client.DoesNotExist:
            raise serializers.ValidationError("You do not have a Client profile.")

        # Fall back to the client's saved location when none was provided.
        if "location" not in validated_data:
            if not client.location:
                raise serializers.ValidationError(
                    {"location": "Location is required and no client default exists."}
                )
            validated_data["location"] = client.location

        validated_data["client"] = client
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data = self._apply_coordinates(validated_data)
        validated_data.pop("client", None)
        return super().update(instance, validated_data)


# =========================================================
# CartItem
# =========================================================
class CartItemSerializer(serializers.ModelSerializer):
    """Read-only CartItem representation."""

    product = ProductBriefSerializer(read_only=True)
    total_price = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )

    class Meta:
        model = CartItem
        fields = [
            "id",
            "cart",
            "product",
            "quantity",
            "price_at_purchase",
            "total_price",
            "added_at",
            "updated_at",
        ]
        read_only_fields = fields


class CartItemCreateOrUpdateSerializer(serializers.ModelSerializer):
    """
    Write serializer for CartItem.

    Context:
        cart_pk : parent Cart id (used at create; instance.cart on update)
    """

    class Meta:
        model = CartItem
        fields = ["id", "cart", "product", "quantity", "price_at_purchase"]
        read_only_fields = ["id", "cart"]
        extra_kwargs = {
            "quantity": {"min_value": 1},
            "price_at_purchase": {"required": False},
        }

    def validate(self, attrs):
        cart_pk = self.context.get("cart_pk")
        product = attrs.get("product") or getattr(self.instance, "product", None)

        # Resolve parent cart.
        if self.instance is not None:
            cart = self.instance.cart
        else:
            if cart_pk is None:
                raise serializers.ValidationError(
                    "Serializer must be given `cart_pk` in its context."
                )
            try:
                cart = Cart.objects.get(pk=cart_pk)
            except Cart.DoesNotExist:
                raise serializers.ValidationError("The specified cart does not exist.")

        # Single-shop rule.
        if product is not None and cart.shop_id is not None:
            if product.shop_id != cart.shop_id:
                raise serializers.ValidationError(
                    {
                        "product": (
                            "This product belongs to a different shop than the "
                            "cart. A cart can only contain products from one shop."
                        )
                    }
                )

        # unique_together(cart, product).
        if product is not None:
            qs = CartItem.objects.filter(cart=cart, product=product)
            if self.instance is not None:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(
                    {"product": "This product is already in the cart."}
                )

        return attrs

    def create(self, validated_data):
        cart_pk = self.context.get("cart_pk")
        try:
            cart = Cart.objects.get(pk=cart_pk)
        except Cart.DoesNotExist:
            raise serializers.ValidationError("The specified cart does not exist.")

        product = validated_data.get("product")

        # Lazy shop assignment — mirrors CartItem.clean().
        if cart.shop_id is None and product is not None:
            cart.shop = product.shop
            cart.save(update_fields=["shop"])

        # Auto-fill price_at_purchase from the product.
        if not validated_data.get("price_at_purchase"):
            validated_data["price_at_purchase"] = product.price

        validated_data["cart"] = cart
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data.pop("cart", None)
        if "product" in validated_data and not validated_data.get("price_at_purchase"):
            validated_data["price_at_purchase"] = validated_data["product"].price
        return super().update(instance, validated_data)


# =========================================================
# Cart
# =========================================================
class CartSerializer(serializers.ModelSerializer):
    """Read-only Cart representation with nested items."""

    items = CartItemSerializer(many=True, read_only=True)
    shop = ShopVendorBriefSerializer(read_only=True)
    street = StreetSerializer(read_only=True)
    client = ClientSerializer(read_only=True)
    total = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    item_count = serializers.IntegerField(read_only=True)
    location = serializers.SerializerMethodField()

    class Meta:
        model = Cart
        fields = [
            "id",
            "client",
            "guest_token",
            "shop",
            "location",
            "street",
            "is_active",
            "created_at",
            "updated_at",
            "items",
            "total",
            "item_count",
        ]
        read_only_fields = fields

    def get_location(self, instance):
        if not instance.location:
            return None
        return {
            "type": "Point",
            "coordinates": [instance.location.x, instance.location.y],
        }


class CartCreateSerializer(serializers.ModelSerializer):
    """
    Write serializer for Cart creation.

    Context:
        user_pk : if present, cart is tied to that user's Client;
                  otherwise, a guest cart is created (guest_token auto).
    """

    lon = serializers.FloatField(write_only=True, required=False)
    lat = serializers.FloatField(write_only=True, required=False)

    class Meta:
        model = Cart
        fields = ["id", "location", "lon", "lat", "street"]
        read_only_fields = ["id", "location"]

    def validate(self, attrs):
        lon = attrs.get("lon")
        lat = attrs.get("lat")
        if (lon is None) != (lat is None):
            raise serializers.ValidationError(
                {"location": "Both 'lon' and 'lat' must be provided together."}
            )
        if lon is not None and not (-180.0 <= lon <= 180.0):
            raise serializers.ValidationError(
                {"lon": "Longitude must be between -180 and 180."}
            )
        if lat is not None and not (-90.0 <= lat <= 90.0):
            raise serializers.ValidationError(
                {"lat": "Latitude must be between -90 and 90."}
            )

        user_pk = self.context.get("user_pk")
        if user_pk is not None and not Client.objects.filter(user_id=user_pk).exists():
            raise serializers.ValidationError(
                "Authenticated user has no Client profile."
            )

        
        return attrs

    def _apply_coordinates(self, validated_data):
        lon = validated_data.pop("lon", None)
        lat = validated_data.pop("lat", None)
        if lon is not None and lat is not None:
            validated_data["location"] = Point(lon, lat, srid=4326)
        return validated_data

    def create(self, validated_data):
        validated_data = self._apply_coordinates(validated_data)

        user_pk = self.context.get("user_pk")
        if user_pk is not None:
            try:
                validated_data["client"] = Client.objects.get(user_id=user_pk)
            except Client.DoesNotExist:
                raise serializers.ValidationError(
                    "Authenticated user has no Client profile."
                )
        # else: leave client=None → guest cart, guest_token auto-generated.

        return super().create(validated_data)


class CartUpdateSerializer(serializers.ModelSerializer):
    """
    Write serializer for Cart updates.

    Only a small set of fields can change. `client` and `guest_token` are
    never writable — ownership is fixed for the life of the cart.
    """

    lon = serializers.FloatField(write_only=True, required=False)
    lat = serializers.FloatField(write_only=True, required=False)

    class Meta:
        model = Cart
        fields = ["id", "location", "lon", "lat", "street", "is_active"]
        read_only_fields = ["id", "location"]

    def validate(self, attrs):
        lon = attrs.get("lon")
        lat = attrs.get("lat")
        if (lon is None) != (lat is None):
            raise serializers.ValidationError(
                {"location": "Both 'lon' and 'lat' must be provided together."}
            )
        return attrs

    def update(self, instance, validated_data):
        lon = validated_data.pop("lon", None)
        lat = validated_data.pop("lat", None)
        if lon is not None and lat is not None:
            validated_data["location"] = Point(lon, lat, srid=4326)
        # `client` and `guest_token` are not in `fields`, so they can't
        # be touched here even if a client sends them.
        return super().update(instance, validated_data)


# =========================================================
# Cart merge (login/registration flow)
# =========================================================
class CartMergeSerializer(serializers.Serializer):
    """
    Input serializer for merging a guest cart into a client's cart.

    Context:
        user_pk : authenticated user id (its Client will own the result).

    Body:
        guest_token : UUID of the guest cart to merge.
    """

    guest_token = serializers.UUIDField()

    def validate_guest_token(self, value):
        try:
            cart = Cart.objects.get(guest_token=value, is_active=True)
        except Cart.DoesNotExist:
            raise serializers.ValidationError("No active guest cart with that token.")
        self._guest_cart = cart
        return value

    def save(self, **kwargs):
        user_pk = self.context.get("user_pk")
        if user_pk is None:
            raise serializers.ValidationError(
                "Serializer must be given `user_pk` in its context."
            )
        try:
            client = Client.objects.get(user_id=user_pk)
        except Client.DoesNotExist:
            raise serializers.ValidationError("You do not have a Client profile.")

        return self._guest_cart.attach_to_client(client)