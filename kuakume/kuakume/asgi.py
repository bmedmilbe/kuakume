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
from shipping.consumers import DeliverConsumer
from shipping.middleware import ShippingAuthMiddlewareStack
from shopping.consumers import ClientConsumer
from shopping.middleware import ShoppingAuthMiddlewareStack
from store.consumers import StoreConsumer
from store.middleware import VendorTokenAuthMiddlewareStack

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'kuakume.settings.dev')

application = ProtocolTypeRouter({
    'http': get_asgi_application(),
    'websocket': URLRouter([
        path(
            'ws/store/', 
            VendorTokenAuthMiddlewareStack(StoreConsumer.as_asgi())
        ),
        
        path(
            'ws/shipping/', 
            ShippingAuthMiddlewareStack(DeliverConsumer.as_asgi())
        ),
        path(
            'ws/shopping/', 
            ShoppingAuthMiddlewareStack(ClientConsumer.as_asgi())
        ),
    ]),
})

