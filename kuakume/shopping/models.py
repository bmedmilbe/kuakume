import uuid
from decimal import Decimal

from django.conf import settings
from django.contrib.gis.db import models
from django.core.exceptions import ValidationError
from shipping.models import Deliver
from store.models import Product, ShopVendor, Street


class Client(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='clients')
    location = models.PointField(srid=4326, null=True, blank=True)
    street = models.ForeignKey(Street, on_delete=models.CASCADE, related_name='clients', null=True, blank=True)

    def __str__(self):
        return f"Client: {self.user.username}"

class Order(models.Model):
    class DeliveryStatus(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        DISPATCHED = 'DISPATCHED', 'Dispatched'
        DELIVERED = 'DELIVERED', 'Delivered'
        CANCELLED = 'CANCELLED', 'Cancelled'

    class PaymentStatus(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        SENT = 'SENT', 'Sent'
        PAID = 'PAID', 'Paid'
        FAILED = 'FAILED', 'Failed'

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='orders')
    deliver = models.ForeignKey(Deliver, on_delete=models.CASCADE, related_name='orders', null=True, blank=True)
    # Statuses 
    delivery_status = models.CharField(max_length=20, choices=DeliveryStatus.choices, default=DeliveryStatus.PENDING)
    payment_status = models.CharField(max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.PENDING)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)  
    updated_at = models.DateTimeField(auto_now=True)      

    location = models.PointField(srid=4326)
    street = models.ForeignKey(Street, on_delete=models.CASCADE, related_name='orders', null=True, blank=True)
    shop = models.ForeignKey(ShopVendor, on_delete=models.CASCADE, related_name='orders', null=True, blank=True)
    
    def __str__(self):
        return f"Order #{self.id} - Client: {self.client.user.username}"

    @property
    def total(self):
        """Calculates the total monetary value of the entire order by summing all items."""
        return sum(
            (item.quantity * item.price_at_purchase for item in self.items.all()), 
            Decimal('0.00')
        )


class OrderItem(models.Model):
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name="Order"
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name='order_items',
        verbose_name="Product"
    )
    quantity = models.PositiveIntegerField(
        default=1,
        verbose_name="Quantity"
    )
    price_at_purchase = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        verbose_name="Price at Purchase"
    )

    class Meta:
        verbose_name = "Order Item"
        verbose_name_plural = "Order Items"
        unique_together = ('order', 'product')

    def __str__(self):
        return f"{self.quantity} x {self.product.name} (Order #{self.order.id})"

    @property
    def total_price(self):
        """Calculates the total value of this specific order line."""
        return self.quantity * self.price_at_purchase

    def clean(self):
        """Validates that the selected product belongs to the order's designated shop."""
        super().clean()
        
        if self.order and self.product:
            if not self.order.shop_id:
                self.order.shop = self.product.shop
                self.order.save()
            
            elif self.product.shop_id != self.order.shop_id:
                raise ValidationError({
                    'product': f"This product belongs to '{self.product.shop}', "
                               f"but Order #{self.order.id} is tied to '{self.order.shop}'."
                })

    def save(self, *args, **kwargs):
        """Forces the validation logic to run during programmatic saves."""
        self.full_clean()
        super().save(*args, **kwargs)




