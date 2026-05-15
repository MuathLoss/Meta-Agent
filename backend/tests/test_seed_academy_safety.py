import pytest

from app.seed import seed_academy


def test_seed_academy_refuses_to_run_in_staging_or_production(monkeypatch):
    monkeypatch.setattr(seed_academy.settings, "app_env", "production")

    def fail_if_called(*args, **kwargs):
        raise AssertionError("seed must fail before touching database setup")

    monkeypatch.setattr(seed_academy.Base.metadata, "create_all", fail_if_called)

    with pytest.raises(RuntimeError) as exc:
        seed_academy.main()

    assert "local/dev-only" in str(exc.value)


def test_seed_academy_local_dev_guard_and_demo_password_still_work(monkeypatch):
    monkeypatch.setattr(seed_academy.settings, "app_env", "development")
    monkeypatch.setattr(seed_academy, "DEMO_PASSWORD", "LocalOnly123!")

    seed_academy.ensure_local_seed_allowed()

    assert seed_academy.demo_password() == "LocalOnly123!"


def test_seed_academy_rejects_short_demo_password(monkeypatch):
    monkeypatch.setattr(seed_academy, "DEMO_PASSWORD", "short")

    with pytest.raises(RuntimeError):
        seed_academy.demo_password()
