"""Il sync scrive meno di quello che Garmin gli manda.

**Il difetto.** ``daily_health`` ha le colonne per Body Battery, respirazione,
SpO2 e secondi di attività; ``activities`` ha calorie, zone cardiache, numero di
lap e vasche attive, temperatura, fuso. Il payload di Garmin li contiene. Il
parser del sync non li mappa, e nella pagina Oggi la Body Battery risulta
assente: non perché la fonte non ce l'abbia, ma perché nessuno l'ha letta.

**Il difetto che invece non c'è, e la prova che lo dice.** Sembrava che
``INSERT OR REPLACE`` con un elenco parziale di colonne sostituisse la riga
intera, svuotando ogni tre ore le colonne dell'export sulle attività dentro la
finestra di sovrapposizione. Misurato: DuckDB aggiorna **solo** le colonne
nominate e lascia stare le altre. I test della prima classe restano perché ora
quel comportamento è una dipendenza dichiarata: se qualcuno passasse a un
``INSERT OR REPLACE`` che nomina tutte le colonne, o a un ``DELETE`` seguito da
``INSERT``, la cancellazione silenziosa diventerebbe vera e questi test la
fermerebbero.
"""

from datetime import date, datetime

import duckdb
import pytest

from garmin_coach.database import SCHEMA
from garmin_coach.ingest import sync

GIORNO = date(2026, 8, 18)


class ClientFinto:
    """Restituisce payload nella forma dell'API web, senza toccare la rete."""

    def __init__(self, activities=None, summary=None):
        self._activities = activities or []
        self._summary = summary or {}

    def get_activities_by_date(self, start, end):
        return self._activities

    def get_user_summary(self, day):
        return self._summary

    def get_sleep_data(self, day):
        return {}

    def get_hrv_data(self, day):
        return {}


@pytest.fixture
def connection():
    con = duckdb.connect(":memory:")
    con.execute(SCHEMA)
    yield con
    con.close()


# ── Quello che il sync cancella senza dirlo ──────────────────────────────

@pytest.fixture
def attivita_completa(connection):
    """Un'attività come l'ha importata l'export: tutte le colonne piene."""
    connection.execute(
        "INSERT INTO activities (activity_id, start_time_utc, start_time_local, "
        " activity_date, timezone_id, sport, is_swim, environment, name, "
        " distance_m, duration_s, calories_kcal, hr_zone_2_s, hr_zone_3_s, "
        " lap_count, active_lengths, avg_swim_cadence_spm, total_strokes, "
        " max_temperature_c, rpe, pool_length_m, device_id, source_object_id, "
        " imported_at) "
        "VALUES (7001, ?, ?, ?, 'Europe/Rome', 'lap_swimming', TRUE, 'pool', "
        " 'Piscina', 3000, 3600, 500, 900, 400, 24, 120, 32, 1450, 27.5, 6, "
        " 25, 3112233445, 'abc', ?)",
        [datetime(2026, 8, 18, 8), datetime(2026, 8, 18, 8), GIORNO,
         datetime(2026, 8, 18, 9)])
    # Il sync riparte dall'ultimo giorno noto: questa riga è anche il cursore.
    return 7001


def _payload_attivita(activity_id: int = 7001) -> dict:
    """La stessa attività come la restituisce l'API web: unità SI."""
    return {
        "activityId": activity_id,
        "startTimeGMT": "2026-08-18T08:00:00.0",
        "startTimeLocal": "2026-08-18T10:00:00.0",
        "activityType": {"typeKey": "lap_swimming"},
        "activityName": "Piscina",
        "distance": 3000.0,
        "duration": 3600.0,
        "poolLength": 2500.0,
        "calories": 500.0,
        "lapCount": 24,
        "activeLengths": 120,
        "maxTemperature": 27.5,
        "timeZoneId": "Europe/Rome",
        "deviceId": 3112233445,
    }


COLONNE_CHE_IL_SYNC_NON_NOMINA = [
    "calories_kcal", "hr_zone_2_s", "hr_zone_3_s", "lap_count",
    "active_lengths", "max_temperature_c", "rpe", "timezone_id",
]


class TestQuelloCheIlSyncNonDeveCancellare:
    @pytest.mark.parametrize("colonna", COLONNE_CHE_IL_SYNC_NON_NOMINA)
    def test_a_column_the_sync_ignores_is_not_emptied_by_it(
            self, connection, attivita_completa, colonna):
        """Ignorare un campo è accettabile. Cancellarlo non lo è.

        L'attività è la stessa — stesso ``activity_id`` — e cade dentro la
        finestra di sovrapposizione. Dopo il sync deve avere almeno quello che
        aveva prima. **Oggi passa**: è un presidio, non una riparazione.
        """
        prima = connection.execute(
            f"SELECT {colonna} FROM activities WHERE activity_id = 7001"
        ).fetchone()[0]
        assert prima is not None, "la riga di partenza deve avere il valore"

        report = sync.pull(connection, until=GIORNO,
                           client=ClientFinto(activities=[_payload_attivita()]))
        assert report.succeeded, report.errors

        dopo = connection.execute(
            f"SELECT {colonna} FROM activities WHERE activity_id = 7001"
        ).fetchone()[0]
        assert dopo is not None, (
            f"il sync ha svuotato «{colonna}»: la colonna non è nel suo elenco "
            "e INSERT OR REPLACE sostituisce la riga intera")


# ── Quello che il sync non legge ─────────────────────────────────────────

