from app.services.telegram_adapter import TelegramAdapter


def test_telegram_inbound_normalization():
    payload = {
        "update_id": 1001,
        "message": {
            "message_id": 77,
            "chat": {"id": 99887766, "type": "private"},
            "text": "السلام عليكم",
        },
    }
    msg = TelegramAdapter().normalize_inbound(payload)
    assert msg is not None
    assert msg.provider_message_id == "telegram-update-1001"
    assert msg.customer_address == "99887766"
    assert msg.chat_id == "99887766"
    assert msg.text == "السلام عليكم"


def test_telegram_secret_validation():
    adapter = TelegramAdapter()
    assert adapter.valid_secret_token("tenant-secret", "tenant-secret")
    assert not adapter.valid_secret_token("wrong", "tenant-secret")


def test_telegram_expected_verification_token_falls_back_to_bot_token():
    adapter = TelegramAdapter()
    assert adapter.expected_verification_token({"bot_token": "123:abc"}) == "123:abc"
    assert adapter.expected_verification_token({"bot_token": "123:abc", "secret_token": "tenant-secret"}) == "tenant-secret"
