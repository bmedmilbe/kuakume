import pytest
from django.core.exceptions import ValidationError

from core.models import User
from core.tests.factories import UserFactory


@pytest.mark.django_db
class TestCoreModels:
    def test_create_new_user(self):
        # Given
        user = UserFactory.build()

        # Act
        user.save()
        users_count = User.objects.count()

        # Then
        assert users_count == 1
        assert user.phone is not None

    def test_create_new_user_wrong_number(self):
        # Given
        data = {
            "phone": "9882053",
            "username": "9882053",
            "password": "password123",
        }

        # Act & Then
        with pytest.raises(ValidationError):
            User.objects.create(**data)

    def test_create_new_user_no_data(self):
        # Given
        data = {}

        # Act & Then
        with pytest.raises(ValidationError):
            User.objects.create(**data)