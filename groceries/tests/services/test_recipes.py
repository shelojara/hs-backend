from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from groceries.gemini_service import (
    RecipeFullFromGemini,
    RecipeIngredientLine,
)
from groceries.models import (
    SEARCH_DEFAULT_EMOJI,
    Product,
    Recipe,
    RecipeGenerationStatus,
    RecipeIngredient,
    RecipeMessage,
    RecipeStep,
)
from groceries.tests.services.conftest import user as _user
from groceries.services import (
    InvalidRecipeListCursorError,
    RecipeGenerationFailedError,
    create_recipe_from_title_and_notes,
    delete_recipe,
    get_recipe,
    list_recipe_messages,
    list_user_recipes,
    recipe_chat_about_recipe,
    recipe_ingredient_in_catalog_flags,
    run_recipe_gemini_job,
    update_recipe,
)

User = get_user_model()


@pytest.mark.django_db
@patch("groceries.services.recipes._q.async_task")
@patch("groceries.services.gemini_service.suggest_product_emoji", return_value="")
@patch("groceries.services.gemini_service.fetch_recipe_full_chile")
def test_create_recipe_from_title_and_notes_persists_gemini_output(
    mock_fetch,
    _mock_suggest,
    mock_async,
):
    u = _user(username="chef1")
    mock_fetch.return_value = RecipeFullFromGemini(
        ingredients=(
            RecipeIngredientLine(name="Papa", amount="500 g"),
            RecipeIngredientLine(name="Cebolla", amount="1 unidad"),
        ),
        steps=("Pelar papas.", "Hervir 15 min."),
        emoji="🥘",
    )
    r = create_recipe_from_title_and_notes(
        title="  Charquicán  ",
        notes="  sin carne  ",
        user_id=u.pk,
    )
    mock_async.assert_called_once_with(
        "groceries.scheduled_tasks.run_recipe_gemini_job",
        r.pk,
        task_name=f"groceries_recipe_gemini:{r.pk}",
    )
    mock_fetch.assert_not_called()
    row = Recipe.objects.get(pk=r.pk)
    assert row.generation_status == RecipeGenerationStatus.PENDING
    run_recipe_gemini_job(recipe_id=r.pk)
    mock_fetch.assert_called_once_with(title="Charquicán", notes="sin carne")
    row = Recipe.objects.get(pk=r.pk)
    assert row.user_id == u.pk
    assert row.title == "Charquicán"
    assert row.notes == "sin carne"
    assert row.generation_status == RecipeGenerationStatus.COMPLETED
    assert row.emoji == "🥘"
    ings = list(row.ingredients.order_by("order", "id"))
    assert len(ings) == 2
    assert ings[0].name == "Papa" and ings[0].amount == "500 g"
    sts = list(row.steps.order_by("order", "id"))
    assert len(sts) == 2
    assert sts[0].text == "Pelar papas."


@pytest.mark.django_db
@patch("groceries.services.recipes._q.async_task")
@patch("groceries.services.gemini_service.fetch_recipe_full_chile", return_value=None)
def test_run_recipe_gemini_job_marks_failed_when_gemini_empty(_mock_fetch, _mock_async):
    u = _user()
    r = create_recipe_from_title_and_notes(title="X", notes="", user_id=u.pk)
    run_recipe_gemini_job(recipe_id=r.pk)
    row = Recipe.objects.get(pk=r.pk)
    assert row.generation_status == RecipeGenerationStatus.FAILED
    assert row.generation_error_message
    assert row.ingredients.count() == 0


@pytest.mark.django_db
def test_create_recipe_from_title_and_notes_empty_title_raises():
    u = _user()
    with pytest.raises(ValueError, match="title"):
        create_recipe_from_title_and_notes(title="   ", notes="", user_id=u.pk)


@pytest.mark.django_db
@patch("groceries.services.recipes._q.async_task")
def test_create_recipe_placeholder_notes_stored_empty(_mock_async):
    u = _user()
    r = create_recipe_from_title_and_notes(
        title="Pollo",
        notes="  Sin notas  ",
        user_id=u.pk,
    )
    assert Recipe.objects.get(pk=r.pk).notes == ""


