
from .common import *

SECURE_SSL_REDIRECT = True          # redireciona HTTP → HTTPS
SESSION_COOKIE_SECURE = True        # cookie só via HTTPS
CSRF_COOKIE_SECURE = True           # idem
SECURE_HSTS_SECONDS = 31536000      # força HTTPS por 1 ano
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")  # atrás de proxy