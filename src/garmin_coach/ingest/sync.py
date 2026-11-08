"""Aggiornamento incrementale da Garmin Connect.

L'export scaricato a mano si ferma a una data. Questo modulo colma il divario e
lo tiene colmato, senza toccare né l'export né il resto del sistema.

**Isolamento.** È l'unica parte del progetto che parla con l'esterno. Se Garmin
cambia l'autenticazione — è già successo a marzo 2026 con la deprecazione di
``garth`` — si rompe solo questo file: il coach continua a funzionare sui dati
locali, dichiarando che non sono aggiornati.

**Credenziali.** Questo modulo non le chiede e non le conserva mai. Il primo
accesso lo esegue l'atleta con ``python -m garmin_coach login``: le credenziali
vanno da lui direttamente alla libreria Garmin, che salva un token in
``data/garmin_token/``. Da lì in poi il sync usa solo il token.

**Unità di misura.** L'API web non è coerente con sé stessa: misurato il
2026-08-20 sull'account reale, la distanza arriva in metri e la lunghezza vasca
in centimetri (2500 per una vasca da 25 m). Invece di assumere una forma, ogni
valore viene riportato all'unità del database provando le scale note e
tenendo la prima che lo porta in un intervallo fisicamente sensato. La scala
riconosciuta finisce nel report, così resta visibile e non diventa una magia
nascosta nel codice.

Se **nessuna** scala nota spiega un valore — 900 bpm non è un problema di unità
di misura — il sync si ferma senza scrivere niente.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import duckdb

from .. import paths, timestamps
from . import garmin_read_only
from .garmin_login import (  # noqa: F401 - riesportati per compatibilità
    RateLimited, TOKEN_STORE, connect_client, log_in as save_login)

# Quanti giorni si riscaricano oltre l'ultimo già presente. Garmin corregge i
# dati del giorno precedente (sonno, stress, body battery): senza sovrapposizione
# si conserverebbe una versione provvisoria.
OVERLAP_DAYS = 3

# Il divario massimo colmabile in una sola esecuzione. Oltre, meglio un export
# completo che migliaia di chiamate.
MAX_CATCHUP_DAYS = 120

SOURCE_PREFIX = "garmin-connect://"

# ── Controlli di plausibilità ───────────────────────────────────────────────
# L'API web di Garmin usa unità SI (metri, secondi); l'export usa unità scalate
# (centimetri, millisecondi). Se il sync ricevesse i formati dell'export
# scriverebbe distanze cento volte più grandi. Questi limiti lo impediscono.
PLAUSIBLE = {
    "distance_m": (0, 100_000),        # 100 km in una sola sessione è già assurdo
    "duration_s": (0, 24 * 3600),
    "avg_hr_bpm": (25, 230),
    "pool_length_m": (10, 100),
    "avg_swolf": (10, 200),
    "resting_hr_bpm": (25, 120),
    "total_sleep_s": (0, 20 * 3600),
    "hrv_ms": (5, 250),
    # Metriche tecniche e di carico. Garmin scrive 0 al posto del dato mancante
    # su queste in particolare: lo zero non entra mai (vedi _checked).
    "avg_stroke_distance_m": (0.3, 5),     # metri per bracciata
    "avg_swim_cadence_spm": (5, 150),      # bracciate al minuto
    "total_strokes": (1, 50_000),
    "garmin_training_load": (0.1, 1_000),
    "training_effect": (0.1, 5.1),         # scala Garmin, 0-5
}


# Le scale che Garmin usa davvero. Misurato sul campo il 2026-08-20: l'API web
# restituisce la distanza in metri ma la lunghezza vasca in **centimetri**
# (2500 per una vasca da 25 m). Non è un'incoerenza da correggere a mano: è la
# forma reale della risposta, e va riconosciuta invece che assunta.
#
# Per ogni campo si provano i divisori in ordine. Vince il primo che porta il
# valore dentro l'intervallo fisicamente sensato. Se nessuno ci riesce, il
# valore è davvero anomalo e il sync si ferma.
UNIT_CANDIDATES = {
    "distance_m": (1.0, 100.0),            # metri o centimetri
    "duration_s": (1.0, 1000.0),           # secondi o millisecondi
    "pool_length_m": (1.0, 100.0),         # metri o centimetri
    "avg_stroke_distance_m": (1.0, 100.0),
    "avg_hr_bpm": (1.0,),                  # mai scalata
    "resting_hr_bpm": (1.0,),
    "avg_swolf": (1.0,),
    "total_sleep_s": (1.0, 1000.0),
    "hrv_ms": (1.0,),
}

UNIT_NAMES = {1.0: "unità base", 100.0: "centesimi", 1000.0: "millesimi"}


class ImplausibleValue(ValueError):
    """Un valore che non torna con nessuna delle scale note: non è un problema
    di unità di misura, è un dato anomalo."""


def _checked(name: str, value: object, detected: dict | None = None) -> float | None:
    """Il valore riportato all'unità del database, riconoscendone la scala."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number == 0:
        return None

    low, high = PLAUSIBLE[name]
    for divisor in UNIT_CANDIDATES.get(name, (1.0,)):
        candidate = number / divisor
        if low <= candidate <= high:
            if divisor != 1.0 and detected is not None:
                detected[name] = UNIT_NAMES.get(divisor, f"÷{divisor:g}")
            return candidate

    tried = ", ".join(f"÷{d:g} → {number / d:g}"
                      for d in UNIT_CANDIDATES.get(name, (1.0,)))
    raise ImplausibleValue(
        f"{name} = {number}: nessuna scala nota lo porta nell'intervallo "
        f"{low}-{high} (provate: {tried}). Il sync si ferma invece di scrivere "
        "un dato che non sa interpretare.")


