# Campaign Workflow (v2)

Diese README beschreibt die neue Resend x Notion Pipeline:

- Lead-Erfassung via Web-Form (`/admin/lead`) oder CLI-Fallback
- Sequenzversand mit Templates (`python -m legacy.send_campaign`)
- Warm/Cold Profile
- Cold-Import und Verifikation
- Unsubscribe + Webhook Rueckfluss

## 1) Architektur auf einen Blick

- Lead Intake:
  - `admin/lead.html` -> `api/admin/lead.py` -> Notion CRM
  - `python -m legacy.generate_personal_link` als CLI-Fallback
- Versand:
  - `legacy/send_campaign.py` (CLI: `python -m legacy.send_campaign`) liest Notion, rendert Jinja2 Templates, sendet via Resend
- Compliance:
  - `api/unsubscribe.py` verarbeitet Abmeldungen und setzt Notion-Status
  - `api/resend_webhook.py` verarbeitet Bounce/Complaint/Open/Click
- Cold Outreach:
  - `python -m legacy.import_cold_excel` (Import)
  - `python -m legacy.verify_cold_contacts` (Pre-Check)

## 2) Admin-Login + Formular in `/admin/lead`

Das Formular ist in `admin/lead.html` implementiert.

- Zugang:
  - Login unter `/admin/login` mit `.env` Wert `ADMIN_PORTAL_PASSWORD`.
  - Erfolgreicher Login setzt eine sichere Session-Cookie und erlaubt Zugriff auf `/admin/lead`.
- `Company` (Pflicht):
  - Wird auf Notion-Feld `Company` geschrieben.
- `First Name` (Pflicht):
  - Wird auf `First Name` geschrieben.
- `Last Name` (Pflicht):
  - Wird auf `Last Name` geschrieben.
- `Email` (Pflicht):
  - Wird validiert und auf `Email` geschrieben.
- `Phone` (optional):
  - Wird normalisiert (`0...` -> `+49...`, `00...` -> `+...`).
- `Tags (CSV)`:
  - Kommagetrennte Tags, z. B. `automotive, messe_hannover`.
  - Wird als Notion `Tags` (multi_select) gespeichert.
- `Consent Source`:
  - Herkunft/Einwilligungskontext, z. B. `Visitenkarte - Hannover Messe`.
  - Wird auf `Consent_Source` gespeichert.

Beim Speichern setzt der API-Handler zusaetzlich:

- `Source=business_card`
- `Status=new`
- `Sequence=business_card_intro`
- `Sequence_Step=0`
- `Next_Send_At=now`
- `Variante=A`
- Tracking-Link in `Link`

## 3) Lokal starten (empfohlen)

### 3.1 Python Umgebung

Wenn dein System-Python Probleme macht, nutze `uv`:

```bash
cd /Users/maxbeitler/Development/certiq_website
brew install uv
rm -rf .venv
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

### 3.2 Environment

Mindestens benoetigt:

- `NOTION_TOKEN`
- `NOTION_CRM_DATABASE_ID`
- `ADMIN_INGEST_TOKEN`
- `ADMIN_PORTAL_PASSWORD`
- `ADMIN_PORTAL_SESSION_SECRET`
- `RESEND_API_KEY` (warm)
- `RESEND_API_KEY_OUTBOUND` (cold outbound Profil)
- `UNSUBSCRIBE_SECRET`
- `APP_BASE_URL`

Siehe `.env.example` fuer Vollstaendigkeit.

### 3.3 Dev Server

```bash
vercel dev
```

Dann:

- Lead-Form: `http://localhost:3000/admin/lead`

## 4) Sicherheitslogik Ingest (wichtig)

`api/admin/lead.py` ist standardmaessig lokal-only:

