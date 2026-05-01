# AGENTS.md

## Cursor Cloud specific instructions

**Backend monorepo:** one Django project; **auth** (and related shared infrastructure) lives in common code paths and is reused across apps. Top-level directories such as `pagechecker/` are **independent applications**—each owns its domain, services, and tests. Expect **more apps** to land over time (for example groceries, manga); treat new app directories the same way: shared auth, app-local code.

This document focuses on the **Page Checker** app: a Django Ninja API that monitors web pages for content changes. It uses SQLite (no external DB server needed) and `uv` as the Python package manager.

### Quick reference

| Action | Command |
|--------|---------|
| Install deps | `uv sync` |
| Run migrations | `uv run manage.py migrate` |
| Start dev server | `make run` (or `uv run manage.py runserver`) |
| Start worker | `make worker` (or `uv run manage.py qcluster`) |
| Start all (web + worker) | `make serve` (or `uv run honcho start`) |
| Lint | `uv run ruff check .` |
| Tests (app-scoped) | `uv run pytest pagechecker/` · `groceries/` · `auth/` · `backend/` |
| Make migrations | `make migrations` |

### Caveats

- **uv must be installed** (`curl -LsSf https://astral.sh/uv/install.sh | sh`). It is not a system package — it lives in `~/.local/bin` which is sourced via `~/.bashrc`.
- The API uses RPC-style POST endpoints at `/api/v1.PageChecker.<Method>` (e.g., `CreatePage`, `ListPages`, `GetPage`, `CheckPage`, `DeletePage`). There is no REST-style routing.
- Design follows **CQS** (Command Query Separation): methods named like `List*`, `Get*` are queries (read-only toward persisted domain state); methods like `Create*`, `Update*`, `Delete*`, `Check*`, `Associate*` are commands (may write or trigger side effects such as fetches and snapshots). Same HTTP verb (POST) for transport; intent is in the RPC method name.
- Django Ninja auto-generates interactive API docs at `/api/docs`.
- `check_page` makes outbound HTTP requests to fetch monitored URLs — network access is required.
- The SQLite database file (`db.sqlite3`) is created in the project root after running migrations. It is gitignored.
- When you change or add logic in `pagechecker/services.py`, add or extend **pytest** coverage in `pagechecker/tests/` (pytest-django; use `@pytest.mark.django_db` when the database is involved). Run `uv run pytest pagechecker/` together with `uv run ruff check .`. Prefer **app-scoped** test runs (`uv run pytest <app>/` or `uv run pytest path/to/test_file.py`) instead of `uv run pytest` for the whole repo—faster feedback. Use the full tree only when a change touches shared layers and you need cross-app confidence.
- **Test services, not HTTP routes.** Prefer calling functions in `pagechecker/services.py` directly. Do not add or extend tests that hit `/api/...` RPC endpoints via `django.test.Client` unless there is an explicit reason (e.g. auth middleware contract). Interactive behavior stays verifiable via `/api/docs`.
- **Do not test schemas.** Do not add or extend tests for Pydantic/Ninja `Schema` classes in `pagechecker/schemas.py` (e.g. `model_validate` round-trips). API shapes stay covered indirectly via services and `/api/docs`.
- **Django admin:** Whenever you add a new `models.Model` subclass in an app, register it in that app’s `admin.py` (`admin.site.register(MyModel)` or a `ModelAdmin` subclass) so rows appear under `/admin/`. Same change applies when introducing a new app that defines models.
- **Port & Host header:** `make serve` (honcho + gunicorn via Procfile) binds to port **5000**. `ALLOWED_HOSTS` includes `localhost` but not `127.0.0.1`, so always use `-H "Host: localhost"` when curling from the VM. `make run` (Django dev server) defaults to port **8000**.
- **PATH for uv:** In non-login shells (e.g. tmux, subprocesses), `~/.local/bin` may not be on PATH. Prefix commands with `export PATH="$HOME/.local/bin:$PATH"` or source `~/.bashrc` first.
