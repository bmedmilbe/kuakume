from django.conf import settings
from django.contrib.gis.db import models

# ==========================================
# CUSTOM MANAGERS & QUERYSETS FOR OPTIMISATION
# ==========================================

class VendorQuerySet(models.QuerySet):
    def get_queryset(self):
        # Prefetches the reverse 'shops' relationship and its deep relations
        return super().get_queryset().select_related('user').prefetch_related(
            'shops__street__district',
            'shops__products__product_images'
        )

class DistrictQuerySet(models.QuerySet):
    def get_queryset(self):
        # Prefetches reverse 'street' and down to products
        return super().get_queryset().prefetch_related(
            'street__shops__products'
        )

class StreetQuerySet(models.QuerySet):
    def get_queryset(self):
        return super().get_queryset().select_related('district').prefetch_related(
            'shops__products'
        )

class ShopVendorQuerySet(models.QuerySet):
    def get_queryset(self):
        # Prefetches reverse 'products' relationship and nested images/content
        return super().get_queryset().select_related(
            'vendor__user', 
            'street__district'
        ).prefetch_related(
            'products__product_images',
            'products__category'
        )

class ProductQuerySet(models.QuerySet):
    def get_queryset(self):
        # Resolves N+1 for multi-table relationships (images and contents)
        return super().get_queryset().select_related(
            'shop__vendor__user', 
            'shop__street__district', 
            'category'
        ).prefetch_related(
            'product_images',
            'productcontent_set__content'  # Accesses the intermediate M2M table
        )

class ProductImagesQuerySet(models.QuerySet):
    def get_queryset(self):
        return super().get_queryset().select_related(
            'product__shop__vendor__user',
            'product__category'
        )

class ProductContentQuerySet(models.QuerySet):
    def get_queryset(self):
        return super().get_queryset().select_related(
            'product__shop__vendor__user', 
            'product__category', 
            'content'
        )

# ==========================================
# REFACTORED MODELS
# ==========================================

class Vendor(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='vendor_user')
    account_number_pt = models.CharField(max_length=50, blank=True, null=True)
    account_number_stp = models.CharField(max_length=50, blank=True, null=True)
    account_name_pt = models.CharField(max_length=100, blank=True, null=True)
    account_name_stp = models.CharField(max_length=100, blank=True, null=True)
    is_active = models.BooleanField(default=False)

    objects = VendorQuerySet.as_manager()

    def __str__(self):
        return f"Vendor: {self.user.phone}"
    
class District(models.Model):
    name = models.CharField(max_length=255)
    city_name = models.CharField(max_length=255)
    
    objects = DistrictQuerySet.as_manager()
    
class Street(models.Model):
    name = models.CharField(max_length=255, unique=True)
    district = models.ForeignKey(District, on_delete=models.CASCADE, related_name='street')    

    objects = StreetQuerySet.as_manager()

class ShopVendor(models.Model):
    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name='shops')
    street = models.ForeignKey(Street, on_delete=models.CASCADE, related_name='shops')
    location = models.PointField(srid=4326)
    contact_number = models.CharField(max_length=20)

    objects = ShopVendorQuerySet.as_manager()

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

    objects = ProductQuerySet.as_manager()

    def __str__(self):
        return self.name

class ProductImages(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='product_images')
    picture = models.FileField(upload_to='kuakume/products')

    objects = ProductImagesQuerySet.as_manager()

    def __str__(self):
        return self.product.name

class Content(models.Model):
    name = models.CharField(max_length=255, unique=True)

class ProductContent(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    content = models.ForeignKey(Content, on_delete=models.CASCADE)

    objects = ProductContentQuerySet.as_manager()

    class Meta:
        unique_together = ('product', 'content')

    def __str__(self):
        return f"{self.product.name} - {self.content.name}"