- Auf Vercel Deployment blockiert der Endpoint mit `403`.
- Nur wenn `ALLOW_REMOTE_INGEST=true` gesetzt ist, waere Remote-Ingest erlaubt.
- Authentifizierung erfolgt primaer ueber Admin-Session-Cookie (Login-Portal).
- Fuer CLI/Fallback bleibt `Authorization: Bearer <ADMIN_INGEST_TOKEN>` weiterhin moeglich.

## 5) Versand mit `python -m legacy.send_campaign`

### 5.1 Wichtige Flags

- `--sequence`: Sequenzname (`business_card_intro`, `business_card_formal`, `cold_outbound`)
- `--profile`: `default` oder `outbound`
- `--dry-run`: nur Vorschau
- `--test-email --test-to ...`: eine Testmail
- `--status`: nur bestimmte Status (CSV)
- `--exclude-status`: Status ausschliessen (CSV)
- `--tags`: mindestens ein Tag muss matchen (CSV)
- `--limit`: max. Empfaenger

### 5.2 Standard-Warm-Flow

```bash
python -m legacy.send_campaign --sequence business_card_intro --profile default --dry-run
python -m legacy.send_campaign --sequence business_card_intro --profile default --test-email --test-to deine@mail.de
python -m legacy.send_campaign --sequence business_card_intro --profile default
```

### 5.3 Cold-Outreach-Flow

```bash
python -m legacy.import_cold_excel ./leads.xlsx --note "Engineering Liste 2026" --dry-run
python -m legacy.import_cold_excel ./leads.xlsx --note "Engineering Liste 2026" --tags "cold_research,engineering"
python -m legacy.verify_cold_contacts --batch 500 --only-unchecked
python -m legacy.send_campaign --sequence cold_outbound --profile outbound --dry-run --limit 25
python -m legacy.send_campaign --sequence cold_outbound --profile outbound --limit 25
```

## 6) Guardrails (automatische Regeln)

- `outbound` Profil nur mit `--sequence cold_outbound`.
- Cold Versand nur wenn:
  - `Source=cold_research`
  - `Status=cold_verified`
  - `Bounce_Probe_Result=valid`
  - `Legitimate_Interest_Basis` ist gefuellt
- Mails bekommen automatisch:
  - `List-Unsubscribe`
  - `List-Unsubscribe-Post`
  - Resend Tags (`sequence`, `step`, `kunden_id`, `profile`)

## 7) Webhooks und Rueckfluss

- `api/resend_webhook.py` mappt:
  - `email.bounced` -> `Status=bounced`, `Last_Bounce_At`
  - `email.complained` -> `Status=unsubscribed`
  - `email.opened` -> `Last_Opened_At`, `Open_Count`, ggf. `Status=engaged`
  - `email.clicked` -> `Last_Clicked_At`, `Click_Count`, ggf. `Status=engaged`
- `api/unsubscribe.py` setzt bei erfolgreicher Abmeldung den Notion-Status auf `unsubscribed`.

### 7.1 Resend Webhook einrichten (Production)

Damit Opens/Clicks/Bounces automatisch nach Notion fliessen:

1. Vercel-Deployment live; `APP_BASE_URL` auf die Production-Root setzen (z. B. `https://certiq.tech`).
2. In `.env` / Vercel Environment: `RESEND_WEBHOOK_SECRET` setzen — **derselbe** Secret-String wie im Resend-Dashboard beim Webhook.
3. Resend Dashboard: **Webhooks** → Endpoint URL:

   `{APP_BASE_URL}/api/resend_webhook`

   z. B. `https://certiq.tech/api/resend_webhook`

4. Events abonnieren mindestens: `email.bounced`, `email.complained`, `email.opened`, `email.clicked`.
5. Test: eine echte/Test-Mail an dich senden, Link klicken, in Notion prüfen ob `Last_Clicked_At` / `Click_Count` steigen und `tags.kunden_id` im Resend-Payload zur richtigen Zeile passt (Versender setzt `kunden_id` als Resend-Tag).

### 7.2 Open/Click Tracking (Domain-Ebene bei Resend)

