web: uv run manage.py migrate && uv run manage.py collectstatic --noinput && uv run gunicorn backend.wsgi:application --bind 0.0.0.0:${PORT:-8000}
worker: uv run manage.py qcluster
