from django.urls import path, include

app_name = 'lessons'

urlpatterns = [
    path('v1/', include(('apps.lessons.api.v1.urls', 'v1'), namespace='v1')),
]

