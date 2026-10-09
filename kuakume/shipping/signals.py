from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Deliver


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_vendor_per_user(sender, instance, created, **kwargs):
    if created:  
        Deliver.objects.create(user=instance)
