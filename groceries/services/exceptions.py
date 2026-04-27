class InvalidProductListCursorError(Exception):
    """Cursor token invalid or used with wrong parameters."""

    def __init__(self, message: str = "Invalid cursor.") -> None:
        super().__init__(message)


class NoOpenBasketError(Exception):
    """No basket with purchased_at unset exists."""

    def __init__(self, message: str = "No open basket.") -> None:
        super().__init__(message)


class InvalidRecipeListCursorError(Exception):
    """Cursor token invalid or used with wrong user."""

    def __init__(self, message: str = "Invalid cursor.") -> None:
        super().__init__(message)


class RecipeGenerationFailedError(Exception):
    """Gemini recipe chat returned no usable reply or API error."""