OK = "ok"
PARTIAL = "partial"
FAILED = "failed"


@dataclass
class SyncReport:
    """Cosa il sync ha davvero fatto, con tre esiti invece di due.

    ``succeeded`` era vero ogni volta che ``errors`` era vuoto, e gli errori dei
    singoli giorni non finivano lì dentro: un sync in cui **ogni** giorno era
    fallito si dichiarava riuscito, scriveva nel log che era andato bene, e
    lasciava l'atleta a guardare dati vecchi convinto che fossero freschi.

    Due esiti non bastano. «Tutto preso», «ci sono buchi noti» e «non ho preso
    niente» sono tre situazioni diverse per chi le legge, e portano a tre gesti
    diversi: nessuno, ricontrollare fra un'ora, guardare cosa si è rotto.
    """

    start: date | None = None
    end: date | None = None
    activities_from: date | None = None
    health_from: date | None = None
    activities_written: int = 0
    health_days_written: int = 0
    health_days_requested: int = 0
    errors: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    empty_days: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    units_detected: dict = field(default_factory=dict)

    @property
    def outcome(self) -> str:
        """Tre esiti, e la distinzione che li rende utili.

        Un giorno in cui Garmin risponde «non ho niente» è una risposta giusta:
        l'orologio non era al polso. Un giorno in cui la chiamata esplode non è
        una risposta. Confonderli farebbe due danni opposti — un archivio con
        buchi veri che si dichiara completo, oppure un sync sano che grida al
        guasto ogni volta che l'atleta è stato un giorno senza orologio.
        """
        if self.errors:
            return FAILED
        # Aver chiesto dei giorni e aver visto fallire **tutti** i tentativi non
        # è un sync riuscito con zero novità: è un sync che non ha funzionato.
        if self.skipped and len(self.skipped) == self.health_days_requested:
            return FAILED
        if self.skipped:
            return PARTIAL
        return OK

    @property
    def succeeded(self) -> bool:
        """Falso solo quando non è arrivato niente.

        Un sync parziale ha portato dati veri e vale la pena tenerli: quello
        che non deve fare è passare per completo, e infatti ``summary()`` lo
        dice e ``outcome`` lo distingue.
        """
        return self.outcome != FAILED

    def summary(self) -> str:
        if self.errors:
            return f"sync fallito: {self.errors[0]}"
        if self.outcome == FAILED:
            return (f"sync fallito: nessuno dei {self.health_days_requested} "
                    f"giorni chiesti a Garmin è arrivato "
                    f"({len(self.skipped)} tentativi non riusciti)")

        testa = "sync parziale" if self.outcome == PARTIAL else "sync"
        line = (f"{testa} {self.start} → {self.end}: "
                f"{self.activities_written} attività, "
                f"{self.health_days_written} giorni di salute"
                f" su {self.health_days_requested}")
        if self.skipped:
            line += f"\n  {len(self.skipped)} giorni non presi, elencati sotto"
        if self.empty_days:
            line += (f"\n  {len(self.empty_days)} giorni senza dati su Garmin "
                     "(orologio non indossato, o non ancora sincronizzato)")
        for nota in self.limitations:
            line += f"\n  {nota}"
        if self.units_detected:
            scales = ", ".join(f"{k} in {v}"
                               for k, v in sorted(self.units_detected.items()))
            line += f"\n  scale riconosciute: {scales}"
        return line


