from datetime import datetime

from typing import Annotated

from ninja import Schema
from pydantic import AfterValidator, computed_field


def _strip_nonempty_question_text(v: str) -> str:
    s = v.strip()
    if not s:
        msg = "Question text must not be empty."
        raise ValueError(msg)
    return s


def _strip_nonempty_category_name(v: str) -> str:
    s = v.strip()
    if not s:
        msg = "Category name must not be empty."
        raise ValueError(msg)
    return s


class Snapshot(Schema):
    id: int
    created_at: datetime
    md_content: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def content(self) -> str:
        """Alias of md_content for backward-compatible API clients."""
        return self.md_content


class Question(Schema):
    id: int
    text: str
    created_at: datetime


class Category(Schema):
    id: int
    name: str
    emoji: str


class Page(Schema):
    id: int
    url: str
    title: str = ""
    icon: str = ""
    category: Category | None = None
    created_at: datetime
    last_checked_at: datetime | None = None
    latest_snapshot: Snapshot | None = None
    questions: list[Question] = []


class CreatePageRequest(Schema):
    url: str


class CreatePageResponse(Schema):
    page_id: int


class CheckPageRequest(Schema):
    page_id: int


class CheckPageResponse(Schema):
    has_changed: bool


class GetPageRequest(Schema):
    page_id: int


class GetPageResponse(Schema):
    page: Page


class ListPagesRequest(Schema):
    limit: int = 20
    offset: int = 0


class ListPagesResponse(Schema):
    pages: list[Page]


class DeletePageRequest(Schema):
    page_id: int


class DeletePageResponse(Schema):
    pass


class UpdatePageRequest(Schema):
    page_id: int
    url: str
    keep_snapshots: bool = False
    category_id: int | None = None


class UpdatePageResponse(Schema):
    pass


class CompareSnapshotsRequest(Schema):
    page_id: int
    question: str
    use_html: bool = False


class CompareSnapshotsResponse(Schema):
    answer: str


class ListQuestionsResponse(Schema):
    questions: list[Question]


class ListCategoriesResponse(Schema):
    categories: list[Category]


class CreateCategoryRequest(Schema):
    name: Annotated[str, AfterValidator(_strip_nonempty_category_name)]


class CreateCategoryResponse(Schema):
    category_id: int


class CreateQuestionRequest(Schema):
    text: Annotated[str, AfterValidator(_strip_nonempty_question_text)]


class CreateQuestionResponse(Schema):
    question_id: int


class DeleteQuestionRequest(Schema):
    question_id: int


class DeleteQuestionResponse(Schema):
    pass


class AssociateQuestionsWithPageRequest(Schema):
    page_id: int
    question_ids: list[int]


class AssociateQuestionsWithPageResponse(Schema):
    pass
