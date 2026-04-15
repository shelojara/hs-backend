# Background Scheduler Research

Evaluated lightweight alternatives to Celery for running periodic background work (e.g. daily `check_page` for pages with `should_report_daily=True`).

**Constraints:** Django 6.0, SQLite, Nixpacks/Docker, no Redis/RabbitMQ, single-container deployment.

---

## Options

### 1. Django 6.0 Native Tasks + `django-tasks-local`

Django 6.0 ships `django.tasks` — a standard API for background work. Out of the box it only has `ImmediateBackend` (sync, dev-only) and `DummyBackend` (testing). Third-party backends provide real execution.

**`django-tasks-local`** (by Lincoln Loop) adds `ThreadPoolBackend` / `ProcessPoolBackend` — runs tasks in-process, zero infrastructure.

| Aspect | Detail |
|---|---|
| Deps | `django-tasks-local` (pure Python) |
| Broker | None — in-process thread/process pool |
| Scheduling | **Not built-in.** `django.tasks` only supports one-off `enqueue()`. Periodic scheduling requires a management command + cron/`sleep` loop, or pairing with `django-scheduled-tasks` |
| Persistence | In-memory only; tasks lost on restart |
| Worker process | None needed — runs inside gunicorn |
| Maturity | Very new (2026), small community |

**Verdict:** Good abstraction layer, but **no native scheduling** and **no persistence**. Needs additional glue for periodic work. Best if you want to align with Django's future direction and only need fire-and-forget tasks.

---

### 2. django-q2 (ORM broker)

Fork of django-q, actively maintained. Uses Django ORM as broker — works with SQLite, no external services.

| Aspect | Detail |
|---|---|
| Deps | `django-q2` + optional `croniter` (for cron expressions) |
| Broker | Django ORM (`'orm': 'default'`) — uses your existing SQLite |
| Scheduling | **Built-in.** `Schedule` model + admin UI. Supports minutes/hourly/daily/weekly/cron |
| Persistence | Full — tasks and results stored in DB |
| Worker process | **Separate process required:** `python manage.py qcluster` |
| Admin UI | Yes — queued/successful/failed/scheduled tasks visible in Django admin |
| Maturity | Established, well-documented |

**Verdict:** Best fit for this project. Zero new infrastructure (uses existing SQLite). Built-in scheduling with admin UI. Trade-off: needs a second process (`qcluster`), which means a separate Nixpacks service or a process manager.

<details>
<summary>Example config</summary>

```python
# settings.py
INSTALLED_APPS = [
    ...
    "django_q",
]

Q_CLUSTER = {
    "name": "pagechecker",
    "workers": 2,
    "timeout": 120,
    "orm": "default",       # SQLite via Django ORM
}
```

```python
# pagechecker/tasks.py
from pagechecker.services import check_page
from pagechecker.models import Page

def check_daily_pages():
    for page in Page.objects.filter(should_report_daily=True):
        check_page(page.id)
```

Schedule via admin or code:
```python
from django_q.tasks import schedule
from django_q.models import Schedule

schedule(
    "pagechecker.tasks.check_daily_pages",
    schedule_type=Schedule.DAILY,
    next_run="08:00",
)
```
</details>

---

### 3. Huey (SqliteHuey)

Minimal task queue by Charles Leifer. Supports SQLite storage via `SqliteHuey` (requires `peewee` ORM).

