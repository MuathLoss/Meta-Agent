from pathlib import Path
import sys

from sqlalchemy import inspect, text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.db import engine


def has_column(inspector, table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def run() -> None:
    inspector = inspect(engine)
    with engine.begin() as conn:
        if not has_column(inspector, "faq_items", "english_question"):
            conn.execute(text("ALTER TABLE faq_items ADD COLUMN english_question TEXT"))
        if not has_column(inspector, "faq_items", "english_answer"):
            conn.execute(text("ALTER TABLE faq_items ADD COLUMN english_answer TEXT"))
        if not has_column(inspector, "intent_definitions", "supported_languages"):
            conn.execute(text("ALTER TABLE intent_definitions ADD COLUMN supported_languages VARCHAR(20) DEFAULT 'ar'"))
            conn.execute(text("UPDATE intent_definitions SET supported_languages = 'ar' WHERE supported_languages IS NULL"))
        if not has_column(inspector, "intent_definitions", "response_mode"):
            conn.execute(text("ALTER TABLE intent_definitions ADD COLUMN response_mode VARCHAR(20) DEFAULT 'faq'"))
            conn.execute(text("UPDATE intent_definitions SET response_mode = 'faq' WHERE response_mode IS NULL"))
        if not has_column(inspector, "intent_definitions", "custom_response_ar"):
            conn.execute(text("ALTER TABLE intent_definitions ADD COLUMN custom_response_ar TEXT"))
        if not has_column(inspector, "intent_definitions", "custom_response_en"):
            conn.execute(text("ALTER TABLE intent_definitions ADD COLUMN custom_response_en TEXT"))


if __name__ == "__main__":
    run()
    print("FAQ/Intents phase-1 migration completed.")
