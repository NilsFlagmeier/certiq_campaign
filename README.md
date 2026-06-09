# certiq_campaign

Lokales Campaign- und Marketing-Tool für Certiq-Mitarbeiter. Verwaltet E-Mail-Kampagnen, Lead-Intake, Analytics und Website-Metriken.

**Nur lokal ausführen** — nicht auf Vercel oder einem öffentlichen Server deployen.

## Setup

```bash
git clone <repo-url>/certiq_campaign
cd certiq_campaign

python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
# .env mit Secrets vom Team-Lead ausfüllen

python scripts/hash_admin_password.py   # einmalig für Login-Passwort
python scripts/run_local.py
```

Öffne http://127.0.0.1:8787/admin/login

## Was dieses Tool macht

- E-Mail-Kampagnen (Twenty CRM + Resend)
- Lead-Intake-Formular
- Kampagnen-Analytics (Supabase Event Store)
- PageSpeed, Clarity, Google Search Console Metriken

## Wichtig

- Unsubscribe-Links in Kampagnen-E-Mails zeigen auf `https://certiq.tech/api/unsubscribe` (öffentlicher Endpoint auf certiq_website).
- `APP_BASE_URL` in `.env` muss `https://certiq.tech` bleiben.
- `.env` niemals committen.

## Updates

```bash
git pull
pip install -r requirements.txt   # bei Dependency-Änderungen
python scripts/run_local.py
```

Weitere Details: [docs/SETUP.md](docs/SETUP.md), [docs/CAMPAIGN_WORKFLOW.md](docs/CAMPAIGN_WORKFLOW.md)
