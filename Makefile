run:
	uv run manage.py runserver

worker:
	uv run manage.py qcluster

serve:
	uv run honcho start

migrate:
	uv run manage.py migrate

collectstatic:
	uv run manage.py collectstatic --noinput

migrations:
	uv run manage.py makemigrations

test:
	uv run pytest