@pytest.mark.django_db
@patch("groceries.services.recipes._q.async_task")
def test_create_recipe_from_title_sets_default_emoji_before_generation(_mock_async):
    u = _user()
    r = create_recipe_from_title_and_notes(title="Tortilla", notes="", user_id=u.pk)
    row = Recipe.objects.get(pk=r.pk)
    assert row.emoji == SEARCH_DEFAULT_EMOJI
    assert row.generation_status == RecipeGenerationStatus.PENDING


@pytest.mark.django_db
@patch("groceries.services.recipes._q.async_task")
@patch("groceries.services.gemini_service.suggest_product_emoji", return_value="🧄")
@patch("groceries.services.gemini_service.fetch_recipe_full_chile")
def test_run_recipe_gemini_job_uses_suggest_emoji_when_json_omits_emoji(
    mock_fetch,
    mock_suggest,
    _mock_async,
):
    u = _user(username="chef_emoji_fallback")
    mock_fetch.return_value = RecipeFullFromGemini(
        ingredients=(RecipeIngredientLine(name="Ajo", amount="1"),),
        steps=("Sofreír.",),
    )
    r = create_recipe_from_title_and_notes(title="Salsa verde", notes="", user_id=u.pk)
    run_recipe_gemini_job(recipe_id=r.pk)
    row = Recipe.objects.get(pk=r.pk)
    assert row.emoji == "🧄"
    mock_suggest.assert_called_once_with(name="Salsa verde")


@pytest.mark.django_db
@patch("groceries.services.recipes._q.async_task")
@patch("groceries.services.gemini_service.suggest_product_emoji", return_value="")
@patch("groceries.services.gemini_service.fetch_recipe_full_chile")
def test_get_recipe_returns_row_for_owner(mock_fetch, _mock_suggest, _mock_async):
    u = _user(username="chef2")
    u2 = _user(username="other")
    mock_fetch.return_value = RecipeFullFromGemini(
        ingredients=(RecipeIngredientLine(name="Ajo", amount="2 dientes"),),
        steps=("Picar.",),
    )
    r = create_recipe_from_title_and_notes(title="Salsa", notes="", user_id=u.pk)
    run_recipe_gemini_job(recipe_id=r.pk)
    out = get_recipe(recipe_id=r.pk, user_id=u.pk)
    assert out.pk == r.pk
    assert list(out.ingredients.values_list("name", flat=True)) == ["Ajo"]
    with pytest.raises(Recipe.DoesNotExist):
        get_recipe(recipe_id=r.pk, user_id=u2.pk)


@pytest.mark.django_db
def test_recipe_ingredient_in_catalog_flags_icontains_standard_name():
    u = _user(username="chef_cat")
    Product.objects.create(
        user=u,
        name="Leche Colún",
        standard_name="Leche entera 1 L",
        brand="Colún",
        price=Decimal("1000"),
        format="1 L",
    )
    flags = recipe_ingredient_in_catalog_flags(
        user_id=u.pk,
        ingredient_names=["Leche", "Huevos", "  leche  "],
    )
    assert flags["Leche"] is True
    assert flags["Huevos"] is False
    assert flags["leche"] is True


@pytest.mark.django_db
def test_list_recipe_messages_ordered_oldest_first():
    u = _user(username="msg_list_u")
    r = Recipe.objects.create(user=u, title="Chatty", notes="")
    RecipeIngredient.objects.create(recipe=r, order=0, name="A", amount="")
    RecipeStep.objects.create(recipe=r, order=0, text="S")
    base = timezone.now()
    m1 = RecipeMessage.objects.create(
        recipe=r,
        user_message="first",
        assistant_answer="a1",
        recipe_updated=False,
    )
    RecipeMessage.objects.filter(pk=m1.pk).update(created_at=base)
    m2 = RecipeMessage.objects.create(
        recipe=r,
        user_message="second",
        assistant_answer="a2",
        recipe_updated=True,
    )
    RecipeMessage.objects.filter(pk=m2.pk).update(created_at=base + timedelta(seconds=1))

    rows = list_recipe_messages(recipe_id=r.pk, user_id=u.pk)
    assert [m.pk for m in rows] == [m1.pk, m2.pk]
    assert rows[0].user_message == "first"
    assert rows[1].recipe_updated is True


