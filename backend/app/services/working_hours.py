from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo
from sqlalchemy.orm import Session
from app.models.entities import Branch, BusinessSetting, Tenant


def _parse_hhmm(value: str) -> time | None:
    try:
        hour, minute = value.strip().split(":", 1)
        return time(int(hour), int(minute))
    except Exception:
        return None


def _periods_from_hours_json(hours_json: dict) -> list[tuple[time, time]]:
    periods: list[tuple[time, time]] = []
    raw_periods = hours_json.get("periods") if isinstance(hours_json, dict) else None
    if isinstance(raw_periods, list):
        for item in raw_periods:
            if not isinstance(item, dict):
                continue
            start = _parse_hhmm(str(item.get("from") or item.get("start") or ""))
            end = _parse_hhmm(str(item.get("to") or item.get("end") or ""))
            if start and end:
                periods.append((start, end))

    # Also support simple dashboard JSON like {"morning":"09:00-13:00"}
    for value in (hours_json or {}).values():
        if isinstance(value, str) and "-" in value:
            left, right = value.split("-", 1)
            start = _parse_hhmm(left)
            end = _parse_hhmm(right)
            if start and end:
                periods.append((start, end))
    return periods


def is_inside_working_hours(db: Session, tenant: Tenant, now: datetime | None = None) -> bool:
    """Returns True when at least one active branch is currently open.

    This is intentionally tenant-scoped and channel-independent. The academy hours are seeded
    into the branch record, but the platform core does not hardcode academy timings.
    """
    policy = db.query(BusinessSetting).filter(BusinessSetting.tenant_id == tenant.id, BusinessSetting.key == "out_of_hours_policy").first()
    policy_json = policy.value_json if policy else {}
    if policy_json.get("disabled") is True or policy_json.get("force_open") is True:
        return True

    tz = ZoneInfo(tenant.timezone or "Asia/Riyadh")
    current = now.astimezone(tz) if now else datetime.now(tz)
    current_time = current.time()
    branches = db.query(Branch).filter(Branch.tenant_id == tenant.id, Branch.is_active.is_(True)).all()
    if not branches:
        return True
    for branch in branches:
        for start, end in _periods_from_hours_json(branch.hours_json or {}):
            if start <= end:
                if start <= current_time <= end:
                    return True
            else:
                # Overnight period support, e.g. 22:00-02:00.
                if current_time >= start or current_time <= end:
                    return True
    return False


def should_auto_reply_out_of_hours(db: Session, tenant: Tenant) -> bool:
    policy = db.query(BusinessSetting).filter(BusinessSetting.tenant_id == tenant.id, BusinessSetting.key == "out_of_hours_policy").first()
    policy_json = policy.value_json if policy else {}
    return policy_json.get("mode") == "auto_reply_only"
