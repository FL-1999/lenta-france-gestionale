# Audit UI/UX & Mobile — Lenta France Gestionale

## Scope & note
- **Solo analisi**: nessuna modifica di logica business.
- **Output**: checklist, problemi mobile e roadmap in 4 fasi.
- **TODO commentati** inseriti in `static/css/style.css` come promemoria per gli step successivi.

---

## 1) Scansione struttura progetto (routes, templates, static, auth/roles)

### Routes & routers
- **App principale / route HTML**: `main.py`
  - Dashboard manager: `GET /manager/dashboard`
  - Dashboard caposquadra: `GET /capo/dashboard`
  - Cantieri manager: `GET /manager/cantieri`, `GET/POST /manager/cantieri/nuovo`, `GET/POST /manager/cantieri/{site_id}/modifica`
  - Magazzino: `routes/magazzino.py` (tutte le route `manager_magazzino_*` e `capo_magazzino_*`)
- **Routers API**: `routers/` (users, sites, machines, reports, fiches)
- **Routes specialistiche HTML**: `routes/` (audit, manager_personale, manager_veicoli, magazzino)

### Templates
- Base/layout: `templates/shared/base.html`, `templates/base.html`
- Home pubblica: `templates/home.html`
- Manager: `templates/manager/` + `templates/manager_*.html`
- Caposquadra: `templates/capo/` + `templates/capo_*.html`
- Magazzino: `templates/manager/magazzino/` e `templates/capo/magazzino/`

### Static assets
- CSS principale: `static/css/style.css`
- JS: `static/js/` (mappe cantieri, preview map, theme switcher, charts)
- Immagini: `static/img/`

### Auth / roles
- Autenticazione JWT/cookie: `auth.py`
- Ruoli: `models.py` (`RoleEnum`: `admin`, `manager`, `caposquadra`)
- Guard rails HTML: `get_current_active_user_html` e check su ruolo nei route HTML (`main.py`, `routes/magazzino.py`).

---

## 2) Pagine principali (path + template)

- **Home manager**
  - Route: `GET /manager/dashboard` (`main.py`)
  - Template: `templates/manager/home_manager.html`
- **Home caposquadra**
  - Route: `GET /capo/dashboard` (`main.py`)
  - Template: `templates/capo/home_capo.html`
- **Lista cantieri**
  - Route: `GET /manager/cantieri` (`main.py`)
  - Template: `templates/manager/cantieri.html`
  - Alternativa legacy: `templates/manager/cantieri_lista.html` (usata in viste storiche/alternative)
- **Form cantiere**
  - Route: `GET/POST /manager/cantieri/nuovo`, `GET/POST /manager/cantieri/{site_id}/modifica` (`main.py`)
  - Template: `templates/manager/cantiere_form.html`
- **Magazzino**
  - Manager: `GET /manager/magazzino` (`routes/magazzino.py`) -> `templates/manager/magazzino/items_list.html`
  - Caposquadra: `GET /capo/magazzino` (`routes/magazzino.py`) -> `templates/capo/magazzino/items_list.html`
- **Sotto soglia**
  - Route: `GET /manager/magazzino/sotto-soglia` (`routes/magazzino.py`)
  - Template: `templates/manager/magazzino/sotto_soglia.html`

---

## 3) Problemi mobile attuali (layout, navbar, tabelle, bottoni, mappe, modali)

> **Legenda priorità:** P0 = altissimo impatto/alto rischio; P1 = alto; P2 = medio; P3 = basso.

### Layout generale
- [ ] **P1**: densità elevata di card/griglie su schermi piccoli (KPI, shortcut, moduli) con gap fissi -> rischio di scroll lungo e overload visivo.
- [ ] **P2**: padding generosi in `container` e `card` che comprimono contenuti su 360px.

### Navbar
- [ ] **P0**: navbar orizzontale senza collapse/hamburger -> overflow su mobile con molte voci e badge.
- [ ] **P1**: badge e label a fianco delle icone aumentano la larghezza minima.

### Tabelle/listati
- [ ] **P0**: tabelle senza contenitore scroll orizzontale dedicato -> colonne vanno a capo e diventano poco leggibili.
- [ ] **P1**: azioni in colonna (`.table-actions`) con molti bottoni -> tapp target stretti e wrapping incoerente.

### Bottoni & CTA
- [ ] **P1**: pulsanti inline con `white-space: nowrap` e affiancamenti multipli -> rischio overflow orizzontale.
- [ ] **P2**: mancano size/stacking dedicati a mobile per CTA primarie/secondarie.

### Mappe
- [ ] **P1**: mappe con altezza fissa (`420px`) su mobile -> prende quasi tutta la viewport e rende difficile scroll.
- [ ] **P2**: nessun fallback mobile per "tap-to-expand" o modalità compatta.

### Modali
- [ ] **P1**: modali centrati con larghezza fissa `min(720px, 100%)` e padding standard -> su mobile manca una modalità full-screen e un close coerente.

---

## 4) Roadmap in 4 fasi (impatto/rischio)

### Fase A — UI Mobile (alta priorità, basso rischio)
**Obiettivo:** rendere navigazione e principali viste usabili su 360–414px.
- [ ] A1. Navbar responsive con hamburger/off-canvas (riduzione label, badge compatti).
- [ ] A2. Tabelle: wrapper scroll orizzontale + header sticky + semplificazione colonne su mobile.
- [ ] A3. CTA: stacking verticale dei bottoni + size `btn-lg` per touch.
- [ ] A4. Modali: versione full-screen + close sempre visibile.
- [ ] A5. Mappe: altezza ridotta + toggle “espandi mappa”.

### Fase B — PWA (medio impatto, rischio medio)
**Obiettivo:** installabilità e uso offline di base.
- [ ] B1. Aggiungere `manifest.json` e icone PWA.
- [ ] B2. Service worker per cache statica (CSS/JS/logo).
- [ ] B3. Offline fallback per pagine principali (home, dashboard).

### Fase C — Performance (alto impatto, rischio medio)
**Obiettivo:** migliorare tempo di rendering e carichi pesanti.
- [ ] C1. Lazy-load delle mappe (caricare JS maps solo quando visibile).
- [ ] C2. Ridurre payload di tabelle (paginazione o virtualizzazione).
- [ ] C3. Audit CSS duplicato (`templates/css/style.css` vs `static/css/style.css`).

### Fase D — Test/Regressione (medio impatto, basso rischio)
**Obiettivo:** evitare regressioni UI/UX.
- [ ] D1. Checklist manuale mobile (360/414px) per home manager/capo + magazzino.
- [ ] D2. Snapshot visuali dei layout chiave.
- [ ] D3. Test accessibilità base (focus order, contrasto, tapp target).

---

## Checklist interventi (ordinati per impatto/rischio)

- [ ] **P0** Navbar responsive + riduzione densità voci (Fase A1)
- [ ] **P0** Tabelle con scroll orizzontale e azioni raggruppate (Fase A2)
- [ ] **P1** Modali full-screen mobile + close coerente (Fase A4)
- [ ] **P1** CTA stacking verticale + target touch (Fase A3)
- [ ] **P1** Mappe con altezza dinamica + toggle (Fase A5)
- [ ] **P2** PWA manifest + SW statico (Fase B1-B2)
- [ ] **P2** Lazy-load mappe + paginazione tabelle (Fase C1-C2)
- [ ] **P3** Test regressione visuale e checklist mobile (Fase D1-D3)
