"""L'analisi di una seduta: dove il coach conosce il nuoto e Garmin no.

I test negativi contano più di quelli positivi. Un lap chiamato «serie», un
confronto fra vasche diverse o un'anomalia dichiarata su tre casi sono errori
che non si vedono guardando la pagina: sembrano tutti risposte sensate.
"""

from datetime import date, datetime, timedelta

import duckdb
import pytest

from garmin_coach.analysis import sessions
from garmin_coach.analysis.insight import Status
from garmin_coach.database import SCHEMA
from garmin_coach.metrics.evidence import Availability

GIORNO = date(2026, 8, 20)


@pytest.fixture
def connection():
    con = duckdb.connect(":memory:")
    con.execute(SCHEMA)
    yield con
    con.close()


def add_session(con, activity_id: int, day: date = GIORNO, *,
                environment: str = "pool", pool_length_m: float | None = 25.0,
                distance_m: float = 3000, duration_s: float = 3600,
                device_id: int = 1, avg_hr_bpm=None, rpe=None, name=None):
    con.execute(
        "INSERT INTO activities (activity_id, start_time_utc, start_time_local, "
        "activity_date, sport, is_swim, environment, name, distance_m, duration_s, "
        "pool_length_m, avg_hr_bpm, rpe, device_id, source_object_id, imported_at) "
        "VALUES (?, ?, ?, ?, ?, TRUE, ?, ?, ?, ?, ?, ?, ?, ?, 'sha', ?)",
        [activity_id, datetime.combine(day, datetime.min.time()).replace(hour=20),
         datetime.combine(day, datetime.min.time()).replace(hour=20), day,
         "open_water_swimming" if environment == "open_water" else "lap_swimming",
         environment, name, distance_m, duration_s, pool_length_m, avg_hr_bpm,
         rpe, device_id, datetime(2026, 1, 1)])


def add_laps(con, activity_id: int, paces, *, distance_m: float = 100,
             stroke: str = "freestyle", is_rest: bool = False, start_index: int = 0):
    """Una fila di lap con i passi indicati, in secondi per 100 m."""
    for offset, pace in enumerate(paces):
        con.execute(
            "INSERT INTO activity_laps (activity_id, lap_index, distance_m, "
            "duration_s, stroke, pace_per_100m_s, is_rest, source_object_id, "
            "imported_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'oggetto', ?)",
            [activity_id, start_index + offset, distance_m,
             pace * distance_m / 100, stroke, pace, is_rest, datetime(2026, 1, 1)])


def add_match(con, activity_id: int, verdict: str, reason: str = ""):
    con.execute(
        "INSERT INTO activity_source_matches (activity_id, source_object_id, "
        "verdict, method, reason, decided_at) VALUES (?, 'oggetto', ?, 'tempo', ?, ?)",
        [activity_id, verdict, reason, datetime(2026, 1, 1)])


class TestALapIsNeverASeries:
    def test_the_word_series_is_not_used_for_a_group_of_laps(self, connection):
        add_session(connection, 1)
        add_laps(connection, 1, [90, 91, 92, 93])

        packet = sessions.detail(connection, 1)
        testo = (packet.observation + " "
                 + " ".join(str(c) for c in packet.comparisons)).lower()

        assert "serie" not in testo.replace("una serie dichiarata", ""), (
            "«8×100» è un'interpretazione dell'allenatore, un lap è un fatto")
        assert "ripetute" in testo or "gruppo" in testo

    def test_every_group_declares_how_much_the_grouping_can_be_trusted(self, connection):
        add_session(connection, 1)
        add_laps(connection, 1, [90, 91, 92, 93])

        packet = sessions.detail(connection, 1)

        for gruppo in packet.comparisons:
            if "repeats" in gruppo:
                assert gruppo["recognition"] in ("riconosciuta", "incerta",
                                                 "non riconosciuta")

    def test_laps_that_vary_wildly_are_not_declared_a_recognised_group(self, connection):
        add_session(connection, 1)
        add_laps(connection, 1, [70, 95, 130, 82])   # nessun disegno riconoscibile

        packet = sessions.detail(connection, 1)
        gruppo = packet.comparisons[0]

        assert gruppo["recognition"] == "incerta"
        assert any("incerta" in limite for limite in packet.limitations)

    def test_fewer_than_three_repeats_is_not_a_trend(self, connection):
        add_session(connection, 1)
        add_laps(connection, 1, [90, 95])

        packet = sessions.detail(connection, 1)

        assert packet.status == Status.INSUFFICIENT_DATA
        assert "almeno tre" in packet.observation

    def test_rests_are_not_counted_as_repeats_gone_wrong(self, connection):
        """Una riga con `is_rest` serve a ricostruire i tempi di partenza."""
        add_session(connection, 1)
        add_laps(connection, 1, [90, 91, 92])
        add_laps(connection, 1, [600, 600, 600], is_rest=True, start_index=50)

        packet = sessions.detail(connection, 1)

        assert packet.comparisons[0]["repeats"] == 3
        assert packet.comparisons[0]["median_pace_s"] < 100


