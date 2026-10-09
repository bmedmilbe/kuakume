from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Client


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_vendor_per_user(sender, instance, created, **kwargs):
    if created:  
        Client.objects.create(user=instance)
