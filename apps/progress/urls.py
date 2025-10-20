from django.urls import path, include

app_name = 'progress'

urlpatterns = [
    path('v1/', include(('apps.progress.api.v1.urls', 'v1'), namespace='v1')),
]

