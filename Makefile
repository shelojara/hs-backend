run:
	uv run manage.py runserver

migrate:
	uv run manage.py migrate

collectstatic:
	uv run manage.py collectstatic --noinput

migrations:
	uv run manage.py makemigrations
