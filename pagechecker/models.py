from django.conf import settings
from django.db import models


class ApiKey(models.Model):
    """API key credential for authenticating API requests."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="api_keys",
    )
    # Public prefix for indexed lookup; full secret never stored.
    key_prefix = models.CharField(max_length=32, unique=True, db_index=True)
    # bcrypt hash of full secret; verify with bcrypt.checkpw.
    key_hash = models.CharField(max_length=128, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"ApiKey({self.key_prefix}…) user={self.user_id}"


class ReportInterval(models.TextChoices):
    DAILY = "DAILY", "Daily"
    WEEKLY = "WEEKLY", "Weekly"
    MONTHLY = "MONTHLY", "Monthly"


class Snapshot(models.Model):
    page = models.ForeignKey("Page", on_delete=models.CASCADE, related_name="snapshots")

    created_at = models.DateTimeField(auto_now_add=True)

    html_content = models.TextField(default="")
    md_content = models.TextField(default="")
    feature = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"{self.page.url} - {self.created_at}"


class Question(models.Model):
    """Question."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="questions",
    )
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return self.text[:80] + ("…" if len(self.text) > 80 else "")


class Category(models.Model):
    name = models.TextField()
    emoji = models.CharField(max_length=64)

    def __str__(self) -> str:
        return self.name


class Page(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="pages",
    )
    url = models.URLField()
    title = models.CharField(max_length=512, blank=True, default="")
    icon = models.URLField(max_length=2048, blank=True, default="")

    category = models.ForeignKey(
        Category,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="pages",
    )

    questions = models.ManyToManyField(
        "Question",
        related_name="pages",
        blank=True,
    )

    highlighted_question = models.ForeignKey(
        "Question",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="highlighted_on_pages",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    last_checked_at = models.DateTimeField(null=True)

    report_interval = models.CharField(
        max_length=16,
        choices=ReportInterval.choices,
        null=True,
        blank=True,
    )

    feature_instruction = models.TextField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("owner", "url"),
                name="pagechecker_page_owner_url_uniq",
            ),
        ]

    def __str__(self):
        return self.url

    @property
    def latest_snapshot(self) -> Snapshot | None:
        return self.snapshots.order_by("-created_at").first()