Open- und Click-Tracking werden bei Resend auf **Domain-Ebene** geschaltet, nicht im einzelnen `Emails.send`-Body.

- Für **Warm** (`profile default`, Absender-Domain certiq.tech): Im Resend-Dashboard unter **Domains** fuer `certiq.tech` Open- und Click-Tracking aktivieren (und Tracking-CNAME wie angegeben setzen).
- Für **Outbound** (`profile outbound`): Entweder separate Subdomain `outbound.certiq.tech` mit eigenen Tracking-Einstellungen oder bewusst weniger Tracking (Profile in [lib/profiles.py](../lib/profiles.py) hat `track_opens`/`track_clicks` = `False` für Cold als fachliche Vorgabe).

Fachliche Zuordnung: [lib/profiles.py](../lib/profiles.py) — dort siehst du die intendierten Tracking-Defaults pro Profil.

## 8) Multi-Kampagnen und eine Zeile Notion (“Single Source of Truth”)

- Pro Kontakt gilt **ein** aktives Sequenz-Setup ueber `Sequence`, `Sequence_Step`, `Next_Send_At`.
- Wenn `Sequence` in Notion gesetzt ist und von der CLI-Sequence abweicht, wird der Kontakt beim Lauf uebersprungen (Filter in [legacy/send_campaign.py](../legacy/send_campaign.py)).
- **`Sequence_Step`**: wie viele Steps der Kontakt bereits erhalten hat; der naechste Versand ist `SEQUENCES[Sequence][Sequence_Step]` (Null-basierte Liste in [legacy/sequences.py](../legacy/sequences.py)).
- **Historie**: `Gesendete Kampagnen` fuehlt pro Versand ein Tag (Multi-Select), bleibt bei Sequenzwechsel erhalten.

### 8.1 Parallel-Kohorten (empfohlen)

1. Segmentierung uber `Tags` (z. B. `netzwerk`, `geschaeftsfuehrer`).
2. Pro Kohorte `Sequence` setzen (`business_card_intro` vs. `business_card_formal`).
3. Versand: `--sequence ... --tags netzwerk --dry-run` dann live mit `--limit`.

### 8.2 Nacheinander dieselbe Person

Wenn eine Sequenz fertig ist (`Sequence_Step` entspricht letztem Step, `Next_Send_At` leer):

1. In Notion neue `Sequence` setzen, `Sequence_Step = 0`, `Next_Send_At` heute oder leer.
2. Naechsten Lauf mit passendem `--sequence` ausführen.

## 9) Notion Views (empfohlen als manuelle Saves)

Alle Filter setzt du als **gefilterte DB-Views** in Notion:

| View-Name       | Zweck |
|----------------|--------|
| `Outbound_heute` | `Next_Send_At` ist heute oder frueher UND `Status` ist nicht eines von: unsubscribed, bounced, paused, replied, cold_disqualified |
| `Engaged`        | Sortierung nach `Last_Clicked_At` absteigend (oder nach `Click_Count`). Optional nur `Last_Clicked_At` ist nicht leer |
| `Risiko`         | `Status` ist `bounced` ODER `Open_Count > 3` ohne Klick (`Last_Clicked_At` leer) |
| `GF`             | `Tags` enthaelt `geschaeftsfuehrer` |
| `Nach_Sequence` | Gruppierung oder Filter nach Property `Sequence` fuer Batch-Sending |

Exact Notion UI: Datenbank öffnen → **+ Neue Ansicht** → Filter/Sortierung wie oben.

## 10) Wochen-Workflow (Operational Discipline)

1. **Montag:** Neue Leads kategorisieren (`Tags`), `Sequence` und `Consent_Source` pruefen, `Next_Send_At` fuer erste Welle setzen.
2. Pro geplanter Kohorte:
   ```bash
   python -m legacy.send_campaign --sequence business_card_intro --profile default --dry-run [--tags kohorte]
   python -m legacy.send_campaign --sequence business_card_intro --profile default --test-email --test-to DEINE@MAIL [--test-contact-email CRM_EMAIL]
   python -m legacy.send_campaign --sequence business_card_intro --profile default [--tags kohorte] --limit N
   ```
