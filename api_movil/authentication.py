from rest_framework.authentication import TokenAuthentication


class BearerTokenAuthentication(TokenAuthentication):
    """Token DRF para Android usando Authorization: Bearer <token>."""
    keyword = "Bearer"
