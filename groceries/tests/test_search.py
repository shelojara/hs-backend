from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone

from groceries.gemini_service import MerchantProductInfo
from groceries.models import Product, Search, SearchStatus
from groceries.services import (
    candidate_in_user_catalog_by_standard_name,
    create_search,
    delete_search,
    get_search,
    list_direct_child_searches,
    list_searches,
    load_user_catalog_standard_names_normalized,
    run_ingredient_product_search_job,
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
    assert row.parent_id is None
    assert row.status == SearchStatus.PENDING
    assert row.result_candidates == []
    assert row.kind == ""
    mock_async.assert_called_once_with(
        "groceries.scheduled_tasks.run_product_search_job",
        sid,
        task_name=f"groceries_product_search:{sid}",
    )


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.classify_search_query_kind",
    return_value="",
)
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
def test_run_product_search_job_marks_completed_with_candidates(
    _mock_gemini,
    _mock_kind,
):
    u = User.objects.create_user(username="s2", password="pw")
    row = Search.objects.create(user_id=u.pk, query="leche")
    run_product_search_job(search_id=row.pk)
    row.refresh_from_db()
    assert row.status == SearchStatus.COMPLETED
    assert row.completed_at is not None
    assert row.kind == ""
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
    _mock_kind.assert_called_once_with(query="leche")


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.classify_search_query_kind",
    return_value="",
)
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_candidates",
    side_effect=RuntimeError("no key"),
)
def test_run_product_search_job_runtime_error_marks_failed(_mock_gemini, _mock_kind):
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
@patch("groceries.services.async_task")
@patch(
    "groceries.services.gemini_service.classify_search_query_kind",
    return_value="recipe",
)
@patch(
    "groceries.services.gemini_service.fetch_recipe_common_ingredients_chile",
    return_value=["Pasta seca"],
)
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_candidates",
    return_value=[
        MerchantProductInfo(
            display_name="Pasta penne 500 g",
            standard_name="Pasta seca",
            brand="",
            price=None,
            format="500 g",
            emoji="🍝",
            merchant="Lider",
        ),
    ],
)
def test_recipe_search_enqueues_parallel_ingredient_jobs_then_child_completes_parent(
    _mock_fetch,
    _mock_ingredients,
    _mock_kind,
    mock_async,
):
    u = User.objects.create_user(username="skind", password="pw")
    row = Search.objects.create(user_id=u.pk, query="carbonara")
    run_product_search_job(search_id=row.pk)
    row.refresh_from_db()
    assert row.kind == "recipe"
    assert row.status == SearchStatus.COMPLETED
    assert row.result_candidates == []
    assert row.completed_at is not None
    _mock_ingredients.assert_called_once()
    assert _mock_ingredients.call_args.kwargs["recipe_query"] == "carbonara"
    children = list(Search.all_objects.filter(parent_id=row.pk).order_by("pk"))
    assert len(children) == 1
    assert children[0].query == "Pasta seca"
    assert children[0].status == SearchStatus.PENDING
    mock_async.assert_called_once_with(
        "groceries.scheduled_tasks.run_ingredient_product_search_job",
        children[0].pk,
        task_name=f"groceries_ingredient_search:{children[0].pk}",
    )
    _mock_fetch.assert_not_called()
    run_ingredient_product_search_job(search_id=children[0].pk)
    row.refresh_from_db()
    children[0].refresh_from_db()
    assert children[0].status == SearchStatus.COMPLETED
    assert row.status == SearchStatus.COMPLETED
    assert row.result_candidates == []
    _mock_fetch.assert_called_once()
    assert _mock_fetch.call_args.kwargs["query"] == "Pasta seca"
    assert _mock_fetch.call_args.kwargs["max_products"] == 10
    assert children[0].result_candidates == [
        {
            "display_name": "Pasta penne 500 g",
            "standard_name": "Pasta seca",
            "brand": "",
            "price": None,
            "format": "500 g",
            "emoji": "🍝",
            "merchant": "Lider",
            "ingredient": "Pasta seca",
        },
    ]


@pytest.mark.django_db
@patch("groceries.services.async_task")
@patch(
    "groceries.services.gemini_service.classify_search_query_kind",
    return_value="recipe",
)
@patch(
    "groceries.services.gemini_service.fetch_recipe_common_ingredients_chile",
    return_value=["Pasta seca"],
)
@patch("groceries.services.gemini_service.fetch_merchant_product_candidates")
def test_recipe_root_skips_enqueue_when_all_ingredients_in_catalog(
    mock_fetch,
    _mock_ingredients,
    _mock_kind,
    _mock_async,
):
    u = User.objects.create_user(username="scat1", password="pw")
    Product.objects.create(
        user_id=u.pk,
        name="Pasta",
        standard_name="Pasta seca",
    )
    root = Search.objects.create(user_id=u.pk, query="carbonara")
    run_product_search_job(search_id=root.pk)
    root.refresh_from_db()
    assert root.status == SearchStatus.COMPLETED
    assert not Search.all_objects.filter(parent_id=root.pk).exists()
    _mock_async.assert_not_called()
    mock_fetch.assert_not_called()


