from typing import Any

from lib.campaign_store import last_contact_index
from lib.twenty_crm import field_last_contacted_at, list_people, normalize_person, patch_person


def sync_last_contact_to_twenty() -> dict[str, Any]:
    index = last_contact_index()
    updated = 0
    skipped = 0
    for record in list_people():
        person = normalize_person(record)
        person_id = person.get("person_id", "")
        if not person_id:
            skipped += 1
            continue
        last_contact = index.get(person_id) or index.get(person.get("kunden_id", ""))
        if not last_contact:
            skipped += 1
            continue
        current = person.get("last_contacted_at", "")
        if current and current >= last_contact:
            skipped += 1
            continue
        patch_person(person_id, {field_last_contacted_at(): last_contact})
        updated += 1
    return {
        "updated": updated,
        "skipped": skipped,
        "indexSize": len(index),
    }
