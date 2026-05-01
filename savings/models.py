"""Domain models for savings goals, pro-rata distribution, and group registry."""

from decimal import Decimal

from django.conf import settings
from django.db import models


class SavingsScope(models.TextChoices):
    """Personal vs shared family bucket (matches UI toggle)."""

    PERSONAL = "PERSONAL", "Personal"
    FAMILY = "FAMILY", "Family"


class SavingsAsset(models.Model):
    """Savings goal / asset with weight for pro-rata distribution."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="savings_assets",
    )
    scope = models.CharField(
        max_length=16,
        choices=SavingsScope.choices,
        db_index=True,
    )
    name = models.CharField(max_length=255)
    weight = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        default=Decimal("1"),
        help_text="Relative weight for pro-rata allocation among selected assets.",
    )
    current_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0"),
    )
    target_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0"),
    )
    currency = models.CharField(
        max_length=3,
        default="CLP",
        help_text="ISO 4217 currency code (e.g. CLP).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("scope", "name", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("owner", "scope", "name"),
                name="savings_asset_owner_scope_name_uniq",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.scope}) owner={self.owner_id}"


class DistributionSession(models.Model):
    """One pro-rata sync / group registry row (budget applied across assets)."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="savings_distribution_sessions",
    )
    scope = models.CharField(
        max_length=16,
        choices=SavingsScope.choices,
        db_index=True,
    )
    budget_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        help_text="Total amount distributed in this session (signed).",
    )
    currency = models.CharField(max_length=3, default="CLP")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-id")

    def __str__(self) -> str:
        return (
            f"DistributionSession({self.budget_amount} {self.currency} "
            f"{self.scope} owner={self.owner_id})"
        )


class DistributionLine(models.Model):
    """Per-asset slice for a session; snapshots survive asset edits/deletes."""

    session = models.ForeignKey(
        DistributionSession,
        on_delete=models.CASCADE,
        related_name="lines",
    )
    asset = models.ForeignKey(
        SavingsAsset,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="distribution_lines",
    )
    asset_name_snapshot = models.CharField(max_length=255)
    weight_snapshot = models.DecimalField(max_digits=12, decimal_places=4)
    selected = models.BooleanField(default=True)
    share_percent = models.DecimalField(
        max_digits=7,
        decimal_places=4,
        help_text="Percent of selected weight total (0–100).",
    )
    allocated_amount = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        ordering = ("id",)

    def __str__(self) -> str:
        return (
            f"DistributionLine({self.asset_name_snapshot!r} "
            f"{self.allocated_amount} session={self.session_id})"
        )
