from django.db import models


def normalize_manga_hidden_rel_path(raw: str) -> str:
    """POSIX-style path under manga root: no leading slash, no empty segments, no '..' left."""
    s = (raw or "").strip().replace("\\", "/").strip("/")
    parts: list[str] = []
    for p in s.split("/"):
        if not p or p == ".":
            continue
        if p == "..":
            if parts:
                parts.pop()
            continue
        parts.append(p)
    return "/".join(parts)


class MangaHiddenDirectory(models.Model):
    """Directory path (relative to manga root) excluded from ListMangaDirectories tree."""

    rel_path = models.CharField(
        max_length=1024,
        unique=True,
        help_text="Path under manga root using forward slashes, e.g. archive/old or Series Name",
    )

    class Meta:
        ordering = ("rel_path",)
        verbose_name = "hidden manga directory"
        verbose_name_plural = "hidden manga directories"

    def clean(self) -> None:
        from django.core.exceptions import ValidationError

        n = normalize_manga_hidden_rel_path(self.rel_path)
        if not n:
            raise ValidationError({"rel_path": "Enter a non-empty path (no ..-only segments)."})
        self.rel_path = n

    def save(self, *args, **kwargs) -> None:
        self.rel_path = normalize_manga_hidden_rel_path(self.rel_path)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.rel_path
