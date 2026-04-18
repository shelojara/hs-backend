from django.db import models
from django.utils import timezone


class Product(models.Model):
    name = models.CharField(max_length=255)
    last_bought_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name

    @property
    def time_since_last_bought(self):
        """Duration since last purchase, or None if never bought."""
        if self.last_bought_at is None:
            return None
        return timezone.now() - self.last_bought_at
