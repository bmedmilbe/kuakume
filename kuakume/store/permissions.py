from rest_framework import permissions


class IsVendorActive(permissions.BasePermission):
    """
    Allows access only to authenticated users who have an active vendor profile.
    """
   
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
            
        vendor = getattr(request.user, 'vendor_user', None)
        
        return bool(vendor and vendor.is_active)