@pytest.mark.django_db
def test_list_recipe_messages_wrong_user_raises():
    u = _user(username="msg_owner")
    other = _user(username="msg_other")
    r = Recipe.objects.create(user=u, title="Mine", notes="")
    RecipeIngredient.objects.create(recipe=r, order=0, name="A", amount="")
    RecipeStep.objects.create(recipe=r, order=0, text="S")
    RecipeMessage.objects.create(
        recipe=r,
        user_message="x",
        assistant_answer="y",
        recipe_updated=False,
    )
    with pytest.raises(Recipe.DoesNotExist):
        list_recipe_messages(recipe_id=r.pk, user_id=other.pk)


@pytest.mark.django_db
def test_delete_recipe_removes_row_and_children():
    u = _user(username="chef_del")
    r = Recipe.objects.create(user=u, title="Gone", notes="")
    RecipeIngredient.objects.create(recipe=r, order=0, name="X", amount="")
    RecipeStep.objects.create(recipe=r, order=0, text="Y")
    rid = r.pk
    RecipeMessage.objects.create(
        recipe=r,
        user_message="hi",
        assistant_answer="bye",
        recipe_updated=False,
    )
    delete_recipe(recipe_id=rid, user_id=u.pk)
    assert Recipe.objects.filter(pk=rid).count() == 0
    assert RecipeIngredient.objects.filter(recipe_id=rid).count() == 0
    assert RecipeStep.objects.filter(recipe_id=rid).count() == 0
    assert RecipeMessage.objects.filter(recipe_id=rid).count() == 0


@pytest.mark.django_db
@patch("groceries.services.gemini_service.fetch_recipe_chat_chile")
def test_recipe_chat_about_recipe_answer_only_no_db_change(mock_fetch):
    from groceries.gemini_service import RecipeChatFromGemini

    u = _user(username="chat_u1")
    r = Recipe.objects.create(user=u, title="Sopa", notes="")
    RecipeIngredient.objects.create(recipe=r, order=0, name="Agua", amount="1 L")
    RecipeStep.objects.create(recipe=r, order=0, text="Hervir.")
    raw = '{"answer": "Prueba de sal al final.", "update_recipe": false}'
    mock_fetch.return_value = RecipeChatFromGemini(
        answer="Prueba de sal al final.",
        update_recipe=False,
        updated=None,
        gemini_response_raw=raw,
    )

    out = recipe_chat_about_recipe(
        recipe_id=r.pk,
        user_id=u.pk,
        message="  ¿Cuándo sal?  ",
    )
    assert out.answer == "Prueba de sal al final."
    assert out.recipe_updated is False
    row = get_recipe(recipe_id=r.pk, user_id=u.pk)
    assert row.title == "Sopa"
    assert list(
        row.ingredients.order_by("order").values_list("name", flat=True),
    ) == ["Agua"]
    mock_fetch.assert_called_once()
    stored = RecipeMessage.objects.get(recipe_id=r.pk)
    assert stored.user_message == "¿Cuándo sal?"
    assert stored.assistant_answer == "Prueba de sal al final."
    assert stored.gemini_response_raw == raw
    assert stored.recipe_updated is False


