"""La fotografia dello stato, ricalcolata a comando (D0).

## La domanda a cui risponde

*"Cosa c'è davvero nel database adesso, e cosa non c'è?"*

Un rapporto di stato scritto a mano invecchia il giorno dopo e comincia a mentire
senza che nessuno se ne accorga: è già successo due volte in questo progetto —
un audit ha letto le vasche mentre un import era in corso e ha registrato
un terzo delle righe reali.

Questa fotografia si ricalcola con un comando. Se il numero è vecchio è perché
non l'hai rifatta, non perché qualcuno l'ha trascritta male.

## Cosa separa

La distinzione che conta è fra **baseline immutabile** e **stato crescente**:

- l'export Garmin copre fino al 4 luglio 2026 ed è chiuso: quei numeri non
  devono più cambiare, e se cambiano è un errore;
- tutto ciò che viene dopo arriva dal sync e cresce a ogni nuotata: pretendere
  che resti uguale a un atteso significa fallire ogni volta che l'atleta si
  allena.

Confonderle è il difetto che ha fatto fallire cinque criteri su quattordici
finché non sono stati ancorati alla data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

import duckdb

from .database import table_exists

from . import paths
from .verification import EXPORT_LAST_DAY

# Copertura di un campo: quante sedute della baseline lo hanno davvero.
# Sono le colonne su cui si regge o cade un'analisi, non tutte quelle esistenti.
COVERAGE_FIELDS = [
    ("frequenza cardiaca", "avg_hr_bpm", "assente prima del 2021 (R9)"),
    ("carico Garmin", "garmin_training_load", "assente prima del 2021"),
    ("RPE percepito", "rpe", "inserito a mano sull'orologio"),
    ("SWOLF", "avg_swolf", "confrontabile solo a parità di vasca e dispositivo"),
    ("distanza per bracciata", "avg_stroke_distance_m", "Garmin scrive 0 al posto del vuoto"),
]


@dataclass
class StateReport:
    taken_at: datetime
    baseline: dict = field(default_factory=dict)
    current: dict = field(default_factory=dict)
    coverage: list = field(default_factory=list)
    detail: dict = field(default_factory=dict)
    tables: list = field(default_factory=list)

    def lines(self) -> list[str]:
        out = [
            f"FOTOGRAFIA DELLO STATO — {self.taken_at:%d/%m/%Y %H:%M}",
            "",
            f"  BASELINE IMMUTABILE (fino al {EXPORT_LAST_DAY})",
            "  Questi numeri non devono più cambiare.",
        ]
        for label, value in self.baseline.items():
            out.append(f"    {label:<34} {value:>9,}")

        out += ["", "  STATO CORRENTE (cresce a ogni nuotata)"]
        for label, value in self.current.items():
            formatted = f"{value:,}" if isinstance(value, int) else str(value)
            out.append(f"    {label:<34} {formatted:>9}")

        out += ["", "  COPERTURA SULLA BASELINE",
                "  Un'analisi che usa un campo scoperto al 40% non è più precisa,",
                "  è solo più sicura di sé."]
        for label, present, total, share, caveat in self.coverage:
            out.append(f"    {label:<24} {present:>5,}/{total:<6,} {share:>4.0%}   {caveat}")

        out += ["", "  DETTAGLIO DELLE SEDUTE (file FIT)"]
        for label, value in self.detail.items():
            formatted = f"{value:,}" if isinstance(value, int) else str(value)
            out.append(f"    {label:<34} {formatted:>9}")

        out += ["", "  TABELLE"]
        for name, rows in self.tables:
            out.append(f"    {name:<34} {rows:>9,}")
        return out

    def text(self) -> str:
        return "\n".join(self.lines())


def _one(connection: duckdb.DuckDBPyConnection, sql: str) -> object:
    return connection.execute(sql).fetchone()[0]


def take(connection: duckdb.DuckDBPyConnection) -> StateReport:
    report = StateReport(taken_at=datetime.now())
    baseline = f"activity_date <= DATE '{EXPORT_LAST_DAY}'"

    report.baseline = {
        "attività": _one(connection, f"SELECT count(*) FROM activities WHERE {baseline}"),
        "sedute di nuoto": _one(connection,
                                f"SELECT count(*) FROM activities WHERE is_swim AND {baseline}"),
        "di cui in vasca": _one(connection, "SELECT count(*) FROM activities WHERE "
                                            f"sport = 'lap_swimming' AND {baseline}"),
        "di cui in acque libere": _one(connection, "SELECT count(*) FROM activities WHERE "
                                       f"sport = 'open_water_swimming' AND {baseline}"),
    }

    # daily_status non fa parte dello schema di base: la crea il calcolo delle
    # metriche. Prima che sia stato eseguito la fotografia deve dirlo, non
    # fallire: uno stato incompleto è un'informazione, un errore no.
    has_status = table_exists(connection, "daily_status")
    last_day = None
    if has_status:
        last_day = _one(connection, "SELECT max(status_date) FROM daily_status")

    report.current = {
        "attività totali": _one(connection, "SELECT count(*) FROM activities"),
        "sedute di nuoto totali": _one(connection,
                                       "SELECT count(*) FROM activities WHERE is_swim"),
        f"aggiunte dopo il {EXPORT_LAST_DAY}": _one(
            connection, f"SELECT count(*) FROM activities WHERE NOT ({baseline})"),
        "giorni in daily_status": _one(connection, "SELECT count(*) FROM daily_status")
        if has_status else "non ancora calcolata",
        "ultimo giorno con dati": str(last_day) if last_day else "—",
        "giorni di ritardo": (date.today() - last_day).days if last_day else "—",
    }

    total = report.baseline["sedute di nuoto"]
    for label, column, caveat in COVERAGE_FIELDS:
        present = _one(connection,
                       f"SELECT count({column}) FROM activities WHERE is_swim AND {baseline}")
        report.coverage.append((label, present, total,
                                present / total if total else 0, caveat))

    # Il dettaglio FIT ha tre coperture diverse, e vanno tenute separate: un FIT
    # agganciato non garantisce che contenga vasche, e una seduta senza vasche in
    # mare non è un dato mancante ma un concetto che non esiste (criterio 11).
    pool = _one(connection, "SELECT count(*) FROM activities WHERE sport = 'lap_swimming'")
    if table_exists(connection, "activity_laps") and table_exists(connection, "pool_lengths"):
        matched = _one(connection, "SELECT count(DISTINCT activity_id) FROM activity_laps")
        with_lengths = _one(connection,
                            "SELECT count(DISTINCT activity_id) FROM pool_lengths WHERE is_active")
        sea = _one(connection, "SELECT count(*) FROM activities "
                               "WHERE sport = 'open_water_swimming'")
        sea_matched = _one(connection, "SELECT count(DISTINCT activity_id) FROM "
                                       "activity_laps WHERE environment = 'open_water'")
        # Etichette distinte: due voci con lo stesso nome si sovrascriverebbero
        # a vicenda, e la fotografia mostrerebbe un numero al posto di un altro.
        report.detail = {
            "sedute in vasca": pool,
            "  in vasca, con FIT": matched - sea_matched,
            "  in vasca, con vasche": with_lengths,
            "sedute in acque libere": sea,
            "  in mare, con FIT": sea_matched,
            "  in mare, vasche": "non applicabile per definizione",
        }
        # I verdetti dicono *perché* una seduta non ha il dettaglio. Senza,
        # "manca" e "ce n'erano due e non ho scelto" sono la stessa riga.
        if table_exists(connection, "activity_source_matches"):
            for verdict, count in connection.execute(
                    "SELECT verdict, count(DISTINCT activity_id) "
                    "FROM activity_source_matches GROUP BY 1 ORDER BY 2 DESC").fetchall():
                report.detail[f"verdetto: {verdict}"] = count
    else:
        report.detail = {"dettaglio FIT": "non ancora importato"}

    names = [row[0] for row in connection.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'main' ORDER BY table_name").fetchall()]
    report.tables = [(name, _one(connection, f"SELECT count(*) FROM {name}"))
                     for name in names]
    return report


def backup_database(label: str) -> "paths.Path":
    """Una copia del database prima di toccarne lo schema (D0).

    Non è un sistema di backup: è la rete sotto le migrazioni. Il database resta
    interamente ricostruibile dall'export, ma ricostruirlo costa minuti e una
    copia costa secondi.
    """
    import shutil

    paths.ensure_data_dirs()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = paths.DATA / "backup" / f"coach-{stamp}-{label}.duckdb"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(paths.DATABASE, destination)
    return destination
