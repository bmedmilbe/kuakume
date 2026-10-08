import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from .factories import UserFactory

User = get_user_model()

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



@pytest.mark.django_db
class TestUserCreationAPI:

    @pytest.mark.parametrize(
        "payload, expected_email",
        [
            # Case 1: Email is omitted (Optional check)
            (
                {
                    "first_name": "John",
                    "last_name": "Doe",
                    "username": "johndoe123",
                    "phone": "+4475836648484",
                    "password": "SecurePassword123!",
                },
                None,  # Defaults to an empty string in Django if omitted
            ),
            # Case 2: Email is provided
            (
                {
                    "first_name": "Jane",
                    "last_name": "Smith",
                    "username": "janesmith456",
                    "phone": "+4475836648485",
                    "password": "AnotherSecurePassword123!",
                    "email": "jane.smith@example.com",
                },
                "jane.smith@example.com",
            ),
        ],
    )
    def test_create_user_success_variants(
        self, payload, expected_email
    ):
        """Validates that both missing and filled optional email schemas create users cleanly."""
        api_client = APIClient()
        user_create_url = reverse("user-list")
        response = api_client.post(user_create_url, payload, format="json")

        # Assert correct HTTP status code (201 Created)
        assert response.status_code == status.HTTP_201_CREATED

        # Assert user actually saved to database
        user = User.objects.get(username=payload["username"])
        assert user.email == expected_email

        # Assert response details mapping correctly
        response_data = response.data
        assert response_data["username"] == payload["username"]
        assert response_data["first_name"] == payload["first_name"]
        assert response_data["last_name"] == payload["last_name"]
        assert "password" not in response_data  # Passwords must never leak

    @pytest.mark.parametrize(
        "incomplete_payload, expected_error_fields",
        [
            # Missing username & password
            (
                {
                    "first_name": "No",
                    "last_name": "Credentials",
                    "phone": "+4475836648486",
                },
                ["username", "password"],
            ),
            # Missing username only
            (
                {
                    "first_name": "No",
                    "last_name": "Username",
                    "phone": "+4475836648487",
                    "password": "PasswordOnly123!",
                },
                ["username"],
            ),
            # Missing password only
            (
                {
                    "first_name": "No",
                    "last_name": "Password",
                    "username": "nopasswordguy",
                    "phone": "+4475836648488",
                },
                ["password"],
            ),
        ],
    )
    def test_create_user_missing_required_fields_fails(
        self, incomplete_payload, expected_error_fields
    ):
        """Validates API schema validation errors on required credential items."""
        api_client = APIClient()
        user_create_url = reverse("user-list")
        response = api_client.post(
            user_create_url, incomplete_payload, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        for field in expected_error_fields:
            assert field in response.data