@pytest.mark.django_db
@patch("groceries.services.gemini_service.fetch_recipe_chat_chile")
def test_recipe_chat_about_recipe_persists_when_model_requests_update(mock_fetch):
    from groceries.gemini_service import RecipeChatFromGemini, RecipeFullFromGemini

    u = _user(username="chat_u2")
    r = Recipe.objects.create(user=u, title="Viejo", notes="notas fijas")
    RecipeIngredient.objects.create(recipe=r, order=0, name="X", amount="")
    RecipeStep.objects.create(recipe=r, order=0, text="Paso viejo.")
    raw = (
        '{"answer": "Actualizado.", "update_recipe": true, '
        '"ingredients": [{"name": "Y", "amount": "100 g"}], "steps": ["Nuevo paso."]}'
    )
    mock_fetch.return_value = RecipeChatFromGemini(
        answer="Actualizado.",
        update_recipe=True,
        updated=RecipeFullFromGemini(
            ingredients=(RecipeIngredientLine(name="Y", amount="100 g"),),
            steps=("Nuevo paso.",),
        ),
        gemini_response_raw=raw,
    )

    out = recipe_chat_about_recipe(
        recipe_id=r.pk,
        user_id=u.pk,
        message="Cambia todo",
    )
    assert out.recipe_updated is True
    row = get_recipe(recipe_id=r.pk, user_id=u.pk)
    assert row.title == "Viejo"
    assert row.notes == "notas fijas"
    assert list(
        row.ingredients.order_by("order").values_list("name", flat=True),
    ) == ["Y"]
    assert list(row.steps.order_by("order").values_list("text", flat=True)) == [
        "Nuevo paso.",
    ]
    stored = RecipeMessage.objects.get(recipe_id=r.pk)
    assert stored.user_message == "Cambia todo"
    assert stored.assistant_answer == "Actualizado."
    assert stored.gemini_response_raw == raw
    assert stored.recipe_updated is True


@pytest.mark.django_db
@patch("groceries.services.gemini_service.fetch_recipe_chat_chile")
def test_recipe_chat_about_recipe_persists_recipe_ops_patch(mock_fetch):
    from groceries.gemini_service import RecipeChatFromGemini

    u = _user(username="chat_ops")
    r = Recipe.objects.create(user=u, title="Arroz", notes="")
    RecipeIngredient.objects.create(recipe=r, order=0, name="Arroz", amount="1 taza")
    RecipeIngredient.objects.create(recipe=r, order=1, name="Agua", amount="2 tazas")
    RecipeStep.objects.create(recipe=r, order=0, text="Hervir.")
    RecipeStep.objects.create(recipe=r, order=1, text="Reposar.")
    raw = (
        '{"answer": "Agregué sal.", "update_recipe": true, '
        '"recipe_ops": [{"op": "insert_ingredient", "index": 2, "name": "Sal", "amount": "1 pizca"}]}'
    )
    mock_fetch.return_value = RecipeChatFromGemini(
        answer="Agregué sal.",
        update_recipe=True,
        updated=None,
        recipe_ops=(
            {
                "op": "insert_ingredient",
                "index": 2,
                "name": "Sal",
                "amount": "1 pizca",
            },
        ),
        gemini_response_raw=raw,
    )

    out = recipe_chat_about_recipe(
        recipe_id=r.pk,
        user_id=u.pk,
        message="Agrega sal al final de ingredientes",
    )
    assert out.recipe_updated is True
    row = get_recipe(recipe_id=r.pk, user_id=u.pk)
    assert list(
        row.ingredients.order_by("order").values_list("name", "amount"),
    ) == [
        ("Arroz", "1 taza"),
        ("Agua", "2 tazas"),
        ("Sal", "1 pizca"),
    ]
    assert list(row.steps.order_by("order").values_list("text", flat=True)) == [
        "Hervir.",
        "Reposar.",
    ]
    stored = RecipeMessage.objects.get(recipe_id=r.pk)
    assert stored.gemini_response_raw == raw


@pytest.mark.django_db
def test_recipe_chat_about_recipe_empty_message_raises():
    u = _user(username="chat_u3")
    r = Recipe.objects.create(user=u, title="T", notes="")
    RecipeIngredient.objects.create(recipe=r, order=0, name="A", amount="")
    RecipeStep.objects.create(recipe=r, order=0, text="S")
    with pytest.raises(ValueError, match="Message"):
        recipe_chat_about_recipe(recipe_id=r.pk, user_id=u.pk, message="   ")