@pytest.mark.django_db
@patch("groceries.services.async_task")
@patch(
    "groceries.services.gemini_service.classify_search_query_kind",
    return_value="recipe",
)
@patch(
    "groceries.services.gemini_service.fetch_recipe_common_ingredients_chile",
    return_value=["Pasta seca", "Leche"],
)
@patch("groceries.services.gemini_service.fetch_merchant_product_candidates")
def test_recipe_root_enqueues_only_ingredients_not_in_catalog(
    mock_fetch,
    _mock_ingredients,
    _mock_kind,
    mock_async,
):
    u = User.objects.create_user(username="scat_mix", password="pw")
    Product.objects.create(
        user_id=u.pk,
        name="Pasta",
        standard_name="Pasta seca",
    )
    root = Search.objects.create(user_id=u.pk, query="tarta")
    run_product_search_job(search_id=root.pk)
    children = list(Search.all_objects.filter(parent_id=root.pk).order_by("pk"))
    assert len(children) == 1
    assert children[0].query == "Leche"
    mock_async.assert_called_once_with(
        "groceries.scheduled_tasks.run_ingredient_product_search_job",
        children[0].pk,
        task_name=f"groceries_ingredient_search:{children[0].pk}",
    )
    mock_fetch.assert_not_called()
    run_ingredient_product_search_job(search_id=children[0].pk)
    assert mock_fetch.call_count == 1
    assert mock_fetch.call_args.kwargs["query"] == "Leche"


@pytest.mark.django_db
@patch("groceries.services.async_task")
@patch(
    "groceries.services.gemini_service.classify_search_query_kind",
    return_value="question",
)
@patch(
    "groceries.services.gemini_service.fetch_question_related_grocery_products_chile",
    return_value=["Leche sin lactosa"],
)
@patch("groceries.services.gemini_service.fetch_merchant_product_candidates")
def test_question_search_enqueues_child_product_jobs(
    mock_fetch,
    _mock_related,
    _mock_kind,
    mock_async,
):
    u = User.objects.create_user(username="skind2", password="pw")
    row = Search.objects.create(user_id=u.pk, query="is oat milk healthy")
    run_product_search_job(search_id=row.pk)
    row.refresh_from_db()
    assert row.kind == "question"
    assert row.status == SearchStatus.COMPLETED
    assert row.result_candidates == []
    assert row.completed_at is not None
    _mock_related.assert_called_once_with(question="is oat milk healthy")
    children = list(Search.all_objects.filter(parent_id=row.pk).order_by("pk"))
    assert len(children) == 1
    assert children[0].query == "Leche sin lactosa"
    assert children[0].status == SearchStatus.PENDING
    mock_async.assert_called_once_with(
        "groceries.scheduled_tasks.run_ingredient_product_search_job",
        children[0].pk,
        task_name=f"groceries_ingredient_search:{children[0].pk}",
    )
    mock_fetch.assert_not_called()


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.classify_search_query_kind",
    return_value="question",
)
@patch(
    "groceries.services.gemini_service.fetch_question_related_grocery_products_chile",
    return_value=[],
)
@patch("groceries.services.gemini_service.fetch_merchant_product_candidates")
def test_question_search_marks_failed_when_no_related_products(
    _mock_fetch,
    _mock_related,
    _mock_kind,
):
    u = User.objects.create_user(username="sq_empty", password="pw")
    row = Search.objects.create(user_id=u.pk, query="why sky blue")
    run_product_search_job(search_id=row.pk)
    row.refresh_from_db()
    assert row.status == SearchStatus.FAILED
    assert row.kind == "question"
    assert row.result_candidates == []
    _mock_fetch.assert_not_called()


@pytest.mark.django_db
@patch("groceries.services.async_task")
@patch(
    "groceries.services.gemini_service.classify_search_query_kind",
    return_value="question",
)
@patch(
    "groceries.services.gemini_service.fetch_question_related_grocery_products_chile",
    return_value=["Leche sin lactosa", "Avena"],
)
@patch("groceries.services.gemini_service.fetch_merchant_product_candidates")
def test_question_root_enqueues_only_products_not_in_catalog(
    mock_fetch,
    _mock_related,
    _mock_kind,
    mock_async,
):
    u = User.objects.create_user(username="sq_cat", password="pw")
    Product.objects.create(
        user_id=u.pk,
        name="Avena hojuelas",
        standard_name="Avena",
    )
    root = Search.objects.create(user_id=u.pk, query="desayuno saludable?")
    run_product_search_job(search_id=root.pk)
    children = list(Search.all_objects.filter(parent_id=root.pk).order_by("pk"))
    assert len(children) == 1
    assert children[0].query == "Leche sin lactosa"
    mock_async.assert_called_once()
    mock_fetch.assert_not_called()


