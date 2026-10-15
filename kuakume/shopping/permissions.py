from rest_framework import permissions


class IsClientActive(permissions.BasePermission):
    """
    Allows access only to authenticated users who have an active vendor profile.
    """
   
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
            
        client = getattr(request.user, 'clients', None)
        
        return bool(client and client.is_active)
