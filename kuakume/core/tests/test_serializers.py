
import pytest

from core.serializers import UserCreateSerializer


@pytest.mark.django_db
def test_successfully_create_user():
    data = {
        "first_name": "John",
        "last_name": "Doe",
        "username": "johndoe123",
        "phone": "+4475836648484",
        "password": "SecurePassword123!",
    }

    serializer = UserCreateSerializer(data=data)

    assert serializer.is_valid() is True
    
    user = serializer.save()

    assert user.first_name == data['first_name']
    assert user.last_name == data['last_name']
    assert user.username == data['username']
    assert user.phone == data['phone']
    
    assert user.check_password(data['password']) is True


test_data = [
        {
            "first_name": "John",
            "last_name": "Doe",
            "username": "johndoe123",
            "password": "SecurePassword123!",
        },
        {
            "first_name": "John",
            "last_name": "Doe",
            "phone": "+4475836648484",
            "password": "SecurePassword123!",
        },
        {
            "last_name": "Doe",
            "username": "johndoe123",
            "phone": "+4475836648484",
            "password": "SecurePassword123!",
        },
        {
            "first_name": "John",
            "username": "johndoe123",
            "phone": "+4475836648484",
            "password": "SecurePassword123!",
        },
        {
            "first_name": "John",
            "last_name": "Doe",
            "username": "johndoe123",
            "phone": "+4475836648484",
        },
        {}
]

@pytest.mark.django_db
@pytest.mark.parametrize("payload", test_data)
def test_do_not_create_user_with_invalid_data(payload):

    serializer = UserCreateSerializer(data=payload)

    assert serializer.is_valid() is False
