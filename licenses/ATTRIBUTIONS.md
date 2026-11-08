# Componenti, licenze e riuso

| Repository/componente | Licenza verificata | Impiego |
|---|---|---|
| [Coach Watts](https://github.com/watt-mind/coach) | Apache-2.0 | Base Nuxt UI: layout, carte fitness adattate, app.config e palette CSS; screenshot di riferimento |
| [Garmin Personal API Python](https://github.com/garmin/connect-personal-api-python) | Apache-2.0 | Client ufficiale installato 1.0.0, autenticazione e letture |
| [Zoned](https://github.com/alarboulletmarin/zoned) | MIT, copyright 2026 alarboulletmarin | Libreria swimming.json e scarti delle zone CSS adattati in Python |
| [Garmin Health Data](https://github.com/diegoscarabelli/garmin-health-data) | Apache-2.0 | Ispezionato modello e pipeline; nessun secondo SQLite/importer. Usa già fitdecode, come il parser locale: duplicarlo non apporta valore |
| [Performance Analytics](https://github.com/samaritano0/Performance-Analytics) | Licenza di riuso non individuata nella ricognizione | Solo riferimento concettuale; nessun codice o asset copiato; stack SQL Server/Power BI non integrato |
| [Claude Coach](https://github.com/dwedigital/claude-coach) | MIT | Solo riferimento; memoria Markdown e contratto coach già esistenti, nessuna nuova dashboard Next.js |
| [Endurain](https://github.com/endurain-project/endurain) | AGPL-3.0 | Solo valutazione; nessun codice incorporato, nessuna migrazione |
| [Garmin Health Dashboard](https://github.com/cggmx/garmin-health-dashboard) | MIT | `SleepCard.tsx` adattata in `frontend/app/components/SleepStagesCard.vue`: Vue, dati canonici e assenze esplicite; esclusi punteggi sintetici e benchmark di popolazione |
| [Garmin-Grafana](https://github.com/arpanghosh8453/garmin-grafana) | BSD-3-Clause | Catalogo di pannelli e screenshot studiati; nessun JSON di dashboard o importer incorporato |
| [Quantified Self](https://github.com/jimmykane/quantified-self) | AGPL-3.0-only, permesso aggiuntivo Mapbox per alcune parti frontend | Modello analitico studiato; nessun codice incorporato |

Ulteriore riuso Coach Watts: `RecoveryContextTimeline.vue` e tipo
`recovery-context.ts` e `CoachCalendarDayCard.vue`, dal commit sotto indicato; traduzioni e adapter locale
sono segnalati nei sorgenti. Nuovi helper di formattazione non copiano
il sistema di servizi/stores upstream.

Garmin Health Dashboard commit `020d7f53fe8b93bbef0eb5555c0481195043fd9d`.
La sua licenza integrale è in `garmin-health-dashboard-MIT.txt`.
La ricerca estesa, distinguendo adattamenti e riferimenti, è in
`docs/RICERCA-DASHBOARD-GITHUB.md`.

Orchestrazione dello sviluppo richiesta dall'utente: skill
`dispatching-parallel-agents` e `verification-before-completion` da
[obra/superpowers](https://github.com/obra/superpowers), MIT, copyright 2025
Jesse Vincent, commit `2ce8aa15d05bd57213e6f746f953aafb7ded7a8b`.
Installate in `~/.codex/skills/` con licenza inclusa. Non sono dipendenze runtime
dell'applicazione e non aggiungono servizi o invio di dati.

Coach Watts commit `4d8d65c297cb326897b74553ee4766ead971b6a7`;
Zoned `739e3666555d5a6e5cdb16e275c6182be08b4b75`;
Garmin Health Data `2a1d5827aaedecdaaa7f314a87d828bafe984c47`.
Cloni di studio separati in `data/references/`, esclusi da Git e dalla build.

Le parti Coach Watts modificate recano avvisi nei sorgenti. Licenze integrali
in `coach-watts-APACHE-2.0.txt` e `zoned-MIT.txt`. Le dipendenze frontend
mantengono le proprie licenze nei pacchetti e nel lockfile.
Nuxt UI, Vue, Tailwind, Chart.js e vue-chartjs non sono componenti proprietari
copiati da Performance Analytics.

Nessun Garmin FIT SDK incorporato: viene riutilizzato il parser fitdecode
già adottato dal progetto. Nessuna esportazione FIT o scrittura Garmin è
presentata come implementata. Le condizioni della Personal API continuano
ad applicarsi al suo uso personale.
