"""I file originali scaricati dal sync, e il tempo di nuoto depurato.

## Cosa difendono

1. **Un file salvato come `.fit` è un FIT.** La prima versione si è fidata del
   formato predefinito di `garminconnect` — che è **TCX**, cioè XML — e ha
   scritto venti file XML con estensione `.fit`. Nessuno se ne sarebbe accorto
   finché `details` non avesse smesso in silenzio di trovare lap.
2. **Si scarica solo quello che manca.** Questo account è già stato bloccato
   una volta con un 429: chiedere di nuovo un file che c'è già è una richiesta
   sprecata verso un servizio di terzi.
3. **Il tempo di nuoto si taglia solo alle estremità.** Un tratto lento in
   mezzo è un ristoro o una boa: toglierlo trasformerebbe un tempo in una
   somma di pezzi scelti.
"""

from datetime import datetime, timedelta

import duckdb
import pytest

from garmin_coach.analysis import swimming_time
from garmin_coach.database import SCHEMA
from garmin_coach.ingest import fit_download


def _fit_bytes(payload: bytes = b"corpo") -> bytes:
    """Dodici byte di header con la firma giusta, più un corpo qualunque."""
    return b"\x0e\x10\x00\x00" + b"\x00" * 4 + b".FIT" + payload


class TestTellingAFitFromSomethingElse:
    def test_a_real_fit_is_recognised(self):
        assert fit_download.looks_like_fit(_fit_bytes()) is True

    def test_a_tcx_is_not_a_fit(self):
        # Il caso vero: la libreria restituisce TCX se non le si chiede altro.
        assert fit_download.looks_like_fit(
            b'<?xml version="1.0" encoding="UTF-8"?><TrainingCenterDatabase>'
        ) is False

    def test_something_too_short_is_not_a_fit(self):
        assert fit_download.looks_like_fit(b"corto") is False

    def test_empty_is_not_a_fit(self):
        assert fit_download.looks_like_fit(b"") is False


class TestUnwrappingWhatGarminSends:
    def test_a_zipped_fit_is_unwrapped(self):
        import io
        import zipfile

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as bundle:
            bundle.writestr("12345.fit", _fit_bytes(b"dentro"))

        estratto = fit_download._fit_from(buffer.getvalue())

        assert estratto is not None
        assert fit_download.looks_like_fit(estratto)

    def test_a_bare_fit_passes_through(self):
        # Se un giorno Garmin smettesse di incartarlo, i byte arriverebbero
        # già buoni e non devono essere rifiutati.
        crudo = _fit_bytes()

        assert fit_download._fit_from(crudo) == crudo

    def test_a_zip_without_a_fit_gives_nothing(self):
        import io
        import zipfile

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as bundle:
            bundle.writestr("lettura.txt", b"niente di utile")

        assert fit_download._fit_from(buffer.getvalue()) is None

    def test_nothing_in_nothing_out(self):
        assert fit_download._fit_from(b"") is None


@pytest.fixture
def connection():
    con = duckdb.connect(":memory:")
    con.execute(SCHEMA)
    yield con
    con.close()


def _nuotata(con, activity_id, giorno):
    con.execute("""
        INSERT INTO activities (activity_id, activity_date, start_time_utc,
            sport, is_swim, duration_s, distance_m, source_object_id, imported_at)
        VALUES (?, ?, ?, 'lap_swimming', true, 3600, 3000, 'sha', ?)
    """, [activity_id, giorno, datetime(giorno.year, giorno.month, giorno.day, 8),
          datetime(2026, 1, 1)])


def _lap(con, activity_id):
    con.execute("""
        INSERT INTO activity_laps (activity_id, lap_index, duration_s,
            distance_m, source_object_id, imported_at)
        VALUES (?, 0, 60, 100, 'sha', ?)
    """, [activity_id, datetime(2026, 1, 1)])


