"""Ensure Twenty People has campaign fields used by the admin portal."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

from lib.twenty_crm import (  # noqa: E402
    DEFAULT_FIELD_EMAIL_STATE,
    DEFAULT_FIELD_KUNDEN_ID,
    DEFAULT_FIELD_LAST_CONTACT_CAMPAIGN,
    DEFAULT_FIELD_LAST_CONTACTED_AT,
    DEFAULT_FIELD_SENT_CAMPAIGNS,
    ensure_person_field,
    field_email_state,
    field_kunden_id,
    field_last_contact_campaign,
    field_last_contacted_at,
    field_sent_campaigns,
    get_twenty_config,
)


def main() -> int:
    load_dotenv(ROOT / ".env", override=True)
    base_url, _ = get_twenty_config()
    print(f"Twenty instance: {base_url}")

    specs = [
        (field_email_state(), "Email State", "TEXT", DEFAULT_FIELD_EMAIL_STATE),
        (field_last_contacted_at(), "Last Contacted At", "DATE_TIME", DEFAULT_FIELD_LAST_CONTACTED_AT),
        (field_kunden_id(), "Kunden ID", "TEXT", DEFAULT_FIELD_KUNDEN_ID),
        (field_last_contact_campaign(), "Last Contact Campaign", "TEXT", DEFAULT_FIELD_LAST_CONTACT_CAMPAIGN),
        (field_sent_campaigns(), "Sent Campaigns", "TEXT", DEFAULT_FIELD_SENT_CAMPAIGNS),
    ]
    created = 0
    for name, label, field_type, default_name in specs:
        if ensure_person_field(name, label, field_type):
            print(f"Created field: {name}")
            created += 1
        else:
            print(f"Field already exists: {name}")
        if name != default_name:
            print(f"  (env override, default would be {default_name})")

    print(f"Done. Created {created} new field(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