@pytest.mark.django_db
@patch("groceries.services.gemini_service.fetch_recipe_chat_chile")
def test_recipe_chat_about_recipe_wrong_user_raises(mock_fetch):
    u = _user(username="owner_chat")
    other = _user(username="other_chat")
    r = Recipe.objects.create(user=u, title="Mine", notes="")
    RecipeIngredient.objects.create(recipe=r, order=0, name="A", amount="")
    RecipeStep.objects.create(recipe=r, order=0, text="S")
    with pytest.raises(Recipe.DoesNotExist):
        recipe_chat_about_recipe(recipe_id=r.pk, user_id=other.pk, message="Hola")
    mock_fetch.assert_not_called()


@pytest.mark.django_db
@patch("groceries.services.gemini_service.fetch_recipe_chat_chile", return_value=None)
def test_recipe_chat_about_recipe_raises_when_gemini_empty(_mock):
    u = _user(username="chat_u4")
    r = Recipe.objects.create(user=u, title="T", notes="")
    RecipeIngredient.objects.create(recipe=r, order=0, name="A", amount="")
    RecipeStep.objects.create(recipe=r, order=0, text="S")
    with pytest.raises(RecipeGenerationFailedError):
        recipe_chat_about_recipe(recipe_id=r.pk, user_id=u.pk, message="?")
    assert RecipeMessage.objects.filter(recipe_id=r.pk).count() == 0


@pytest.mark.django_db
def test_delete_recipe_wrong_user_raises():
    u = _user(username="owner_del")
    other = _user(username="other_del")
    r = Recipe.objects.create(user=u, title="Mine", notes="")
    RecipeIngredient.objects.create(recipe=r, order=0, name="A", amount="")
    RecipeStep.objects.create(recipe=r, order=0, text="S")
    with pytest.raises(Recipe.DoesNotExist):
        delete_recipe(recipe_id=r.pk, user_id=other.pk)
    assert Recipe.objects.filter(pk=r.pk).exists()


@pytest.mark.django_db
@patch("groceries.services.recipes._q.async_task")
def test_update_recipe_rejects_while_generation_pending(_mock_async):
    u = _user()
    r = create_recipe_from_title_and_notes(title="T", notes="", user_id=u.pk)
    assert r.generation_status == RecipeGenerationStatus.PENDING
    with pytest.raises(ValueError, match="progress"):
        update_recipe(
            recipe_id=r.pk,
            user_id=u.pk,
            title="T",
            notes="",
            ingredient_lines=[("A", "")],
            step_texts=["S"],
        )


@pytest.mark.django_db
def test_update_recipe_replaces_metadata_ingredients_and_steps():
    u = _user(username="chef_edit")
    r = Recipe.objects.create(user=u, title="Old title", notes="old notes")
    RecipeIngredient.objects.create(recipe=r, order=0, name="Salt", amount="pinch")
    RecipeStep.objects.create(recipe=r, order=0, text="Old step.")

    out = update_recipe(
        recipe_id=r.pk,
        user_id=u.pk,
        title="  New title  ",
        notes="  new notes  ",
        ingredient_lines=[
            ("Tomate", "2"),
            ("Cebolla", "1"),
        ],
        step_texts=["Picar.", "Sofreír."],
    )
    assert out.title == "New title"
    assert out.notes == "new notes"
    names = list(out.ingredients.order_by("order").values_list("name", flat=True))
    assert names == ["Tomate", "Cebolla"]
    texts = list(out.steps.order_by("order").values_list("text", flat=True))
    assert texts == ["Picar.", "Sofreír."]
    assert list(out.ingredients.order_by("order").values_list("order", flat=True)) == [0, 1]
    assert list(out.steps.order_by("order").values_list("order", flat=True)) == [0, 1]


@pytest.mark.django_db
def test_update_recipe_wrong_user_raises():
    u = _user(username="owner_r")
    other = _user(username="intruder_r")
    r = Recipe.objects.create(user=u, title="Mine", notes="")
    RecipeIngredient.objects.create(recipe=r, order=0, name="X", amount="")
    RecipeStep.objects.create(recipe=r, order=0, text="Do.")
    with pytest.raises(Recipe.DoesNotExist):
        update_recipe(
            recipe_id=r.pk,
            user_id=other.pk,
            title="Stolen",
            notes="",
            ingredient_lines=[("Y", "")],
            step_texts=["Go."],
        )


