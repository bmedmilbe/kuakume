import pytest
from django.core.exceptions import ValidationError

from core.models import User
from core.tests.factories import UserFactory


@pytest.mark.django_db
class TestCoreModels:
    def test_create_new_user(self):
        # Given
        user = UserFactory.build(phone = "+2399912345")

        # Act
        user.save()
        users_count = User.objects.count()

        # Then
        assert users_count == 1
        assert user.phone is not None
    

    def test_create_new_user_wrong_number(self):
        # Given
        user = UserFactory.build(phone="9882053")
        

        # Act & Then
        with pytest.raises(ValidationError):
            user.save()

    def test_not_create_without_phone(self):
        # Given
        user = UserFactory.build(email="test@test.com")
        
    
        # Act & Then
        with pytest.raises(ValidationError):
            user.save()
            
    def test_create_new_user_no_data(self):
        # Given
        data = {}

        # Act & Then
        with pytest.raises(ValidationError):
            User.objects.create(**data)

    def test_not_accept_duplicated_email(self):
        # Given
        user = UserFactory(phone = "+2399912345", email="test@test.com")
        user = UserFactory.build(phone = "+23999123745", email="test@test.com")
        
        
        # Act & Then
        with pytest.raises(ValidationError):
            user.save()


    def test_not_accept_duplicated_phone(self):
        # Given
        user = UserFactory(phone = "+2399912345" )
        user = UserFactory.build(phone = "+2399912345")
        
        
        # Act & Then
        with pytest.raises(ValidationError):
            user.save()

    def test_not_accept_duplicated_username(self):
            # Given
            user = UserFactory(phone = "+2399912345", username = "+2399912345" )
            user = UserFactory.build(phone = "+2399912345", username = "+2399912345")
            
            
            # Act & Then
            with pytest.raises(ValidationError):
                user.save()