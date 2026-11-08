"""Intento contro risultato: la seduta detta da chi l'ha fatta.

Senza l'intento il coach puo' dire "il passo e' rallentato del 10%" e non puo'
dire se era previsto. **Un rallentamento voluto e uno subito hanno la stessa
forma nei numeri**, e distinguerli non e' un problema di analisi: e' un problema
di informazione mancante.

Quando l'intento non c'e', la pagina lo chiede - e lo chiede *dopo* aver
mostrato cosa e' successo, perche' cosi' l'atleta vede a che cosa serve.
"""

from datetime import date, datetime

import duckdb
import pytest

from garmin_coach import paths
from garmin_coach.analysis import sessions
from garmin_coach.database import SCHEMA

GIORNO = date(2026, 8, 20)
SEDUTA = 7


@pytest.fixture
def coach_dir(tmp_path, monkeypatch):
    cartella = tmp_path / "coach"
    (cartella / "diario").mkdir(parents=True)
    monkeypatch.setattr(paths, "COACH", cartella)
    return cartella


@pytest.fixture
def connection(coach_dir):
    con = duckdb.connect(":memory:")
    con.execute(SCHEMA)
    con.execute(
        "INSERT INTO activities (activity_id, start_time_utc, start_time_local, "
        " activity_date, sport, is_swim, environment, distance_m, duration_s, "
        " pool_length_m, source_object_id, imported_at) VALUES "
        "(?, ?, ?, ?, 'lap_swimming', TRUE, 'pool', 1200, 1800, 25, 'sha', ?)",
        [SEDUTA, datetime(2026, 8, 20, 19), datetime(2026, 8, 20, 19), GIORNO,
         datetime(2026, 1, 1)])
    for i in range(6):
        con.execute(
            "INSERT INTO activity_laps (activity_id, lap_index, start_time_utc, "
            " duration_s, distance_m, stroke, avg_cadence_spm, "
            " pace_per_100m_s, is_rest, source_object_id, imported_at) "
            "VALUES (?, ?, ?, ?, 200, 'freestyle', 28, ?, FALSE, 'fit://x', ?)",
            [SEDUTA, i, datetime(2026, 8, 20, 19, i * 5), 160 + i * 4,
             80 + i * 2, datetime(2026, 1, 1)])
    yield con
    con.close()


def _nota(coach_dir, finalita, rpe=None):
    righe = [f"\n## 2026-08-20\n", f"**Seduta {SEDUTA}** del 2026-08-20"]
    if rpe is not None:
        righe.append(f"- fatica percepita: **{rpe}/10** (CR10)")
    righe.append(f"- finalità: **{finalita}**")
    (coach_dir / "diario" / "2026-W34.md").write_text(
        "# W34\n" + "\n".join(righe) + "\n", encoding="utf-8")


class TestSenzaIntentoLaPaginaLoChiede:
    def test_it_says_it_cannot_tell_whether_it_went_as_planned(self, connection):
        packet = sessions.detail(connection, SEDUTA).as_dict()

        testo = " ".join(packet["limitations"])
        assert "non se e' andata come doveva" in testo.replace("è", "e'")

    def test_it_asks_for_the_intent_after_showing_what_happened(self, connection):
        """La domanda c'era gia', e meglio scritta di quella che avevo aggiunto.

        Quello che mancava non era la domanda: era dire **cosa cambia** se
        resta senza risposta, che e' l'unica cosa che da' un motivo per
        rispondere. Questo test tiene la domanda dov'e' e verifica che chieda
        davvero la finalita'.
        """
        packet = sessions.detail(connection, SEDUTA).as_dict()

        assert "finalit" in (packet["next_question"] or "")

    def test_the_observation_still_says_what_happened(self, connection):
        """Il limite non sostituisce l'analisi: i numeri restano."""
        packet = sessions.detail(connection, SEDUTA).as_dict()

        assert packet["observation"]
        assert packet["comparisons"]


class TestConLIntentoLaPaginaLoAffianca:
    def test_the_declared_purpose_appears_next_to_the_result(self, connection,
                                                             coach_dir):
        _nota(coach_dir, "soglia", rpe=8)

        packet = sessions.detail(connection, SEDUTA).as_dict()

        testo = " ".join(packet["limitations"])
        assert "soglia" in testo and "8/10" in testo

    def test_it_does_not_judge_whether_the_stimulus_landed(self, connection,
                                                           coach_dir):
        """Dire "lo stimolo e' arrivato" e' un giudizio, e il giudizio non sta
        qui: sta nel coach, che ha il contratto per motivarlo. Questa funzione
        mette le due cose una accanto all'altra e nomina chi decide."""
        _nota(coach_dir, "soglia", rpe=8)

        testo = " ".join(sessions.detail(connection, SEDUTA).as_dict()["limitations"])
        assert "allenatore" in testo

    def test_it_stops_asking_once_it_knows(self, connection, coach_dir):
        _nota(coach_dir, "velocita", rpe=9)

        packet = sessions.detail(connection, SEDUTA).as_dict()

        assert "doveva essere questa seduta" not in (packet["next_question"] or "")
