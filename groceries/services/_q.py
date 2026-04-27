"""django-q async enqueue; separate module so tests patch ``groceries.services._q.async_task``."""

from django_q.tasks import async_task

__all__ = ["async_task"]
