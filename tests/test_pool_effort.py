"""La prova in vasca letta vasca per vasca: cede l'ampiezza o la frequenza?

## Cosa difendono

1. **La scomposizione è un'identità**, non un modello: velocità = ampiezza ×
   frequenza, e le bracciate si semplificano. Se un giorno qualcuno la
   sostituisse con una correlazione, il primo test fallisce.
2. **Il caso che i lap non vedono**: ampiezza che cala e frequenza che sale a
   compensare, con il passo apparentemente tenuto. È il motivo per cui questo
   modulo esiste.
3. **Lo zero di Garmin non è una misura.** Zero bracciate su una vasca nuotata
   significa «non registrate», e i metri per bracciata restano assenti invece
   di diventare infinito.
4. **La prima vasca resta fuori dal confronto**: contiene una spinta dal muro
   che nessun'altra vasca ha.
5. **La soglia si adatta alla prova.** Una prova lunga e regolare distingue
   differenze che una corta e irregolare non può distinguere, e il numero lo
   dice invece di far finta.
6. **Stili diversi non si confrontano.** I metri per bracciata di un delfino e
   di uno stile libero misurano due movimenti, non due stati di forma.
"""

from datetime import date, datetime

import duckdb
import pytest

from garmin_coach.analysis import pool_effort as pe
from garmin_coach.database import SCHEMA

VASCA = 25.0


@pytest.fixture
def connection():
    con = duckdb.connect(":memory:")
    con.execute(SCHEMA)
    _seduta(con, 1)
    yield con
    con.close()


def _seduta(con, activity_id, vasca=VASCA):
    con.execute("""
        INSERT INTO activities (activity_id, activity_date, start_time_utc,
            sport, is_swim, duration_s, distance_m, pool_length_m,
            source_object_id, imported_at)
        VALUES (?, ?, ?, 'lap_swimming', true, 600, 1000, ?, 'sha', ?)
    """, [activity_id, date(2026, 6, 1), datetime(2026, 6, 1, 8), vasca,
          datetime(2026, 1, 1)])


def _vasche(con, tempi, bracciate=None, stili=None, activity_id=1,
            lap_index=0, attive=True):
    """Scrive una sequenza di vasche. `tempi` decide quante sono.

    `length_index` è unico per attività, non per lap: la numerazione riprende
    da dove è arrivata, come fa l'orologio.
    """
    primo = con.execute(
        "SELECT coalesce(max(length_index) + 1, 0) FROM pool_lengths "
        "WHERE activity_id = ?", [activity_id]).fetchone()[0]
    for i, durata in enumerate(tempi):
        br = bracciate[i] if bracciate else 20.0
        st = stili[i] if stili else "freestyle"
        con.execute("""
            INSERT INTO pool_lengths (activity_id, length_index, lap_index,
                duration_s, stroke, total_strokes, is_active,
                source_object_id, imported_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'sha', ?)
        """, [activity_id, primo + i, lap_index, durata, st, br, attive,
              datetime(2026, 1, 1)])


def _costante(quante, durata=20.0, bracciate=20.0):
    return [durata] * quante, [bracciate] * quante


class TestTheIdentity:
    def test_speed_is_exactly_amplitude_times_frequency(self):
        # Non è una correlazione osservata: le bracciate si semplificano.
        # Verificato sull'archivio vero su 127.358 vasche, errore massimo
        # 2,5e-16. Qui si difende la proprietà, non il campione.
        vasca = pe.Length(index=0, pool_length_m=25.0, duration_s=17.3,
                          strokes=19.0, stroke="freestyle")

        assert vasca.speed_ms == pytest.approx(vasca.dps_m * vasca.rate_hz,
                                               rel=1e-12)

    def test_a_length_without_strokes_has_no_amplitude_nor_frequency(self):
        # Garmin scrive 0 invece di omettere: 6.471 vasche attive dell'archivio
        # hanno zero bracciate. Dividere per zero darebbe infinito, e un
        # infinito in una media la distrugge in silenzio.
        vasca = pe.Length(index=0, pool_length_m=25.0, duration_s=20.0,
                          strokes=0.0, stroke="freestyle")

        assert vasca.dps_m is None
        assert vasca.rate_hz is None
        assert vasca.swolf is None
        assert vasca.pace_100_s == pytest.approx(80.0), (
            "il passo nasce dal tempo e resta leggibile anche senza bracciate")


