"""Recipe, RecipeIngredient, RecipeStep persistence."""

import pytest
from django.contrib.auth import get_user_model

from groceries.models import Product, Recipe, RecipeIngredient, RecipeStep

User = get_user_model()


@pytest.mark.django_db
def test_recipe_ingredients_and_steps_ordering():
    u = User.objects.create_user(username="recipe_models_u", password="pw")
    p = Product.objects.create(user=u, name="flour")
    r = Recipe.objects.create(user=u, title="Bread")

    RecipeIngredient.objects.create(recipe=r, order=1, name="water", amount="1 cup")
    RecipeIngredient.objects.create(recipe=r, order=0, name="flour", amount="500g", product=p)
    RecipeStep.objects.create(recipe=r, order=1, text="Knead.")
    RecipeStep.objects.create(recipe=r, order=0, text="Mix dry.")

    assert list(r.ingredients.values_list("name", flat=True)) == ["flour", "water"]
    assert list(r.steps.values_list("text", flat=True)) == ["Mix dry.", "Knead."]
    assert RecipeIngredient.objects.get(recipe=r, name="flour").product_id == p.pk
