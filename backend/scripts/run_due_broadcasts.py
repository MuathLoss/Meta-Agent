from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.db import SessionLocal
from app.services.broadcast_service import BroadcastService


def main() -> None:
    service = BroadcastService()
    with SessionLocal() as db:
        results = service.process_due_broadcasts(db)
        db.commit()
    print({"processed": len(results), "results": [r.__dict__ for r in results]})


if __name__ == "__main__":
    main()