class TestFindingEfforts:
    def test_a_continuous_swim_is_one_effort(self, connection):
        tempi, bracciate = _costante(16)
        _vasche(connection, tempi, bracciate)

        trovati = pe.efforts(connection, 1)

        assert len(trovati) == 1
        assert trovati[0].distance_m == pytest.approx(400.0)

    def test_a_short_swim_is_not_an_effort(self, connection):
        tempi, bracciate = _costante(6)
        _vasche(connection, tempi, bracciate)

        assert pe.efforts(connection, 1) == [], (
            "sei vasche danno due meta' da tre: una media di tre vasche "
            "non descrive una tendenza")

    def test_rest_lengths_stay_out(self, connection):
        tempi, bracciate = _costante(16)
        _vasche(connection, tempi, bracciate)
        _vasche(connection, [60.0], [0.0], lap_index=1, attive=False)

        trovati = pe.efforts(connection, 1)

        assert len(trovati) == 1
        assert trovati[0].distance_m == pytest.approx(400.0)

    def test_separate_laps_are_separate_efforts(self, connection):
        tempi, bracciate = _costante(16)
        _vasche(connection, tempi, bracciate, lap_index=0)
        _vasche(connection, tempi, bracciate, lap_index=1, activity_id=1)

        assert len(pe.efforts(connection, 1)) == 2

    def test_the_longest_effort_is_the_test(self, connection):
        _vasche(connection, *_costante(8), lap_index=0)
        _vasche(connection, *_costante(24), lap_index=1)

        assert pe.longest(connection, 1).distance_m == pytest.approx(600.0)


class TestTheVerdict:
    def test_a_steady_effort_is_held(self, connection):
        tempi, bracciate = _costante(16)
        _vasche(connection, tempi, bracciate)

        assert pe.efforts(connection, 1)[0].verdict == pe.HELD

    def test_a_clearly_fading_effort_is_named(self, connection):
        tempi = [20.0] * 8 + [24.0] * 8
        _vasche(connection, tempi, [20.0] * 16)

        uno = pe.efforts(connection, 1)[0]

        assert uno.verdict == pe.FADING
        assert uno.pace_change_pct > 0

    def test_a_negative_split_is_named_building(self, connection):
        tempi = [24.0] * 8 + [20.0] * 8
        _vasche(connection, tempi, [20.0] * 16)

        assert pe.efforts(connection, 1)[0].verdict == pe.BUILDING

    def test_the_first_length_stays_out_of_the_comparison(self, connection):
        # La prima vasca parte dal muro e vale un secondo di regalo. Se
        # entrasse nel confronto, una prova perfettamente regolare
        # risulterebbe «in calando» solo per la spinta iniziale.
        tempi = [14.0] + [20.0] * 15
        _vasche(connection, tempi, [20.0] * 16)

        uno = pe.efforts(connection, 1)[0]

        assert uno.verdict == pe.HELD
        assert len(uno.compared) == 15


class TestTheNoiseThreshold:
    def test_a_longer_effort_can_see_smaller_differences(self, connection):
        # Stessa irregolarità — l'alternanza 19/21 ha lo stesso CV in
        # entrambe — e lunghezze diverse. Con tempi identici il CV sarebbe
        # zero e le due prove finirebbero tutte e due sul pavimento della
        # soglia, misurando niente.
        _vasche(connection, [19.0, 21.0] * 5, [20.0] * 10, lap_index=0)
        _vasche(connection, [19.0, 21.0] * 20, [20.0] * 40, lap_index=1)

        corta, lunga = pe.efforts(connection, 1)

        assert lunga.noise_pct < corta.noise_pct, (
            "il rumore si media via, e quanto dipende da quante vasche ci sono")

    def test_an_irregular_effort_admits_it_sees_less(self, connection):
        _vasche(connection, [20.0] * 16, [20.0] * 16, lap_index=0)
        _vasche(connection, [16.0, 24.0] * 8, [20.0] * 16, lap_index=1)

        regolare, irregolare = pe.efforts(connection, 1)

        assert irregolare.noise_pct > regolare.noise_pct

    def test_the_threshold_never_claims_absurd_precision(self, connection):
        tempi, bracciate = _costante(60)
        _vasche(connection, tempi, bracciate)

        assert pe.efforts(connection, 1)[0].noise_pct >= pe.MIN_NOISE_PCT


