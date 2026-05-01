"""Domain models for savings goals, pro-rata distribution, and group registry."""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class SavingsScope(models.TextChoices):
    """Personal vs shared family bucket (matches UI toggle)."""

    PERSONAL = "PERSONAL", "Personal"
    FAMILY = "FAMILY", "Family"


class AssetState(models.TextChoices):
    """Lifecycle for savings goals."""

    ACTIVE = "ACTIVE", "Active"
    COMPLETED = "COMPLETED", "Completed"


class Family(models.Model):
    """Shared savings bucket for multiple users (family scope)."""

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="savings_families_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "families"

    def __str__(self) -> str:
        return f"Family #{self.pk}"


class FamilyMembership(models.Model):
    """User belongs to a family (shared access to FAMILY-scoped savings rows)."""

    family = models.ForeignKey(
        Family,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="savings_family_memberships",
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("family", "user"),
                name="savings_family_membership_uniq",
            ),
            models.UniqueConstraint(
                fields=("user",),
                name="savings_family_membership_one_per_user",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.user_id is None:
            return
        qs = FamilyMembership.objects.filter(user_id=self.user_id)
        if self.pk is not None:
            qs = qs.exclude(pk=self.pk)
        other = qs.select_related("family").first()
        if other is not None:
            raise ValidationError(
                {
                    "user": (
                        "Each user may belong to only one family. This user is "
                        f"already in family #{other.family_id}."
                    )
                }
            )

    def __str__(self) -> str:
        return f"FamilyMembership(family={self.family_id} user={self.user_id})"


class Asset(models.Model):
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
    family = models.ForeignKey(
        Family,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="savings_assets",
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
        null=True,
        blank=True,
    )
    currency = models.CharField(
        max_length=3,
        default="CLP",
        help_text="ISO 4217 currency code (e.g. CLP).",
    )
    emoji = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Display emoji for this goal (often suggested via Gemini).",
    )
    state = models.CharField(
        max_length=16,
        choices=AssetState.choices,
        default=AssetState.ACTIVE,
        db_index=True,
        help_text="Completed goals are excluded from new distributions and rush transfers.",
    )
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the goal was marked completed (null while active).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("scope", "name", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("owner", "name"),
                condition=models.Q(scope=SavingsScope.PERSONAL),
                name="savings_asset_personal_owner_name_uniq",
            ),
            models.UniqueConstraint(
                fields=("family", "name"),
                condition=models.Q(scope=SavingsScope.FAMILY),
                name="savings_asset_family_name_uniq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(scope=SavingsScope.PERSONAL, family__isnull=True)
                    | models.Q(scope=SavingsScope.FAMILY, family__isnull=False)
                ),
                name="savings_asset_scope_family_consistent",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.scope}) owner={self.owner_id}"


class Distribution(models.Model):
    """One pro-rata sync / group registry row (budget applied across assets)."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="savings_distributions",
    )
    scope = models.CharField(
        max_length=16,
        choices=SavingsScope.choices,
        db_index=True,
    )
    family = models.ForeignKey(
        Family,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="distributions",
    )
    budget_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        help_text="Total amount distributed in this run (signed).",
    )
    currency = models.CharField(max_length=3, default="CLP")
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-id")
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(scope=SavingsScope.PERSONAL, family__isnull=True)
                    | models.Q(scope=SavingsScope.FAMILY, family__isnull=False)
                ),
                name="savings_distribution_scope_family_consistent",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"Distribution({self.budget_amount} {self.currency} "
            f"{self.scope} owner={self.owner_id})"
        )


class DistributionLine(models.Model):
    """Per-asset allocation for a distribution."""

    distribution = models.ForeignKey(
        Distribution,
        on_delete=models.CASCADE,
        related_name="lines",
    )
    asset = models.ForeignKey(
        Asset,
        on_delete=models.PROTECT,
        related_name="distribution_lines",
    )
    allocated_amount = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        ordering = ("id",)

    def __str__(self) -> str:
        return (
            f"DistributionLine(asset={self.asset_id} amount={self.allocated_amount} "
            f"distribution={self.distribution_id})"
        )
