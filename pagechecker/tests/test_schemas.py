import pytest
from django.contrib.auth import get_user_model

from pagechecker.models import Category, Page
from pagechecker.schemas import CreateCategoryResponse, Page as PageSchema

User = get_user_model()


def test_create_category_response_only_category_id():
    out = CreateCategoryResponse(category_id=42)
    assert out.model_dump() == {"category_id": 42}


@pytest.mark.django_db
def test_page_schema_category_nested_or_null():
    owner = User.objects.create_user(username="schema_user", password="pw")
    bare = Page.objects.create(
        url="https://example.com/schema-page-bare",
        owner=owner,
    )
    out = PageSchema.model_validate(bare)
    assert out.category is None

    cat = Category.objects.create(name="Docs", emoji="📄")
    linked = Page.objects.create(
        url="https://example.com/schema-page-cat",
        category=cat,
        owner=owner,
    )
    linked = Page.objects.select_related("category").get(pk=linked.pk)
    out2 = PageSchema.model_validate(linked)
    assert out2.category is not None
    assert out2.category.id == cat.id
    assert out2.category.name == "Docs"
    assert out2.category.emoji == "📄"
