from django.contrib import admin
from django.urls import include, path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from .views import ApiRootView, HealthView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("auth/token", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("auth/token/refresh", TokenRefreshView.as_view(), name="token_refresh"),
    path("", include("appointments.urls")),
    path("", ApiRootView.as_view(), name="api-root"),
    path("health", HealthView.as_view(), name="health"),
]
