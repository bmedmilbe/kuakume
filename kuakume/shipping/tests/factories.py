import factory
from core.tests.factories import UserFactory
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import Point
from factory.django import DjangoModelFactory
from store.tests.factories import StoreUserFactory, StreetFactory

from ..models import Deliver, DeliverData

User = get_user_model()

class ShippingUserFactory(UserFactory):
    class Meta:
        model = User
        django_get_or_create = ['username', 'phone'] 


    phone = "+35945755755"
# =========================================================
# Deliver
# =========================================================
class DeliverFactory(DjangoModelFactory):
    class Meta:
        model = Deliver
        django_get_or_create = ['user'] 

    user = factory.SubFactory(StoreUserFactory)
    street = factory.SubFactory(StreetFactory)
    location = factory.LazyFunction(lambda: Point(0.0, 0.0, srid=4326))
    is_active = False


# =========================================================
# DeliverData
# =========================================================
class DeliverDataFactory(DjangoModelFactory):
    class Meta:
        model = DeliverData

    deliver = factory.SubFactory(DeliverFactory)
    street = factory.SubFactory(StreetFactory)

    full_name = factory.Faker("name")
    date_of_birth = factory.Faker("date_of_birth", minimum_age=18, maximum_age=65)
    residence = factory.Faker("address")

    document_number = factory.Sequence(lambda n: f"DOC-{n:08d}")

    id_front = factory.django.FileField(filename="id_front.png")
    id_back = factory.django.FileField(filename="id_back.png")
    verification_status = DeliverData.VerificationStatus.PENDING
    approved_at = None
    approved_by = None