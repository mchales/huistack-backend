from django.conf import settings
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import (
    TokenBlacklistView,
    TokenObtainPairView,
    TokenRefreshView,
)
from social_core.exceptions import AuthException
from social_django.utils import load_backend, load_strategy
import requests

from .serializers import (
    CookieTokenBlacklistSerializer,
    CookieTokenRefreshSerializer,
    CookieTokenObtainPairSerializer,
    CustomUserSerializer,
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


class GoogleOAuthExchangeView(RefreshTokenCookieMixin, APIView):
    permission_classes = [AllowAny]
    GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'

    def post(self, request, *args, **kwargs):
        if not settings.SOCIAL_AUTH_GOOGLE_OAUTH2_KEY or not settings.SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET:
            return Response(
                {'detail': 'Google sign-in is not configured.'},
                status=status.HTTP_501_NOT_IMPLEMENTED,
            )

        code = request.data.get('code')
        redirect_uri = request.data.get('redirect_uri') or settings.GOOGLE_OAUTH_DEFAULT_REDIRECT_URI

        if not code:
            return Response(
                {'detail': 'Missing authorization code.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if redirect_uri not in settings.GOOGLE_OAUTH_ALLOWED_REDIRECTS:
            return Response(
                {'detail': 'redirect_uri is not allowed.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        token_data, error = self.exchange_code_for_tokens(code, redirect_uri)
        if error:
            return Response({'detail': error['detail']}, status=error['status'])

        access_token = token_data.get('access_token')
        if not access_token:
            return Response(
                {'detail': 'Google did not return an access token.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        strategy = load_strategy(request)
        backend = load_backend(strategy, 'google-oauth2', redirect_uri=redirect_uri)

        try:
            user = backend.do_auth(access_token, response=token_data)
        except AuthException as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        if not user or not user.is_active:
            return Response({'detail': 'Authentication failed.'}, status=status.HTTP_403_FORBIDDEN)

        refresh = RefreshToken.for_user(user)
        payload = {
            'access': str(refresh.access_token),
            'user': CustomUserSerializer(user, context={'request': request}).data,
            'provider': 'google',
        }

        response = Response(payload)
        self.set_refresh_cookie(response, str(refresh))
        return response

    def exchange_code_for_tokens(self, code, redirect_uri):
        data = {
            'code': code,
            'client_id': settings.SOCIAL_AUTH_GOOGLE_OAUTH2_KEY,
            'client_secret': settings.SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET,
            'redirect_uri': redirect_uri,
            'grant_type': 'authorization_code',
        }

        try:
            token_response = requests.post(
                self.GOOGLE_TOKEN_URL,
                data=data,
                timeout=settings.GOOGLE_OAUTH_TOKEN_TIMEOUT,
            )
        except requests.RequestException:
            return None, {
                'detail': 'Unable to reach Google. Try again.',
                'status': status.HTTP_503_SERVICE_UNAVAILABLE,
            }

        payload = token_response.json()
        if token_response.status_code != 200:
            detail = payload.get('error_description') or payload.get('error') or 'Code exchange failed.'
            return None, {'detail': detail, 'status': status.HTTP_400_BAD_REQUEST}

        return payload, None
