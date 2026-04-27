from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from groceries.gemini_service import MerchantProductInfo
from groceries.models import SEARCH_DEFAULT_EMOJI, Product, Search, SearchStatus
from groceries.services import (
    candidate_in_user_catalog_by_standard_name,
    create_search,
    delete_search,
    get_search,
    list_searches,
    load_user_catalog_standard_names_normalized,
    make_user_catalog_in_catalog_check,
    retry_empty_completed_search,
    run_product_search_job,
    search_result_candidates_as_product_schemas,
)

User = get_user_model()


@pytest.mark.django_db
@patch("groceries.services.async_task")
def test_create_search_persists_pending_and_enqueues_worker(mock_async):
    u = User.objects.create_user(username="s1", password="pw")
    sid = create_search(query="  leche  ", user_id=u.pk)
    row = Search.objects.get(pk=sid)
    assert row.user_id == u.pk
    assert row.query == "leche"
    assert row.emoji == SEARCH_DEFAULT_EMOJI
    assert row.status == SearchStatus.PENDING
    assert row.result_candidates == []
    mock_async.assert_called_once_with(
        "groceries.scheduled_tasks.run_product_search_job",
        sid,
        task_name=f"groceries_product_search:{sid}",
    )


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_candidates",
    return_value=[
        MerchantProductInfo(
            display_name="Leche 1 L",
            standard_name="Leche entera",
            brand="Colún",
            price=Decimal("1990"),
            format="1 L",
            emoji="🥛",
            merchant="Lider",
        ),
    ],
)
def test_run_product_search_job_marks_completed_with_candidates(_mock_gemini):
    u = User.objects.create_user(username="s2", password="pw")
    row = Search.objects.create(user_id=u.pk, query="leche")
    run_product_search_job(search_id=row.pk)
    row.refresh_from_db()
    assert row.status == SearchStatus.COMPLETED
    assert row.completed_at is not None
    assert row.result_candidates == [
        {
            "display_name": "Leche 1 L",
            "standard_name": "Leche entera",
            "brand": "Colún",
            "price": "1990.00",
            "format": "1 L",
            "emoji": "🥛",
            "merchant": "Lider",
            "ingredient": "",
        },
    ]
    assert row.emoji == "🥛"


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_candidates",
    return_value=[
        MerchantProductInfo(
            display_name="A",
            standard_name="",
            brand="",
            price=None,
            format="",
            emoji="",
            merchant="",
        ),
        MerchantProductInfo(
            display_name="B",
            standard_name="",
            brand="",
            price=None,
            format="",
            emoji="🧀",
            merchant="",
        ),
    ],
)
def test_run_product_search_job_search_emoji_defaults_when_first_candidate_blank(
    _mock_gemini,
):
    u = User.objects.create_user(username="s2b", password="pw")
    row = Search.objects.create(user_id=u.pk, query="q")
    run_product_search_job(search_id=row.pk)
    row.refresh_from_db()
    assert row.status == SearchStatus.COMPLETED
    assert row.emoji == SEARCH_DEFAULT_EMOJI
    assert row.result_candidates[0]["emoji"] == ""
    assert row.result_candidates[1]["emoji"] == "🧀"


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_candidates",
    side_effect=RuntimeError("no key"),
)
def test_run_product_search_job_runtime_error_marks_failed(_mock_gemini):
    u = User.objects.create_user(username="s3", password="pw")
    row = Search.objects.create(user_id=u.pk, query="x")
    before = timezone.now()
    run_product_search_job(search_id=row.pk)
    row.refresh_from_db()
    assert row.status == SearchStatus.FAILED
    assert row.completed_at is not None
    assert row.completed_at >= before
    assert row.result_candidates == []


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_candidates",
    return_value=[
        MerchantProductInfo(
            display_name="X",
            standard_name="",
            brand="",
            price=None,
            format="",
            emoji="",
            merchant="",
        ),
    ],
)
def test_run_product_search_job_skips_soft_deleted_search(_mock_gemini):
    u = User.objects.create_user(username="s_skip", password="pw")
    row = Search.objects.create(user_id=u.pk, query="leche")
    delete_search(search_id=row.pk, user_id=u.pk)
    run_product_search_job(search_id=row.pk)
    row = Search.all_objects.get(pk=row.pk)
    assert row.status == SearchStatus.PENDING
    assert row.result_candidates == []
    assert row.completed_at is None
    _mock_gemini.assert_not_called()


@pytest.mark.django_db
def test_get_search_returns_row_for_owner():
    u = User.objects.create_user(username="gs1", password="pw")
    row = Search.objects.create(user_id=u.pk, query="milk")
    got = get_search(search_id=row.pk, user_id=u.pk)
    assert got.pk == row.pk
    assert got.query == "milk"


