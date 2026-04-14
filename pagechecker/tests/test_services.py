import pytest

from pagechecker.models import Page, Question
from pagechecker.services import associate_questions_with_page


@pytest.mark.django_db
def test_associate_questions_with_page_replaces_skips_unknown_clears_empty():
    page = Page.objects.create(url="https://example.com/associate-m2m-test")
    q1 = Question.objects.create(text="one")
    q2 = Question.objects.create(text="two")
    q3 = Question.objects.create(text="three")

    associate_questions_with_page(page.id, [q1.id, q2.id])
    page.refresh_from_db()
    assert set(page.questions.values_list("id", flat=True)) == {q1.id, q2.id}

    associate_questions_with_page(page.id, [q2.id, q3.id])
    page.refresh_from_db()
    assert set(page.questions.values_list("id", flat=True)) == {q2.id, q3.id}

    associate_questions_with_page(page.id, [q1.id, 999_999])
    page.refresh_from_db()
    assert set(page.questions.values_list("id", flat=True)) == {q1.id}

    associate_questions_with_page(page.id, [])
    page.refresh_from_db()
    assert list(page.questions.values_list("id", flat=True)) == []