@pytest.mark.django_db
@override_settings(
    FLAGS={
        "SKIP_SEARCH_QUERY_CLASSIFICATION": [
            {"condition": "boolean", "value": True},
        ],
    },
)
@patch(
    "groceries.services.gemini_service.classify_search_query_kind",
    return_value="question",
)
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
def test_run_product_search_job_skip_classification_forces_product(
    _mock_fetch,
    _mock_kind,
):
    u = User.objects.create_user(username="s_skip_cls", password="pw")
    row = Search.objects.create(user_id=u.pk, query="is oat milk healthy")
    run_product_search_job(search_id=row.pk)
    row.refresh_from_db()
    assert row.status == SearchStatus.COMPLETED
    assert row.kind == "product"
    assert row.result_candidates
    _mock_kind.assert_not_called()
    _mock_fetch.assert_called_once()


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
@patch("groceries.services.gemini_service.classify_search_query_kind")
def test_run_product_search_job_skips_soft_deleted_search(_mock_kind, _mock_gemini):
    u = User.objects.create_user(username="s_skip", password="pw")
    row = Search.objects.create(user_id=u.pk, query="leche")
    delete_search(search_id=row.pk, user_id=u.pk)
    run_product_search_job(search_id=row.pk)
    row = Search.all_objects.get(pk=row.pk)
    assert row.status == SearchStatus.PENDING
    assert row.result_candidates == []
    assert row.completed_at is None
    _mock_gemini.assert_not_called()
    _mock_kind.assert_not_called()


@pytest.mark.django_db
def test_list_searches_returns_latest_ten_newest_first_ordered_by_pk():
    u = User.objects.create_user(username="ls1", password="pw")
    other = User.objects.create_user(username="ls2", password="pw")
    ids = []
    for i in range(12):
        row = Search.objects.create(user_id=u.pk, query=f"q{i}")
        ids.append(row.pk)
    for i in range(3):
        Search.objects.create(user_id=other.pk, query=f"other{i}")
    rows = list_searches(user_id=u.pk)
    assert len(rows) == 10
    want = list(reversed(ids[-10:]))
    assert [r.pk for r in rows] == want
    assert all(r.user_id == u.pk for r in rows)


@pytest.mark.django_db
def test_list_searches_excludes_child_searches():
    u = User.objects.create_user(username="ls_child", password="pw")
    root = Search.objects.create(user_id=u.pk, query="root")
    Search.objects.create(user_id=u.pk, query="child", parent_id=root.pk)
    rows = list_searches(user_id=u.pk)
    assert len(rows) == 1
    assert rows[0].pk == root.pk


@pytest.mark.django_db
def test_list_searches_annotates_sub_search_count():
    u = User.objects.create_user(username="ls_subcnt", password="pw")
    root = Search.objects.create(user_id=u.pk, query="root")
    Search.objects.create(user_id=u.pk, query="c1", parent_id=root.pk)
    Search.objects.create(user_id=u.pk, query="c2", parent_id=root.pk)
    rows = list_searches(user_id=u.pk)
    assert len(rows) == 1
    assert rows[0].sub_search_count == 2


@pytest.mark.django_db
def test_list_searches_sub_search_count_excludes_soft_deleted_children():
    u = User.objects.create_user(username="ls_subdel", password="pw")
    root = Search.objects.create(user_id=u.pk, query="root")
    alive = Search.objects.create(user_id=u.pk, query="alive", parent_id=root.pk)
    gone = Search.objects.create(user_id=u.pk, query="gone", parent_id=root.pk)
    delete_search(search_id=gone.pk, user_id=u.pk)
    rows = list_searches(user_id=u.pk)
    assert rows[0].sub_search_count == 1
    assert alive.pk in {c.pk for c in Search.objects.filter(parent_id=root.pk)}


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
def test_list_direct_child_searches_newest_first_excludes_other_parent():
    u = User.objects.create_user(username="ch1", password="pw")
    root_a = Search.objects.create(user_id=u.pk, query="a")
    root_b = Search.objects.create(user_id=u.pk, query="b")
    c_old = Search.objects.create(user_id=u.pk, query="old", parent_id=root_a.pk)
    c_new = Search.objects.create(user_id=u.pk, query="new", parent_id=root_a.pk)
    Search.objects.create(user_id=u.pk, query="other tree", parent_id=root_b.pk)
    got = list_direct_child_searches(root_a.pk, user_id=u.pk)
    assert [r.pk for r in got] == [c_new.pk, c_old.pk]


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
def test_list_searches_orders_by_created_at_newest_first():
    u = User.objects.create_user(username="ls3", password="pw")
    base = timezone.now()
    older = Search.objects.create(user_id=u.pk, query="older")
    newer = Search.objects.create(user_id=u.pk, query="newer")
    Search.objects.filter(pk=older.pk).update(created_at=base - timedelta(hours=2))
    Search.objects.filter(pk=newer.pk).update(created_at=base - timedelta(hours=1))
    assert older.pk < newer.pk
    rows = list_searches(user_id=u.pk)
    assert [r.pk for r in rows] == [newer.pk, older.pk]


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
