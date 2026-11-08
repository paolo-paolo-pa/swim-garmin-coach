# Swim Garmin Coach

A swim coach that runs **on your own computer**: it reads your Garmin watch data and shows how you are
doing and what has changed, without inventing a single number.

> Status: working prototype, shared as a developed project. All data in this repository is **synthetic**.
> The code, comments and in-app texts are in Italian; this README is in English.

## What it does

- **Swim analytics**: volume (weeks without swims shown as 0 km, periods without data shown as gaps),
  repeat comparison by distance, stroke and pool length, SWOLF and pace by watch model.
- **Open water**: sessions and heart rate, with GPS checks.
- **Load and recovery**: sleep, HRV, resting heart rate with personal baselines and explicit missing-data bands.
- **Calendar and planning**: planned vs done, 1-4 week proposals, workout builder, critical swim speed tests.
- **Coach (optional)**: an AI assistant that only receives an analytic package and whose numbers are validated.

## Principles

1. Calculation is deterministic; the language model only interprets.
2. Missing data stays missing. A zero and "no data" never look alike.
3. Comparisons across different pools, strokes or watch models are refused, not footnoted.

## Quick start (Windows, Python 3.12, Node 20+)

```bash
python -m venv .venv && .venv\Scripts\pip install -e .
python scripts/make_demo_data.py          # creates a synthetic archive in data/
cd frontend && npm ci && npm run build && cd ..
python -m uvicorn garmin_coach.app.server:app --port 8766
```

Open <http://127.0.0.1:8766/>. Tests: `python -m pytest tests`.

## Using your own data

Put your athlete notes in `coach/` and your Garmin export in `garmin-export/` (both ignored by git), or use the
optional Garmin personal API. A trainer can run a separate copy with their own data: nothing leaves the computer.
Watch models are declared in `coach/orologi.md` (see `coach/LEGGIMI.md`).

## Credits and license

MIT. The interface derives from [Coach Watts](https://github.com/newpush/coach) (Apache-2.0); see
`licenses/` for all reused components. Not affiliated with Garmin.
