"""UTM and tracking-URL filter helpers for campaign analytics."""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any
from urllib.parse import parse_qs, urlparse

UTM_FIELD_NAMES = (
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_content",
    "utm_term",
    "user_id",
)

STORE_FILTER_FIELDS = (
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "user_id",
)

ROW_KEY_ALIASES: dict[str, tuple[str, ...]] = {
    "utm_source": ("utm_source", "Source", "source"),
    "utm_medium": ("utm_medium", "Medium", "medium"),
    "utm_campaign": ("utm_campaign", "Campaign", "campaign"),
    "utm_content": ("utm_content", "Content", "content"),
    "utm_term": ("utm_term", "Term", "term"),
    "user_id": ("user_id", "UserId", "kunden_id"),
}


@dataclass
class UtmFilter:
    utm_source: str = ""
    utm_medium: str = ""
    utm_campaign: str = ""
    utm_content: str = ""
    utm_term: str = ""
    user_id: str = ""

    def active_fields(self) -> dict[str, str]:
        return {
            name: value
            for name in UTM_FIELD_NAMES
            if (value := str(getattr(self, name) or "").strip())
        }

    def is_active(self) -> bool:
        return bool(self.active_fields())


def _first_query_value(query: dict[str, list[str]], key: str) -> str:
    values = query.get(key) or []
    if not values:
        return ""
    return str(values[0] or "").strip()


def parse_tracking_url(url: str) -> UtmFilter:
    raw = (url or "").strip()
    if not raw:
        return UtmFilter()
    if "://" not in raw:
        raw = f"https://placeholder.local/{raw.lstrip('/')}"
    query = parse_qs(urlparse(raw).query)
    return UtmFilter(
        utm_source=_first_query_value(query, "utm_source"),
        utm_medium=_first_query_value(query, "utm_medium"),
        utm_campaign=_first_query_value(query, "utm_campaign"),
        utm_content=_first_query_value(query, "utm_content"),
        utm_term=_first_query_value(query, "utm_term"),
        user_id=_first_query_value(query, "user_id"),
    )


def utm_filter_from_query(query: dict[str, list[str]]) -> UtmFilter:
    return UtmFilter(
        utm_source=str((query.get("utm_source", [""])[0] or "")).strip(),
        utm_medium=str((query.get("utm_medium", [""])[0] or "")).strip(),
        utm_campaign=str((query.get("utm_campaign", [""])[0] or "")).strip(),
        utm_content=str((query.get("utm_content", [""])[0] or "")).strip(),
        utm_term=str((query.get("utm_term", [""])[0] or "")).strip(),
        user_id=str((query.get("user_id", [""])[0] or "")).strip(),
    )


def _row_value(row: dict[str, Any], field_name: str) -> str:
    for key in ROW_KEY_ALIASES.get(field_name, (field_name,)):
        if key in row:
            return str(row.get(key) or "").strip()
    return ""


def _matches_fields(row: dict[str, Any], filt: UtmFilter | None, field_names: tuple[str, ...]) -> bool:
    if filt is None or not filt.is_active():
        return True
    active = filt.active_fields()
    for name in field_names:
        expected = active.get(name)
        if not expected:
            continue
        actual = _row_value(row, name)
        if actual != expected:
            return False
    return True


def matches_row(row: dict[str, Any], filt: UtmFilter | None) -> bool:
    return _matches_fields(row, filt, UTM_FIELD_NAMES)


def matches_store_row(row: dict[str, Any], filt: UtmFilter | None) -> bool:
    return _matches_fields(row, filt, STORE_FILTER_FIELDS)


def matches_url_query(url: str, filt: UtmFilter | None) -> bool:
    if filt is None or not filt.is_active():
        return True
    parsed = parse_tracking_url(url)
    for name, expected in filt.active_fields().items():
        actual = str(getattr(parsed, name) or "").strip()
        if actual != expected:
            return False
    return True


def to_query_params(filt: UtmFilter | None) -> dict[str, str]:
    if filt is None:
        return {}
    return filt.active_fields()


def parse_bool_query(value: str) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def filter_to_dict(filt: UtmFilter | None) -> dict[str, str]:
    if filt is None:
        return {}
    return {field.name: str(getattr(filt, field.name) or "").strip() for field in fields(UtmFilter)}
