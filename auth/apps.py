from django.apps import AppConfig


class AuthConfig(AppConfig):
    """API JWT login; label must differ from django.contrib.auth."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "auth"
    label = "jwt_auth"
