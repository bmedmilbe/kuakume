from django.contrib.auth import get_user_model
from djoser.serializers import (
    UserCreateSerializer,
    UserSerializer,
)
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

User = get_user_model()
class UserCreateSerializer(UserCreateSerializer):
    email = serializers.CharField(allow_null=True, required=False)

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'username','phone', 'password', 'email']

    def create(self, validated_data):
        user = User.objects.create(**validated_data)
        user.set_password(validated_data['password'])
        user.save()
        return user


class UserSerializer(UserSerializer):
    is_vendor_active = serializers.SerializerMethodField()
    is_client_active = serializers.SerializerMethodField()
    is_deliver_active = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 
            'first_name', 
            'last_name', 
            'is_vendor_active', 
            'is_client_active', 
            'is_deliver_active'
        ]

    def get_is_vendor_active(self, obj):
        vendor = getattr(obj, 'vendor_user', None)
        return bool(vendor and vendor.is_active)

    def get_is_client_active(self, obj):
        client = getattr(obj, 'clients', None)
        return bool(client and client.is_active)

    def get_is_deliver_active(self, obj):
        deliver = getattr(obj, 'delivery_profile', None)
        return bool(deliver and deliver.is_active)

    
class TokenCreateSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        user_data = UserSerializer(user).data
        for key, value in user_data.items():
            if key != 'id':
                token[key] = value
        return token



        