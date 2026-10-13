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

    class Meta:
        model = User
        fields = ['id','first_name', 'last_name', 'username']

    
class TokenCreateSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        user_data = UserSerializer(user).data
        for key, value in user_data.items():
            if key != 'id':
                token[key] = value
        return token



        