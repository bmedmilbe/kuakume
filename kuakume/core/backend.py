from django.contrib.auth import get_user_model
from django.contrib.auth.backends import BaseBackend
from django.contrib.auth.hashers import check_password
from django.db.models import Q

User = get_user_model()

class BackendWithPhoneOrEmailOrUsername(BaseBackend):
    def authenticate(self, request, username=None, password=None):
        try:
            user = User.objects.get(Q(email=username)|Q(phone=username)|Q(username=username))
            if check_password(password,user.password):
                return user
        except User.DoesNotExist:
            pass
        return None


    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None

    