def _last_day(connection: duckdb.DuckDBPyConnection, table: str,
              column: str) -> date | None:
    return connection.execute(f"SELECT max({column}) FROM {table}").fetchone()[0]


def _cursors(connection: duckdb.DuckDBPyConnection
             ) -> tuple[date | None, date | None]:
    """Da dove riparte ciascuna delle due famiglie di dati.

    Erano un cursore solo, il massimo fra le due. Una nuotata di ieri spostava
    il cursore in avanti anche con la salute ferma a tre mesi prima: quel buco
    non si sarebbe chiuso mai più, e niente lo diceva.

    Le due famiglie hanno vite separate per davvero — l'orologio scarico non
    registra il sonno ma l'attività la carica il telefono — quindi vogliono due
    cursori. Se una delle due non ha nessuna riga si riparte dall'altra: è
    l'unico riferimento che c'è.
    """
    attivita = _last_day(connection, "activities", "activity_date")
    salute = _last_day(connection, "daily_health", "health_date")
    return (attivita or salute), (salute or attivita)


def _activity_row(raw: dict, imported_at: datetime,
                  detected: dict | None = None) -> tuple | None:
    """Un'attività dell'API web nella forma della tabella ``activities``.

    L'API web usa unità SI: metri e secondi, non centimetri e millisecondi come
    l'export. **Ogni** valore numerico passa dal controllo di plausibilità: un
    campo che entra grezzo è un campo che può scrivere uno zero al posto di un
    dato mancante, e uno zero finto inquina ogni media che lo attraversa.
    """
    activity_id = raw.get("activityId")
    start = timestamps.to_utc(raw.get("startTimeGMT"))
    if activity_id is None or start is None:
        return None

    local = timestamps.to_utc(raw.get("startTimeLocal"))
    sport = ((raw.get("activityType") or {}).get("typeKey")
             or raw.get("activityType") or "unknown")
    is_swim = sport in ("lap_swimming", "open_water_swimming")

    return (
        int(activity_id),
        start.replace(tzinfo=None),
        local.replace(tzinfo=None) if local else None,
        (local or start).date(),
        sport,
        is_swim,
        {"lap_swimming": "pool", "open_water_swimming": "open_water"}.get(sport),
        raw.get("activityName"),
        _checked("duration_s", raw.get("duration"), detected),
        _checked("duration_s", raw.get("elapsedDuration"), detected),
        _checked("duration_s", raw.get("movingDuration"), detected),
        _checked("distance_m", raw.get("distance"), detected),
        _checked("avg_hr_bpm", raw.get("averageHR"), detected),
        _checked("avg_hr_bpm", raw.get("maxHR"), detected),
        _checked("pool_length_m", raw.get("poolLength"), detected),
        _checked("avg_swolf", raw.get("averageSwolf"), detected),
        _checked("avg_stroke_distance_m", raw.get("avgStrokeDistance"), detected),
        _checked("avg_swim_cadence_spm",
                 raw.get("averageSwimCadenceInStrokesPerMinute"), detected),
        _checked("total_strokes", raw.get("strokes"), detected),
        _checked("garmin_training_load", raw.get("activityTrainingLoad"), detected),
        _checked("training_effect", raw.get("aerobicTrainingEffect"), detected),
        _checked("training_effect", raw.get("anaerobicTrainingEffect"), detected),
        int(raw["deviceId"]) if raw.get("deviceId") else None,
        f"{SOURCE_PREFIX}activity/{activity_id}",
        imported_at,
    )


