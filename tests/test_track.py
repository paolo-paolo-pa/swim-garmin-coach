"""La traccia al secondo, e il cancello che dice quando non regge.

## Cosa difendono

1. **Il collegamento gara ↔ nuotata arriva in archivio.** Fino al 24/08/2026
   veniva letto dal markdown, contato nel rapporto come `linked_to_garmin` e
   poi buttato, perché `races` non aveva la colonna. Il rapporto tornava lo
   stesso: è il motivo per cui serve un criterio e non un conteggio.
2. **Nessuna coordinata entra nel database.** Il divieto sulle coordinate
   precise diventa una proprietà dello schema invece di una regola da
   ricordare, e un test lo verifica sulle colonne reali.
3. **Il segmento esiste solo fra due fix consecutivi.** Dopo un buco del GPS la
   retta fra i due estremi non è il tratto nuotato, e attribuirla a un punto
   solo falserebbe l'andamento — oltre a nascondere il buco proprio al
   controllo che serve a trovarlo.
4. **Il cancello rifiuta dicendo perché.** «Di questa gara posso dirti il
   totale, non come l'hai distribuita» è una risposta; «nessun dato» no.
"""

from datetime import datetime, timedelta

import duckdb
import pytest

from garmin_coach.database import SCHEMA
from garmin_coach.ingest import track


@pytest.fixture
def connection():
    con = duckdb.connect(":memory:")
    con.execute(SCHEMA)
    yield con
    con.close()


