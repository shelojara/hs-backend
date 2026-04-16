# AGENTS.md

## Cursor Cloud specific instructions

This is a Django-based **Page Checker** API (Django Ninja) that monitors web pages for content changes. It uses SQLite (no external DB server needed) and `uv` as the Python package manager.

### Quick reference

| Action | Command |
|--------|---------|
| Install deps | `uv sync` |
| Run migrations | `uv run manage.py migrate` |
| Start dev server | `make run` (or `uv run manage.py runserver`) |
| Start worker | `make worker` (or `uv run manage.py qcluster`) |
| Start all (web + worker) | `make serve` (or `uv run honcho start`) |
| Lint | `uv run ruff check .` |
| Tests | `uv run pytest` |
| Make migrations | `make migrations` |

### Caveats

- **uv must be installed** (`curl -LsSf https://astral.sh/uv/install.sh | sh`). It is not a system package — it lives in `~/.local/bin` which is sourced via `~/.bashrc`.
- The API uses RPC-style POST endpoints at `/api/v1.PageChecker.<Method>` (e.g., `CreatePage`, `ListPages`, `GetPage`, `CheckPage`, `DeletePage`). There is no REST-style routing.
- Design follows **CQS** (Command Query Separation): methods named like `List*`, `Get*` are queries (read-only toward persisted domain state); methods like `Create*`, `Update*`, `Delete*`, `Check*`, `Associate*` are commands (may write or trigger side effects such as fetches and snapshots). Same HTTP verb (POST) for transport; intent is in the RPC method name.
- Django Ninja auto-generates interactive API docs at `/api/docs`.
- `check_page` makes outbound HTTP requests to fetch monitored URLs — network access is required.
- The SQLite database file (`db.sqlite3`) is created in the project root after running migrations. It is gitignored.
- When you change or add logic in `pagechecker/services.py`, add or extend **pytest** coverage in `pagechecker/tests/` (pytest-django; use `@pytest.mark.django_db` when the database is involved). Run `uv run pytest` together with `uv run ruff check .`.
- **Test services, not HTTP routes.** Prefer calling functions in `pagechecker/services.py` directly. Do not add or extend tests that hit `/api/...` RPC endpoints via `django.test.Client` unless there is an explicit reason (e.g. auth middleware contract). Interactive behavior stays verifiable via `/api/docs`.