_ACTIVITY_COLUMNS = [
    "activity_id", "start_time_utc", "start_time_local", "activity_date",
    "sport", "is_swim", "environment", "name",
    "duration_s", "elapsed_s", "moving_s", "distance_m",
    "avg_hr_bpm", "max_hr_bpm", "pool_length_m", "avg_swolf",
    "avg_stroke_distance_m", "avg_swim_cadence_spm", "total_strokes",
    "garmin_training_load", "garmin_aerobic_te", "garmin_anaerobic_te",
    "device_id", "source_object_id", "imported_at",
]


def pull(connection: duckdb.DuckDBPyConnection, until: date | None = None,
         client=None) -> SyncReport:
    """Scarica il periodo mancante e lo scrive nelle stesse tabelle dell'export."""
    report = SyncReport()
    until = until or date.today()

    ultima_attivita, ultima_salute = _cursors(connection)
    if ultima_attivita is None:
        report.errors.append(
            "Il database è vuoto: eseguire prima l'import dall'export.")
        return report

    # Il tetto guarda la famiglia **più fresca**: se perfino quella è indietro
    # di oltre quattro mesi, il database è vecchio e la risposta giusta è un
    # export nuovo, non migliaia di chiamate. Se invece è indietro una sola
    # famiglia, quella si recupera fin dove il tetto arriva e il buco che resta
    # viene dichiarato — bloccare le attività di oggi perché la salute è vecchia
    # sarebbe di nuovo l'accoppiamento che stiamo togliendo.
    piu_fresca = max(ultima_attivita, ultima_salute)
    if (until - (piu_fresca - timedelta(days=OVERLAP_DAYS))).days > MAX_CATCHUP_DAYS:
        report.errors.append(
            f"Divario di {(until - piu_fresca).days} giorni, oltre il limite di "
            f"{MAX_CATCHUP_DAYS}. Conviene un nuovo export completo da Garmin.")
        return report

    def _finestra(ultimo: date, cosa: str) -> date:
        inizio = ultimo - timedelta(days=OVERLAP_DAYS)
        tetto = until - timedelta(days=MAX_CATCHUP_DAYS)
        if inizio < tetto:
            report.limitations.append(
                f"{cosa}: restano scoperti i giorni dal {inizio} al {tetto}, "
                f"oltre il tetto di {MAX_CATCHUP_DAYS} giorni per esecuzione. "
                "Rilanciare il sync li recupera un pezzo per volta.")
            return tetto
        return inizio

    report.activities_from = _finestra(ultima_attivita, "attività")
    report.health_from = _finestra(ultima_salute, "salute")
    start = min(report.activities_from, report.health_from)
    report.start, report.end = start, until

    # Il client passa sempre dal muro di sola lettura (D3): i metodi di
    # scrittura di Garmin non sono raggiungibili da qui, e ogni risposta viene
    # salvata su disco prima di essere interpretata.
    try:
        if client is None:
            raw_client = connect_client()
            capabilities = garmin_read_only.probe(raw_client)
            if not capabilities.usable:
                report.errors.append(capabilities.explain())
                return report
            client = garmin_read_only.wrap(raw_client)
    except (RuntimeError, Exception) as error:  # noqa: BLE001
        report.errors.append(str(error))
        return report

    imported_at = datetime.now(timezone.utc).replace(tzinfo=None)

    try:
        activities = client.get_activities_by_date(
            report.activities_from.isoformat(), until.isoformat())
    except Exception as error:  # noqa: BLE001
        report.errors.append(f"Garmin non ha risposto: {type(error).__name__}")
        return report

    rows = []
    for raw in activities or []:
        try:
            row = _activity_row(raw, imported_at, report.units_detected)
        except ImplausibleValue as error:
            report.errors.append(str(error))
            return report          # meglio fermarsi che scrivere dati sbagliati
        if row:
            rows.append(row)

    if rows:
        placeholders = ", ".join("?" * len(_ACTIVITY_COLUMNS))
        connection.executemany(
            f"INSERT INTO activities ({', '.join(_ACTIVITY_COLUMNS)}) "
            f"VALUES ({placeholders}) ON CONFLICT (activity_id) DO UPDATE SET "
            + ', '.join(f'{c} = COALESCE(excluded.{c}, activities.{c})'
                        for c in _ACTIVITY_COLUMNS if c != 'activity_id'), rows)
        report.activities_written = len(rows)

    report.health_days_written = _pull_health(
        connection, client, report.health_from, until, imported_at, report)

    connection.execute(
        "INSERT OR REPLACE INTO import_log "
        "(source_path, source_object_id, target_table, rows_written, imported_at) "
        "VALUES (?, ?, 'activities', ?, ?)",
        [f"{SOURCE_PREFIX}activities/{report.activities_from}_{until}",
         f"{SOURCE_PREFIX}{report.activities_from}_{until}",
         report.activities_written, imported_at])
    return report


