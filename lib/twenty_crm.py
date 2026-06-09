"""Twenty CRM REST client for admin campaign flows."""

from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

from lib.campaign_store import get_unsubscribed_emails, last_contact_index


TWENTY_API_URL_ENV = "TWENTY_API_URL"
TWENTY_API_KEY_ENV = "TWENTY_CRM_API_KEY"
TWENTY_PAGE_SIZE_ENV = "TWENTY_PEOPLE_PAGE_SIZE"
TWENTY_SSL_VERIFY_ENV = "TWENTY_SSL_VERIFY"

FIELD_EMAIL_STATE_ENV = "TWENTY_FIELD_EMAIL_STATE"
FIELD_LAST_CONTACTED_AT_ENV = "TWENTY_FIELD_LAST_CONTACTED_AT"
FIELD_KUNDEN_ID_ENV = "TWENTY_FIELD_KUNDEN_ID"
FIELD_LAST_CONTACT_CAMPAIGN_ENV = "TWENTY_FIELD_LAST_CONTACT_CAMPAIGN"
FIELD_SENT_CAMPAIGNS_ENV = "TWENTY_FIELD_SENT_CAMPAIGNS"

DEFAULT_FIELD_EMAIL_STATE = "emailState"
DEFAULT_FIELD_LAST_CONTACTED_AT = "lastContactedAt"
DEFAULT_FIELD_KUNDEN_ID = "kundenId"
DEFAULT_FIELD_LAST_CONTACT_CAMPAIGN = "lastContactCampaign"
DEFAULT_FIELD_SENT_CAMPAIGNS = "sentCampaigns"

EMAIL_STATE_BLOCKED = frozenset(
    {"paused", "unsubscribed", "bounced", "replied", "cold_disqualified"}
)

_PERSON_OBJECT_METADATA_ID: str | None = None


def _field_name(env_key: str, default: str) -> str:
    return os.getenv(env_key, default).strip() or default


def field_email_state() -> str:
    return _field_name(FIELD_EMAIL_STATE_ENV, DEFAULT_FIELD_EMAIL_STATE)


def field_last_contacted_at() -> str:
    return _field_name(FIELD_LAST_CONTACTED_AT_ENV, DEFAULT_FIELD_LAST_CONTACTED_AT)


def field_kunden_id() -> str:
    return _field_name(FIELD_KUNDEN_ID_ENV, DEFAULT_FIELD_KUNDEN_ID)


def field_last_contact_campaign() -> str:
    return _field_name(FIELD_LAST_CONTACT_CAMPAIGN_ENV, DEFAULT_FIELD_LAST_CONTACT_CAMPAIGN)


def field_sent_campaigns() -> str:
    return _field_name(FIELD_SENT_CAMPAIGNS_ENV, DEFAULT_FIELD_SENT_CAMPAIGNS)


def get_twenty_config() -> tuple[str, str]:
    base_url = os.getenv(TWENTY_API_URL_ENV, "").strip().rstrip("/")
    api_key = os.getenv(TWENTY_API_KEY_ENV, "").strip() or os.getenv("TWENTY_API_KEY", "").strip()
    if not base_url or not api_key:
        raise RuntimeError("Missing TWENTY_API_URL or TWENTY_CRM_API_KEY")
    return base_url, api_key


def _ssl_context() -> ssl.SSLContext | None:
    raw = os.getenv(TWENTY_SSL_VERIFY_ENV, "true").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return None
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _page_size() -> int:
    try:
        size = int(os.getenv(TWENTY_PAGE_SIZE_ENV, "60").strip() or "60")
    except ValueError:
        size = 60
    return max(1, min(size, 60))


def twenty_request(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    query: dict[str, str] | None = None,
) -> tuple[int, Any]:
    base_url, api_key = get_twenty_config()
    url = f"{base_url}{path}"
    if query:
        url = f"{url}?{urllib.parse.urlencode(query)}"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")

    context = _ssl_context()
    for attempt in range(1, 6):
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            opener = urllib.request.urlopen
            kwargs: dict[str, Any] = {"timeout": 30}
            if context is not None:
                kwargs["context"] = context
            with opener(req, **kwargs) as response:
                raw = response.read().decode("utf-8", errors="replace")
                return response.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as err:
            raw = err.read().decode("utf-8", errors="replace")
            try:
                body = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                body = {"message": raw}
            if err.code == 429 and attempt < 5:
                time.sleep(min(2.0 * attempt, 10.0))
                continue
            return err.code, body
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            if attempt < 5:
                time.sleep(min(2.0 * attempt, 10.0))
                continue
            return 503, {"message": f"Twenty request failed: {err!s}"}
    return 503, {"message": "Twenty request failed after retries"}


def _extract_people_list(body: Any) -> list[dict[str, Any]]:
    if not isinstance(body, dict):
        return []
    data = body.get("data")
    if isinstance(data, dict):
        people = data.get("people")
        if isinstance(people, list):
            return [item for item in people if isinstance(item, dict)]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    people = body.get("people")
    if isinstance(people, list):
        return [item for item in people if isinstance(item, dict)]
    return []