# =========================================================
# Cart
# =========================================================
class Cart(models.Model):
    """
    A shopping cart.

    A cart is owned either by:
      - an authenticated Client (`client` is set), or
      - an anonymous guest (`guest_token` is set).

    Exactly one of the two must be present. Ownership is enforced via a
    CHECK constraint at the database level as well as `clean()`.

    Business rule: a cart may contain products from **one and only one
    shop**. The `shop` FK is populated lazily from the first `CartItem`
    added and then locked in.
    """

    # Owner — either `client` or `guest_token`, never both, never neither.
    client = models.ForeignKey(
        "Client",
        on_delete=models.CASCADE,
        related_name="carts",
        null=True,
        blank=True,
    )
    guest_token = models.UUIDField(
        null=True,
        blank=True,
        unique=True,
        default=None,
        editable=False,
        help_text="Anonymous cart identifier for unauthenticated users.",
    )

    # Single-shop rule: the shop this cart is bound to.
    shop = models.ForeignKey(
        "store.ShopVendor",
        on_delete=models.PROTECT,
        related_name="carts",
        null=True,
        blank=True,
        help_text="Populated from the first CartItem. Locked afterwards.",
    )

    # Optional delivery info captured during guest checkout.
    location = models.PointField(srid=4326, null=True, blank=True)
    street = models.ForeignKey(
        "store.Street",
        on_delete=models.SET_NULL,
        related_name="carts",
        null=True,
        blank=True,
    )

    # Timestamps + lifecycle
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(client__isnull=False, guest_token__isnull=True)
                    | models.Q(client__isnull=True, guest_token__isnull=False)
                ),
                name="cart_owner_xor_guest_token",
            ),
        ]
        indexes = [
            models.Index(fields=["guest_token"]),
            models.Index(fields=["client", "is_active"]),
        ]

    def __str__(self):
        owner = (
            f"client:{self.client.user.username}"
            if self.client_id
            else f"guest:{self.guest_token}"
        )
        return f"Cart #{self.id} ({owner})"

    # -----------------------------------------------------
    # Helpers
    # -----------------------------------------------------
    @property
    def total(self):
        """Sum of all item subtotals."""
        return sum(
            (item.quantity * item.price_at_purchase for item in self.items.all()),
            Decimal("0.00"),
        )

    @property
    def item_count(self):
        return self.items.count()

    def clean(self):
        super().clean()

        # Exactly one owner.
        if (self.client_id is None) == (self.guest_token is None):
            raise ValidationError(
                "A cart must have either a client or a guest_token, not both."
            )

        # If a shop is set and items exist, every item must match that shop.
        if self.pk and self.shop_id:
            offending = self.items.exclude(product__shop_id=self.shop_id)
            if offending.exists():
                raise ValidationError(
                    {"shop": "All cart items must belong to the cart's shop."}
                )

    def save(self, *args, **kwargs):
        # Assign a fresh guest token on first save if this is a guest cart.
        if self.client_id is None and self.guest_token is None:
            self.guest_token = uuid.uuid4()
        super().save(*args, **kwargs)

    # -----------------------------------------------------
    # Domain operations
    # -----------------------------------------------------
    def attach_to_client(self, client):
        """
        Claim a guest cart for an authenticated client.

        Called at login/registration: the guest cart's items are moved into
        the client's existing active cart, or the cart itself is reassigned
        if the client has no active cart yet.
        """
        if self.client_id is not None:
            raise ValidationError("Cart already belongs to a client.")

        existing = Cart.objects.filter(client=client, is_active=True).first()
        if existing is None:
            self.client = client
            self.guest_token = None
            self.save(update_fields=["client", "guest_token"])
            return self

        # Merge items — respect the single-shop rule.
        if existing.shop_id and self.shop_id and existing.shop_id != self.shop_id:
            raise ValidationError(
                "Cannot merge: the two carts belong to different shops."
            )

        for item in self.items.all():
            item.merge_into(existing)  # see CartItem.merge_into

        self.is_active = False
        self.save(update_fields=["is_active"])
        return existing


# =========================================================
# CartItem
# =========================================================
class CartItem(models.Model):
    """
    A single line inside a Cart.

    Mirrors OrderItem, but:
      - `order` is replaced with `cart`.
      - `price_at_purchase` is snapshotted from `product.price` at add
        time (so price changes don't retroactively change the cart).
      - `clean()` enforces the single-shop rule for the parent cart.
    """

    cart = models.ForeignKey(
        Cart,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="Cart",
    )
    product = models.ForeignKey(
        "store.Product",
        on_delete=models.PROTECT,
        related_name="cart_items",
        verbose_name="Product",
    )
    quantity = models.PositiveIntegerField(default=1, verbose_name="Quantity")
    price_at_purchase = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="Price at Purchase",
    )

    # Audit
    added_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Cart Item"
        verbose_name_plural = "Cart Items"
        unique_together = ("cart", "product")
        indexes = [
            models.Index(fields=["cart"]),
        ]

    def __str__(self):
        return f"{self.quantity} x {self.product.name} (Cart #{self.cart_id})"

    @property
    def total_price(self):
        return self.quantity * self.price_at_purchase

    def clean(self):
        super().clean()

        if not self.cart or not self.product:
            return

        # Single-shop rule: lock the cart's shop on first item, then enforce.
        if not self.cart.shop_id:
            self.cart.shop = self.product.shop
            self.cart.save(update_fields=["shop"])

        elif self.product.shop_id != self.cart.shop_id:
            raise ValidationError(
                {
                    "product": (
                        f"This product belongs to '{self.product.shop}', "
                        f"but Cart #{self.cart_id} is tied to "
                        f"'{self.cart.shop}'. A cart can only contain "
                        f"products from a single shop."
                    )
                }
            )

    def save(self, *args, **kwargs):
        # Snapshot price from product if this is a new item.
        if self._state.adding and self.product and not self.price_at_purchase:
            self.price_at_purchase = self.product.price

        self.full_clean()
        super().save(*args, **kwargs)

    # -----------------------------------------------------
    # Merge helper (used by Cart.attach_to_client)
    # -----------------------------------------------------
    def merge_into(self, target_cart):
        """
        Merge this item's quantity into `target_cart`.

        If the same product already exists in the target cart, sum the
        quantities; otherwise, re-parent the item.
        """
        if target_cart.shop_id and self.product.shop_id != target_cart.shop_id:
            raise ValidationError(
                "Cannot merge item: it belongs to a different shop."
            )

        existing = CartItem.objects.filter(
            cart=target_cart, product=self.product
        ).first()
        if existing:
            existing.quantity += self.quantity
            existing.save(update_fields=["quantity"])
            self.delete()
        else:
            self.cart = target_cart
            self.save(update_fields=["cart"])