class TestNoCoordinatesEverLandInTheDatabase:
    def test_the_track_table_has_no_position_columns(self, connection):
        colonne = {riga[0] for riga in connection.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'activity_track'").fetchall()}

        vietate = {"latitude", "longitude", "position_lat", "position_long",
                   "lat", "lon", "latitudine", "longitudine"}

        assert not (colonne & vietate), (
            "un divieto che poggia sull'assenza della colonna e' l'unico che "
            "non si puo' dimenticare di applicare")
        assert "segment_m" in colonne and "heading_deg" in colonne, (
            "quello che serve sono due differenze fra punti, non una posizione")

    def test_no_table_at_all_holds_a_coordinate(self, connection):
        colonne = [riga[0].lower() for riga in connection.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'main'").fetchall()]

        assert not [una for una in colonne
                    if "latitud" in una or "longitud" in una
                    or una in ("lat", "lon", "lng")]


class TestGeometry:
    def test_going_north_is_zero_degrees(self):
        metri, direzione = track._bearing_and_distance((45.0, 9.0), (45.001, 9.0))

        assert direzione == pytest.approx(0.0, abs=0.5)
        assert metri == pytest.approx(110.54, rel=0.01)

    def test_going_east_is_ninety_degrees(self):
        _, direzione = track._bearing_and_distance((45.0, 9.0), (45.0, 9.001))

        assert direzione == pytest.approx(90.0, abs=0.5)

    def test_the_way_back_is_the_opposite_heading(self):
        # È la proprietà su cui poggia tutta la lettura della corrente: andata e
        # ritorno sullo stesso tratto devono differire di 180 gradi, altrimenti
        # confrontarle non misura l'acqua.
        andata = track._bearing_and_distance((45.0, 9.0), (45.001, 9.001))[1]
        ritorno = track._bearing_and_distance((45.001, 9.001), (45.0, 9.0))[1]

        assert abs(andata - ritorno) == pytest.approx(180.0, abs=0.5)


def _punti(quanti, con_fix=None, passo_lat=0.0009, battito=None):
    """Punti finti in fila verso nord, un secondo l'uno.

    `con_fix` dice quali hanno una posizione: serve a simulare i buchi del GPS.
    """
    gradi = 2 ** 31 / 180
    fatti = []
    for i in range(quanti):
        punto = {
            "timestamp": datetime(2026, 6, 1, 8, 0, 0) + timedelta(seconds=i),
            "distance": i * 100.0,
            "speed": 1.4,
            "cadence": 30.0,
        }
        if con_fix is None or i in con_fix:
            punto["position_lat"] = (45.0 + i * passo_lat) * gradi
            punto["position_long"] = 9.0 * gradi
        if battito:
            punto["heart_rate"] = battito
        fatti.append(punto)
    return fatti


class TestBuildingRows:
    def test_the_first_point_has_no_segment(self):
        righe, _ = track._rows(1, _punti(5), "sha", datetime(2026, 1, 1))

        assert righe[0][5] is None and righe[0][6] is None, (
            "un segmento e' fra due punti: il primo non ne ha uno prima")
        assert righe[1][5] is not None

    def test_a_gap_in_the_gps_leaves_the_segment_missing(self):
        # Punti 0,1 con fix, 2 e 3 senza, 4 con. Il segmento del punto 4 non
        # deve esistere: la retta fra il punto 1 e il punto 4 non e' il tratto
        # che e' stato nuotato.
        righe, misure = track._rows(
            1, _punti(5, con_fix={0, 1, 4}), "sha", datetime(2026, 1, 1))

        assert righe[4][5] is None, (
            "dopo un buco la retta fra i due estremi non e' il tratto nuotato")
        assert misure["gps_points"] == 3

    def test_the_gap_shows_up_as_a_shorter_distance(self):
        completa = track._rows(1, _punti(6), "sha", datetime(2026, 1, 1))[1]
        _, misure = track._rows(
            1, _punti(6, con_fix={0, 1, 4, 5}), "sha", datetime(2026, 1, 1))

        assert misure["gps_distance_m"] < completa["gps_distance_m"], (
            "il buco deve accorciare la somma dei segmenti: e' quel divario a "
            "far scattare il cancello")

    def test_it_records_whether_the_heart_was_measured(self):
        _, senza = track._rows(1, _punti(4), "sha", datetime(2026, 1, 1))
        _, con = track._rows(1, _punti(4, battito=140), "sha",
                             datetime(2026, 1, 1))

        assert senza["has_heart_rate"] is False
        assert con["has_heart_rate"] is True

    def test_it_measures_how_often_the_watch_recorded(self):
        _, misure = track._rows(1, _punti(10), "sha", datetime(2026, 1, 1))

        assert misure["median_interval_s"] == pytest.approx(1.0)


class TestTheGate:
    def test_a_clean_recording_passes(self):
        regge, motivo = track.judge(
            {"points": 200, "gps_points": 200, "distance_gap": -0.008}, 10000)

        assert regge is True and motivo is None

    def test_poor_gps_coverage_is_refused_with_a_reason(self):
        # Il caso vero: 06/08/2023, copertura al 12%.
        regge, motivo = track.judge(
            {"points": 3162, "gps_points": 380, "distance_gap": -0.67}, 3643)

        assert regge is False
        assert "GPS" in motivo and "%" in motivo

    def test_a_distance_that_disagrees_is_refused(self):
        # lake01 2026: copertura buona ma distanza ricalcolata -25%.
        regge, motivo = track.judge(
            {"points": 100, "gps_points": 100, "distance_gap": -0.252}, 11155)

        assert regge is False
        assert "distanza" in motivo

    def test_too_few_points_is_its_own_reason(self):
        regge, motivo = track.judge(
            {"points": 1, "gps_points": 1, "distance_gap": 0.0}, 500)

        assert regge is False
        assert "punti" in motivo

    def test_a_missing_distance_never_fails_the_gate_by_itself(self):
        # Senza distanza dell'orologio non si puo' confrontare niente: la
        # risposta e' «non lo so», non «non regge».
        regge, _ = track.judge(
            {"points": 200, "gps_points": 200, "distance_gap": None}, None)

        assert regge is True


class TestTheRaceLink:
    def test_a_declared_race_carries_its_activity(self, connection, tmp_path,
                                                  monkeypatch):
        from garmin_coach.ingest import declared_races as dr

        monkeypatch.setattr(dr.paths, "COACH", tmp_path)
        (tmp_path / "gare-dichiarate.md").write_text(
            "| Data | Gara | Loc | Distanza | Tempo | Ambiente | Pos | "
            "Seduta Garmin | Note |\n|---|---|---|---|---|---|---|---|---|\n"
            "| 2024-05-26 | place21 | place21 | 10 km | 2:31:00 | "
            "acque libere | | 10000000003 | |\n", encoding="utf-8")

        dr.load(connection)

        assert connection.execute(
            "SELECT activity_id FROM races").fetchone()[0] == 10000000003, (
            "il collegamento veniva letto, contato nel rapporto e poi buttato: "
            "non c'era una colonna dove metterlo")

    def test_a_race_without_a_session_keeps_the_link_empty(self, connection,
                                                          tmp_path, monkeypatch):
        from garmin_coach.ingest import declared_races as dr

        monkeypatch.setattr(dr.paths, "COACH", tmp_path)
        (tmp_path / "gare-dichiarate.md").write_text(
            "| Data | Gara | Loc | Distanza | Tempo | Ambiente | Pos | "
            "Seduta Garmin | Note |\n|---|---|---|---|---|---|---|---|---|\n"
            "| 2018-06-29 | place19-place28 | place19 | 36 km | | acque libere | "
            "| | |\n", encoding="utf-8")

        dr.load(connection)

        assert connection.execute(
            "SELECT activity_id FROM races").fetchone()[0] is None, (
            "in vasca la domanda non si pone nemmeno: NULL non e' una lacuna")
