"""Backfill title and icon for existing pages using their latest snapshot HTML."""

from urllib.parse import urljoin

from django.db import migrations

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None


def _extract_metadata(html: str, page_url: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")

    title = ""
    og_title = soup.find("meta", attrs={"property": "og:title"})
    if og_title and og_title.get("content"):
        title = og_title["content"].strip()
    elif soup.title and soup.title.string:
        title = soup.title.string.strip()

    icon = ""
    for rel in (["icon"], ["shortcut", "icon"], ["apple-touch-icon"]):
        link = soup.find("link", rel=rel)
        if link and link.get("href"):
            icon = urljoin(page_url, link["href"])
            break

    if not icon:
        icon = urljoin(page_url, "/favicon.ico")

    return {"title": title, "icon": icon}


def backfill_title_icon(apps, schema_editor):
    if BeautifulSoup is None:
        return

    Page = apps.get_model("pagechecker", "Page")
    Snapshot = apps.get_model("pagechecker", "Snapshot")

    for page in Page.objects.filter(title="", icon=""):
        snapshot = (
            Snapshot.objects.filter(page=page)
            .exclude(html_content="")
            .order_by("-created_at")
            .first()
        )
        if snapshot is None:
            continue

        metadata = _extract_metadata(snapshot.html_content, page.url)
        page.title = metadata["title"]
        page.icon = metadata["icon"]
        page.save(update_fields=["title", "icon"])


class Migration(migrations.Migration):

    dependencies = [
        ("pagechecker", "0005_page_icon_page_title"),
    ]

    operations = [
        migrations.RunPython(backfill_title_icon, migrations.RunPython.noop),
    ]
