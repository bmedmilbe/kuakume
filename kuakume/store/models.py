from django.conf import settings
from django.contrib.gis.db import models


class Vendor(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='vendor_user')
    account_number_pt = models.CharField(max_length=50, blank=True, null=True)
    account_number_stp = models.CharField(max_length=50, blank=True, null=True)
    account_name_pt = models.CharField(max_length=100, blank=True, null=True)
    account_name_stp = models.CharField(max_length=100, blank=True, null=True)
    is_active = models.BooleanField(default=False)
    def __str__(self):
        return f"Vendor: {self.user.phone}"
    
class District(models.Model):
    name = models.CharField(max_length=255)
    city_name = models.CharField(max_length=255)
    
class Street(models.Model):
    name = models.CharField(max_length=255, unique=True)
    district = models.ForeignKey(District, on_delete=models.CASCADE, related_name='street')    

class ShopVendor(models.Model):
    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name='shops')
    street = models.ForeignKey(Street, on_delete=models.CASCADE, related_name='shops')
    location = models.PointField(srid=4326)
    contact_number = models.CharField(max_length=20)

    def __str__(self):
        return f"Shop of {self.vendor.user.username}"

class Category(models.Model):
    name = models.CharField(max_length=255)
    icon = models.CharField(max_length=255, null=True, blank=True)
    picture = models.FileField(upload_to='kuakume/category')

class Product(models.Model):
    shop = models.ForeignKey(ShopVendor, on_delete=models.CASCADE, related_name='products')
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='products')
    name = models.CharField(max_length=255)
    price = models.DecimalField(max_digits=10, decimal_places=2)  

    def __str__(self):
        return self.name

class ProductImages(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='product_images')
    picture = models.FileField(upload_to='kuakume/products')

    def __str__(self):
        return self.product.name

class Content(models.Model):
    name = models.CharField(max_length=255, unique=True)

class ProductContent(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    content = models.ForeignKey(Content, on_delete=models.CASCADE)

    class Meta:
        unique_together = ('product', 'content')

    def __str__(self):
        return f"{self.product.name} - {self.content.name}"