def _extract_person(body: Any) -> dict[str, Any] | None:
    if not isinstance(body, dict):
        return None
    data = body.get("data")
    if isinstance(data, dict):
        for key in ("person", "updatePerson", "createPerson"):
            person = data.get(key)
            if isinstance(person, dict):
                return person
    return body if body.get("id") else None


def _page_info(body: Any) -> dict[str, Any]:
    if isinstance(body, dict):
        page_info = body.get("pageInfo")
        if isinstance(page_info, dict):
            return page_info
    return {}


def _person_email(record: dict[str, Any]) -> str:
    emails = record.get("emails") if isinstance(record.get("emails"), dict) else {}
    primary = str(emails.get("primaryEmail") or "").strip().lower()
    if primary:
        return primary
    return str(record.get("mail") or "").strip().lower()


def _person_company(record: dict[str, Any]) -> str:
    company = str(record.get("firma") or "").strip()
    if company:
        return company
    nested = record.get("company")
    if isinstance(nested, dict):
        return str(nested.get("name") or "").strip()
    return ""


def _person_name(record: dict[str, Any]) -> tuple[str, str]:
    name = record.get("name") if isinstance(record.get("name"), dict) else {}
    first = str(name.get("firstName") or "").strip()
    last = str(name.get("lastName") or "").strip()
    return first, last


def _custom_value(record: dict[str, Any], field_name: str) -> str:
    value = record.get(field_name)
    if value is None:
        return ""
    return str(value).strip()


def normalize_person(record: dict[str, Any]) -> dict[str, Any]:
    first_name, last_name = _person_name(record)
    email = _person_email(record)
    email_state = _custom_value(record, field_email_state()).lower() or "new"
    return {
        "person_id": str(record.get("id") or "").strip(),
        "email": email,
        "first_name": first_name,
        "last_name": last_name,
        "company": _person_company(record),
        "email_state": email_state,
        "last_contacted_at": _custom_value(record, field_last_contacted_at()),
        "kunden_id": _custom_value(record, field_kunden_id()),
        "last_contact_campaign": _custom_value(record, field_last_contact_campaign()),
        "sent_campaigns": _parse_sent_campaigns(_custom_value(record, field_sent_campaigns())),
    }


def _parse_sent_campaigns(raw: str) -> list[str]:
    text = (raw or "").strip()
    if not text:
        return []
    return [part.strip() for part in text.split(",") if part.strip()]


def _merge_last_contacted(person: dict[str, Any], store_index: dict[str, str]) -> str:
    twenty_value = person.get("last_contacted_at") or ""
    store_value = store_index.get(person.get("person_id") or "", "")
    if not twenty_value:
        return store_value
    if not store_value:
        return twenty_value
    try:
        twenty_dt = datetime.fromisoformat(twenty_value.replace("Z", "+00:00"))
        store_dt = datetime.fromisoformat(store_value.replace("Z", "+00:00"))
        return twenty_value if twenty_dt >= store_dt else store_value
    except ValueError:
        return twenty_value or store_value


def blocked_reason(person: dict[str, Any], unsubscribed_emails: set[str]) -> str | None:
    email = (person.get("email") or "").strip().lower()
    if email and email in unsubscribed_emails:
        return "supabase_unsubscribed"
    state = (person.get("email_state") or "").strip().lower()
    if state in EMAIL_STATE_BLOCKED:
        return state
    return None


def is_sendable(person: dict[str, Any], unsubscribed_emails: set[str] | None = None) -> bool:
    emails = unsubscribed_emails if unsubscribed_emails is not None else get_unsubscribed_emails()
    return blocked_reason(person, emails) is None


def list_people() -> list[dict[str, Any]]:
    page_size = _page_size()
    all_people: list[dict[str, Any]] = []
    starting_after = ""
    while True:
        query: dict[str, str] = {"limit": str(page_size), "depth": "1"}
        if starting_after:
            query["starting_after"] = starting_after
        status, body = twenty_request("GET", "/rest/people", query=query)
        if status != 200:
            raise RuntimeError(f"Twenty people list failed ({status}): {body}")
        batch = _extract_people_list(body)
        all_people.extend(batch)
        page_info = _page_info(body)
        if not page_info.get("hasNextPage"):
            break
        starting_after = str(page_info.get("endCursor") or "").strip()
        if not starting_after:
            break
        time.sleep(0.15)
    return all_people


def get_person(person_id: str) -> dict[str, Any] | None:
    status, body = twenty_request("GET", f"/rest/people/{person_id}", query={"depth": "0"})
    if status != 200:
        return None
    person = _extract_person(body)
    return normalize_person(person) if person else None