@pytest.mark.django_db
def test_get_search_wrong_user_raises():
    u = User.objects.create_user(username="gs2", password="pw")
    other = User.objects.create_user(username="gs3", password="pw")
    row = Search.objects.create(user_id=u.pk, query="x")
    with pytest.raises(Search.DoesNotExist):
        get_search(search_id=row.pk, user_id=other.pk)


@pytest.mark.django_db
def test_delete_search_soft_deletes_row_for_owner():
    u = User.objects.create_user(username="ds1", password="pw")
    row = Search.objects.create(user_id=u.pk, query="milk")
    delete_search(search_id=row.pk, user_id=u.pk)
    assert not Search.objects.filter(pk=row.pk).exists()
    dead = Search.all_objects.get(pk=row.pk)
    assert dead.deleted_at is not None


@pytest.mark.django_db
def test_list_searches_excludes_soft_deleted():
    u = User.objects.create_user(username="ds4", password="pw")
    row = Search.objects.create(user_id=u.pk, query="gone")
    delete_search(search_id=row.pk, user_id=u.pk)
    assert list_searches(user_id=u.pk) == []


@pytest.mark.django_db
def test_delete_search_wrong_user_raises():
    u = User.objects.create_user(username="ds2", password="pw")
    other = User.objects.create_user(username="ds3", password="pw")
    row = Search.objects.create(user_id=u.pk, query="x")
    with pytest.raises(Search.DoesNotExist):
        delete_search(search_id=row.pk, user_id=other.pk)
    assert Search.objects.filter(pk=row.pk).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("query", ["xyz", "carbonara"])
@patch("groceries.services.async_task")
def test_retry_empty_completed_search_enqueues_worker(mock_async, query):
    u = User.objects.create_user(username="retry1", password="pw")
    row = Search.objects.create(
        user_id=u.pk,
        query=query,
        status=SearchStatus.COMPLETED,
        result_candidates=[],
        completed_at=timezone.now(),
    )
    retry_empty_completed_search(search_id=row.pk, user_id=u.pk)
    row.refresh_from_db()
    assert row.status == SearchStatus.PENDING
    assert row.completed_at is None
    mock_async.assert_called_once_with(
        "groceries.scheduled_tasks.run_product_search_job",
        row.pk,
        task_name=f"groceries_product_search:{row.pk}",
    )


@pytest.mark.django_db
def test_retry_empty_completed_search_rejects_non_completed():
    u = User.objects.create_user(username="retry3", password="pw")
    row = Search.objects.create(
        user_id=u.pk,
        query="q",
        status=SearchStatus.PENDING,
        result_candidates=[],
    )
    with pytest.raises(ValueError, match="not completed"):
        retry_empty_completed_search(search_id=row.pk, user_id=u.pk)


@pytest.mark.django_db
def test_retry_empty_completed_search_rejects_when_candidates_present():
    u = User.objects.create_user(username="retry4", password="pw")
    row = Search.objects.create(
        user_id=u.pk,
        query="q",
        status=SearchStatus.COMPLETED,
        result_candidates=[{"display_name": "A", "standard_name": "", "brand": "", "format": "", "emoji": ""}],
        completed_at=timezone.now(),
    )
    with pytest.raises(ValueError, match="already has result"):
        retry_empty_completed_search(search_id=row.pk, user_id=u.pk)


@pytest.mark.django_db
def test_retry_empty_completed_search_wrong_user_raises():
    u = User.objects.create_user(username="retry6", password="pw")
    other = User.objects.create_user(username="retry7", password="pw")
    row = Search.objects.create(
        user_id=u.pk,
        query="q",
        status=SearchStatus.COMPLETED,
        result_candidates=[],
        completed_at=timezone.now(),
    )
    with pytest.raises(Search.DoesNotExist):
        retry_empty_completed_search(search_id=row.pk, user_id=other.pk)


@pytest.mark.django_db
def test_list_searches_caps_at_ten_newest_first_other_users_isolated():
    u = User.objects.create_user(username="ls_merge", password="pw")
    other = User.objects.create_user(username="ls_merge_o", password="pw")
    for i in range(3):
        Search.objects.create(user_id=other.pk, query=f"other{i}")
    base = timezone.now()
    ids_chrono = []
    for i in range(11):
        row = Search.objects.create(user_id=u.pk, query=f"q{i}")
        ids_chrono.append(row.pk)
        Search.objects.filter(pk=row.pk).update(
            created_at=base - timedelta(hours=11 - i),
        )
    want = list(reversed(ids_chrono))[:10]
    rows = list_searches(user_id=u.pk)
    assert len(rows) == 10
    assert [r.pk for r in rows] == want
    assert all(r.user_id == u.pk for r in rows)


