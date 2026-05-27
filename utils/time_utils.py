from datetime import datetime, timezone


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ms_to_iso(ms: int | float | None) -> str | None:
    if not ms:
        return None
    return datetime.fromtimestamp(float(ms) / 1000, timezone.utc).replace(microsecond=0).isoformat()


def age_hours_from_ms(ms: int | float | None) -> float | None:
    if not ms:
        return None
    created = datetime.fromtimestamp(float(ms) / 1000, timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - created).total_seconds() / 3600)
