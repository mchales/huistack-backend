from django.conf import settings
from django.contrib.auth import get_user_model
from djoser.serializers import (
    UserCreateSerializer as BaseUserCreateSerializer,
    UserSerializer as BaseUserSerializer,
)
from rest_framework import serializers
from rest_framework_simplejwt.serializers import (
    TokenBlacklistSerializer,
    TokenRefreshSerializer,
    TokenObtainPairSerializer,
)

from apps.accounts.models import CustomUser

class CustomUserCreateSerializer(BaseUserCreateSerializer):
    class Meta(BaseUserCreateSerializer.Meta):
        model = CustomUser
        fields = ('id', 'username', 'email', 'first_name', 'last_name', 'password')

class CustomUserSerializer(BaseUserSerializer):
    class Meta(BaseUserSerializer.Meta):
        model = CustomUser
        fields = ('id', 'username', 'email', 'first_name', 'last_name')


class CookieTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Allow login with either username or email in the same field.

    If the incoming identifier matches a user by username, use it as-is.
    Otherwise, attempt case-insensitive email lookup and substitute the
    resolved username before delegating to the base validator.
    """

    email = serializers.EmailField(required=False)

    def validate(self, attrs):
        identifier_field = self.username_field  # typically 'username'
        identifier = attrs.get(identifier_field) or attrs.get('email')

        if identifier:
            User = get_user_model()
            user = None
            try:
                user = User.objects.get(username=identifier)
            except User.DoesNotExist:
                try:
                    user = User.objects.get(email__iexact=identifier)
                except User.DoesNotExist:
                    user = None

            if user is not None:
                attrs[identifier_field] = user.username

        return super().validate(attrs)


class CookieTokenRefreshSerializer(TokenRefreshSerializer):
    refresh = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        refresh = attrs.get('refresh')
        request = self.context.get('request')

        if not refresh and request is not None:
            cookie_name = settings.SIMPLE_JWT.get('REFRESH_TOKEN_COOKIE_NAME', 'refresh_token')
            refresh = request.COOKIES.get(cookie_name)

        if not refresh:
            raise serializers.ValidationError('Refresh token is missing.')

        attrs['refresh'] = refresh
        return super().validate(attrs)


class CookieTokenBlacklistSerializer(TokenBlacklistSerializer):
    refresh = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        refresh = attrs.get('refresh')
        request = self.context.get('request')

        if not refresh and request is not None:
            cookie_name = settings.SIMPLE_JWT.get('REFRESH_TOKEN_COOKIE_NAME', 'refresh_token')
            refresh = request.COOKIES.get(cookie_name)

        if not refresh:
            raise serializers.ValidationError('Refresh token is missing.')

        attrs['refresh'] = refresh
        return super().validate(attrs)