def test_search_result_candidates_as_product_schemas_null_brand_becomes_empty():
    rows = search_result_candidates_as_product_schemas(
        [
            {
                "display_name": "X",
                "standard_name": "s",
                "brand": None,
                "price": None,
                "format": "",
                "emoji": "",
            },
        ],
        fallback_name="q",
    )
    assert len(rows) == 1
    assert rows[0].brand == ""
    assert rows[0].in_catalog is False


def test_search_result_candidates_as_product_schemas_maps_stored_json():
    rows = search_result_candidates_as_product_schemas(
        [
            {
                "display_name": "Leche 1 L",
                "standard_name": "Leche entera",
                "brand": "Colún",
                "price": "1990.00",
                "format": "1 L",
                "emoji": "🥛",
                "merchant": "Lider",
                "ingredient": "Leche",
            },
        ],
        fallback_name="leche",
    )
    assert len(rows) == 1
    c = rows[0]
    assert c.name == "Leche 1 L"
    assert c.standard_name == "Leche entera"
    assert c.brand == "Colún"
    assert c.price == Decimal("1990.00")
    assert c.format == "1 L"
    assert c.emoji == "🥛"
    assert c.merchant == "Lider"
    assert c.ingredient == "Leche"
    assert c.in_catalog is False


def test_search_result_candidates_as_product_schemas_skips_non_dict_entries():
    rows = search_result_candidates_as_product_schemas(
        [None, "x", {"display_name": "A", "standard_name": "", "brand": "", "format": "", "emoji": ""}],
        fallback_name="q",
    )
    assert len(rows) == 1
    assert rows[0].name == "A"


def test_search_result_candidates_as_product_schemas_uses_fallback_name_when_missing_label():
    rows = search_result_candidates_as_product_schemas(
        [{"standard_name": "s", "brand": "", "format": "", "emoji": ""}],
        fallback_name="  milk  ",
    )
    assert len(rows) == 1
    assert rows[0].name == "milk"
    assert rows[0].in_catalog is False


def test_search_result_candidates_as_product_schemas_in_catalog_when_checker_true():
    rows = search_result_candidates_as_product_schemas(
        [{"display_name": "A", "standard_name": "", "brand": "", "format": "", "emoji": ""}],
        fallback_name="q",
        in_catalog_check=lambda n, s, b: n == "A",
    )
    assert len(rows) == 1
    assert rows[0].in_catalog is True


@pytest.mark.django_db
def test_make_user_catalog_in_catalog_check_aligns_with_catalog_products():
    u = User.objects.create_user(username="mkchk", password="pw")
    Product.objects.create(
        user_id=u.pk,
        name="Leche entera 1 L",
        standard_name="Leche entera",
        brand="Colún",
        format="1 L",
        emoji="🥛",
    )
    check = make_user_catalog_in_catalog_check(user_id=u.pk)
    hit = search_result_candidates_as_product_schemas(
        [
            {
                "display_name": "x",
                "standard_name": "Leche entera",
                "brand": "",
                "format": "",
                "emoji": "",
            },
        ],
        fallback_name="q",
        in_catalog_check=check,
    )
    miss = search_result_candidates_as_product_schemas(
        [
            {
                "display_name": "Arroz",
                "standard_name": "",
                "brand": "",
                "format": "",
                "emoji": "",
            },
        ],
        fallback_name="q",
        in_catalog_check=check,
    )
    assert hit[0].in_catalog is True
    assert miss[0].in_catalog is False


@pytest.mark.django_db
def test_candidate_in_user_catalog_matches_standard_name_folded():
    u = User.objects.create_user(username="icat1", password="pw")
    Product.objects.create(
        user_id=u.pk,
        name="Leche entera 1 L",
        standard_name="Leche entera",
        brand="Colún",
        format="1 L",
        emoji="🥛",
    )
    catalog_std = load_user_catalog_standard_names_normalized(user_id=u.pk)
    assert candidate_in_user_catalog_by_standard_name(
        name="Leche 1 L",
        standard_name="Leche entera",
        brand="Colún",
        catalog_standard_names=catalog_std,
    )
    assert candidate_in_user_catalog_by_standard_name(
        name="",
        standard_name="LECHE ENTERA",
        brand="",
        catalog_standard_names=catalog_std,
    )
    assert candidate_in_user_catalog_by_standard_name(
        name="",
        standard_name="Leche entera\u0301",
        brand="",
        catalog_standard_names=catalog_std,
    )
    assert not candidate_in_user_catalog_by_standard_name(
        name="Arroz",
        standard_name="",
        brand="",
        catalog_standard_names=catalog_std,
    )


def test_candidate_in_user_catalog_false_when_standard_name_differs():
    catalog = frozenset({"leche entera"})
    assert not candidate_in_user_catalog_by_standard_name(
        name="Leche 1 L",
        standard_name="Leche descremada",
        brand="",
        catalog_standard_names=catalog,
    )
