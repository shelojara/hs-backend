"""Groceries domain services (split by area; import from ``groceries.services``)."""

from backend.email_services import send_email_via_gmail
from django.utils import timezone
from django_q.tasks import async_task

from groceries import gemini_service
from .favicon_service import fetch_favicon_url

from .baskets import (
    add_product_to_basket,
    basket_product_lines,
    delete_product_from_basket,
    get_current_basket,
    get_current_basket_with_products,
    list_purchased_baskets,
    list_purchased_baskets_for_running_low,
    purchase_latest_open_basket,
    purchase_single_product,
    recalculate_product_purchase_counts_from_baskets,
    set_product_purchase_in_open_basket,
)
from .constants import (
    DEFAULT_LIST_LIMIT,
    LIST_PURCHASED_BASKETS_LIMIT,
    MAX_LIST_LIMIT,
    RUNNING_LOW_MANUAL_SNOOZE_DAYS,
)
from .exceptions import (
    InvalidProductListCursorError,
    InvalidRecipeListCursorError,
    NoOpenBasketError,
    RecipeChatResult,
    RecipeGenerationFailedError,
)
from .merchants import (
    create_user_merchant,
    delete_user_merchant,
    list_user_merchants,
    update_user_merchant,
)
from .products import (
    CatalogInCatalogCheck,
    candidate_in_user_catalog_by_standard_name,
    create_product_from_candidate,
    delete_product,
    list_products,
    load_user_catalog_standard_names_normalized,
    make_user_catalog_in_catalog_check,
    mark_product_not_running_low,
    recipe_ingredient_in_catalog_flags,
    recheck_product_price,
    running_low_sync_user_ids,
    update_product,
)
from .recipes import (
    create_recipe_from_title_and_notes,
    delete_recipe,
    get_recipe,
    list_recipe_messages,
    list_user_recipes,
    recipe_chat_about_recipe,
    run_recipe_gemini_job,
    update_recipe,
)
from .running_low import sync_running_low_flags_for_user
from .search import (
    create_search,
    delete_search,
    get_search,
    list_searches,
    retry_empty_completed_search,
    run_product_search_job,
    search_result_candidates_as_product_schemas,
)

__all__ = [
    "async_task",
    "DEFAULT_LIST_LIMIT",
    "gemini_service",
    "LIST_PURCHASED_BASKETS_LIMIT",
    "MAX_LIST_LIMIT",
    "RUNNING_LOW_MANUAL_SNOOZE_DAYS",
    "CatalogInCatalogCheck",
    "InvalidProductListCursorError",
    "InvalidRecipeListCursorError",
    "NoOpenBasketError",
    "RecipeChatResult",
    "RecipeGenerationFailedError",
    "add_product_to_basket",
    "basket_product_lines",
    "candidate_in_user_catalog_by_standard_name",
    "create_product_from_candidate",
    "create_recipe_from_title_and_notes",
    "create_search",
    "create_user_merchant",
    "delete_product",
    "delete_product_from_basket",
    "delete_recipe",
    "delete_search",
    "delete_user_merchant",
    "fetch_favicon_url",
    "get_current_basket",
    "get_current_basket_with_products",
    "get_recipe",
    "get_search",
    "list_products",
    "list_purchased_baskets",
    "list_purchased_baskets_for_running_low",
    "list_recipe_messages",
    "list_searches",
    "list_user_merchants",
    "list_user_recipes",
    "load_user_catalog_standard_names_normalized",
    "make_user_catalog_in_catalog_check",
    "mark_product_not_running_low",
    "purchase_latest_open_basket",
    "purchase_single_product",
    "recipe_chat_about_recipe",
    "recipe_ingredient_in_catalog_flags",
    "recalculate_product_purchase_counts_from_baskets",
    "recheck_product_price",
    "retry_empty_completed_search",
    "run_product_search_job",
    "run_recipe_gemini_job",
    "running_low_sync_user_ids",
    "search_result_candidates_as_product_schemas",
    "set_product_purchase_in_open_basket",
    "send_email_via_gmail",
    "sync_running_low_flags_for_user",
    "timezone",
    "update_product",
    "update_recipe",
    "update_user_merchant",
]