# La mappatura fra il riepilogo giornaliero dell'API web e le colonne di
# ``daily_health``. Sta in una tabella e non sparsa dentro una INSERT perché è
# la cosa che si dimentica di aggiornare: le nove righe in fondo erano colonne
# che esistevano nel database, arrivavano nel payload, e nessuno leggeva. Nella
# pagina Oggi la Body Battery risultava assente — non perché Garmin non la
# mandi, ma perché nessuno l'aveva presa.
#
# I nomi non sono indovinati: sono letti da una cattura reale del 19/08/2026 in
# ``data/raw/garmin-connect/``, e ``test_sync_field_mapping`` li ricontrolla
# contro le catture ogni volta che gira.
#
# Attenzione: l'export usa nomi diversi per le stesse cose (``averageSpo2Value``
# invece di ``averageSpo2``). Sono due sorgenti, una sola semantica di colonna.
HEALTH_FIELDS = (
    # (colonna del database, campo del payload, controllo di plausibilità)
    ("resting_hr_bpm", "restingHeartRate", "resting_hr_bpm"),
    ("min_hr_bpm", "minHeartRate", "avg_hr_bpm"),
    ("max_hr_bpm", "maxHeartRate", "avg_hr_bpm"),
    ("steps", "totalSteps", None),
    ("distance_m", "totalDistanceMeters", None),
    ("active_kcal", "activeKilocalories", None),
    ("total_kcal", "totalKilocalories", None),
    ("stress_avg", "averageStressLevel", None),
    ("stress_max", "maxStressLevel", None),
    ("active_s", "activeSeconds", None),
    ("highly_active_s", "highlyActiveSeconds", None),
    ("moderate_minutes", "moderateIntensityMinutes", None),
    ("vigorous_minutes", "vigorousIntensityMinutes", None),
    ("stress_rest_s", "restStressDuration", None),
    ("body_battery_min", "bodyBatteryLowestValue", None),
    ("body_battery_max", "bodyBatteryHighestValue", None),
    ("respiration_avg", "avgWakingRespirationValue", None),
    ("spo2_avg", "averageSpo2", None),
    ("spo2_lowest", "lowestSpo2", None),
)


def _health_row(summary: dict, day: date, imported_at: datetime,
                detected: dict | None = None) -> list:
    """Un giorno di salute nella forma della tabella, campo per campo."""
    valori = []
    for _colonna, campo, controllo in HEALTH_FIELDS:
        grezzo = summary.get(campo)
        valori.append(_checked(controllo, grezzo, detected) if controllo
                      else grezzo)
    return [day, *valori, f"{SOURCE_PREFIX}user_summary/{day.isoformat()}",
            imported_at]


