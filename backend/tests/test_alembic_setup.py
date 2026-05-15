from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.models.entities import Base


def test_alembic_has_one_head_and_metadata_loads():
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    script = ScriptDirectory.from_config(config)

    assert script.get_heads() == ["20260515_0001"]
    assert len(Base.metadata.tables) == 20
    assert "tenants" in Base.metadata.tables
    assert "webhook_events" in Base.metadata.tables


def test_baseline_revision_imports_successfully():
    backend_dir = Path(__file__).resolve().parents[1]
    revision_path = backend_dir / "migrations" / "versions" / "20260515_0001_baseline.py"
    spec = spec_from_file_location("baseline_revision", revision_path)
    assert spec is not None
    assert spec.loader is not None

    module = module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.revision == "20260515_0001"
    assert module.down_revision is None
    assert callable(module.upgrade)
