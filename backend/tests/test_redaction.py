from app.core.redaction import REDACTED, redact_sensitive


def test_redaction_helper_removes_nested_sensitive_keys():
    payload = {
        "ok": True,
        "access_token": "token-secret",
        "nested": {
            "Authorization": "Bearer nested-secret",
            "phone_number_id": "phone-secret",
            "items": [{"bot_token": "123:abc"}, {"safe": "value"}],
        },
    }

    redacted = redact_sensitive(payload)

    assert redacted["access_token"] == REDACTED
    assert redacted["nested"]["Authorization"] == REDACTED
    assert redacted["nested"]["phone_number_id"] == REDACTED
    assert redacted["nested"]["items"][0]["bot_token"] == REDACTED
    assert redacted["nested"]["items"][1]["safe"] == "value"


def test_redaction_helper_handles_lists_and_strings_safely():
    payload = [
        "Bearer secret-token",
        "https://example.test/hook?access_token=abc123&ok=1",
        "postgresql://user:pass@localhost/app",
        {"safe": "https://example.test/path?ok=1"},
    ]

    redacted = redact_sensitive(payload)

    assert redacted[0] == "Bearer [REDACTED]"
    assert "abc123" not in redacted[1]
    assert "access_token=[REDACTED]" in redacted[1]
    assert redacted[2] == REDACTED
    assert redacted[3]["safe"] == "https://example.test/path?ok=1"
