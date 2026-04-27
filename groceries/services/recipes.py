import base64
import json
import logging
from typing import Any

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from . import _q

from groceries import gemini_service
from groceries.gemini_service import (
    RecipeChatFromGemini,
    RecipeFullFromGemini,
    apply_recipe_patch_ops,
)
from groceries.models import (
    SEARCH_DEFAULT_EMOJI,
    Recipe,
    RecipeGenerationStatus,
    RecipeIngredient,
    RecipeMessage,
    RecipeStep,
)

from .constants import DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT
from .exceptions import (
    InvalidRecipeListCursorError,
    RecipeChatResult,
    RecipeGenerationFailedError,
)

logger = logging.getLogger(__name__)


def _clamp_limit(limit: int) -> int:
    if limit < 1:
        return 1
    return min(limit, MAX_LIST_LIMIT)


def _encode_bytes_as_url_safe_base64_without_padding(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_url_safe_base64_without_padding_to_bytes(encoded: str) -> bytes:
    padding = "=" * (-len(encoded) % 4)
    return base64.urlsafe_b64decode(encoded + padding)


def _encode_list_user_recipes_cursor(payload: dict[str, Any]) -> str:
    return _encode_bytes_as_url_safe_base64_without_padding(
        json.dumps(payload, separators=(",", ":")).encode()
    )


def _decode_list_user_recipes_cursor(token: str) -> dict[str, Any]:
    try:
        raw_json = _decode_url_safe_base64_without_padding_to_bytes(token).decode()
        return json.loads(raw_json)
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise InvalidRecipeListCursorError() from exc


_LIST_USER_RECIPES_CURSOR_USER_ID = "u"
_LIST_USER_RECIPES_CURSOR_UPDATED_AT = "t"
_LIST_USER_RECIPES_CURSOR_RECIPE_ID = "i"


def _parse_list_user_recipes_cursor_payload(
    cursor_payload: dict[str, Any],
    *,
    expected_user_id: int,
) -> tuple[str, int]:
    """Return (``updated_at`` ISO string from token, recipe_id) after validating user."""
    try:
        cursor_user_id = cursor_payload[_LIST_USER_RECIPES_CURSOR_USER_ID]
        updated_at_iso = cursor_payload[_LIST_USER_RECIPES_CURSOR_UPDATED_AT]
        recipe_id = int(cursor_payload[_LIST_USER_RECIPES_CURSOR_RECIPE_ID])
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidRecipeListCursorError() from exc
    if cursor_user_id != expected_user_id:
        raise InvalidRecipeListCursorError(
            "Cursor does not match request parameters.",
        )
    if not isinstance(updated_at_iso, str):
        raise InvalidRecipeListCursorError()
    return updated_at_iso, recipe_id


def _normalize_user_recipe_notes(notes: str | None) -> str:
    """Strip user notes; empty if whitespace-only or common 'no notes' placeholders."""
    s = (notes or "").strip()
    if not s:
        return ""
    key = s.casefold()
    if key in {
        "no notes",
        "sin notas",
        "sin nota",
        "n/a",
        "na",
        "-",
        "—",
        "none",
    }:
        return ""
    return s


def create_recipe_from_title_and_notes(
    *,
    title: str,
    notes: str,
    user_id: int,
) -> Recipe:
    """Create recipe row (pending); enqueue worker to fill from Gemini (Chile-focused)."""
    t = (title or "").strip()
    if not t:
        msg = "Recipe title must not be empty."
        raise ValueError(msg)
    note_clean = _normalize_user_recipe_notes(notes)

    recipe = Recipe.objects.create(
        user_id=user_id,
        title=t[:255],
        notes=note_clean,
        emoji=SEARCH_DEFAULT_EMOJI,
        generation_status=RecipeGenerationStatus.PENDING,
    )
    _q.async_task(
        "groceries.scheduled_tasks.run_recipe_gemini_job",
        recipe.pk,
        task_name=f"groceries_recipe_gemini:{recipe.pk}",
    )
    return recipe


def _fail_recipe_generation(
    *,
    recipe: Recipe,
    message: str,
    log_exc: bool = False,
) -> None:
    if log_exc:
        logger.exception(
            "run_recipe_gemini_job: Gemini failed (recipe id=%s)",
            recipe.pk,
        )
    else:
        logger.warning(
            "run_recipe_gemini_job: generation failed (recipe id=%s): %s",
            recipe.pk,
            message[:200],
        )
    now = timezone.now()
    recipe.generation_status = RecipeGenerationStatus.FAILED
    recipe.generation_failed_at = now
    recipe.generation_error_message = (message or "")[:4000]
    recipe.save(
        update_fields=[
            "generation_status",
            "generation_failed_at",
            "generation_error_message",
            "updated_at",
        ],
    )


def run_recipe_gemini_job(*, recipe_id: int) -> None:
    """Background worker: Gemini full recipe → ``Recipe`` ingredients and steps."""
    try:
        recipe = Recipe.objects.get(pk=recipe_id)
    except Recipe.DoesNotExist:
        logger.warning("run_recipe_gemini_job: missing Recipe id=%s", recipe_id)
        return
    if recipe.generation_status != RecipeGenerationStatus.PENDING:
        logger.warning(
            "run_recipe_gemini_job: Recipe id=%s not pending (status=%s); skipping.",
            recipe_id,
            recipe.generation_status,
        )
        return

    t = (recipe.title or "").strip()
    note_clean = _normalize_user_recipe_notes(recipe.notes)

    try:
        full = gemini_service.fetch_recipe_full_chile(title=t, notes=note_clean)
    except RuntimeError:
        _fail_recipe_generation(
            recipe=recipe,
            message="Recipe generation is unavailable (missing API key).",
        )
        return
    except Exception:
        _fail_recipe_generation(
            recipe=recipe,
            message="Recipe generation failed. Try again later.",
            log_exc=True,
        )
        return

    if full is None:
        _fail_recipe_generation(
            recipe=recipe,
            message="Could not obtain a valid recipe from the model. Try again.",
        )
        return

    with transaction.atomic():
        locked = Recipe.objects.select_for_update().get(pk=recipe.pk)
        if locked.generation_status != RecipeGenerationStatus.PENDING:
            return
        RecipeIngredient.objects.bulk_create(
            [
                RecipeIngredient(
                    recipe=locked,
                    order=i,
                    name=line.name[:255],
                    amount=(line.amount or "")[:255],
                )
                for i, line in enumerate(full.ingredients)
            ],
        )
        RecipeStep.objects.bulk_create(
            [
                RecipeStep(recipe=locked, order=i, text=text)
                for i, text in enumerate(full.steps)
            ],
        )
        em = gemini_service.normalize_recipe_emoji(full.emoji)
        if not em:
            try:
                em = gemini_service.suggest_product_emoji(name=t)
            except RuntimeError:
                logger.warning(
                    "run_recipe_gemini_job: skipped emoji fallback (no API key) recipe id=%s",
                    locked.pk,
                )
                em = ""
            except Exception:
                logger.exception(
                    "run_recipe_gemini_job: emoji fallback failed (recipe id=%s)",
                    locked.pk,
                )
                em = ""
        locked.emoji = (em or "")[:64]
        locked.generation_status = RecipeGenerationStatus.COMPLETED
        locked.generation_failed_at = None
        locked.generation_error_message = ""
        locked.save(
            update_fields=[
                "emoji",
                "generation_status",
                "generation_failed_at",
                "generation_error_message",
                "updated_at",
            ],
        )


def get_recipe(*, recipe_id: int, user_id: int) -> Recipe:
    """Return user's recipe with ingredients and steps prefetched."""
    return Recipe.objects.prefetch_related("ingredients", "steps").get(
        pk=recipe_id,
        user_id=user_id,
    )


def list_recipe_messages(
    *,
    recipe_id: int,
    user_id: int,
) -> list[RecipeMessage]:
    """Chat turns for *recipe_id* owned by *user_id*, oldest first (``created_at``, ``id``).

    Raises ``Recipe.DoesNotExist`` when recipe missing or not owned.
    """
    Recipe.objects.get(pk=recipe_id, user_id=user_id)
    return list(
        RecipeMessage.objects.filter(recipe_id=recipe_id).order_by(
            "created_at",
            "id",
        ),
    )


def delete_recipe(*, recipe_id: int, user_id: int) -> None:
    """Hard-delete recipe owned by *user_id* (ingredients and steps cascade).

    Raises ``Recipe.DoesNotExist`` when no row matches *recipe_id* and *user_id*.
    """
    recipe = Recipe.objects.get(pk=recipe_id, user_id=user_id)
    recipe.delete()


def update_recipe(
    *,
    recipe_id: int,
    user_id: int,
    title: str,
    notes: str,
    ingredient_lines: list[tuple[str, str]],
    step_texts: list[str],
) -> Recipe:
    """Replace recipe metadata, ingredients, and steps for owner's row.

    *ingredient_lines* are ``(name, amount)`` pairs in display order.
    *step_texts* are ordered cooking steps. Raises ``ValueError`` when
    title is blank, lists empty, or any ingredient name / step text blank
    after strip. Raises ``Recipe.DoesNotExist`` when not owned by *user_id*.
    """
    t = (title or "").strip()
    if not t:
        msg = "Recipe title must not be empty."
        raise ValueError(msg)
    note_clean = _normalize_user_recipe_notes(notes)
    cleaned_ingredients: list[tuple[str, str]] = []
    for raw_name, raw_amount in ingredient_lines:
        name = (raw_name or "").strip()
        if not name:
            msg = "Each ingredient must have a non-empty name."
            raise ValueError(msg)
        amount = (raw_amount or "").strip()
        cleaned_ingredients.append((name[:255], amount[:255]))
    cleaned_steps: list[str] = []
    for raw_text in step_texts:
        text = (raw_text or "").strip()
        if not text:
            msg = "Each step must have non-empty text."
            raise ValueError(msg)
        cleaned_steps.append(text)
    if not cleaned_ingredients:
        msg = "Recipe must have at least one ingredient."
        raise ValueError(msg)
    if not cleaned_steps:
        msg = "Recipe must have at least one step."
        raise ValueError(msg)

    with transaction.atomic():
        recipe = Recipe.objects.select_for_update().get(pk=recipe_id, user_id=user_id)
        if recipe.generation_status == RecipeGenerationStatus.PENDING:
            msg = "Recipe generation is still in progress."
            raise ValueError(msg)
        recipe.title = t[:255]
        recipe.notes = note_clean
        recipe.save(update_fields=["title", "notes", "updated_at"])
        recipe.ingredients.all().delete()
        recipe.steps.all().delete()
        RecipeIngredient.objects.bulk_create(
            [
                RecipeIngredient(
                    recipe=recipe,
                    order=i,
                    name=name,
                    amount=amount,
                )
                for i, (name, amount) in enumerate(cleaned_ingredients)
            ],
        )
        RecipeStep.objects.bulk_create(
            [
                RecipeStep(recipe=recipe, order=i, text=text)
                for i, text in enumerate(cleaned_steps)
            ],
        )
    return get_recipe(recipe_id=recipe.pk, user_id=user_id)


def _recipe_context_for_gemini_chat(recipe: Recipe) -> str:
    """Plain-text snapshot of recipe for model context (zero-based indices for patch ops)."""
    ing_rows = sorted(recipe.ingredients.all(), key=lambda r: r.order)
    st_rows = sorted(recipe.steps.all(), key=lambda r: r.order)
    ing_block = "\n".join(
        f"ing[{i}] {ing.name} | {(ing.amount or '').strip()}"
        for i, ing in enumerate(ing_rows)
    )
    steps_block = "\n".join(f"step[{i}] {st.text}" for i, st in enumerate(st_rows))
    notes = (recipe.notes or "").strip()
    return (
        f"title: {recipe.title}\n"
        f"notes: {notes}\n\n"
        f"ingredients:\n{ing_block}\n\n"
        f"steps:\n{steps_block}"
    )


def recipe_chat_about_recipe(
    *,
    recipe_id: int,
    user_id: int,
    message: str,
) -> RecipeChatResult:
    """Gemini: short *message* about user's recipe; optionally persist model edits."""
    msg = (message or "").strip()
    if not msg:
        raise ValueError("Message must not be empty.")
    recipe = get_recipe(recipe_id=recipe_id, user_id=user_id)
    if recipe.generation_status == RecipeGenerationStatus.PENDING:
        raise ValueError("Recipe generation is still in progress.")
    if recipe.generation_status == RecipeGenerationStatus.FAILED:
        err = (recipe.generation_error_message or "").strip()
        raise ValueError(err if err else "Recipe generation failed.")
    ctx = _recipe_context_for_gemini_chat(recipe)
    try:
        out: RecipeChatFromGemini | None = gemini_service.fetch_recipe_chat_chile(
            recipe_context=ctx,
            user_message=msg,
        )
    except RuntimeError as exc:
        raise RecipeGenerationFailedError(
            "Recipe chat is unavailable (missing API key).",
        ) from exc
    except Exception as exc:
        logger.exception("recipe_chat_about_recipe: Gemini failed")
        raise RecipeGenerationFailedError(
            "Recipe chat failed. Try again later.",
        ) from exc

    if out is None:
        raise RecipeGenerationFailedError(
            "Could not obtain a valid reply from the model. Try again.",
        )

    recipe_updated = False
    if out.update_recipe:
        resolved: RecipeFullFromGemini | None = None
        if out.recipe_ops:
            ing_rows = sorted(recipe.ingredients.all(), key=lambda r: r.order)
            st_rows = sorted(recipe.steps.all(), key=lambda r: r.order)
            base_ing = [(r.name, (r.amount or "").strip()) for r in ing_rows]
            base_st = [r.text for r in st_rows]
            resolved = apply_recipe_patch_ops(
                ingredients=list(base_ing),
                steps=list(base_st),
                ops=out.recipe_ops,
                max_ingredients=gemini_service.RECIPE_FULL_INGREDIENTS_MAX,
                max_steps=gemini_service.RECIPE_FULL_STEPS_MAX,
            )
        elif out.updated is not None:
            resolved = out.updated
        if resolved is None:
            raise RecipeGenerationFailedError(
                "Could not apply recipe edits from the model. Try again.",
            )
        update_recipe(
            recipe_id=recipe_id,
            user_id=user_id,
            title=recipe.title,
            notes=recipe.notes or "",
            ingredient_lines=[
                (line.name, line.amount) for line in resolved.ingredients
            ],
            step_texts=list(resolved.steps),
        )
        recipe_updated = True

    RecipeMessage.objects.create(
        recipe=recipe,
        user_message=msg,
        assistant_answer=out.answer,
        gemini_response_raw=out.gemini_response_raw or "",
        recipe_updated=recipe_updated,
    )

    return RecipeChatResult(
        answer=out.answer,
        recipe_updated=recipe_updated,
    )


def list_user_recipes(
    *,
    user_id: int,
    limit: int = DEFAULT_LIST_LIMIT,
    cursor: str | None = None,
) -> tuple[list[Recipe], str | None]:
    """List recipes for *user_id* with cursor pagination (newest ``updated_at`` first).

    Does not prefetch ingredients or steps. Caller should not load those for list views.
    """
    page_size = _clamp_limit(limit)
    qs = Recipe.objects.filter(user_id=user_id).order_by("-updated_at", "-pk")

    if cursor:
        cursor_payload = _decode_list_user_recipes_cursor(cursor)
        updated_at_iso, cursor_recipe_id = _parse_list_user_recipes_cursor_payload(
            cursor_payload,
            expected_user_id=user_id,
        )
        cursor_updated_at = parse_datetime(updated_at_iso)
        if cursor_updated_at is None:
            raise InvalidRecipeListCursorError()
        qs = qs.filter(
            Q(updated_at__lt=cursor_updated_at)
            | Q(updated_at=cursor_updated_at, pk__lt=cursor_recipe_id),
        )

    rows = list(qs[: page_size + 1])
    has_next_page = len(rows) > page_size
    page_recipes = rows[:page_size]

    next_cursor = None
    if has_next_page and page_recipes:
        last = page_recipes[-1]
        next_cursor = _encode_list_user_recipes_cursor(
            {
                _LIST_USER_RECIPES_CURSOR_USER_ID: user_id,
                _LIST_USER_RECIPES_CURSOR_UPDATED_AT: last.updated_at.isoformat(),
                _LIST_USER_RECIPES_CURSOR_RECIPE_ID: last.pk,
            },
        )
    return page_recipes, next_cursor