class TestOnlyHomogeneousThingsGetCompared:
    def test_different_strokes_are_never_put_in_the_same_group(self, connection):
        add_session(connection, 1)
        add_laps(connection, 1, [90, 91, 92], stroke="freestyle")
        add_laps(connection, 1, [130, 131, 132], stroke="butterfly", start_index=10)

        packet = sessions.detail(connection, 1)
        gruppi = [c for c in packet.comparisons if "repeats" in c]

        assert len(gruppi) == 2
        assert {g["stroke"] for g in gruppi} == {"freestyle", "butterfly"}

    def test_different_distances_are_never_put_in_the_same_group(self, connection):
        add_session(connection, 1)
        add_laps(connection, 1, [90, 91, 92], distance_m=100)
        add_laps(connection, 1, [95, 96, 97], distance_m=200, start_index=10)

        packet = sessions.detail(connection, 1)
        gruppi = [c for c in packet.comparisons if "repeats" in c]

        assert {g["distance_m"] for g in gruppi} == {100, 200}

    def test_history_is_not_compared_across_pool_lengths(self, connection):
        """In vasca da 50 il peso della virata è dimezzato."""
        add_session(connection, 1, pool_length_m=25)
        add_laps(connection, 1, [90, 91, 92])
        for numero in range(2, 20):        # tante sedute, ma in vasca da 50
            add_session(connection, numero, day=GIORNO - timedelta(days=numero),
                        pool_length_m=50)
            add_laps(connection, numero, [80, 80, 80])

        packet = sessions.detail(connection, 1)
        confronti_storici = [c for c in packet.comparisons if "sessions" in c]

        assert not confronti_storici, "vasche diverse non si confrontano"

    def test_history_is_not_compared_across_devices(self, connection):
        """Fino a quattro dispositivi nello stesso anno (R2)."""
        add_session(connection, 1, device_id=1)
        add_laps(connection, 1, [90, 91, 92])
        for numero in range(2, 20):
            add_session(connection, numero, day=GIORNO - timedelta(days=numero),
                        device_id=999)
            add_laps(connection, numero, [80, 80, 80])

        packet = sessions.detail(connection, 1)

        assert not [c for c in packet.comparisons if "sessions" in c]

    def test_an_anomaly_needs_enough_comparable_cases_to_mean_anything(self, connection):
        add_session(connection, 1)
        add_laps(connection, 1, [90, 91, 92])
        for numero in range(2, 5):         # solo tre sedute omogenee
            add_session(connection, numero, day=GIORNO - timedelta(days=numero))
            add_laps(connection, numero, [80, 80, 80])

        packet = sessions.detail(connection, 1)

        assert not [c for c in packet.comparisons if "sessions" in c]
        assert any("omogenee" in limite for limite in packet.limitations)

    def test_with_enough_homogeneous_sessions_the_comparison_appears(self, connection):
        add_session(connection, 1)
        add_laps(connection, 1, [90, 91, 92])
        for numero in range(2, 15):
            add_session(connection, numero, day=GIORNO - timedelta(days=numero))
            add_laps(connection, numero, [80, 80, 80])

        packet = sessions.detail(connection, 1)
        storici = [c for c in packet.comparisons if "sessions" in c]

        assert storici, "con tredici sedute omogenee il confronto è lecito"
        assert storici[0]["sessions"] >= sessions.MIN_COMPARABLE_SESSIONS