class TestWhatIsWorthDownloading:
    def test_a_swim_without_laps_is_wanted(self, connection, tmp_path,
                                           monkeypatch):
        from datetime import date
        monkeypatch.setattr(fit_download.source_catalog, "RAW_FIT", tmp_path)
        _nuotata(connection, 1, date(2026, 8, 1))

        assert fit_download.without_detail(connection) == [1]

    def test_a_swim_that_already_has_laps_is_left_alone(self, connection,
                                                       tmp_path, monkeypatch):
        from datetime import date
        monkeypatch.setattr(fit_download.source_catalog, "RAW_FIT", tmp_path)
        _nuotata(connection, 1, date(2026, 8, 1))
        _lap(connection, 1)

        assert fit_download.without_detail(connection) == []

    def test_a_file_already_on_disk_is_never_asked_again(self, connection,
                                                        tmp_path, monkeypatch):
        from datetime import date
        monkeypatch.setattr(fit_download.source_catalog, "RAW_FIT", tmp_path)
        _nuotata(connection, 1, date(2026, 8, 1))
        (tmp_path / "1.fit").write_bytes(_fit_bytes())

        assert fit_download.without_detail(connection) == [], (
            "questo account e' gia' stato bloccato con un 429: una richiesta "
            "per un file che c'e' gia' e' sprecata")


def _traccia(con, activity_id, cadenze, passo_s=1):
    for indice, cadenza in enumerate(cadenze):
        con.execute("""
            INSERT INTO activity_track (activity_id, point_index, elapsed_s,
                cadence_spm, source_object_id, imported_at)
            VALUES (?, ?, ?, ?, 'sha', ?)
        """, [activity_id, indice, indice * passo_s, cadenza,
              datetime(2026, 1, 1)])


class TestSwimmingTime:
    def test_a_swim_with_no_waiting_keeps_its_whole_time(self, connection):
        _traccia(connection, 1, [30.0] * 300)

        misura = swimming_time.of(connection, 1)

        assert misura.swimming_s == pytest.approx(misura.recorded_s)
        assert misura.matters is False

    def test_waiting_at_the_start_is_trimmed(self, connection):
        # Il caso vero: sul lake01 2018 l'orologio e' partito 7,5 minuti
        # prima del via.
        _traccia(connection, 1, [0.0] * 120 + [30.0] * 300)

        misura = swimming_time.of(connection, 1)

        assert misura.trimmed_start_s == pytest.approx(120, abs=2)
        assert misura.trimmed_end_s == pytest.approx(0, abs=2)
        assert misura.matters is True

    def test_climbing_out_at_the_end_is_trimmed(self, connection):
        _traccia(connection, 1, [30.0] * 300 + [1.0] * 90)

        misura = swimming_time.of(connection, 1)

        assert misura.trimmed_end_s == pytest.approx(90, abs=2)

    def test_a_slow_stretch_in_the_middle_is_kept(self, connection):
        # Un ristoro, una boa, una medusa: fa parte della gara. Toglierlo
        # trasformerebbe un tempo in una somma di pezzi scelti.
        _traccia(connection, 1, [30.0] * 150 + [0.0] * 60 + [30.0] * 150)

        misura = swimming_time.of(connection, 1)

        assert misura.swimming_s == pytest.approx(misura.recorded_s, abs=2)

    def test_without_cadence_it_says_nothing(self, connection):
        _traccia(connection, 1, [0.0] * 300)

        assert swimming_time.of(connection, 1) is None, (
            "senza cadenza «non stavo nuotando» non si riconosce, e inventare "
            "un taglio sarebbe peggio che lasciare il tempo intero")

    def test_too_few_points_give_no_answer(self, connection):
        _traccia(connection, 1, [30.0] * 10)

        assert swimming_time.of(connection, 1) is None

    def test_the_description_keeps_its_full_stop(self, connection):
        _traccia(connection, 1, [0.0] * 120 + [30.0] * 300)

        frase = swimming_time.describe(swimming_time.of(connection, 1))

        assert frase.endswith(".")
        assert "," in frase, "i decimali si scrivono con la virgola"
