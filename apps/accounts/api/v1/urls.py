from django.urls import path, include

from .views import (
    CookieTokenBlacklistView,
    CookieTokenObtainPairView,
    CookieTokenRefreshView,
    GoogleOAuthExchangeView,
    get_routes,
)

urlpatterns = [
    path('auth/jwt/create/', CookieTokenObtainPairView.as_view(), name='jwt-create'),
    path('auth/jwt/refresh/', CookieTokenRefreshView.as_view(), name='jwt-refresh'),
    path('auth/token/blacklist/', CookieTokenBlacklistView.as_view(), name='token_blacklist'),
    path('auth/', include('djoser.urls')),
    path('auth/social/google/', GoogleOAuthExchangeView.as_view(), name='google-login'),
    path('auth/routes/', get_routes, name='routes'),
]