def patch_person(person_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    status, body = twenty_request("PATCH", f"/rest/people/{person_id}", payload=payload)
    if status not in (200, 201):
        raise RuntimeError(f"Twenty patch failed ({status}): {body}")
    person = _extract_person(body)
    return normalize_person(person) if person else None


def create_person(payload: dict[str, Any]) -> dict[str, Any] | None:
    status, body = twenty_request("POST", "/rest/people", payload=payload)
    if status not in (200, 201):
        raise RuntimeError(f"Twenty create failed ({status}): {body}")
    person = _extract_person(body)
    return normalize_person(person) if person else None


def create_lead_from_intake(
    *,
    email: str,
    first_name: str = "",
    last_name: str = "",
    company: str = "",
    consent_source: str = "Visitenkarte",
    sequence: str = "business_card_intro",
) -> dict[str, Any]:
    normalized_email = (email or "").strip().lower()
    if not normalized_email:
        raise ValueError("Missing email")

    existing = find_person_by_email(normalized_email)
    if existing:
        return {"created": False, "person": existing}

    payload: dict[str, Any] = {
        "name": {
            "firstName": (first_name or "").strip() or "Lead",
            "lastName": (last_name or "").strip(),
        },
        "emails": {"primaryEmail": normalized_email},
        "firma": (company or "").strip(),
        field_email_state(): "new",
        field_last_contact_campaign(): sequence,
    }
    person = create_person(payload)
    if not person:
        raise RuntimeError("Twenty create returned no person")
    return {"created": True, "person": person, "consentSource": consent_source}


def find_person_by_email(email: str) -> dict[str, Any] | None:
    target = (email or "").strip().lower()
    if not target:
        return None
    for record in list_people():
        if _person_email(record) == target:
            return normalize_person(record)
    return None


def find_person_by_id_or_email(person_id: str = "", email: str = "") -> dict[str, Any] | None:
    cleaned_id = (person_id or "").strip()
    if cleaned_id:
        person = get_person(cleaned_id)
        if person:
            return person
    return find_person_by_email(email)


def mark_person_email_state(person_id: str, email_state: str) -> dict[str, Any] | None:
    return patch_person(person_id, {field_email_state(): email_state})


def mark_person_last_contacted(
    person_id: str,
    contacted_at: str | None = None,
    campaign: str = "",
    email_state: str = "working",
) -> dict[str, Any] | None:
    payload: dict[str, Any] = {
        field_last_contacted_at(): contacted_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        field_email_state(): email_state,
    }
    if campaign:
        payload[field_last_contact_campaign()] = campaign
    return patch_person(person_id, payload)


def mark_person_unsubscribed(person_id: str) -> dict[str, Any] | None:
    return mark_person_email_state(person_id, "unsubscribed")


def mark_person_bounced(person_id: str) -> dict[str, Any] | None:
    return mark_person_email_state(person_id, "bounced")


def people_for_campaign() -> list[dict[str, Any]]:
    unsubscribed_emails = get_unsubscribed_emails()
    store_index = last_contact_index()
    people: list[dict[str, Any]] = []
    for record in list_people():
        normalized = normalize_person(record)
        if not normalized.get("email"):
            continue
        normalized["last_contacted_at"] = _merge_last_contacted(normalized, store_index)
        reason = blocked_reason(normalized, unsubscribed_emails)
        normalized["blocked_reason"] = reason
        normalized["sendable"] = reason is None
        normalized["unsubscribed"] = reason in {"unsubscribed", "supabase_unsubscribed"}
        people.append(normalized)
    return people


def get_person_object_metadata_id() -> str:
    global _PERSON_OBJECT_METADATA_ID
    if _PERSON_OBJECT_METADATA_ID:
        return _PERSON_OBJECT_METADATA_ID
    status, body = twenty_request("GET", "/rest/metadata/objects")
    if status != 200:
        raise RuntimeError(f"Twenty metadata objects failed ({status}): {body}")
    objects: list[dict[str, Any]] = []
    if isinstance(body, dict):
        data = body.get("data")
        if isinstance(data, list):
            objects = data
        elif isinstance(data, dict):
            objects = data.get("objects", []) or []
    for obj in objects:
        if str(obj.get("nameSingular") or "").lower() == "person" and obj.get("id"):
            _PERSON_OBJECT_METADATA_ID = str(obj["id"])
            return _PERSON_OBJECT_METADATA_ID
    raise RuntimeError("Twenty person object metadata not found")


def list_person_field_names() -> set[str]:
    status, body = twenty_request("GET", "/rest/metadata/objects")
    if status != 200:
        return set()
    objects: list[dict[str, Any]] = []
    if isinstance(body, dict) and isinstance(body.get("data"), list):
        objects = body["data"]
    for obj in objects:
        if str(obj.get("nameSingular") or "").lower() != "person":
            continue
        return {str(field.get("name") or "") for field in obj.get("fields", []) if field.get("name")}
    return set()


def ensure_person_field(name: str, label: str, field_type: str) -> bool:
    existing = list_person_field_names()
    if name in existing:
        return False
    payload = {
        "name": name,
        "label": label,
        "type": field_type,
        "objectMetadataId": get_person_object_metadata_id(),
    }
    status, body = twenty_request("POST", "/rest/metadata/fields", payload=payload)
    if status not in (200, 201):
        raise RuntimeError(f"Failed to create Twenty field {name} ({status}): {body}")
    return True
