# certiq_campaign — Lokales Setup

## Voraussetzungen

- Python 3.12
- Git-Zugang zum Repository
- Secrets vom Team-Lead (`.env`-Werte)

## Ersteinrichtung

1. Repository klonen und virtuelle Umgebung anlegen (siehe [README.md](../README.md)).
2. `.env` aus `.env.example` erstellen und alle Pflichtfelder setzen:
   - `ADMIN_PORTAL_SESSION_SECRET`
   - `ADMIN_PASSWORD_HASH_B64` (via `python scripts/hash_admin_password.py`)
   - `RESEND_API_KEY`, `RESEND_FROM`
   - `TWENTY_API_URL`, `TWENTY_CRM_API_KEY`
   - `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`
   - `UNSUBSCRIBE_SECRET` (muss mit certiq_website übereinstimmen)
   - `APP_BASE_URL=https://certiq.tech`
3. Optional: Twenty-Felder anlegen: `python scripts/setup_twenty_campaign_fields.py`
4. Server starten: `python scripts/run_local.py`

## Port ändern

```bash
PORT=9000 python scripts/run_local.py
```

Der Server bindet immer an `127.0.0.1` (nur localhost).

## Sicherheit

- Kein Deployment auf öffentliche Server
- `.env` nicht committen
- Tool nur im Firmennetzwerk / auf vertrauenswürdigen Rechnern nutzen
