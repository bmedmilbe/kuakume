import factory
from django.contrib.auth.hashers import make_password
from factory.django import DjangoModelFactory

from core.models import User


class UserFactory(DjangoModelFactory):
    class Meta:
        model = User
        
    password = "password123"
    first_name = "First"
    last_name = "Last"
    username = factory.Sequence(lambda n: f"user_{n}")

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        """Intercepts creation to hash the raw password string before saving."""
        password = kwargs.get("password")
        if password:
            kwargs["password"] = make_password(password)
        return super()._create(model_class, *args, **kwargs)

    
