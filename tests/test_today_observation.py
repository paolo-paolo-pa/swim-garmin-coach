"""L'osservazione del giorno, su dati costruiti a mano.

Il valore di questa pagina non è che produca una frase: è che produca **la frase
giusta e nessun'altra**. I test qui sotto sono quindi soprattutto negativi —
cosa il coach non deve dire — perché è lì che una pagina del genere fa danno.

Le righe si scrivono nelle tabelle sorgente e ``daily_status`` viene ricostruita
dalla stessa funzione che gira in produzione: inserirla a mano collauderebbe una
tabella che nessuno produce così.
"""

from datetime import date, datetime, timedelta

import duckdb
import pytest

from garmin_coach.analysis import today
from garmin_coach.analysis.insight import Status
from garmin_coach.database import SCHEMA
from garmin_coach.metrics import daily_status
from garmin_coach.metrics.evidence import Availability

REFERENCE = date(2026, 8, 21)

# Un giorno tranquillo, ripetuto, che diventa la normalità personale.
CALM = {"hrv_ms": 40, "resting_hr_bpm": 55, "sleep_total_s": 28800,
        "body_battery_max": 90, "stress_avg": 25}


@pytest.fixture
def connection():
    con = duckdb.connect(":memory:")
    con.execute(SCHEMA)
    yield con
    con.close()


def add_day(con, day: date, hrv_ms=None, resting_hr_bpm=None,
            sleep_total_s=None, body_battery_max=None, stress_avg=None):
    """Un giorno nelle tabelle in cui i dati arrivano davvero."""
    if any(v is not None for v in (resting_hr_bpm, body_battery_max, stress_avg)):
        con.execute(
            "INSERT INTO daily_health (health_date, resting_hr_bpm, body_battery_max, "
            "stress_avg, source_object_id, imported_at) VALUES (?, ?, ?, ?, 'sha', ?)",
            [day, resting_hr_bpm, body_battery_max, stress_avg, datetime(2026, 1, 1)])
    if sleep_total_s is not None:
        con.execute(
            "INSERT INTO sleep (sleep_date, total_sleep_s, source_object_id, imported_at) "
            "VALUES (?, ?, 'sha', ?)", [day, sleep_total_s, datetime(2026, 1, 1)])
    if hrv_ms is not None:
        con.execute(
            "INSERT INTO health_status (status_date, hrv_ms, source_object_id, imported_at) "
            "VALUES (?, ?, 'sha', ?)", [day, hrv_ms, datetime(2026, 1, 1)])


def steady_history(con, until: date, days: int = 60, **values):
    """Uno storico regolare, per dare a ogni segnale la sua fascia personale."""
    for offset in range(days, 0, -1):
        add_day(con, until - timedelta(days=offset), **values)


def add_swim(con, day: date, hour: int = 20, distance_m: float = 3000):
    con.execute(
        "INSERT INTO activities (activity_id, start_time_utc, start_time_local, "
        "activity_date, sport, is_swim, environment, distance_m, duration_s, "
        "source_object_id, imported_at) VALUES (?, ?, ?, ?, 'lap_swimming', TRUE, "
        "'pool', ?, 3600, 'sha', ?)",
        [abs(hash((day, hour, distance_m))) % 10**9,
         datetime.combine(day, datetime.min.time()).replace(hour=hour),
         datetime.combine(day, datetime.min.time()).replace(hour=hour),
         day, distance_m, datetime(2026, 1, 1)])


def steady_swimming(con, until: date, days: int = 28, hour: int = 15):
    """Un volume regolare di sfondo.

    Serve a isolare il ramo dei segnali di recupero: senza, una sola nuotata
    negli ultimi sette giorni fa scattare il salto di volume, che ha priorita
    piu alta, e il test collauderebbe un ramo diverso da quello che dichiara.
    """
    for offset in range(1, days + 1):
        add_swim(con, until - timedelta(days=offset), hour=hour, distance_m=3000)


def observe(con, day=None, reference=REFERENCE):
    """Ricostruisce lo stato giornaliero e chiede l'osservazione."""
    daily_status.build(con)
    return today.observation(con, day=day, today=reference)


