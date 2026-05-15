from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.db import engine
from app.models.entities import Base
from scripts.migrate_conversation_metadata_phase2 import run as run_conversation_metadata_phase2_migration
from scripts.migrate_faq_intents_phase1 import run as run_faq_intent_phase1_migration

if __name__ == "__main__":
    Base.metadata.create_all(bind=engine)
    # Keep older local databases compatible when models gain new nullable columns.
    run_faq_intent_phase1_migration()
    run_conversation_metadata_phase2_migration()
    print("Database tables created/verified.")
