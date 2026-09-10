from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.db import SessionLocal
from app.services.telegram_polling_service import TelegramPollingService


def run_once(disable_webhook: bool, service: TelegramPollingService | None = None) -> None:
    service = service or TelegramPollingService()
    with SessionLocal() as db:
        results = service.poll_once(db, disable_webhook=disable_webhook)
        db.commit()
    print({"polled_channels": len(results), "results": [r.__dict__ for r in results]}, flush=True)


def run_loop(interval: float, disable_webhook: bool) -> None:
    sleep_seconds = max(interval, 0.5)

    service = TelegramPollingService()
    while True:
        try:
            run_once(disable_webhook=disable_webhook, service=service)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            print(
                {
                    "status": "polling_error",
                    "error_type": type(exc).__name__,
                    "error": "Provider connection failed. Check Channels for connection details.",
                    "retry_in_seconds": sleep_seconds,
                },
                file=sys.stderr,
                flush=True,
            )
        time.sleep(sleep_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Poll Telegram updates for tenant-scoped channels.")
    parser.add_argument("--loop", action="store_true", help="Keep polling forever.")
    parser.add_argument("--interval", type=float, default=2.0, help="Seconds to sleep between polling iterations in loop mode.")
    parser.add_argument("--keep-webhook", action="store_true", help="Do not disable Telegram webhook before polling.")
    args = parser.parse_args()

    disable_webhook = not args.keep_webhook
    if not args.loop:
        run_once(disable_webhook=disable_webhook)
        return

    run_loop(interval=args.interval, disable_webhook=disable_webhook)


if __name__ == "__main__":
    main()
