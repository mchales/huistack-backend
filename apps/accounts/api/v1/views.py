from django.conf import settings
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework_simplejwt.views import (
    TokenBlacklistView,
    TokenObtainPairView,
    TokenRefreshView,
)

from .serializers import (
    CookieTokenBlacklistSerializer,
    CookieTokenRefreshSerializer,
    CookieTokenObtainPairSerializer,
)


@api_view(["GET"])
def get_routes(request):
    routes = {
        "Auth Endpoints": {
            "User Registration": "/api/v1/auth/users/",
            "User Login (JWT)": "/api/v1/auth/jwt/create/",
            "User Logout (JWT)": "/api/v1/auth/token/blacklist/",
            "Token Refresh": "/api/v1/auth/jwt/refresh/",
            "User Activation": "/api/v1/auth/users/activation/",
            "Password Reset": "/api/v1/auth/users/reset_password/",
            "Password Reset Confirm": "/api/v1/auth/users/reset_password_confirm/",
            "Resend Activation": "/api/v1/auth/users/resend_activation/",
            "Set New Password": "/api/v1/auth/users/set_password/",
            "User Profile": "/api/v1/auth/users/me/",
            "Delete User": "/api/v1/auth/users/{id}/",
            "User List (Admin)": "/api/v1/auth/users/",
            "User Detail (Admin)": "/api/v1/auth/users/{id}/",
        }
    }
    return Response(routes)


class RefreshTokenCookieMixin:
    """Common helpers for issuing and clearing refresh-token cookies."""

    @staticmethod
    def _cookie_conf():
        simple_jwt = settings.SIMPLE_JWT
        return {
            "name": simple_jwt.get("REFRESH_TOKEN_COOKIE_NAME", "refresh_token"),
            "path": simple_jwt.get("REFRESH_TOKEN_COOKIE_PATH", "/"),
            "domain": simple_jwt.get("REFRESH_TOKEN_COOKIE_DOMAIN"),
            "secure": simple_jwt.get("REFRESH_TOKEN_COOKIE_SECURE", True),
            "httponly": simple_jwt.get("REFRESH_TOKEN_COOKIE_HTTP_ONLY", True),
            "samesite": simple_jwt.get("REFRESH_TOKEN_COOKIE_SAMESITE", "None"),
            "max_age": int(simple_jwt["REFRESH_TOKEN_LIFETIME"].total_seconds()),
        }

    def set_refresh_cookie(self, response, refresh_token):
        conf = self._cookie_conf()
        response.set_cookie(
            key=conf["name"],
            value=refresh_token,
            max_age=conf["max_age"],
            path=conf["path"],
            domain=conf["domain"],
            secure=conf["secure"],
            httponly=conf["httponly"],
            samesite=conf["samesite"],
        )

    def clear_refresh_cookie(self, response):
        conf = self._cookie_conf()
        response.delete_cookie(
            conf["name"],
            path=conf["path"],
            domain=conf["domain"],
            samesite=conf["samesite"],
        )


class CookieTokenObtainPairView(RefreshTokenCookieMixin, TokenObtainPairView):
    serializer_class = CookieTokenObtainPairSerializer
    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        data = dict(response.data or {})
        refresh_token = data.get("refresh")
        if refresh_token:
            self.set_refresh_cookie(response, refresh_token)
            data.pop("refresh", None)
            response.data = data
        return response


class CookieTokenRefreshView(RefreshTokenCookieMixin, TokenRefreshView):
    serializer_class = CookieTokenRefreshSerializer

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        data = dict(response.data or {})
        refresh_token = data.get("refresh")
        if refresh_token:
            self.set_refresh_cookie(response, refresh_token)
            data.pop("refresh", None)
            response.data = data
        return response


class CookieTokenBlacklistView(RefreshTokenCookieMixin, TokenBlacklistView):
    serializer_class = CookieTokenBlacklistSerializer

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code < 400:
            self.clear_refresh_cookie(response)
        return response
