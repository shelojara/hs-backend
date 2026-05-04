"""Drive API error text helpers."""

import json

import pytest
from googleapiclient.errors import HttpError


@pytest.mark.parametrize(
    ("payload", "expect_substrings"),
    [
        (
            {
                "error": {
                    "message": "Service Accounts do not have storage quota.",
                    "errors": [{"reason": "storageQuotaExceeded"}],
                },
            },
            ("Service Accounts do not have storage quota", "Apr 2025", "Shared drive"),
        ),
    ],
)
def test_drive_http_error_message_appends_sa_quota_hint(payload, expect_substrings):
    from manga.google_drive_service import drive_http_error_message

    content = json.dumps(payload).encode()
    exc = HttpError(resp=type("R", (), {"status": 403, "reason": "Forbidden"})(), content=content)
    out = drive_http_error_message(exc)
    for s in expect_substrings:
        assert s in out
