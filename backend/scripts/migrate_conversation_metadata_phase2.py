from __future__ import annotations

from sqlalchemy import inspect, text

from app.core.db import engine


def run() -> None:
    inspector = inspect(engine)
    if "conversations" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("conversations")}
    with engine.begin() as conn:
        if "metadata_json" not in columns:
            conn.execute(text("ALTER TABLE conversations ADD COLUMN metadata_json JSON"))


if __name__ == "__main__":
    run()
    print("Conversation metadata migration completed.")