SUMMARY_COMPLETO = {
    "restingHeartRate": 52,
    "minHeartRate": 44,
    "maxHeartRate": 148,
    "totalSteps": 8421,
    "totalDistanceMeters": 6100,
    "activeKilocalories": 780,
    "totalKilocalories": 2450,
    "averageStressLevel": 31,
    "maxStressLevel": 88,
    # Da qui in giù: presenti nel payload, assenti dal database.
    "bodyBatteryMostRecentValue": 61,
    "bodyBatteryHighestValue": 92,
    "bodyBatteryLowestValue": 28,
    "avgWakingRespirationValue": 14.2,
    "averageSpo2": 96.0,
    "lowestSpo2": 91.0,
    "activeSeconds": 4820,
    "highlyActiveSeconds": 1260,
    "moderateIntensityMinutes": 41,
    "vigorousIntensityMinutes": 18,
    "restStressDuration": 15600,
}

CAMPI_SALUTE_ATTESI = [
    ("body_battery_max", 92.0),
    ("body_battery_min", 28.0),
    ("respiration_avg", 14.2),
    ("spo2_avg", 96.0),
    ("spo2_lowest", 91.0),
    ("active_s", 4820.0),
    ("highly_active_s", 1260.0),
    ("moderate_minutes", 41.0),
    ("vigorous_minutes", 18.0),
]


class TestQuelloCheIlSyncNonLegge:
    @pytest.fixture
    def cursore(self, connection):
        connection.execute(
            "INSERT INTO daily_health (health_date, resting_hr_bpm, "
            " source_object_id, imported_at) VALUES (?, 52, 'abc', ?)",
            [GIORNO, datetime(2026, 8, 18, 9)])

    @pytest.mark.parametrize("colonna,atteso", CAMPI_SALUTE_ATTESI)
    def test_a_field_present_in_the_payload_reaches_the_database(
            self, connection, cursore, colonna, atteso):
        """«La Body Battery non c'è» deve voler dire che Garmin non la manda.

        Qui la manda. Se la colonna resta vuota, la pagina Oggi sta dichiarando
        assente un dato che è arrivato e nessuno ha letto — che è la forma di
        disonestà del dato più difficile da vedere, perché somiglia a un limite
        della fonte.
        """
        report = sync.pull(connection, until=GIORNO,
                           client=ClientFinto(summary=SUMMARY_COMPLETO))
        assert report.succeeded, report.errors

        valore = connection.execute(
            f"SELECT {colonna} FROM daily_health WHERE health_date = ?",
            [GIORNO]).fetchone()[0]
        assert valore == pytest.approx(atteso), (
            f"«{colonna}» è nel payload ma non arriva nel database")


# ── Il controllo che non usa dati inventati ──────────────────────────────

class TestControlloSulleCatturaVere:
    """Il giro raw → DB sulle risposte davvero ricevute da Garmin.

    I test qui sopra usano un payload scritto a mano: provano la mappatura, non
    che i nomi dei campi siano quelli veri. Questo la prova sulle catture in
    ``data/raw/garmin-connect/``, che sono le risposte esatte dell'API.

    Si salta quando le catture non ci sono — su un altro computer, o prima del
    primo sync — invece di fallire per assenza di dati personali.
    """

    @pytest.fixture
    def catture(self):
        from garmin_coach.ingest.source_catalog import RAW
        giorni = sorted(g for g in RAW.iterdir()
                        if g.is_dir() and (g / "get_user_summary.json").exists()
                        ) if RAW.exists() else []
        if not giorni:
            pytest.skip("nessuna cattura del sync su questo computer")
        return giorni

    def test_every_mapped_field_exists_in_a_real_payload(self, catture):
        """Un nome di campo sbagliato non è un errore: è un silenzio.

        Se ``bodyBatteryHighestValue`` diventasse ``bodyBatteryHighest``, il
        codice continuerebbe a girare scrivendo NULL, e la pagina Oggi direbbe
        «non disponibile» per sempre. Questo test lo trasforma in un guasto.
        """
        import json

        from garmin_coach.ingest.sync import HEALTH_FIELDS

        visti = set()
        for giorno in catture:
            visti |= set(json.loads(
                (giorno / "get_user_summary.json").read_text(encoding="utf-8")))

        mancanti = [campo for _c, campo, _v in HEALTH_FIELDS if campo not in visti]
        assert not mancanti, (
            f"campi mappati che nessuna cattura contiene: {mancanti}. "
            "O il nome è sbagliato, o Garmin ha cambiato il payload")

    def test_a_captured_day_arrives_in_the_database_whole(self, connection,
                                                          catture):
        """Dal file JSON alla riga del database, senza perdere niente per strada."""
        import json
        from datetime import date as _date

        from garmin_coach.ingest.snapshot_replay import SnapshotClient
        from garmin_coach.ingest.sync import HEALTH_FIELDS

        giorno = catture[-1]
        quando = _date.fromisoformat(giorno.name)
        client = SnapshotClient()
        # La cattura iniziale è immutabile; una versione con hash può
        # contenere il giorno completato da una sincronizzazione successiva.
        # Il mapping va confrontato con il payload realmente rigiocato.
        payload = client.get_user_summary(quando.isoformat())

        connection.execute(
            "INSERT INTO daily_health (health_date, source_object_id, "
            " imported_at) VALUES (?, 'seme', ?)",
            [quando, datetime(2026, 1, 1)])
        sync.pull(connection, until=quando, client=client)

        riga = connection.execute(
            "SELECT " + ", ".join(c for c, _f, _v in HEALTH_FIELDS)
            + " FROM daily_health WHERE health_date = ?", [quando]).fetchone()

        for valore, (colonna, campo, _v) in zip(riga, HEALTH_FIELDS):
            atteso = payload.get(campo)
            if atteso in (None, 0):
                continue      # lo zero e l'assenza li tratta _checked, non qui
            assert valore == pytest.approx(float(atteso)), (
                f"«{colonna}» vale {valore} e nella cattura {campo} vale {atteso}")