3. **Antwort erhalten:** In Notion `Status = replied`, damit weitere Sends ausgeschlossen bleiben.
4. **Webhook pruefen:** Stichprobe ob `email.clicked` / `email.opened` Notion-Spalten befuellt (falls leer → Domain-Tracking + Webhook Secret prufen).

## 11) Typischer Tagesablauf

1. Neue Leads via `/admin/lead` erfassen.
2. `--dry-run` der relevanten Sequenz.
3. Testmail senden.
4. Live senden.
5. Webhook-Events und Notion-Status kontrollieren.

## 12) Troubleshooting

- `NOTION_TOKEN/NOTION_CRM_DATABASE_ID fehlt`:
  - `.env` prüfen.
- `RESEND_API_KEY... fehlt`:
  - passendes Profil und API-Key in `.env` prüfen.
- `Keine passenden Empfaenger`:
  - Filter (`--status`, `--tags`, `--sequence`) und Notion-Felder checken.
- Ingest 403 auf Deployment:
  - erwartetes Verhalten, solange `ALLOW_REMOTE_INGEST` nicht `true` ist.
- Opens/Clicks kommen nie in Notion an:
  - Resend Domain **Open/Click Tracking** aktivieren und Webhook korrekt (Abschnitt 7–7.2).

## 13) Cursor MCP: Resend + Clarity fuer Kampagnen-Analysen

Damit der Agent in Cursor **Resend** (Versand, Broadcasts, Kontakte, Domains, Webhooks) und **Microsoft Clarity** (Traffic, Sessions, Kampagnen-Dimensionen laut Data-Export-API) per MCP abfragen kann:

