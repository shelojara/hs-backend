"""
Copy all Django data from SQLite file to PostgreSQL (POSTGRES_URL).

Uses dumpdata/loaddata with natural keys so contenttypes and permissions
(still created by migrate) line up with foreign keys from migrated schema.
dumpdata runs with ``--all`` (base manager) so soft-deleted rows
(e.g. groceries Product / Search) are included and FKs stay valid.

Typical flow on target host with empty Postgres:

  export POSTGRES_URL='postgresql://user:pass@host:5432/dbname'
  uv run manage.py migrate
  uv run manage.py migrate_sqlite_to_postgres --sqlite-path /path/to/db.sqlite3
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = (
        "Load data from SQLite into PostgreSQL using POSTGRES_URL. "
        "Requires migrations applied on Postgres first. "
        "Clears existing data in the default (Postgres) database before load."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--sqlite-path",
            type=Path,
            default=None,
            help="Path to db.sqlite3 (default: SQLITE_PATH env or project db.sqlite3)",
        )
        parser.add_argument(
            "--skip-flush",
            action="store_true",
            help="Do not flush Postgres before loaddata (append / duplicate risk)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only dump from SQLite to a temp file; print path; skip flush/load",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        postgres_url = os.environ.get("POSTGRES_URL", "").strip()
        if not postgres_url:
            raise CommandError(
                "POSTGRES_URL must be set in the environment so default database is PostgreSQL."
            )

        engine = settings.DATABASES["default"].get("ENGINE", "")
        if "postgresql" not in engine:
            raise CommandError(
                f"Expected default database ENGINE to be PostgreSQL, got {engine!r}. "
                "Unset SQLITE overrides and ensure POSTGRES_URL is set before starting."
            )

        sqlite_path = options["sqlite_path"]
        if sqlite_path is None:
            raw = os.environ.get("SQLITE_PATH", "").strip()
            sqlite_path = Path(raw).expanduser() if raw else Path(settings.BASE_DIR) / "db.sqlite3"
        else:
            sqlite_path = Path(sqlite_path).expanduser()

        if not sqlite_path.is_file():
            raise CommandError(f"SQLite database file not found: {sqlite_path}")

        manage_py = Path(__file__).resolve().parent.parent.parent.parent / "manage.py"
        if not manage_py.is_file():
            manage_py = Path(sys.argv[0])

        dump_env = os.environ.copy()
        dump_env.pop("POSTGRES_URL", None)
        dump_env["SQLITE_PATH"] = str(sqlite_path)

        self.stdout.write(f"Dumping from SQLite: {sqlite_path}")

        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            delete=False,
            encoding="utf-8",
        ) as tmp:
            dump_path = tmp.name

        try:
            cmd = [
                sys.executable,
                str(manage_py),
                "dumpdata",
                "--all",
                "--natural-foreign",
                "--natural-primary",
                "--indent",
                "2",
                "-e",
                "contenttypes",
                "-e",
                "auth.Permission",
                "-o",
                dump_path,
            ]
            proc = subprocess.run(
                cmd,
                env=dump_env,
                cwd=str(Path(manage_py).parent),
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode != 0:
                raise CommandError(
                    f"dumpdata failed (exit {proc.returncode}):\n{proc.stderr or proc.stdout}"
                )

            if options["dry_run"]:
                self.stdout.write(self.style.SUCCESS(f"Dry run: dump written to {dump_path}"))
                return

            if not options["skip_flush"]:
                self.stdout.write("Flushing PostgreSQL database (all tables)...")
                call_command("flush", interactive=False, verbosity=1)

            self.stdout.write(f"Loading fixture into PostgreSQL ({len(Path(dump_path).read_bytes())} bytes)...")
            call_command("loaddata", dump_path, verbosity=1)

        finally:
            if not options["dry_run"]:
                try:
                    os.unlink(dump_path)
                except OSError:
                    pass
            elif options["dry_run"] and Path(dump_path).exists():
                self.stdout.write(f"Leaving dump file: {dump_path}")

        self.stdout.write(self.style.SUCCESS("SQLite → PostgreSQL data migration finished."))
