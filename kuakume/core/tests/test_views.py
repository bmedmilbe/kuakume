import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from .factories import UserFactory


@pytest.mark.django_db
class TestAuthentication:
    
    @pytest.mark.parametrize(
        "username, password, expected_status",
        [
            # Success case: Exact correct credentials with phone
            ("+2399912345", "password123", status.HTTP_200_OK),

            # Success case: Exact correct credentials with email
            ("test@test.com", "password123", status.HTTP_200_OK),
            
            # Failure case: Wrong password
            ("+2399912345", "wrongpassword", status.HTTP_401_UNAUTHORIZED),
            
            # Failure case: Missing payload elements (blank values)
            ("+2399912345", "", status.HTTP_400_BAD_REQUEST),
        ],
    )
    def test_login_with_email_or_phone(self, username, password, expected_status):
        #Arrange
        user = UserFactory(phone = "+2399912345",username=username, email="test@test.com", password="password123")
        client = APIClient()
        url = reverse("jwt-create")

        #Act
        response = client.post(url, data={"username":username, "password":password})

        #Assert
        assert user.username == username
        assert response.status_code == expected_status

        
    def test_not_login_if_non_exist_user(self):
        #Arrange
        client = APIClient()
        url = reverse("jwt-create")

        #Act
        response = client.post(url, data={"username":"+2399912345", "password":"password123"})

        #Assert
        assert response.status_code == status.HTTP_401_UNAUTHORIZED



