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
