import os

import dj_database_url

from .common import *

DATABASE_URL = 'postgresql://postgres:postgres@kuakumedb:5432/kuakume'

DATABASES = {
    'default': dj_database_url.config(
        default=DATABASE_URL,
        conn_max_age=600,
        conn_health_checks=True
    )
}

DATABASES['default']['ENGINE'] = 'django.contrib.gis.db.backends.postgis'

REDIS_URL = os.environ.get('REDIS_URL', 'redis://kuakume-redis:6379')
CHANNEL_LAYERS= {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer',
    },
}

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache"
    }
}