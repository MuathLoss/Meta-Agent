import hashlib
import hmac
import json

from app.services.whatsapp_adapter import WhatsAppAdapter


def test_whatsapp_signature_validation():
    body = b'{"hello":"world"}'
    secret = "secret-test"
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert WhatsAppAdapter().valid_signature(raw_body=body, signature_header=sig, app_secret=secret)
    assert not WhatsAppAdapter().valid_signature(raw_body=body, signature_header="sha256=bad", app_secret=secret)


def test_whatsapp_inbound_normalization():
    payload = {
        "entry": [{"changes": [{"value": {"metadata": {"phone_number_id": "phone-test"}, "messages": [{"id": "wamid.1", "from": "966500000000", "text": {"body": "السلام"}}]}}]}]
    }
    msg = WhatsAppAdapter().normalize_inbound(payload)
    assert msg is not None
    assert msg.provider_message_id == "wamid.1"
    assert msg.customer_phone == "966500000000"
    assert msg.phone_number_id == "phone-test"
