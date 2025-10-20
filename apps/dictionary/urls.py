from django.urls import path, include

app_name = 'dictionary'

urlpatterns = [
    path('v1/', include(('apps.dictionary.api.v1.urls', 'v1'), namespace='v1')),
]