class TestWhenThereIsNothingToSay:
    def test_a_normal_day_says_normal_instead_of_inventing_a_warning(self, connection):
        steady_history(connection, REFERENCE, **CALM)
        add_day(connection, REFERENCE, **CALM)

        packet = observe(connection, REFERENCE)

        assert packet.status == Status.INFORMATIVE
        assert "normale" in packet.observation.lower()

    def test_one_signal_alone_is_noise_and_does_not_become_a_warning(self, connection):
        """HRV e sonno oscillano da soli. Un segnale solo non è un'osservazione."""
        steady_history(connection, REFERENCE, **CALM)
        add_day(connection, REFERENCE, **{**CALM, "hrv_ms": 5})

        packet = observe(connection, REFERENCE)

        assert packet.status == Status.INFORMATIVE


class TestWhenSignalsAgree:
    def test_two_concordant_signals_become_an_observation(self, connection):
        steady_history(connection, REFERENCE, **CALM)
        add_day(connection, REFERENCE, **{**CALM, "hrv_ms": 5, "resting_hr_bpm": 99})

        packet = observe(connection, REFERENCE)

        assert packet.status == Status.WATCH
        assert "2 segnali" in packet.observation

    def test_a_signal_outside_the_band_on_the_good_side_never_counts(self, connection):
        """Un HRV alto e uno basso sono entrambi fuori fascia e non vogliono
        dire la stessa cosa. Sommarli produrrebbe allarmi su giornate buone."""
        steady_history(connection, REFERENCE, **CALM)
        add_day(connection, REFERENCE, hrv_ms=200, resting_hr_bpm=20,
                sleep_total_s=50000, body_battery_max=100, stress_avg=1)

        packet = observe(connection, REFERENCE)

        assert packet.status == Status.INFORMATIVE

    def test_what_reassures_is_shown_next_to_what_worries(self, connection):
        steady_history(connection, REFERENCE, **CALM)
        add_day(connection, REFERENCE, **{**CALM, "hrv_ms": 5, "resting_hr_bpm": 99})

        packet = observe(connection, REFERENCE)

        assert packet.counter_evidence, (
            "una pagina che mostra solo ciò che conferma la propria conclusione "
            "convince invece di informare")

    def test_an_evening_session_is_declared_as_a_counter_fact(self, connection):
        """Il profilo dice che le sedute sono alle [orario]: il sonno della notte
        seguente non è un segnale indipendente di recupero."""
        steady_history(connection, REFERENCE, **CALM)
        add_day(connection, REFERENCE, **{**CALM, "hrv_ms": 5, "resting_hr_bpm": 99})
        steady_swimming(connection, REFERENCE)
        add_swim(connection, REFERENCE - timedelta(days=1), hour=20, distance_m=1)

        packet = observe(connection, REFERENCE)

        assert packet.status == Status.WATCH
        assert "evening_session" in [e.get("field") for e in packet.counter_evidence]

    def test_an_afternoon_session_is_not_used_as_an_excuse(self, connection):
        """Il sabato alle 15 non influenza il sonno della notte seguente: se il
        coach lo citasse comunque, starebbe scusando ogni segnale con qualcosa."""
        steady_history(connection, REFERENCE, **CALM)
        add_day(connection, REFERENCE, **{**CALM, "hrv_ms": 5, "resting_hr_bpm": 99})
        steady_swimming(connection, REFERENCE, hour=15)

        packet = observe(connection, REFERENCE)

        assert packet.status == Status.WATCH
        assert "evening_session" not in [e.get("field") for e in packet.counter_evidence]


