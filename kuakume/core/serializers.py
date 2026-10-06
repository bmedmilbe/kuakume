from django.contrib.auth import get_user_model
from djoser.serializers import UserCreateSerializer
from rest_framework import serializers

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

        