1. **Node.js 20+ LTS** installieren ([nodejs.org](https://nodejs.org/)) — der eingebettete `node` von Cursor reicht **nicht** (kein stabiler `npx`/`PATH` fuer MCP-Prozesse).
2. Im **Repo-Root** einmal Abhaengigkeiten installieren (schnellerer MCP-Start, kein `npx`-Download bei jedem Verbinden):
   ```bash
   npm install
   ```
3. Im Projekt: `.cursor/mcp.json` startet unter **Windows** `tools/mcp-bootstrap.cmd`, das u. a. `%LocalAppData%\Programs\nodejs` und `%ProgramFiles%\nodejs` in den **PATH** legt, damit `node` gefunden wird, wenn Cursor ohne Nutzer-PATH startet.
4. **Erforderliche `.env`-Keys:** `RESEND_API_KEY` (oder `RESEND_EMAIL_API_KEY`), optional `RESEND_FROM` fuer Standard-Absender; fuer Clarity `CLARITY_TOKEN` (Settings → Data Export → neues API-Token).
5. **Cursor neu laden**, dann unter **Einstellungen → MCP** pruefen, ob `resend` und `microsoft-clarity` verbunden sind. Bei Fehlern: **Output → MCP Logs**.

**Fehler `'node' is not recognized'`:** Node.js 20+ LTS installieren, im Repo `npm install` ausfuehren, Cursor **komplett** beenden und neu starten. Wenn `node` weiterhin unbekannt ist: in `.cursor/mcp.json` testweise direkt den vollen Pfad zu `node.exe` als `command` setzen (Interpolation-Beispiel: `${userHome}/AppData/Local/Programs/nodejs/node.exe`).

**macOS / Linux:** In `.cursor/mcp.json` fuer beide Server statt `cmd.exe` z. B. `"command": "/bin/bash"` und `"args": ["${workspaceFolder}/tools/mcp-bootstrap.sh", "resend"]` bzw. `"...", "clarity"]` verwenden (oder sicherstellen, dass `node` im PATH fuer GUI-Apps liegt).

**Doppelter Resend-Eintrag:** Wenn du Resend zusaetzlich als **Cursor-Marketplace-Plugin** aktiviert hast, gibt es zwei MCP-Server mit aehnlichen Tools — einen in den MCP-Einstellungen **deaktivieren** (entweder das Plugin oder die Projekt-Server `resend` aus `.cursor/mcp.json`), sonst doppelte Tool-Namen / Verwirrung.

**Hinweise:** Clarity Data Export ist **raten-limited** (z. B. wenige Tage Rueckblick, begrenzte Requests pro Tag — siehe Microsoft-Doku). Resend-MCP braucht einen Key mit den passenden **Scopes** fuer die gewuenschten Tools. **Notion CRM** laeuft weiter ueber die Notion-Integration/MCP separat von `NOTION_TOKEN` in `.env`.

## 14) Kampagnen-Report (CLI: Notion + Resend + Clarity)

Das Skript `tools/campaign_report.py` erzeugt einen **Markdown-Report** aus:

- **Notion CRM:** alle Zeilen mit E-Mail (Opens/Klicks, Sequence, Gesendete Kampagnen, Next_Send_At, Tags, …)
- **Resend:** letzte gesendete Mails (HTTP `GET /emails`, paginiert) — Abgleich mit CRM nach Empfaenger-Adresse
- **Clarity:** Data-Export `project-live-insights` mit Dimensionen Source/Medium/Campaign (`numOfDays` 1–3)

Voraussetzungen: `.env` mit `NOTION_TOKEN`, `NOTION_CRM_DATABASE_ID`; optional `RESEND_API_KEY` bzw. `RESEND_EMAIL_API_KEY`; optional `CLARITY_TOKEN` (nur wenige API-Calls pro Tag).

**Notion-Seite aus dem Report:** Zusaetzlich `NOTION_REPORTS_PARENT_PAGE_ID` (UUID einer **Page** als Ordner oder einer **Database**). **Jeder Lauf mit `--notion` legt eine neue Seite an** (`pages.create`): unter einer **Seite** erscheint eine neue **Unterseite** im Baum; bei einer **Datenbank** eine neue **Zeile** (nie Ueberschreiben einer bestehenden Seite). Bei Datenbanken muessen ggf. alle **Pflichtfelder** per API setzbar sein; fuer den Report wird nur die **Title**-Spalte befuellt. **Wichtig:** Diese Page/DB muss in Notion mit derselben **Internal Integration** verbunden sein wie euer CRM (`Connections` / *Mit Verbindungen teilen*), sonst liefert die API `object_not_found` (HTTP 404). Aufruf z. B.:

```bash
python tools/campaign_report.py > kampagnen_report.md
python tools/campaign_report.py --out kampagnen_report.md --resend-limit 300 --clarity-days 3
python tools/campaign_report.py --skip-clarity-url   # nur ein Clarity-API-Call (ohne URL/user_id-Dimension)
python tools/campaign_report.py --notion --campaign-name "Q1 Outbound"
python tools/campaign_report.py --out kampagnen_report.md --notion
python tools/campaign_report.py --v2 --out kampagnen_report_v2.md
python tools/campaign_report.py --v2 --notion --campaign-name "Q1 Outbound"
```

**Report v2 (`--v2`) — Sales-Dashboard:** Ein Notion-Toggle **„Sales-Dashboard v2 — Snapshot, Funnel, Patterns, Top-Leads“** mit **Sales-Story zuerst**, dann Detailblöcken:

1. **Snapshot** (Kontakte, eligible, Resend-Sample, Problem-Rate, Open/Click auf Sende-30d-Fenster, Clarity-Sessions Σ + Send-Trend 7d).
2. **Zustellung:** Resend-Event-Mix als **pie** + Tabelle.
3. **Funnel** (CRM + Clarity): Tabelle + **flowchart TD** mit **%-Labels auf den Kanten**; Drop-off-Sätze (größte Stufenverluste).
4. **Performance** nach `Sequence` und `utm_campaign` (inkl. **Vol.%**), je **pie** für Volumenmix.
5. **Sendezeit:** Wochentag + Tageszeit-Buckets (UTC) als **pie** + Open-Rate je Bucket + Kurz-Empfehlung.
6. **Domain-Risiken** aus dem Resend-Sample (min. 3 Sends pro Domain).
7. **Top-Leads** mit **empfohlener Aktion** (`call` / `followup` / `nurture` / `wait`) und **Next-Best-Actions** (3–5 Bullets).
8. **Detail:** Datenqualität, Trendfenster **7d/30d**, Kohorten, Latenz — für Tiefenrecherche.

**Abschnitt 2 (ACTION LIST)** wird mit `--v2` **kompakt** aus dem gleichen Lead-Score gefüttert. **Abschnitt 4** entfällt die klassischen Strategie-Stichpunkte (keine Doppelung zu v2); der **Datenfluss-Mermaid** bleibt.

**Tracking-Voraussetzungen:** Sollen **Open/Click** im CRM und im Report stimmen, müssen **Resend-Webhooks** laufen und **Open/Click-Tracking** an der Versand-Domain aktiv sein — sonst oft **0% Opens** trotz Sends. `CAMPAIGN_REPORT_V2_MIN_SEGMENT` (Standard **5**) steuert die Mindestgröße für Segment-Tabellen.

**Mermaid in Notion:** nur **flowchart** und **pie** (kein `xychart-beta`). Größere Rohdaten-Listen bleiben in den bestehenden Detail-Toggles in Abschnitt 3.

Am Ende gibt `--notion` die **URL der neuen Notion-Seite** auf stdout aus (ohne `--out` wird kein Markdown auf stdout geschrieben). Die Notion-Seite enthaelt einen **gefuehrten Bericht** (Kernzahlen-Callouts, Methodik, dann Detailabschnitte; kleine Markdown-Tabellen als echte Notion-Tabellen, grosse als Code).

**Hinweis:** Clarity liefert keine personenbezogenen E-Mail-Zuordnungen — aggregierte Sessions. **UTMs** im Stamm-Link und in Notion werden mit Clarity **Source/Medium/Campaign** verglichen (Kampagnen-Aliase wie `business_card_intro` → `business_card` wie im Runner). Der Parameter **`user_id`** in der Landing-URL wird mit **`Kunden_ID`** im CRM verknuepft (zweiter Clarity-Request mit Dimension **URL**; zaehlt zur taeglichen Quota).

## 15) Neues Admin-Portal fuer certiq.tech

Der Admin-Bereich orientiert sich strukturell am Referenz-Portal und ist auf Certiq angepasst:

- Login: `/admin/login`
- Dashboard: `/admin`
- Performance: `/admin/performance`
- Kampagne: `/admin/campaign`
- Kampagnen-Analyse: `/admin/campaign/analytics`
- Lead-Erfassung: `/admin/lead`

### 15.1 Admin-API (Auszug)

- `GET /api/admin/config`
- `GET /api/admin/metrics/pagespeed`
- `GET /api/admin/metrics/clarity`
- `GET /api/admin/metrics/gsc` (Stub)
- `GET|POST /api/admin/campaign`
- `POST /api/admin/campaign/preview`
- `POST /api/admin/campaign/test`
- `GET /api/admin/campaign/events`
- `GET /api/admin/campaign/analytics`
- `POST /api/admin/campaign/analytics/sync`
- `POST /api/admin/campaign/sync-last-contact`

### 15.2 Kampagnen-Store

Der persistente Kampagnenzustand liegt in Supabase-Tabellen:

- `campaign_events`
- `campaign_unsubscribes`

Migration: `supabase/migrations/20260522195000_campaign_store.sql`

### 15.3 CRM-Quelle

Kontakte kommen aus **Notion CRM** (nicht Twenty CRM). `Kunden_ID` wird weiterhin als stabiler Tracking-`user_id` verwendet.
