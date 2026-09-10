"""Honest setup checks and read-only provider credential verification."""
from datetime import datetime, timezone
import imaplib
import re
import smtplib
import ssl
import httpx
from app.core.config import settings
from app.services.tenant_channel_service import TenantChannelService

REQUIRED = {
    'telegram': [('bot_token', 'Bot token')],
    'whatsapp': [('access_token', 'Access token'), ('phone_number_id', 'Phone number ID'), ('app_secret', 'App secret'), ('verify_token', 'Webhook verification token')],
    'email': [('smtp_host', 'SMTP server'), ('smtp_username', 'SMTP username'), ('smtp_password', 'SMTP password'), ('smtp_from_email', 'Sender email'), ('imap_host', 'IMAP server'), ('imap_username', 'IMAP username'), ('imap_password', 'IMAP password')],
    'instagram': [('page_access_token', 'Page access token'), ('instagram_business_account_id', 'Instagram business account ID'), ('app_secret', 'App secret'), ('verify_token', 'Webhook verification token')],
    'facebook': [('page_access_token', 'Page access token'), ('page_id', 'Page ID'), ('app_secret', 'App secret'), ('verify_token', 'Webhook verification token')],
    'web_chat': [],
}


def configuration(row):
    creds = TenantChannelService().credentials(row) if row else {}
    public = (row.public_config_json or {}) if row else {}
    return {**public, **creds}


def present(value):
    return bool(str(value or '').strip()) and settings.configured(value)


def readiness(row, channel_type=None):
    kind = row.channel_type if row else channel_type
    if kind not in REQUIRED:
        return {'channel_type': kind, 'ready': False, 'missing': ['Unsupported channel'], 'checks': []}
    try:
        config = configuration(row)
    except Exception:
        return {'channel_type': kind, 'ready': False, 'missing': ['Credentials could not be opened; re-enter them'], 'checks': [], 'verification': None}
    checks = [{'key': key, 'label': label, 'passed': present(config.get(key))} for key, label in REQUIRED[kind]]
    missing = [c['label'] for c in checks if not c['passed']]
    public = (row.public_config_json or {}) if row else {}
    return {'channel_type': kind, 'ready': bool(row and not missing and public.get('enabled') is True), 'checks': checks, 'missing': missing,
            'enabled': public.get('enabled') is True, 'live_send_enabled': public.get('live_send_enabled') is True,
            'verification': public.get('connection_check'),
            'automatic_polling': settings.email_polling_enabled if kind == 'email' else None}


def _bool(value, default):
    return value if isinstance(value, bool) else str(value).lower() == 'true' if value is not None else default


def verify(row):
    check = readiness(row)
    if check.get('missing'):
        return {'status': 'missing_details', 'message': 'Add: ' + ', '.join(check['missing'])}
    kind, config = row.channel_type, configuration(row)
    try:
        if kind == 'telegram':
            with httpx.Client(timeout=10) as client:
                response = client.get(f"https://api.telegram.org/bot{config['bot_token']}/getMe")
                response.raise_for_status()
                if response.json().get('ok') is not True:
                    return {'status': 'credentials_rejected', 'message': 'Telegram rejected this token. Replace it with the current token from BotFather.'}
        elif kind in {'whatsapp', 'instagram', 'facebook'}:
            version = str(config.get('graph_api_version') or 'v20.0')
            if not re.fullmatch(r'v\d+\.\d+', version):
                return {'status': 'invalid_details', 'message': 'Enter the API version configured for your Meta app in vNUMBER.0 format.'}
            key = {'whatsapp': 'phone_number_id', 'instagram': 'instagram_business_account_id', 'facebook': 'page_id'}[kind]
            account = str(config[key])
            if not re.fullmatch(r'[0-9]+', account):
                return {'status': 'invalid_details', 'message': 'The provider account ID must contain digits only.'}
            with httpx.Client(timeout=10) as client:
                response = client.get(f'https://graph.facebook.com/{version}/{account}', params={'fields': 'id'}, headers={'Authorization': 'Bearer ' + str(config.get('access_token') or config.get('page_access_token'))})
                response.raise_for_status()
        elif kind == 'email':
            context = ssl.create_default_context()
            smtp_ssl = _bool(config.get('use_ssl'), False)
            if not smtp_ssl and not _bool(config.get('use_tls'), True):
                return {'status': 'invalid_details', 'message': 'Use TLS or SSL before checking email credentials.'}
            client = smtplib.SMTP_SSL(str(config['smtp_host']), int(config.get('smtp_port') or 465), timeout=10, context=context) if smtp_ssl else smtplib.SMTP(str(config['smtp_host']), int(config.get('smtp_port') or 587), timeout=10)
            with client:
                if not smtp_ssl:
                    client.starttls(context=context)
                client.login(str(config['smtp_username']), str(config['smtp_password']))
                client.noop()
            if not _bool(config.get('imap_use_ssl'), True):
                return {'status': 'invalid_details', 'message': 'Enable IMAP SSL before checking email credentials.'}
            with imaplib.IMAP4_SSL(str(config['imap_host']), int(config.get('imap_port') or 993), ssl_context=context, timeout=10) as inbox:
                inbox.login(str(config['imap_username']), str(config['imap_password']))
                inbox.noop()
        return {'status': 'credentials_verified', 'message': 'Connection check passed. No customer message was sent. Test real inbound and outbound delivery separately.' if kind != 'web_chat' else 'Web chat is configured. Use a virtual test to check your answers.'}
    except (smtplib.SMTPAuthenticationError, imaplib.IMAP4.error):
        return {'status': 'credentials_rejected', 'message': 'Email login failed. Check your app password and SMTP/IMAP access.'}
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if kind == 'telegram' and status in {401, 403}:
            return {'status': 'credentials_rejected', 'message': 'Telegram rejected this bot token. Replace it with the current token from the official BotFather, save, and check again.'}
        return {'status': 'credentials_rejected' if status in {400, 401, 403} else 'provider_unavailable', 'message': 'The provider rejected the connection. Check credentials, account permissions, and API version.'}
    except Exception:
        return {'status': 'provider_unavailable', 'message': 'Could not reach the provider. Check server details and network access, then try again.'}


def stamped_verify(row):
    return {**verify(row), 'checked_at': datetime.now(timezone.utc).isoformat()}