class TestOpenWater:
    def test_the_sea_has_no_lengths_and_that_is_not_a_missing_value(self, connection):
        add_session(connection, 1, environment="open_water", pool_length_m=None)
        add_laps(connection, 1, [95, 96, 97], distance_m=500)

        packet = sessions.detail(connection, 1)
        vasche = [e for e in packet.evidence if e["field"] == "pool_lengths_count"]

        assert vasche, "l'assenza di vasche va dichiarata, non taciuta"
        assert vasche[0]["availability"] == Availability.NOT_APPLICABLE

    def test_the_variable_length_of_sea_laps_is_declared(self, connection):
        add_session(connection, 1, environment="open_water", pool_length_m=None)
        add_laps(connection, 1, [95, 96, 97], distance_m=500)

        packet = sessions.detail(connection, 1)

        assert any("premuti tu a mano" in limite for limite in packet.limitations)


class TestWhatTheCoachRefusesToSay:
    def test_a_slowdown_is_observed_and_never_called_a_collapse(self, connection):
        add_session(connection, 1)
        add_laps(connection, 1, [85, 90, 95, 100, 105])

        packet = sessions.detail(connection, 1)
        whole = " ".join([packet.observation] + packet.limitations).lower()

        for vietato in ("cedimento", "sei crollato", "hai mollato", "cali di forma"):
            assert vietato not in whole, f"linguaggio vietato: {vietato}"
        assert "rallentato" in whole
        assert "la finalità la sai tu e l'allenatore" in whole

    def test_the_equipment_is_always_offered_as_an_alternative_explanation(self, connection):
        """L'orologio non registra palette e pinne: è la prima cosa da escludere
        prima di parlare di forma."""
        add_session(connection, 1)
        add_laps(connection, 1, [90, 91, 92])

        packet = sessions.detail(connection, 1)

        assert any("palette" in limite for limite in packet.limitations)

    def test_missing_heart_rate_before_2021_is_explained_not_hidden(self, connection):
        add_session(connection, 1, day=date(2018, 3, 15), avg_hr_bpm=None)
        add_laps(connection, 1, [90, 91, 92])

        packet = sessions.detail(connection, 1)
        fc = [e for e in packet.evidence if e["field"] == "avg_hr_bpm"]

        assert fc[0]["availability"] == Availability.MISSING
        assert "prima del 2021" in " ".join(fc[0]["notes"])


class TestWhenTheDetailIsNotThere:
    @pytest.mark.parametrize("verdict,atteso", [
        ("unmatched", "arrivate dal sync"),
        ("ambiguous", "distinguibile"),
    ])
    def test_the_reason_is_specific_not_generic(self, connection, verdict, atteso):
        add_session(connection, 1)
        add_match(connection, 1, verdict)

        packet = sessions.detail(connection, 1)

        assert packet.status == Status.INSUFFICIENT_DATA
        assert atteso in " ".join(packet.limitations)

    def test_a_session_that_does_not_exist_says_so(self, connection):
        packet = sessions.detail(connection, 12345)

        assert packet.status == Status.INSUFFICIENT_DATA
        assert not packet.links, (
            "l'assenza di collegamenti è l'invariante su cui l'app distingue "
            "«non trovata» da «trovata e senza dettaglio»")


class TestTheListing:
    def test_it_shows_how_deep_one_can_look_before_opening(self, connection):
        add_session(connection, 1)
        add_laps(connection, 1, [90, 91, 92])
        add_session(connection, 2, day=GIORNO - timedelta(days=1))

        elenco = {voce["activity_id"]: voce for voce in sessions.listing(connection)}

        assert elenco[1]["detail_level"] == "laps"
        assert elenco[2]["detail_level"] == "summary"
        assert elenco[2]["detail_display"] == "solo totali"

    def test_it_can_be_narrowed_to_the_sea(self, connection):
        add_session(connection, 1, environment="pool")
        add_session(connection, 2, environment="open_water", pool_length_m=None)

        elenco = sessions.listing(connection, environment="open_water")

        assert [voce["activity_id"] for voce in elenco] == [2]
