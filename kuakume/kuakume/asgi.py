"""
ASGI config for kuakume project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os

from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application
from django.urls import path
from store.consumers import StoreConsumer
from store.middleware import VendorTokenAuthMiddlewareStack

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'kuakume.settings.dev')

application = ProtocolTypeRouter({
    'http': get_asgi_application(),
    'websocket': VendorTokenAuthMiddlewareStack(
        URLRouter([
        path('ws/store/', StoreConsumer.as_asgi()),
    ])),
})

