from django.apps import AppConfig


class ShoppingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'shopping'
    
    def ready(self):
        from shopping import signals  # noqa: F401