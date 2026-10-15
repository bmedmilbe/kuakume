from urllib.parse import parse_qs

from channels.auth import AuthMiddleware
from channels.db import database_sync_to_async
from channels.sessions import CookieMiddleware, SessionMiddleware
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.db import close_old_connections
from rest_framework_simplejwt.tokens import AccessToken

User = get_user_model()

@database_sync_to_async
def get_client_user(scope):
    """
    Decodes the JWT token from the query string and securely resolves 
    the user along with their active vendor profile in a synchronous thread.
    """
    close_old_connections()
    
    query_string = parse_qs(scope['query_string'].decode())
    token = query_string.get('token')
    if not token:
        return AnonymousUser()
        
    try:
        access_token = AccessToken(token[0])
        user_id = access_token['id'] 
        
        user = User.objects.select_related('clients').get(id=user_id)
    except Exception:
        return AnonymousUser()
        
    if not user.is_active:
        return AnonymousUser()
        
    try:
        client = user.clients
        if not client or not client.is_active:
            return AnonymousUser()
    except User.clients.RelatedObjectDoesNotExist:
        return AnonymousUser()
        
    return user


class ShoppingAuthMiddleware(AuthMiddleware):
    async def resolve_scope(self, scope):
        scope['user'] = await get_client_user(scope)


def ShoppingAuthMiddlewareStack(inner):
    return CookieMiddleware(SessionMiddleware(ShoppingAuthMiddleware(inner)))