| Aspect | Detail |
|---|---|
| Deps | `huey` + `peewee` |
| Broker | SQLite file (separate from Django's db) |
| Scheduling | **Built-in.** `@huey.periodic_task(crontab(...))` decorator |
| Persistence | SQLite-backed |
| Worker process | **Separate process required:** `python manage.py run_huey` |
| Admin UI | None built-in (third-party `huey-monitor` exists) |
| Maturity | Stable, long track record |

**Verdict:** Lightweight and elegant API. Periodic tasks are first-class via decorators. Downsides: adds `peewee` dependency, uses a separate SQLite DB (not Django ORM), and SQLite mode has known stability issues under load. No admin UI without extra packages.

<details>
<summary>Example config</summary>

```python
# settings.py
INSTALLED_APPS = [
    ...
    "huey.contrib.djhuey",
]

HUEY = {
    "huey_class": "huey.SqliteHuey",
    "name": "pagechecker",
    "immediate": False,
    "connection": {"filename": "huey.db"},
}
```

```python
# pagechecker/tasks.py
from huey import crontab
from huey.contrib.djhuey import periodic_task
from pagechecker.services import check_page
from pagechecker.models import Page

@periodic_task(crontab(hour="8", minute="0"))
def check_daily_pages():
    for page in Page.objects.filter(should_report_daily=True):
        check_page(page.id)
```
</details>

---

### 4. APScheduler / django-apscheduler

Pure-Python in-process scheduler. No broker, no worker process.

| Aspect | Detail |
|---|---|
| Deps | `apscheduler` (+ `django-apscheduler` for ORM job store) |
| Broker | None — in-process |
| Scheduling | **Built-in.** Interval, cron, date triggers |
| Persistence | In-memory default; optional `DjangoJobStore` (DB-backed) |
| Worker process | **None** — runs inside gunicorn process |
| Admin UI | `django-apscheduler` adds admin views |
| Maturity | Very mature library |

**Verdict:** Simplest deployment — no extra process. But **dangerous with multi-worker gunicorn**: each worker spawns its own scheduler, causing duplicate task execution. Mitigation: run gunicorn with `--workers 1` or use file locks. Not ideal for production scaling.

<details>
<summary>Example config</summary>

```python
# settings.py
INSTALLED_APPS = [
    ...
    "django_apscheduler",
]

SCHEDULER_DEFAULT = True
```

```python
# pagechecker/apps.py  (in AppConfig.ready)
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

def start_scheduler():
    from pagechecker.services import check_page
    from pagechecker.models import Page

    def check_daily_pages():
        for page in Page.objects.filter(should_report_daily=True):
            check_page(page.id)

    scheduler = BackgroundScheduler()
    scheduler.add_job(check_daily_pages, CronTrigger(hour=8, minute=0), id="daily_check", replace_existing=True)
    scheduler.start()
```
</details>

---

## Comparison Matrix

| | django-q2 | Huey | APScheduler | Django Tasks + local |
|---|---|---|---|---|
| Extra infra | None | None | None | None |
| Uses existing SQLite | **Yes** (ORM broker) | No (own SQLite) | Optional | No (in-memory) |
| Built-in scheduling | **Yes** | **Yes** | **Yes** | No |
| Admin UI | **Yes** | No | Via plugin | No |
| Separate worker proc | Yes | Yes | **No** | **No** |
| Multi-worker safe | **Yes** | **Yes** | **No** | **No** |
| Task persistence | **Yes** | Yes | Optional | No |
| Retry/failure handling | **Yes** | Yes | No | No |
| Maturity | High | High | High | Low |

---

## Deployment: Running a Worker with Nixpacks

Nixpacks only runs **one process** per container. Options for running `qcluster` or `run_huey` alongside gunicorn:

### Option A: Two services (recommended)
Deploy two containers from same image — one `web`, one `worker`:

```
# Procfile
web: gunicorn backend.wsgi:application
worker: python manage.py qcluster
```

Configure hosting platform to run both (e.g. Railway/Render support multiple services from one repo).

### Option B: Process manager in single container
Use a lightweight process manager like `honcho` or a shell script:

```
# Procfile
web: honcho start -f Procfile.dev
```

```
# Procfile.dev
web: gunicorn backend.wsgi:application
worker: python manage.py qcluster
```

### Option C: In-process (APScheduler only)
No extra process needed. Just gunicorn with `--workers 1`. Simplest but limits scaling.

---

## Recommendation

**For this project: `django-q2` with ORM broker.**

Reasons:
1. **Zero new infrastructure** — reuses existing SQLite via Django ORM
2. **Built-in periodic scheduling** with admin UI — configure check intervals without code deploys
3. **Task persistence and retry** — failed checks tracked and retryable
4. **Multi-worker safe** — no duplicate execution issues
5. **Well-documented**, actively maintained fork
6. **Clean separation** — `qcluster` worker is a Django management command, easy to add to deployment

Trade-off: requires running a second process. For this app's scale (SQLite, single-server), Option B (honcho/shell wrapper) or platform-level multi-service works fine.

**Runner-up: Huey** if you prefer decorator-based periodic task definitions and don't need admin UI.

**Avoid APScheduler in production** unless you commit to single-worker gunicorn.
