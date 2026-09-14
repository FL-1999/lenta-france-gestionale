# ASTRA WEBSITE HANDOVER — Lenta France

> **Audience:** GPT‑6 Astra (and any frontier model) tasked with performing an independent, critical audit of the "Lenta France website".
> **Author:** Claude (Opus 4.8), 2026‑09‑14. Prepared by direct inspection of the repository at commit `f18ad16`. **Code is the source of truth** — every claim below was verified against the codebase, not against README/docs (several of which are obsolete; discrepancies are called out explicitly).
> **Scope of this phase:** ANALYSIS ONLY. Nothing in the product was modified to produce this document.

---

## ⚠️ READ THIS FIRST — Critical framing (expectation vs. reality)

The request that produced this handover assumes a **public marketing website** for Lenta France — a company specialised in **special foundations and geotechnical works** on the Côte d'Azur / Monaco — with a hero, services showcase, project references, SEO, conversion funnels, etc.

**That website does not exist in this repository.**

What this repository actually contains is an **internal, login‑gated, multi‑role operations management application** (an Italian "gestionale") for running construction sites. Concretely:

- The domain root `/` is **not** a marketing homepage. It is a **login gateway** (`templates/home.html`) whose entire content is a headline "Lenta France – Login / Accès unique", a one‑line subtitle, and a single **"Accedi / Accéder"** button to `/login`. Authenticated users are immediately redirected to their role dashboard (`main.py:678‑700`).
- **Every functional page is behind authentication.** Anonymous visitors are 303‑redirected to `/login` (`auth.py:322‑342`). There are **no public informational pages** a prospect, maître d'ouvrage, bureau d'études or architect could ever see.
- There is **no hero, no services page, no project/reference gallery, no company story, no certifications page, no team page, no contact form, no SEO, no analytics, no lead capture, no outbound email.** The only outward‑facing company contact details anywhere are static lines inside an **authenticated PDF cover template** (`templates/manager/fiches/_pdf_cover.html`).

**Consequence for the audit.** Roughly half of the classic "website audit" dimensions (public SEO, OpenGraph/social, marketing hero, conversion/lead‑gen funnels, storytelling, referenze showcase) **do not apply to the current artifact** because the current artifact is an internal tool, not a public site. They are not "bad" — they are **absent by design**.

Astra must therefore treat this as **two distinct questions** and keep them separate:

- **Question A — Audit the thing that exists:** the internal gestionale, judged as an internal B2B operational web app (architecture, code quality, security, maintainability, UX for daily operators, mobile for field use).
- **Question B — Strategise the thing that does not exist:** the public marketing website Lenta France would need to "look like one of the most serious and technologically advanced special‑foundations firms on the Côte d'Azur / Monaco". This is a **greenfield / V2** effort, not a refactor of the current codebase. Nothing in this repo can be "improved" into that site; it would be built fresh.

Both are legitimate and are explicitly requested. Do not collapse them into one. Do not audit the login gate as if it were a failed marketing homepage, and do not report "missing SEO/hero/CTA" as defects of the current app without first stating that the current app is not a public site.

---

## 1. Lenta France & Website Purpose

**Company (reconstructed from the codebase — verify with the client, see §22).** Lenta France appears to be an Italian‑led contractor operating in France specialised in **special foundations and geotechnical works** (fondazioni speciali / fondations spéciales). Strong signals in the domain model:

