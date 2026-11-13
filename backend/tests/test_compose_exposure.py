"""Spec v1.2, Phase 0 and Section 13: only ports 80/443 are public; PostgreSQL and Redis are
never published; the 8 GB pilot server keeps headroom. Reads the compose files next to backend/."""
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
PROD = REPO / "docker-compose.prod.yml"
STAGING = REPO / "docker-compose.staging.yml"
pytestmark = pytest.mark.skipif(not PROD.exists(), reason="compose files are not mounted next to backend/")

LONG_RUNNING = {"caddy", "frontend", "backend", "worker", "postgres", "redis"}
MEMORY_UNITS = {"k": 1 / 1024, "m": 1, "g": 1024}


def services(path: Path) -> dict:
    return yaml.safe_load(path.read_text())["services"]


def memory_mb(value: str) -> float:
    value = value.strip().lower()
    return float(value[:-1]) * MEMORY_UNITS[value[-1]]


def test_production_publishes_only_caddy_on_80_and_443():
    published = {name: svc.get("ports", []) for name, svc in services(PROD).items() if svc.get("ports")}
    assert set(published) == {"caddy"}
    assert {str(port).split(":")[0] for port in published["caddy"]} == {"80", "443"}


def test_production_database_and_queue_are_on_the_internal_network_only():
    compose = yaml.safe_load(PROD.read_text())
    assert compose["networks"]["data"]["internal"] is True
    for name in ("postgres", "redis"):
        assert compose["services"][name]["networks"] == ["data"]
        assert "ports" not in compose["services"][name]
        assert "expose" not in compose["services"][name]


def test_production_redis_requires_a_password():
    command = " ".join(services(PROD)["redis"]["command"])
    assert "--requirepass" in command
    assert "noeviction" in command


def test_production_services_have_health_checks_and_memory_limits():
    prod = services(PROD)
    assert LONG_RUNNING <= set(prod)
    for name in LONG_RUNNING:
        assert "healthcheck" in prod[name], name
        assert prod[name]["deploy"]["resources"]["limits"]["memory"], name


def test_production_memory_limits_leave_half_of_8_gb_free():
    total = sum(memory_mb(services(PROD)[name]["deploy"]["resources"]["limits"]["memory"]) for name in LONG_RUNNING)
    assert total <= 4096


def test_production_has_no_out_of_scope_services():
    images = " ".join(str(svc.get("image", "")) for svc in services(PROD).values()).lower()
    for unwanted in ("ollama", "garage", "minio", "n8n", "telegram"):
        assert unwanted not in images
    assert "telegram" not in services(PROD)


def test_staging_publishes_only_the_dashboard_on_localhost():
    published = {name: svc.get("ports", []) for name, svc in services(STAGING).items() if svc.get("ports")}
    assert set(published) == {"frontend"}
    assert all(str(port).startswith("127.0.0.1:") for port in published["frontend"])


@pytest.mark.parametrize("path", [PROD, STAGING], ids=["prod", "staging"])
def test_product_scope_is_pinned_in_compose(path):
    environment = yaml.safe_load(path.read_text())["x-backend"]["environment"]
    assert environment["ENABLED_CHANNELS"] == "web_chat,whatsapp"
    assert environment["BROADCASTS_ENABLED"] == "false"
    assert environment["OLLAMA_ENABLED"] == "false"
