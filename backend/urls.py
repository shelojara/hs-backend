"""
URL configuration for backend project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import path
from ninja import NinjaAPI

from manga.drive_oauth_admin_views import google_drive_oauth_callback, google_drive_oauth_start
from manga.drive_picker_admin_views import google_drive_picker_token

api = NinjaAPI()

api.add_router("", "auth.api_v1.router")
api.add_router("", "pagechecker.api_v1.router")
api.add_router("", "groceries.api_v1.router")
api.add_router("", "savings.api_v1.router")
api.add_router("", "manga.api_v1.router")


urlpatterns = [
    path(
        "admin/manga/googledriveoauth/start/",
        google_drive_oauth_start,
        name="admin_manga_gdrive_oauth_start",
    ),
    path(
        "admin/manga/googledriveoauth/callback/",
        google_drive_oauth_callback,
        name="admin_manga_gdrive_oauth_callback",
    ),
    path(
        "admin/manga/googledriveoauth/picker-token/",
        google_drive_picker_token,
        name="admin_manga_gdrive_picker_token",
    ),
    path("admin/", admin.site.urls),
    path("api/", api.urls),
]