class TestTheVolumeJumpTheAthleteAskedFor:
    @staticmethod
    def _ramp(con, until: date):
        """20 km negli ultimi 7 giorni, 20 km nei 21 precedenti.

        La media delle quattro settimane è 10 km: il doppio, cioè oltre soglia.
        """
        for offset in range(1, 8):
            add_swim(con, until - timedelta(days=offset), distance_m=20000 / 7)
        for offset in range(8, 29):
            add_swim(con, until - timedelta(days=offset), distance_m=20000 / 21)

    def test_a_volume_jump_comes_before_the_recovery_signals(self, connection):
        """L'atleta ha dichiarato lui l'innesco: volume che sale sproporzionato."""
        steady_history(connection, REFERENCE, **CALM)
        add_day(connection, REFERENCE, **CALM)
        self._ramp(connection, REFERENCE)

        packet = observe(connection, REFERENCE)

        assert packet.status == Status.WATCH
        assert "volume" in packet.observation.lower()

    def test_it_never_becomes_a_diagnosis_or_an_injury_forecast(self, connection):
        steady_history(connection, REFERENCE, **CALM)
        add_day(connection, REFERENCE, **CALM)
        self._ramp(connection, REFERENCE)

        packet = observe(connection, REFERENCE)
        whole = " ".join([packet.observation] + packet.limitations).lower()

        # La parola «diagnosi» compare, ed e giusto: compare nella frase che la
        # nega. Quello che non deve comparire e l'affermazione.
        for forbidden in ("sei in sovrallenamento", "rischi un infortunio",
                          "ti farai male", "devi fermarti", "riposo obbligato",
                          "e una diagnosi", "prevedo"):
            assert forbidden not in whole, f"linguaggio vietato: {forbidden}"
        assert "non una previsione di infortunio" in whole

    def test_a_steady_volume_is_not_announced(self, connection):
        steady_history(connection, REFERENCE, **CALM)
        add_day(connection, REFERENCE, **CALM)
        for offset in range(1, 29):
            add_swim(connection, REFERENCE - timedelta(days=offset), distance_m=3000)

        packet = observe(connection, REFERENCE)

        assert packet.status == Status.INFORMATIVE


class TestWhenTheDataDoesNotReach:
    def test_before_the_sensors_existed_the_answer_is_i_do_not_know_yet(self, connection):
        """FC a riposo, stress e Body Battery non esistono prima del 2021, e
        l'HRV prima del settembre 2025. Non è un difetto da riempire."""
        old = date(2018, 3, 15)
        steady_history(connection, old, sleep_total_s=28800)
        add_day(connection, old, sleep_total_s=28800)

        packet = observe(connection, old)

        assert packet.status == Status.INSUFFICIENT_DATA
        assert "settembre 2025" in " ".join(packet.limitations)

    def test_not_measured_and_no_history_are_two_different_absences(self, connection):
        """Regola Aurea n.5: `missing` e `insufficient_data` non sono sinonimi."""
        day = date(2026, 3, 1)
        add_day(connection, day, hrv_ms=40, resting_hr_bpm=55)   # nessuno storico

        packet = observe(connection, day)

        states = {entry["field"]: entry["availability"] for entry in packet.evidence}
        assert states["hrv_ms"] == Availability.INSUFFICIENT_DATA, "valore c'è, fascia no"
        assert states["sleep_total_s"] == Availability.MISSING, "valore non misurato"
        assert "non sono stati misurati" in packet.observation
        assert "abbastanza storia" in packet.observation

    def test_an_empty_database_says_so_instead_of_crashing(self, connection):
        packet = today.observation(connection, today=REFERENCE)

        assert packet.status == Status.INSUFFICIENT_DATA
        assert packet.freshness.data_through is None


class TestTheAnswerAlwaysCarriesItsOwnDate:
    def test_stale_data_is_declared_instead_of_being_called_today(self, connection):
        stopped = date(2026, 8, 10)
        steady_history(connection, stopped, **CALM)
        add_day(connection, stopped, **CALM)

        packet = observe(connection)      # nessun giorno chiesto: l'ultimo che c'è

        assert packet.freshness.days_behind == 11
        assert packet.freshness.is_stale
        assert "10/08/2026" in packet.freshness.as_dict()["display"]

    def test_every_number_shown_carries_its_evidence(self, connection):
        steady_history(connection, REFERENCE, **CALM)
        add_day(connection, REFERENCE, **CALM)

        packet = observe(connection, REFERENCE)

        for entry in packet.evidence:
            assert "availability" in entry, f"{entry['field']} senza disponibilità"
            assert "display" in entry, f"{entry['field']} senza testo da mostrare"
            assert "method_version" in entry, f"{entry['field']} senza versione"

    def test_the_links_reach_real_sessions(self, connection):
        steady_history(connection, REFERENCE, **CALM)
        add_day(connection, REFERENCE, **CALM)
        add_swim(connection, REFERENCE - timedelta(days=1))

        packet = observe(connection, REFERENCE)

        assert packet.links, "l'osservazione deve poter essere aperta fino alla seduta"
        assert all("activity_id" in link for link in packet.links)