@pytest.mark.django_db
def test_update_recipe_requires_nonempty_lists():
    u = _user()
    r = Recipe.objects.create(user=u, title="T", notes="")
    RecipeIngredient.objects.create(recipe=r, order=0, name="A", amount="")
    RecipeStep.objects.create(recipe=r, order=0, text="S")
    with pytest.raises(ValueError, match="ingredient"):
        update_recipe(
            recipe_id=r.pk,
            user_id=u.pk,
            title="T",
            notes="",
            ingredient_lines=[],
            step_texts=["One"],
        )
    with pytest.raises(ValueError, match="step"):
        update_recipe(
            recipe_id=r.pk,
            user_id=u.pk,
            title="T",
            notes="",
            ingredient_lines=[("A", "")],
            step_texts=[],
        )


@pytest.mark.django_db
def test_update_recipe_rejects_blank_ingredient_name_or_step_text():
    u = _user()
    r = Recipe.objects.create(user=u, title="T", notes="")
    RecipeIngredient.objects.create(recipe=r, order=0, name="A", amount="")
    RecipeStep.objects.create(recipe=r, order=0, text="S")
    with pytest.raises(ValueError, match="name"):
        update_recipe(
            recipe_id=r.pk,
            user_id=u.pk,
            title="T",
            notes="",
            ingredient_lines=[("  ", "1")],
            step_texts=["Ok"],
        )
    with pytest.raises(ValueError, match="step"):
        update_recipe(
            recipe_id=r.pk,
            user_id=u.pk,
            title="T",
            notes="",
            ingredient_lines=[("Ok", "")],
            step_texts=["   "],
        )


@pytest.mark.django_db
def test_list_user_recipes_empty():
    u = _user()
    rows, nxt = list_user_recipes(user_id=u.pk)
    assert rows == [] and nxt is None


@pytest.mark.django_db
def test_list_user_recipes_paginates_with_cursor():
    u = _user(username="chef_page")
    base = timezone.now()
    r_old = Recipe.objects.create(user=u, title="old", notes="")
    Recipe.objects.filter(pk=r_old.pk).update(updated_at=base - timedelta(hours=2))
    r_mid = Recipe.objects.create(user=u, title="mid", notes="")
    Recipe.objects.filter(pk=r_mid.pk).update(updated_at=base - timedelta(hours=1))
    r_new = Recipe.objects.create(user=u, title="new", notes="")
    Recipe.objects.filter(pk=r_new.pk).update(updated_at=base)

    p1, cur = list_user_recipes(user_id=u.pk, limit=2)
    assert [r.pk for r in p1] == [r_new.pk, r_mid.pk]
    assert cur is not None

    p2, cur2 = list_user_recipes(user_id=u.pk, limit=2, cursor=cur)
    assert [r.pk for r in p2] == [r_old.pk]
    assert cur2 is None


@pytest.mark.django_db
def test_list_user_recipes_single_select_no_prefetch():
    u = _user()
    Recipe.objects.create(user=u, title="A", notes="")
    with CaptureQueriesContext(connection) as ctx:
        list_user_recipes(user_id=u.pk, limit=10)
    assert len(ctx.captured_queries) == 1


@pytest.mark.django_db
def test_list_user_recipes_rejects_invalid_cursor():
    u = _user()
    with pytest.raises(InvalidRecipeListCursorError):
        list_user_recipes(user_id=u.pk, cursor="not-a-token")


@pytest.mark.django_db
def test_list_user_recipes_rejects_cursor_from_different_user():
    alice = _user(username="alice_r")
    bob = _user(username="bob_r")
    base = timezone.now()
    for i in range(3):
        r = Recipe.objects.create(user=alice, title=f"x{i}", notes="")
        Recipe.objects.filter(pk=r.pk).update(updated_at=base - timedelta(seconds=i))
    _, cur = list_user_recipes(user_id=alice.pk, limit=2)
    assert cur is not None
    with pytest.raises(InvalidRecipeListCursorError):
        list_user_recipes(user_id=bob.pk, cursor=cur)
