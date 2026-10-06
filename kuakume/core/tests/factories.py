import factory
from factory.django import DjangoModelFactory

from core.models import User


class UserFactory(DjangoModelFactory):
    class Meta:
        model = User
        django_get_or_create = ["phone"]

    phone = "+2399912345"
    password = "password123"
    first_name = "First"
    last_name = "Last"
    username = factory.Sequence(lambda n: f"user_{n}")
    
