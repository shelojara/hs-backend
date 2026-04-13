from django.db import models


class Snapshot(models.Model):
    page = models.ForeignKey("Page", on_delete=models.CASCADE, related_name="snapshots")

    created_at = models.DateTimeField(auto_now_add=True)

    content = models.TextField()
    html_content = models.TextField(default="")
    features = models.JSONField(default=list)
    content_insights = models.JSONField(default=dict)

    def __str__(self):
        return f"{self.page.url} - {self.created_at}"


class Page(models.Model):
    url = models.URLField(unique=True)
    title = models.CharField(max_length=512, blank=True, default="")
    icon = models.URLField(max_length=2048, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    last_checked_at = models.DateTimeField(null=True)

    def __str__(self):
        return self.url

    @property
    def latest_snapshot(self) -> Snapshot | None:
        return self.snapshots.order_by("-created_at").first()