class TestWhatGaveWay:
    def test_amplitude_giving_way_is_recognised(self, connection):
        # Stessa frequenza, bracciata più corta: il passo cala perché l'acqua
        # scappa. 20 bracciate -> 24 con il tempo che cresce in proporzione
        # tiene la frequenza ferma.
        tempi = [20.0] * 8 + [24.0] * 8
        bracciate = [20.0] * 8 + [24.0] * 8
        _vasche(connection, tempi, bracciate)

        uno = pe.efforts(connection, 1)[0]

        assert uno.verdict == pe.FADING
        assert uno.attribution == pe.AMPLITUDE

    def test_frequency_giving_way_is_recognised(self, connection):
        # Stessa ampiezza, ritmo più lento: stesse bracciate per vasca, ma
        # ogni vasca dura di più.
        tempi = [20.0] * 8 + [24.0] * 8
        bracciate = [20.0] * 16
        _vasche(connection, tempi, bracciate)

        uno = pe.efforts(connection, 1)[0]

        assert uno.verdict == pe.FADING
        assert uno.attribution == pe.FREQUENCY

    def test_the_compensation_invisible_to_laps_is_recognised(self, connection):
        # Il caso per cui questo modulo esiste. Il passo resta quasi identico —
        # a livello di lap non succede niente — ma la bracciata si è accorciata
        # del 20% e il ritmo è salito per coprire il buco.
        tempi = [20.0] * 8 + [20.6] * 8
        bracciate = [20.0] * 8 + [25.0] * 8
        _vasche(connection, tempi, bracciate)

        uno = pe.efforts(connection, 1)[0]

        assert uno.attribution == pe.COMPENSATED
        assert uno.dps_change_pct < 0 and uno.rate_change_pct > 0

    def test_mixed_strokes_refuse_the_question(self, connection):
        tempi = [20.0] * 8 + [26.0] * 8
        stili = ["freestyle"] * 8 + ["butterfly"] * 8
        _vasche(connection, tempi, [20.0] * 16, stili)

        uno = pe.efforts(connection, 1)[0]

        assert uno.single_stroke is False
        assert uno.attribution == pe.MIXED_STROKES, (
            "i metri per bracciata di due nuotate diverse misurano il cambio "
            "di stile, non la stanchezza")

    def test_without_strokes_it_says_nothing_instead_of_guessing(self, connection):
        tempi = [20.0] * 8 + [24.0] * 8
        _vasche(connection, tempi, [0.0] * 16)

        uno = pe.efforts(connection, 1)[0]

        assert uno.verdict == pe.FADING, "il passo si legge comunque"
        assert uno.attribution is None


class TestThePage:
    def test_it_explains_without_eating_the_full_stop(self, connection):
        # Difetto vero, trovato leggendo l'output: `.replace(".", ",")` su una
        # frase intera trasformava anche il punto finale in una virgola.
        tempi, bracciate = _costante(16)
        _vasche(connection, tempi, bracciate)

        corpo = pe.as_page_dict(connection, 1)

        assert corpo["available"] is True
        assert corpo["efforts"][0]["explanation"].endswith(".")

    def test_a_session_without_long_swims_says_why(self, connection):
        _vasche(connection, *_costante(4))

        corpo = pe.as_page_dict(connection, 1)

        assert corpo["available"] is False
        assert "vasche di fila" in corpo["why"]

    def test_missing_values_show_a_dash_not_a_zero(self, connection):
        _vasche(connection, [20.0] * 16, [0.0] * 16)

        vasca = pe.as_page_dict(connection, 1)["efforts"][0]["lengths"][0]

        assert vasca["dps"] == "—"
        assert vasca["rate"] == "—"
        assert vasca["swolf"] == "—"