- Machinery and equipment typical of deep foundations: perforatrici / drilling rigs, bentonite pumps, cranes, "gabbie" (**reinforcement cages**), grabs/benne.
- **Fiches techniques** with **stratigraphy** and **concrete curves** (`072_add_fiche_courbe_beton.sql`, `FicheStratigrafia`) — i.e. pile/panel technical records.
- **Transport logistics with real GPS truck tracking** (`routes/trasporti.py`, `/api/trasporti/gps/webhook`, `services/gps_provider.py`).
- Bilingual **Italian/French** throughout — an Italian company operating on French sites (consistent with the Côte d'Azur / Monaco geography stated by the client).

**Purpose of the current software.** To run the back‑office and field operations of that contractor: construction sites (cantieri), machinery, technical sheets (fiches), daily work reports (rapportini), warehouse (magazzino), purchase orders (ordini), equipment with QR labels (attrezzature), staff & attendance (personale/presenze), vehicles (veicoli), transport/logistics with GPS, and site economics/margins. It is an operational tool for employees, **not** a customer‑facing property.

**Purpose of a hypothetical public website (Question B).** To make that operational sophistication legible to buyers — general contractors, maîtres d'ouvrage, bureaux d'études, architects — and to generate qualified B2B leads. It would need to project engineering credibility, real jobsite proof, technical capability, and a premium‑but‑industrial image. **None of this exists today.**

---

## 2. Current Website Architecture

- **Shape:** A single **FastAPI monolith** rendering **server‑side Jinja2 HTML** (multi‑page app, full page loads; no SPA, no client framework). Progressive enhancement via a handful of vanilla‑JS modules.
- **Entry point:** `main.py` — a **single ~9,022‑line / 338 KB module** that both creates the app and holds the majority of route handlers inline, plus 18 additional routers imported from two packages (`routers/`, `routes/`).
- **Rendering model:** Each request → auth check (cookie‑borne JWT) → SQLAlchemy/SQLModel query → Jinja2 template → HTML. Charts, maps and the QR scanner are hydrated client‑side by page‑specific scripts loading CDN libraries.
- **Auth model:** JWT (HS256) in HttpOnly cookies, with a refresh‑token cookie and an automatic refresh middleware. **Multi‑role** users with a `current_role` cookie and role‑based redirects/permissions.
- **State/PWA:** Installable PWA (manifest + service worker with stale‑while‑revalidate caching + an `/offline` fallback). Dark‑first theme with a light variant toggled client‑side.
- **Hosting:** Runs on **Render** with an **external managed PostgreSQL** (per comments in `database.py:7‑9`); SQLite is used locally.

**High‑level request/trust flow:**

```
Browser ──cookie(JWT)──> FastAPI (main.py + routers/ + routes/)
                              │  refresh_token_middleware (auto re‑mint)
                              │  CORS (prod‑hardened) · request‑id · static cache headers
                              ▼
                   Auth deps (auth.py) ── role/permission gate (permissions.py)
                              ▼
              SQLAlchemy + SQLModel  ──>  PostgreSQL (Render/external) | SQLite (dev)
                              ▼
                     Jinja2 templates (143 files)  ──>  HTML
                              ▼
        page‑specific JS: Google Maps · ApexCharts · Chart.js · html5‑qrcode (CDN)
```

---

## 3. Technology Stack

| Layer | Choice | Notes / evidence |
|---|---|---|
| Language | Python **3.10+** (union `X\|Y`, `tuple[...]`) | **No version pin** — no `runtime.txt` / `.python-version` / `pyproject.toml`. |
| Web framework | **FastAPI** | `main.py:463`. |
| ASGI server | **uvicorn[standard]** | No gunicorn in `requirements.txt`. Start command not committed. |
| Templating | **Jinja2** (SSR) | `main.py:534`. |
| ORM | **Mixed SQLAlchemy (declarative `Base`) + SQLModel** | `Personale`, `Veicolo` are SQLModel `table=True`; rest are SQLAlchemy. |
| Validation | **Pydantic v2** | `schemas.py` uses `ConfigDict`, `from_attributes`. |
| DB | **PostgreSQL** (prod) / **SQLite** (dev) | `database.py:10`; `psycopg2-binary`. |
| Migrations | **None (no Alembic)** — 70 hand‑numbered raw‑SQL files + startup auto‑`ALTER TABLE` + `create_all` | `migrations/001…072`, `database.py:37‑116`, `db_upgrade.py` (28 KB). |
| Auth | **JWT HS256** (python‑jose), access 60 min + refresh 30 d | `auth.py:50‑51,229`. |
| Password hashing | **passlib `pbkdf2_sha256`** (not bcrypt/argon2) | `auth.py:60‑68`. |
| PDF | **WeasyPrint** (+ Playwright/Chromium fallback) | fiche/report PDF export. |
| QR | **segno** (server SVG) + **html5‑qrcode** (client scan) | equipment labels + driver scanner. |
| Maps | **Google Maps JS API** (+ markerclusterer) | heavy: sites, depots, trips, operational map. |
| Charts | **ApexCharts** and **Chart.js** (two libraries) | manager dashboard vs reportistica. |
| CSS | **Custom**, single `style.css` (~9,058 lines / 202 KB). No framework. | + `unused/legacy_style.css` (dead), 16 inline `<style>` blocks. |
| Fonts | **System font stack only** (no web fonts loaded) | "Inter"/"Roboto Mono" named as fallbacks but never fetched. |
| JS | **Vanilla** (17 files). No React/Vue/htmx/Alpine. | |
| Tests | **pytest** — 17 test files | `tests/`. |
| CI/CD | **None** | no `.github/workflows`, no Docker/Procfile/render.yaml. |
| Deps pinning | **Effectively none** (only `httpx>=0.28.0`) | non‑reproducible builds. |

---

## 4. Repository Map

```
lenta-france-gestionale/
├── main.py                     ★ 9,022 lines — app + most routes + startup logic
├── auth.py                     JWT, hashing, login endpoints, auth deps, role redirects
├── permissions.py              Role→permission matrix + access helpers
├── database.py                 Engine/session (SQLite/PG), startup auto‑migration helpers
├── db_upgrade.py               Home‑grown schema upgrade (28 KB)
├── template_context.py         build_template_context, i18n t(), badge/permission helpers
├── backend_i18n.py             Backend message it/fr dictionary translation
├── schemas.py                  Pydantic v2 schemas
├── notifications.py            In‑app DB notifications (no email)
├── deps.py / audit_utils.py / backup_utils.py / logging_config.py / *_repository.py
├── models/                     entities.py (largest), supplier.py, depot.py,
│                               purchase_order.py, veicoli.py, base.py
├── routers/                    users, sites, machines, reports, fiches, notifications  (REST/API‑ish)
├── routes/                     manager_personale, manager_veicoli, manager_depositi,
│                               manager_attrezzature, magazzino (56 routes), ordini (29),
│                               trasporti (25), economics, reportistica, audit, backup
├── services/                   gps_provider.py, etc.
├── utils/                      google_maps.py, etc.
├── templates/                  143 .html — see §5 (104 under manager/)
│   ├── shared/base.html        ★ real base layout (extended by ~121 templates)
│   ├── base.html               ⚠ near‑duplicate legacy base (extended by ~10)
│   ├── home.html / login.html / offline.html
│   ├── admin/ capo/ driver/ manager/ gabbie/ errors/ legacy/
├── static/
│   ├── css/style.css           ★ 9,058 lines   ·  css/unused/legacy_style.css ⚠ dead
│   ├── js/                      17 vanilla files (maps, charts, qr, theme, sw)
│   ├── img/                     logo.png (239 KB), icon‑{192,512,512‑maskable}.png
│   ├── manifest.webmanifest    ★ linked   ·  manifest.json ⚠ legacy, unlinked
│   └── sw.js                    service worker (stale‑while‑revalidate)
├── migrations/                 001…072 raw SQL (70 files) — no Alembic
├── tests/                      17 pytest files
├── docs/                       audit_report.md, role_access_matrix.md ⚠(partly obsolete), …
├── scripts/                    check_conflict_markers, perf_smoke, backup_db
├── README.md                   ⚠ 3‑line stub (only a conflict‑marker check)
└── CODE_REVIEW.md              ⚠ partly obsolete (see §13)
```

`★` = load first (see §21).  `⚠` = duplication / dead / stale.

---

## 5. Pages & Information Architecture

**There is no public IA.** The only unauthenticated surface is: `/` (login gate), `/login`, `/offline`, `/set-lang`, `/set-language/{code}`, `/logout`, `/static/*`. Everything else is role‑gated.

**Authenticated IA is organised by role**, entered from the top navbar (desktop) / bottom tab bar (mobile) — there is **no sidebar and no footer**. Landing destination after login depends on role (`shared/base.html`, `get_default_route`):

| Role (enum in `models/entities.py:35‑41`) | Home | Primary areas |
|---|---|---|
| `admin` | manager dashboard | Everything + Users, Settings, Audit, Backup, site **margins** (admin‑only) |
| `manager` | `/manager/dashboard` | Cantieri, Fiches, Rapportini, Macchinari, Attrezzature, Magazzino, Ordini, Depositi, Trasporti, Personale, Presenze, Economics, Gabbie, Report |
| `caposquadra` | `/capo/dashboard` | Rapportini, Fiches, warehouse requests (capo) |
| `magazzino` | `/manager/magazzino/dashboard` | Warehouse only (items, categories, movements, requests, thresholds) |
| `driver` | `/driver/trasporti/viaggi` | Assigned trips, trip detail with **QR scanner** |
| `ferraiolo` | gabbie | Reinforcement cages only |

> ⚠ **Doc discrepancy:** `docs/role_access_matrix.md` also describes `CONTABILITA` and `HR` roles — these **do not exist** in `RoleEnum`. Treat that doc as aspirational/stale.

**Functional module map (all authenticated):**

- **Cantieri (sites):** list/create/edit/detail, documents, tasks (overview/history), project configuration, economics detail, progress grids ("avanzamento griglie"), map. (`routers/sites.py`, `main.py`, `manager/cantieri*`, `manager/site_*`.)
- **Macchinari (machinery):** machines + types + site assignments + notes history. (`routers/machines.py`, `manager/macchinari*`.)
- **Fiches (technical sheets):** list/create/detail with stratigraphy and concrete curves; PDF export with cover. (`routers/fiches.py`, `manager/fiches*`.)
- **Rapportini (daily reports):** list/detail/export; capo creation; workers & hours. (`routers/reports.py`, `manager/rapportini*`, `capo/*`.)
- **Magazzino (warehouse — 56 routes, 20 templates):** items, categories, macro‑categories, movements, requests, below‑threshold, consumption report, archive, duplicate/rettifica. (`routes/magazzino.py`.)
- **Ordini (purchase orders — 29 routes):** orders, suppliers (create‑on‑the‑fly), delivery notes (bolle), invoices, **email wizard** (builds email content; no SMTP send). (`routes/ordini.py`.)
- **Depositi (depots)** & **Fornitori (suppliers):** CRUD + maps. (`routes/manager_depositi.py`.)
- **Trasporti (transport — 25 routes):** dashboard, planner, new trip, trip detail, movements, map, equipment‑in‑transit, **GPS webhook + sync**. (`routes/trasporti.py`.)
- **Attrezzature (equipment):** list/new/edit + **printable QR labels** (segno). (`routes/manager_attrezzature.py`.)
- **Personale (staff)** & **Presenze (attendance):** CRUD + attendance. (`routes/manager_personale.py`.)
- **Veicoli (vehicles):** CRUD, optional GPS device linkage. (`routes/manager_veicoli.py`.)
- **Economics:** site budgets, entries, margins (margin visible to admin only). (`routes/economics.py`.)
- **Gabbie (reinforcement cages):** dedicated area for `ferraiolo`. (`templates/gabbie/`.)
- **Cross‑cutting:** Users management, Notifications (in‑app, 30 s polling), Audit log, DB Backup/export, Reportistica/Produzione dashboards.

---

## 6. Current UX

- **Operator‑centric, not visitor‑centric.** The product optimises for authenticated daily users doing CRUD and workflow, not for first‑time visitors being persuaded. There is no funnel, no onboarding, no marketing narrative.
- **Navigation:** dense top navbar with several dropdowns ("Generali", "Menu/Navigation", notifications bell, profile + role switcher, language flags, theme toggle), permission‑gated per role. On mobile, a **bottom tab bar** replaces it (Home, Cantieri, Depositi, Magazzino, Report, Trasporti, Profilo).
- **Task flows:** list → detail → form is the dominant pattern, repeated across ~15 modules. Multi‑step forms exist (e.g. cantiere stepper). QR flows: manager prints equipment labels; driver scans on the trip‑detail page (blocks loading equipment flagged in maintenance).
- **Feedback:** in‑app notifications (polling), badges (e.g. warehouse pending requests), localized error pages (403/404/500).
- **Known UX rough edges:** heavy reliance on dropdown‑in‑dropdown navigation; the desktop navbar can **overflow on mobile** because a compact hamburger/off‑canvas is still a TODO (`style.css:205`); large forms; some duplicated/parallel pages for the same concept (see §17) which can confuse mainteners and users alike.

---

## 7. Current UI / Design System

- **Aesthetic:** dark‑first "night‑blue" theme — radial‑gradient slate background (`#1f2937 → #0b1120 → #020617`), elevated cards `#1f2937`, **indigo/violet accents** (`--color-accent:#6366f1`, `--color-accent-soft:#8b5cf6`), gradient primary buttons, KPI tiles with gradients/shadows, subtle paper texture. A **light theme** is defined via `:root[data-theme="light"]` and toggled by `theme_switcher.js`.
- **Tokens** (in `:root`, `style.css`): spacing `--space-1..7` = 4/8/12/16/24/32/48; radii 6/10/14/18 + pill; type scale base `0.94rem`, title `1.25rem`, KPI value `1.8rem`; semantic colors success `#16a34a`, danger `#dc2626`, warning `#f59e0b`.
- **Components:** `.btn`/`.btn-primary`/`.btn-secondary`, `.card` (heavily used), `.data-table`, `.kpi`, `.badge`, `.modal`, `.page-header/.page-title/.page-subtitle/.page-eyebrow`, form primitives. All bespoke.
- **Typography:** **system fonts only** (`system-ui, -apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter"…`). No brand typeface is loaded. Tables reference "Roboto Mono" but it is not fetched → system mono fallback.
- **Iconography:** predominantly **emoji** (🧰 🚐 🖨️ …). A Bootstrap‑Icons class (`bi bi-bell-fill`) is used on the notifications bell **without** loading Bootstrap‑Icons CSS/font → that glyph likely does not render.
- **Assets:** logo is a **wide raster PNG** (948×245, 239 KB); no SVG logo. PWA icons present. No favicon link.
- **Consistency:** broadly consistent within the custom system, but a **single 9,058‑line CSS file** plus 16 inline `<style>` blocks and a dead `unused/legacy_style.css` make the system hard to reason about and prone to drift.

**As an internal tool the UI is competent and cohesive.** As a *public premium brand* it would not be reused: no brand typography, emoji icons, and a raster logo are below the bar Question B implies.

---

## 8. Mobile & Responsive

- **Viewport meta present** in both bases.
- **~48 `@media` blocks** across many breakpoints (most common `768px`, ×8), plus 5 `@media print` and one coarse‑pointer query — substantial responsive effort, appropriate for field use on phones/tablets.
- **Mobile nav = bottom tab bar** (`.bottom-nav`, shown `≤767px`); desktop dropdowns are hidden on mobile. **No hamburger/off‑canvas yet** — explicit TODO (`style.css:205`); consequently the **top navbar can overflow on small screens** in states where the bottom bar doesn't fully substitute it.
- **PWA installability** makes the tool usable app‑like on site.
- **Gaps:** no true compact primary nav on mobile; wide `data-table`s and map/chart pages need horizontal‑scroll care; the 239 KB non‑responsive logo is heavy for mobile.

---

## 9. Content & Company Positioning

**What the code communicates about Lenta France (internally):** a technically serious, operationally mature foundations/geotechnical contractor — it tracks rigs and bentonite pumps, reinforcement cages, stratigraphy and concrete curves, GPS‑tracked truck logistics, warehouse and procurement, site budgets and margins, across a bilingual it/fr workforce.

**What the code communicates publicly:** essentially **nothing** — a login button.

**The positioning gap (Fase 2 core finding).** There is a stark mismatch between (a) the demonstrated operational/engineering competence encoded in the software and (b) the **zero public expression** of that competence. A buyer researching Lenta France finds no hero, no service descriptions, no project references, no certifications, no machinery fleet, no team, no proof — because there is no public site at all. If the business goal is to *look like one of the most serious special‑foundations firms on the Côte d'Azur/Monaco*, the current web presence delivers 0% of that; the raw material (real projects, real machinery, real technical depth) clearly exists operationally but has never been turned into public content.

**Do not invent company facts.** Real service list, project references, certifications (e.g. QUALIBAT/FNTP‑type), fleet, headcount, geographic coverage, and brand assets are **not derivable** from this repo and must be gathered from the client (see §22).

---

## 10. SEO

**For the current internal app, SEO is intentionally moot** (login wall, nothing to index). Factual state:

- **Absent:** `robots.txt`, `sitemap.xml`, `<meta name="description">` (present in only 6 templates), `<meta name="keywords">`, `rel="canonical"`, OpenGraph, Twitter cards, JSON‑LD/schema.org, `hreflang`.
- **Present:** localized `<title>` per page (good), PWA/app‑shell meta.
- **No active crawl blocking either** (no `robots`/`noindex`) — but also nothing public to crawl.
- **i18n is cookie‑based on a single URL** (no `/it` `/fr` paths, no `hreflang`) — fine for an app, **unusable for multilingual SEO** if a public site is ever built here.

**Implication for Question B:** a public marketing site would need SEO built from scratch (indexable URLs, per‑language routes + hreflang, service/landing pages targeting terms like *fondations spéciales, pieux forés, parois moulées, micropieux, soutènement, géotechnique*, structured data for LocalBusiness/Organization, sitemap/robots).

---

## 11. Performance

- **Server rendering** keeps client JS light on most pages; heavy libs (Google Maps, ApexCharts, Chart.js, html5‑qrcode) load **only on the pages that need them** (from CDNs jsdelivr/unpkg).
- **Caching:** static assets get `Cache-Control` (`main.py` `add_static_cache_headers`): `style.css` = `no-cache`; versioned/hashed assets = 1‑year immutable; others = 1 day. Service worker precaches the shell and uses stale‑while‑revalidate for css/js.
- **Concerns:**
  - **One 202 KB CSS file** loaded on every page (with `no-cache`, so revalidated each navigation) — no critical‑CSS split, no purge of unused rules; a dead `unused/legacy_style.css` also sits in the tree.
  - **239 KB raster logo**, no responsive/`srcset`, no SVG.
  - **`main.py` at 9,022 lines** imports and constructs a large surface at startup; startup also runs auto‑migrations + admin seeding (import‑time side effects).
  - **No GZip/Brotli middleware** in‑app (compression, if any, depends on the Render edge).
  - **Two chart libraries** shipped for effectively one need.
- **No measured metrics** (no Lighthouse/RUM/perf budget committed). `scripts/perf_smoke.py` exists but is not a web‑vitals tool.

---

## 12. Accessibility

Not formally addressed; mixed signals from a quick read:

- **Positives:** semantic‑ish structure with headings, `aria-label`s on some chart containers and nav, localized page `<title>`s, focusable controls, `<meta viewport>`.
- **Risks / to verify:** **emoji‑as‑icons** without text alternatives in places; a **non‑rendering Bootstrap‑Icons glyph** on a functional control (notifications); dark‑theme **contrast** of muted text (`--color-text-muted:#9fb0c7`) on dark cards should be checked against WCAG AA; dropdown‑heavy nav keyboard operability; forms' label/`for` associations and error messaging; focus management in modals; the mobile navbar overflow. No automated a11y testing exists.

A formal audit (axe/Lighthouse + keyboard pass) is needed; treat current state as **unknown‑leaning‑partial**, not verified‑accessible.

---

## 13. Security & Privacy

**Verified current state (do NOT trust `CODE_REVIEW.md`, which is partly obsolete — it claims `SECRET_KEY` defaults to `changeme` unconditionally and that CORS is fully open; both have since been hardened for production).**

Good posture:
- **Production refuses to start** without `SECRET_KEY` and with wildcard/credentialed CORS (`auth.py:24‑48`, `main.py:399‑439`).
- Passwords hashed with `pbkdf2_sha256`; auth cookies are **HttpOnly**, `SameSite=lax`.
- Refresh‑token rotation middleware; request‑id middleware; localized error pages; an **audit log**.

Weaknesses / risks (evidence):
- 🔴 **Hardcoded fallback admin credentials** in `create_initial_admin` (`main.py:283‑284`): if `ADMIN_EMAIL`/`ADMIN_PASSWORD` env vars are unset, a **known email + password** is provisioned at startup. This is real, committed source and should be treated as a **credential‑exposure / account‑takeover risk** in any environment where the env vars are not set. *(The literal value is deliberately omitted from this document; remediation = require the env vars and fail fast, and rotate the account.)*
- 🟠 **Auth/refresh/role cookies never set `Secure`** — transmittable over HTTP (`main.py:201‑221`, `auth.py:169‑176`); the `lang` cookie is explicitly `secure=False`.
- 🟠 **No security‑headers middleware:** no CSP, HSTS, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`.
- 🟠 **No rate limiting / brute‑force protection** on `/login` or token endpoints.
- 🟠 **Dependencies unpinned** (only `httpx>=0.28.0`) → supply‑chain / reproducibility risk.
- 🟡 **`"changeme"` dev fallback secret** (gated to non‑prod via `ALLOW_DEV_INSECURE_SECRET`).
- 🟡 **Import‑time side effects:** `create_all` + auto‑`ALTER TABLE` + admin seeding run at startup rather than via controlled migrations/bootstrap.
- 🟡 **No `TrustedHostMiddleware` / HTTPS‑redirect** in‑app (may be handled at Render edge — unverified).

**Privacy:** no cookie‑consent banner, no privacy policy, no GDPR page. This is acceptable for a purely internal tool using only functional cookies, but **must** be revisited before any public/marketing site (which would need consent + privacy policy, especially in the EU).

---

## 14. Forms / Leads / Conversion

- **No lead/conversion surface exists.** There are **no contact, quote (devis/preventivo), newsletter, or callback forms** anywhere.
- **Every form is internal CRUD/workflow** (login, users, sites, fiches, rapportini, warehouse, orders, transport, etc.).
- **No outbound email** (no SMTP/SendGrid/SES). The orders "email wizard" (`routes/ordini.py`) assembles email *content* but does not send it in‑app; notifications are **in‑app DB rows only** (`notifications.py`).
- **Only outward contact data:** static phone/fax/email lines in an authenticated fiche **PDF cover** template.

**Implication for Question B:** lead capture, CRM/inbox routing, and transactional email would all be **net‑new** for a public site.

---

## 15. Analytics / Tracking

- **None.** No Google Analytics/GTM, Plausible, Matomo, Meta Pixel, Hotjar, Segment, Mixpanel — verified absent.
- **Cookies are strictly functional:** `access_token`, `refresh_token`, `current_role` (HttpOnly), `lang` (readable, for UI language). No marketing/analytics cookies.
- The word "analytics" in the codebase refers to **internal dashboard charts** (rapportini trends, hours per site), not visitor tracking.

---

## 16. Deployment & Infrastructure

- **Platform:** **Render** (per `database.py` comments), with **external managed PostgreSQL** (Neon/Supabase‑style). SQLite for local dev.
- **No infra‑as‑code in repo:** no Dockerfile, docker‑compose, Procfile, `render.yaml`, `fly.toml`, `runtime.txt`, or `.env.example`. **Start command, Python version, and env‑var configuration live only in the Render dashboard** (not version‑controlled) — a knowledge/repro risk.
- **No CI/CD:** no `.github/workflows`; tests are not run automatically on push. Only helper scripts (`check_conflict_markers.py`, `perf_smoke.py`, `backup_db.py`).
- **Schema management:** startup‑time auto‑migration (`database.py`, `db_upgrade.py`) + 70 raw‑SQL files, no migration ledger/rollback.
- **Required env vars (from code):** `SECRET_KEY` (prod‑required), `DATABASE_URL`, `APP_ENV`/`ENVIRONMENT`/`FASTAPI_ENV`, `CORS_ALLOW_ORIGINS` (+ methods/headers/credentials), `ADMIN_EMAIL`/`ADMIN_PASSWORD`/`ADMIN_LANGUAGE`/`ADMIN_FORCE_RESET`, `GOOGLE_MAPS_API_KEY`, `GPS_PROVIDER`, `ALLOW_DEV_INSECURE_SECRET`, `DB_AUTO_FIX`/`RUN_DB_CHECK`/`DEBUG_DB_SCHEMA_CHECK`, `BACKUP_DIR`, `LOG_*`, `ASSET_VERSION`, `PLAYWRIGHT_CHROMIUM_PATH`.

---

## 17. Technical Debt

- 🔴 **`main.py` is a 9,022‑line god‑module** — app creation, ~75 inline route handlers, startup logic, admin seeding, helpers all in one file. Primary maintainability bottleneck.
- 🟠 **Two parallel router packages** with inconsistent conventions: `routers/` (users, sites, machines, reports, fiches, notifications) vs `routes/` (everything newer). No shared prefix strategy (paths hardcoded per route).
- 🟠 **Duplicated base layouts:** `templates/base.html` vs `templates/shared/base.html` (near‑identical; the former extended by ~10 templates, the latter by ~121).
- 🟠 **Template duplication / half‑finished flat→subfolder refactor:** e.g. `fiches.html` vs `fiches_list.html` vs `fiches_lista.html`; `veicoli_list.html` vs `veicoli/veicoli_list.html`; `personale_list.html` vs `personale/personale_list.html`. Plus a `templates/legacy/` folder of 6 superseded list pages.
- 🟠 **Dead CSS:** `static/css/unused/legacy_style.css`; plus 16 inline `<style>` blocks scattered across templates.
- 🟠 **Duplicated PWA manifests:** `manifest.webmanifest` (linked) vs `manifest.json` (legacy, unlinked, references a non‑square logo as 512×512).
- 🟠 **Mixed ORM** (SQLAlchemy + SQLModel) for no clear reason.
- 🟠 **No Alembic;** ad‑hoc startup schema mutation.
- 🟠 **Unpinned dependencies;** no lockfile.
- 🟡 **Two chart libraries** (ApexCharts + Chart.js) for overlapping needs.
- 🟡 **Broken icon dependency** (Bootstrap‑Icons class without stylesheet).
- 🟡 **Obsolete docs:** `README.md` (3‑line stub), `CODE_REVIEW.md` (stale security claims), `role_access_matrix.md` (phantom CONTABILITA/HR roles).
- 🟡 **i18n via inline `{% if lang=='fr' %}` in ~89 templates** — verbose, error‑prone, hard to keep in sync (three coexisting mechanisms: inline conditionals, `t()` helper, backend dictionary).

---

## 18. Known Weaknesses

- **No public web presence at all** for a company that (per the brief) wants to look like a top‑tier technical firm — the single biggest gap.
- **Security:** hardcoded fallback admin creds; cookies without `Secure`; no security headers; no rate limiting; unpinned deps.
- **Ops:** no CI, no IaC, undocumented Render config, startup‑time migrations, no reproducible builds.
- **Maintainability:** 9k‑line `main.py`; router/template/manifest/CSS duplication; dead code.
- **UI for premium branding:** system fonts, emoji icons, raster logo — fine internally, insufficient for a premium public brand.
- **Mobile:** navbar overflow (no hamburger yet).
- **Accessibility:** unmeasured; several concrete risks.
- **SEO/i18n for public use:** cookie‑based single‑URL i18n is not indexable/multilingual‑SEO‑friendly.

---

## 19. What Is Good and Should Be Preserved

- **Deep, real operational domain model** — sites, machinery, reinforcement cages, fiches with stratigraphy/concrete curves, warehouse, procurement, transport with **real GPS**, equipment QR flow, site economics/margins. This is the company's genuine differentiator and a goldmine of **authentic content** for any future public site.
- **Production security hardening that already exists** (fail‑fast on missing `SECRET_KEY`, prod CORS guards, HttpOnly cookies, refresh rotation, audit log).
- **Cohesive custom design system** with real theming (dark/light), tokens, and a consistent component vocabulary.
- **Multi‑role permission model** (`permissions.py`) that is reasonably granular and centralised.
- **PWA + offline + responsive effort** — sensible for field/jobsite use.
- **Server‑rendered simplicity** — no SPA complexity; fast to reason about per page (module size aside).
- **Bilingual it/fr coverage** across the whole app.
- **A test suite exists** (17 pytest files) and the recent equipment/QR work is tested end‑to‑end.

---

## 20. Opportunities for Improvement

**For the internal app (Question A):** split `main.py` into routers/services; unify `routers/`+`routes/` and the two base templates; delete `legacy/`, `unused/` CSS, and duplicate manifests; adopt Alembic + a bootstrap command (remove import‑time seeding and the hardcoded admin fallback); pin deps + add a lockfile + CI (tests, lint, secret scan); add security headers + `Secure` cookies + login rate limiting; add a mobile hamburger; extract i18n into catalogs; run a formal a11y + Lighthouse pass; consolidate to one chart library; ship an SVG logo + real icon set.

**For the missing public site (Question B):** design and build a **separate, indexable, bilingual (fr/it) marketing website** — hero with real jobsite photography/video, service pages (fondations spéciales, pieux, parois moulées, micropieux, soutènement, géotechnique), a **projects/references** gallery drawn from the (authenticated) real project data, machinery fleet, certifications, team, geographic coverage (Côte d'Azur/Monaco), metrics/proof, and B2B lead capture — with full technical SEO, structured data, analytics + consent, and a premium‑but‑industrial visual identity. This is greenfield and should not be shoehorned into the gestionale.

---

## 21. Important Files Astra Should Inspect First

1. `main.py` — app assembly (`:463`), root/login (`:678`,`:2261`), admin seeding + **hardcoded fallback** (`:269‑292`), CORS (`:399‑439`), middleware (`:470‑580`), router includes (`:9005‑9022`).
2. `auth.py` — SECRET_KEY policy (`:24‑48`), hashing (`:60‑68`), JWT (`:219‑247`), cookies (`:169‑176`), auth deps/redirects (`:322‑342`), login endpoints (`:469‑503`).
3. `permissions.py` — full role→permission matrix and access helpers.
4. `database.py` + `db_upgrade.py` — engine, sessions, **startup auto‑migration**; `migrations/` for the raw‑SQL history.
5. `models/entities.py` — the real domain model and `RoleEnum`.
6. `templates/shared/base.html` — the real layout (nav, mobile bottom‑nav, PWA meta, scripts) and `templates/home.html` / `login.html`.
7. `static/css/style.css` — the entire design system (tokens at top `:root`, light theme `:root[data-theme="light"]`).
8. `routes/trasporti.py` (GPS + logistics), `routes/magazzino.py` (largest module), `routes/manager_attrezzature.py` (QR labels) — representative of the operational depth.
9. `templates/manager/fiches/_pdf_cover.html` — the only outward‑facing company contact strings.
10. `CODE_REVIEW.md`, `docs/role_access_matrix.md`, `README.md` — **read critically; verify against code (several are stale).**

---

## 22. Open Questions (Astra should get answers from the client before Question B)

1. **Goal confirmation:** Do you want (A) an audit/refactor of the internal gestionale, (B) a brand‑new public marketing website, or (C) both? They are separate efforts.
2. **Real company facts** (not derivable from code): exact legal name/entity, precise service list and specialties, flagship **project references** (with client permission to publish), **certifications/qualifications** (QUALIBAT, FNTP, ISO, etc.), fleet inventory, headcount/team, years in business, geographic coverage, and any existing brand assets (SVG logo, brand colors, typography, photography/video library).
3. **Domain & existing presence:** is there a current public domain/site elsewhere (WordPress, etc.)? Any existing analytics/Search Console history? Social profiles?
4. **Target audience priority:** general contractors vs maîtres d'ouvrage vs bureaux d'études vs architects — and the primary desired conversion (contact form? phone? RFQ/appel d'offres?).
5. **Languages/markets:** fr‑only, or fr+it (and any others)? SEO target regions.
6. **Content readiness:** are there professional jobsite photos/videos, case studies, and technical write‑ups available, or must these be produced?
7. **Ops constraints:** must a new public site stay on Render? Any CMS preference for non‑technical editors? Data‑privacy/consent requirements.
8. **Security remediation window:** can the hardcoded admin fallback be removed and the account rotated now?

---

## PROMPT FOR GPT‑6 ASTRA

> Copy everything below (together with this handover file and repository access) into the Astra session.

You are **GPT‑6 Astra**, acting **simultaneously** as: **Principal Web Engineer**, **Senior UX/UI Designer**, **Technical SEO specialist**, **Web‑performance specialist**, **B2B conversion / lead‑generation specialist**, and **digital consultant for a technical firm in the construction/geotechnical sector** (special foundations).

You are auditing the web presence of **Lenta France**, a company specialised in **special foundations and geotechnical works** operating on the **Côte d'Azur / Monaco**. The goal is an **independent, critical, evidence‑based audit** — not validation.

**Ground rules**

1. **Analyse first. Do NOT modify anything** in this phase. Read the entire handover, then **verify its key claims directly against the repository** — the code is the source of truth. Do **not** assume Claude's prior decisions (in code or in this handover) are correct; challenge them where warranted.
2. **Critical framing you must resolve up front (see §0 of the handover):** this repository is an **internal, login‑gated, multi‑role operations gestionale**, **not a public marketing website**. There is no public homepage, hero, services page, references, SEO, analytics, or lead capture — they are **absent by design**, not defects of a marketing site. Treat the work as two separate questions and keep them separate:
   - **A — Audit what exists:** the internal gestionale as an internal B2B operational web app (architecture, code quality, security, maintainability, operator UX, field mobile).
   - **B — Strategise what does not exist:** the **greenfield public marketing website** Lenta France would need to look like one of the most serious and technologically advanced special‑foundations firms on the Côte d'Azur/Monaco. This cannot be "refactored" out of the current app; it would be built fresh.
   State clearly which of A / B / both you are addressing, and ask the client to confirm scope (handover §22) before doing deep Question‑B work.
3. **Do not invent company facts.** Where real service lists, references, certifications, fleet, team, or brand assets are needed and not in the repo, **flag them as questions for the client** (handover §22) rather than fabricating.
4. **Never expose secrets.** The repo contains a hardcoded fallback admin credential (handover §13, `main.py:283‑284`); reference it by location and recommend remediation, but **do not reproduce the value**.
5. **Be fair.** Do not manufacture problems. Where something is done well, say so and mark it **LEAVE AS IS**.

**Evaluate the current artifact across four lenses**

- **A. TECHNICAL** — architecture, code quality/maintainability (note the 9k‑line `main.py`, dual router packages, duplicated templates/manifests/CSS, mixed ORM, no Alembic/CI/IaC, unpinned deps), performance, and security (hardcoded admin fallback, cookies without `Secure`, missing security headers, no rate limiting).
- **B. UX/UI** — visual hierarchy, navigation, responsive/mobile (bottom‑nav, missing hamburger), clarity, and **perceived quality / modernity / credibility** (system fonts, emoji icons, raster logo, dark‑first theme).
- **C. BUSINESS** — if a general contractor, maître d'ouvrage, bureau d'études, or architect lands on Lenta France's web presence, do they quickly understand **why to contact Lenta France**? (Today: they cannot — there is only a login wall.)
- **D. VISIBILITY** — technical SEO, content SEO, semantic structure, and the site's ability to rank for relevant services/works (today: no public, indexable content; cookie‑based single‑URL i18n).

**For every significant proposal, use exactly this structure:**
`Problem → Evidence (file/line or concrete observation) → Impact → Proposed solution → Benefit → Difficulty → Priority`

**Classify every finding as one of:** `CRITICAL` · `HIGH VALUE` · `MEDIUM` · `NICE TO HAVE` · `LEAVE AS IS`.

**Beyond a technical audit — the vision question (required).** Answer explicitly:

> *"If this site were rebuilt today to make Lenta France look like one of the most serious and technologically advanced special‑foundations firms on the Côte d'Azur / Monaco, what would you change?"*

Evaluate and give concrete direction for: homepage, hero, jobsite photography/video, services presentation, references/projects, company metrics/KPIs (if available), proof of competence, qualifications/certifications, machinery, team, geographic coverage, CTAs, contact, micro‑interactions, animations, typography, palette, layout, and storytelling.
**Constraint:** this must remain appropriate for a **real special‑foundations contractor** — a balance of **engineering + jobsites + reliability + technical capability + premium image**. **Not** a generic "AI‑startup" redesign.

**Produce the following outputs, in order:**

1. Executive Summary
2. Overall current assessment
3. Strengths
4. Main problems
5. Technical audit
6. UX/UI audit
7. Mobile audit
8. SEO audit
9. Performance audit
10. Conversion / business audit
11. Proposed visual evolution
12. Proposed new information architecture (if needed)
13. What to keep
14. What to remove
15. What to improve
16. Prioritised roadmap
17. Quick wins
18. Structural interventions
19. Optional **Website V2** proposal

**Finally, give a clear recommendation:** should Lenta France **incrementally improve the current codebase**, or is the current architecture/design so limiting (for the public‑site goal in particular) that a **V2 / separate public site** is preferable? Justify the recommendation with the evidence you gathered.
