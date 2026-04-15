from django.db import models


class Snapshot(models.Model):
    page = models.ForeignKey("Page", on_delete=models.CASCADE, related_name="snapshots")

    created_at = models.DateTimeField(auto_now_add=True)

    html_content = models.TextField(default="")
    md_content = models.TextField(default="")

    def __str__(self):
        return f"{self.page.url} - {self.created_at}"


class Question(models.Model):
    """Question."""

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
    url = models.URLField(unique=True)
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

    created_at = models.DateTimeField(auto_now_add=True)

    last_checked_at = models.DateTimeField(null=True)

    def __str__(self):
        return self.url

    @property
    def latest_snapshot(self) -> Snapshot | None:
        return self.snapshots.order_by("-created_at").first()