@contextmanager
def _one_day_or_none(connection: duckdb.DuckDBPyConnection):
    """Le tre scritture di un giorno valgono come una sola.

    Erano tre ``execute`` separati, e DuckDB conferma ognuno per conto suo: se
    l'endpoint del sonno falliva, il giorno restava con la salute scritta e il
    sonno mancante. Alla successiva esecuzione quel giorno risultava già fatto,
    perché il cursore lo aveva superato — e il buco diventava permanente.
    """
    connection.execute("BEGIN TRANSACTION")
    try:
        yield
    except BaseException:
        connection.execute("ROLLBACK")
        raise
    connection.execute("COMMIT")


def _pull_health(connection: duckdb.DuckDBPyConnection, client, start: date,
                 until: date, imported_at: datetime, report: SyncReport) -> int:
    """Salute, sonno e HRV giorno per giorno.

    Un giorno che fallisce non ferma gli altri: viene annotato, non scritto a
    metà, e il sync lo dichiara nel proprio esito invece di tacerlo.
    """
    written = 0
    day = start
    while day <= until:
        report.health_days_requested += 1
        iso = day.isoformat()
        try:
            summary = client.get_user_summary(iso)
            if not summary:
                # Nessuna risposta per quel giorno. Scrivere comunque la riga
                # produrrebbe un giorno fatto di NULL che dichiara una
                # copertura che non c'è — e sposterebbe il cursore oltre un
                # buco vero (Regola Aurea n.5).
                report.empty_days.append(iso)
                day += timedelta(days=1)
                continue

            with _one_day_or_none(connection):
                colonne = ["health_date",
                           *(c for c, _f, _v in HEALTH_FIELDS),
                           "source_object_id", "imported_at"]
                connection.execute(
                    f"INSERT OR REPLACE INTO daily_health ({', '.join(colonne)}) "
                    f"VALUES ({', '.join('?' * len(colonne))})",
                    _health_row(summary, day, imported_at, report.units_detected))

                sleep = (client.get_sleep_data(iso) or {}).get("dailySleepDTO") or {}
                total = _checked("total_sleep_s", sleep.get("sleepTimeSeconds"),
                                 report.units_detected)
                if total:
                    connection.execute(
                        "INSERT OR REPLACE INTO sleep "
                        "(sleep_date, total_sleep_s, deep_s, light_s, rem_s, awake_s, "
                        " sleep_score, source_object_id, imported_at) "
                        "VALUES (?,?,?,?,?,?,?,?,?)",
                        [day, total, sleep.get("deepSleepSeconds"),
                         sleep.get("lightSleepSeconds"), sleep.get("remSleepSeconds"),
                         sleep.get("awakeSleepSeconds"),
                         ((sleep.get("sleepScores") or {}).get("overallScore")
                          if (sleep.get("sleepScores") or {}).get("overallScore") is not None
                          else ((sleep.get("sleepScores") or {}).get("overall") or {}).get("value")),
                         f"{SOURCE_PREFIX}sleep/{iso}", imported_at])

                hrv = (client.get_hrv_data(iso) or {}).get("hrvSummary") or {}
                value = _checked("hrv_ms", hrv.get("lastNightAvg"),
                                 report.units_detected)
                if value:
                    connection.execute(
                        "INSERT OR REPLACE INTO health_status "
                        "(status_date, hrv_ms, hrv_baseline_low, hrv_baseline_high, "
                        " hrv_status, source_object_id, imported_at) "
                        "VALUES (?,?,?,?,?,?,?)",
                        [day, value,
                         (hrv.get("baseline") or {}).get("lowUpper"),
                         (hrv.get("baseline") or {}).get("upperBound"),
                         hrv.get("status"),
                         f"{SOURCE_PREFIX}hrv/{iso}", imported_at])
            written += 1
        except ImplausibleValue as error:
            report.errors.append(str(error))
            return written
        except Exception as error:  # noqa: BLE001
            report.skipped.append(f"{iso}: {type(error).__name__}")
            if getattr(error, "stop_sync", False):
                report.errors.append(str(error))
                return written
        day += timedelta(days=1)
    return written
