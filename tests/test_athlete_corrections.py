"""Un record formalmente valido che non descrive quello che l'atleta ha fatto.

## Il caso

L'attività Garmin `10000000001` — «place20 Open Water Swimming», 20/09/2025 —
dice 25.824 m in 6h31. Riepilogo dell'export e file FIT concordano perfettamente,
e per il progetto questo è sempre stato il segno che un dato è buono.

Non lo è. Il FIT contiene 28 lap, **2.306 bracciate in totale**, cadenza media 8
e 11,2 m per bracciata: lunghi tratti in movimento senza bracciate. Per
confronto, place19 2018 su 30,6 km ha 17.293 bracciate, cadenza 28, 1,77 m per
bracciata. L'atleta ha confermato di non aver nuotato 25,8 km nel 2025.

## Cosa contamina oggi, misurato sull'archivio vero

- **9,1%** del volume di nuoto 2025 (25,8 km su 282,4);
- la **seconda distanza** di tutta la storia, dietro solo a place19 2018;
- `daily_status` del 20/09/2025: `swim_km_7d` 25,8 — cioè quasi tutta la
  settimana — e ACWR 1,46;
- **28 giorni** di `daily_status` ne portano il peso nelle finestre a 28 giorni.

## Cosa deve fare la correzione

Il raw resta intoccabile: l'export e i FIT non si riscrivono mai, e il database
deve restare ricostruibile da zero. La decisione umana vive in
`coach/correzioni-dati.md` e diventa uno strato che le analisi attraversano.

Nessun activity ID compare nel codice di analisi. Se domani l'atleta escludesse
un'altra attività, non si tocca una riga di Python.
"""

from datetime import date, datetime

import duckdb
import pytest

from garmin_coach import corrections, paths
from garmin_coach.database import SCHEMA
from garmin_coach.metrics import daily_status

place20 = 10000000001
GIORNO_place20 = date(2025, 9, 20)

CORREZIONI_MD = """# Correzioni dei dati confermate dall'atleta

## Stati ammessi

- `exclude`: non usare l'attività in alcuna metrica.

## Decisioni

| Activity ID | Stato | Data attività | Ambito | Decisione e motivo | Confermata il |
|---:|---|---|---|---|---|
| 10000000001 | `exclude` | 2025-09-20 | distanza, volume, carico | Registrazione mista: 2.306 bracciate su 25,8 km. | 2026-08-21 |
"""


@pytest.fixture
def coach_dir(tmp_path, monkeypatch):
    cartella = tmp_path / "coach"
    cartella.mkdir()
    (cartella / "correzioni-dati.md").write_text(CORREZIONI_MD, encoding="utf-8")
    monkeypatch.setattr(paths, "COACH", cartella)
    return cartella


@pytest.fixture
def connection(coach_dir):
    """Due nuotate: quella vera di 3 km e quella da escludere di 25,8 km."""
    con = duckdb.connect(":memory:")
    con.execute(SCHEMA)
    con.execute("""
        INSERT INTO activities (activity_id, start_time_utc, start_time_local,
                                activity_date, sport, is_swim, environment,
                                distance_m, duration_s, garmin_training_load,
                                device_id, source_object_id, imported_at)
        VALUES
        (10000000001, TIMESTAMP '2025-09-20 07:00', TIMESTAMP '2025-09-20 09:00',
         DATE '2025-09-20', 'open_water_swimming', TRUE, 'open_water',
         25824.48, 23470.78, 400, 1, 'sha', TIMESTAMP '2026-01-01'),
        (900001, TIMESTAMP '2025-09-22 07:00', TIMESTAMP '2025-09-22 09:00',
         DATE '2025-09-22', 'lap_swimming', TRUE, 'pool',
         3000, 3600, 50, 1, 'sha', TIMESTAMP '2026-01-01')
    """)
    corrections.apply(con)
    daily_status.build(con)
    yield con
    con.close()


# ── La decisione umana, letta dove l'atleta la scrive ────────────────────

class TestLaDecisioneSiLeggeDalMarkdown:
    def test_the_correction_is_read_from_the_athlete_file(self, coach_dir):
        decisioni = corrections.declared()

        assert len(decisioni) == 1
        una = decisioni[0]
        assert una.activity_id == place20
        assert una.status == "exclude"
        assert una.confirmed_on == date(2026, 8, 21)
        assert "2.306 bracciate" in una.reason

    def test_no_activity_id_is_written_in_the_analysis_code(self):
        """Il numero dell'attività non deve comparire in nessuna funzione.

        Un ID nel codice è una decisione umana travestita da costante: sopravvive
        a chi l'ha presa, non porta con sé il motivo, e la seconda esclusione si
        fa copiando la prima.
        """
        import pathlib

        radice = pathlib.Path(corrections.__file__).parent
        colpevoli = []
        for sorgente in radice.rglob("*.py"):
            if str(place20) in sorgente.read_text(encoding="utf-8"):
                colpevoli.append(sorgente.name)
        assert not colpevoli, (
            f"l'identificativo dell'attività compare in {colpevoli}: la "
            "decisione dell'atleta è finita dentro il codice")

    def test_an_unknown_status_is_refused_instead_of_ignored(self, tmp_path,
                                                             monkeypatch):
        """Uno stato che il progetto non conosce non è un'assenza di decisione.

        Silenziarlo vorrebbe dire includere di nuovo il record che l'atleta
        credeva escluso.
        """
        cartella = tmp_path / "coach"
        cartella.mkdir()
        (cartella / "correzioni-dati.md").write_text(
            CORREZIONI_MD.replace("`exclude`", "`cancellalo`"), encoding="utf-8")
        monkeypatch.setattr(paths, "COACH", cartella)

        with pytest.raises(corrections.UnknownDecision):
            corrections.declared()


# ── Le superfici che oggi lo includono ───────────────────────────────────

class TestNonEntraInNessunaAggregazione:
    def test_the_canonical_view_leaves_it_out(self, connection):
        rimaste = connection.execute(
            "SELECT count(*) FROM canonical_activities").fetchone()[0]
        assert rimaste == 1

    def test_the_raw_table_still_has_it(self, connection):
        """Il raw non si tocca: la correzione è uno strato, non una cancellazione.

        È anche l'unico modo per poter cambiare idea, e per poter mostrare
        all'atleta cosa è stato escluso e perché.
        """
        assert connection.execute(
            "SELECT count(*) FROM activities WHERE activity_id = ?",
            [place20]).fetchone()[0] == 1

    def test_the_period_volume_does_not_count_it(self, connection):
        from garmin_coach.analysis import volume

        misura = volume.of_period(connection, date(2025, 9, 1), date(2025, 9, 30))

        assert misura.distance_km == pytest.approx(3.0), (
            f"il volume del periodo è {misura.distance_km} km: dentro c'è "
            "un'attività che l'atleta ha escluso")
        assert misura.sessions == 1

    def test_daily_status_does_not_carry_it(self, connection):
        riga = connection.execute(
            "SELECT swim_distance_m, swim_km_7d FROM daily_status "
            "WHERE status_date = ?", [GIORNO_place20]).fetchone()
        assert riga is None or not riga[0], (
            "daily_status attribuisce 25,8 km a un giorno che l'atleta dice di "
            "non aver nuotato")

    def test_the_load_of_the_excluded_day_does_not_move_the_windows(self,
                                                                    connection):
        """Il carico è la cosa che sopravvive più a lungo: 28 giorni di finestre
        lo portano, e con esso ACWR, monotonia e strain."""
        carico = connection.execute(
            "SELECT max(load_acute_7) FROM daily_status "
            "WHERE status_date BETWEEN ? AND ?",
            [GIORNO_place20, date(2025, 10, 17)]).fetchone()[0]
        assert (carico or 0) <= 50, (
            f"il carico a 7 giorni arriva a {carico}: dentro c'è il carico di "
            "un'attività esclusa")

    def test_it_is_not_a_personal_best(self, connection):
        piu_lunga = connection.execute(
            "SELECT activity_id FROM canonical_activities "
            "WHERE is_swim ORDER BY distance_m DESC LIMIT 1").fetchone()[0]
        assert piu_lunga != place20

    def test_the_mcp_tools_do_not_see_it(self, connection):
        from garmin_coach.mcp import queries

        risposta = queries.swim_history(connection, date(2025, 9, 1),
                                        date(2025, 9, 30))
        assert risposta["totals"]["distance_km"] == pytest.approx(3.0)
        assert risposta["totals"]["sessions"] == 1

    def test_the_session_page_says_it_is_excluded_instead_of_hiding_it(
            self, connection):
        """Sparire non basta: l'atleta deve poter aprire quel giorno e leggere
        perché quel record non conta, altrimenti la correzione sembra un buco."""
        from garmin_coach.analysis import sessions

        packet = sessions.detail(connection, place20).as_dict()

        testo = packet["observation"] + " ".join(packet["limitations"])
        assert "esclus" in testo.lower(), (
            "la pagina della seduta non dice che è stata esclusa")
        assert "2.306 bracciate" in testo, "manca il motivo della decisione"


# ── Il contratto: nessuna analisi salta lo strato ────────────────────────

class TestNessunaAnalisiScavalcaLoStrato:
    """Se una pagina interroga ``activities`` invece della vista, la correzione
    non è implementata: è implementata *quasi*, che è peggio, perché sembra
    fatta.
    """

    DEVONO_USARE_LA_VISTA = [
        "analysis/volume.py", "analysis/today.py", "analysis/progress.py",
        "analysis/sessions.py", "metrics/daily_status.py",
        "mcp/queries.py", "mcp/planning.py", "app/server.py",
        "vertical_slice.py",
    ]

    @pytest.mark.parametrize("modulo", DEVONO_USARE_LA_VISTA)
    def test_the_module_never_aggregates_the_raw_table(self, modulo):
        import pathlib
        import re

        percorso = pathlib.Path(corrections.__file__).parent / modulo
        testo = percorso.read_text(encoding="utf-8")
        dirette = re.findall(r"(?:FROM|JOIN)\s+activities\b", testo, re.I)
        assert not dirette, (
            f"{modulo} interroga la tabella grezza {len(dirette)} volte: le "
            "attività escluse dall'atleta rientrano da lì")

    def test_the_ingest_still_writes_the_raw_table(self):
        """Il divieto vale per chi legge per analizzare, non per chi importa:
        l'import **deve** scrivere il raw, che è la cosa che non si perde."""
        import pathlib

        percorso = (pathlib.Path(corrections.__file__).parent
                    / "ingest" / "summaries.py")
        assert "activities" in percorso.read_text(encoding="utf-8")


# ── Dopo un sync e dopo una ricostruzione ────────────────────────────────

class TestLaCorrezioneSopravvive:
    def test_rebuilding_the_quality_layer_keeps_the_decision(self, connection):
        """Il database si ricostruisce da zero: la decisione non vive lì dentro,
        vive in `coach/` e ci rientra a ogni ricostruzione."""
        connection.execute("DELETE FROM activity_quality")
        assert connection.execute(
            "SELECT count(*) FROM canonical_activities").fetchone()[0] == 2

        corrections.apply(connection)

        assert connection.execute(
            "SELECT count(*) FROM canonical_activities").fetchone()[0] == 1

    def test_applying_twice_does_not_duplicate_the_decision(self, connection):
        corrections.apply(connection)
        corrections.apply(connection)

        assert connection.execute(
            "SELECT count(*) FROM activity_quality").fetchone()[0] == 1

    def test_a_decision_about_an_activity_that_is_not_there_is_not_lost(
            self, connection, coach_dir):
        """Un'esclusione su un'attività non ancora importata deve restare scritta.

        Se il sync la porta domani, la correzione dev'essere già in attesa —
        altrimenti l'attività esclusa rientra per una notte e finisce nelle
        medie prima che qualcuno se ne accorga.
        """
        (coach_dir / "correzioni-dati.md").write_text(
            CORREZIONI_MD + "| 777 | `exclude` | 2026-01-01 | tutto | "
            "Prova. | 2026-08-21 |\n", encoding="utf-8")

        corrections.apply(connection)

        assert connection.execute(
            "SELECT count(*) FROM activity_quality WHERE activity_id = 777"
        ).fetchone()[0] == 1


class TestVerifySaSeLaCorrezioneEApplicata:
    """Meglio nessuna correzione che una correzione che sembra applicata.

    Una riga scritta in `coach/correzioni-dati.md` e non arrivata in
    `activity_quality` e' la peggiore delle due situazioni possibili: l'atleta
    crede di aver tolto quel record, e il record continua a pesare su ogni
    media.
    """

    def _criterio(self, connection, identifier):
        from garmin_coach.verification import run_checks
        return next(c for c in run_checks(connection) if c.identifier == identifier)

    def test_an_applied_correction_passes(self, connection):
        assert self._criterio(connection, "C11").passed

    def test_a_declared_correction_that_never_landed_is_reported(self, connection):
        connection.execute("DELETE FROM activity_quality")

        criterio = self._criterio(connection, "C11")
        assert not criterio.passed
        assert str(place20) in str(criterio.actual)

    def test_a_correction_with_the_wrong_status_does_not_pass(self, connection):
        connection.execute(
            "UPDATE activity_quality SET status = 'keep' WHERE activity_id = ?",
            [place20])

        criterio = self._criterio(connection, "C11")

        assert not criterio.passed
        assert str(place20) in str(criterio.actual)

    def test_the_swim_metres_are_compared_against_the_canonical_view(
            self, connection):
        """C6e confrontava il raw col derivato.

        Da quando esistono le esclusioni i due numeri **devono** differire: e'
        il senso stesso della correzione. Confrontarli farebbe fallire il
        criterio esattamente quando la correzione funziona.
        """
        assert self._criterio(connection, "C6e").passed


class TestLaMacchinaSegnalaLaPersonaDecide:
    """I limiti sono fisici, non statistici.

    Una soglia statistica su un archivio personale segnala l'atleta quando
    migliora. Una soglia fisica segnala soltanto cio' che un essere umano non fa.

    Il caso vero trovato nell'audit del 22/08/2026: 26/05/2021, 700 m in due
    minuti, 29 bracciate. Sono 18,2 s/100 m e 24 m per bracciata. Nessuno lo
    aveva notato in nove anni.
    """

    def _nuotata(self, con, activity_id, distanza, durata, bracciate):
        from datetime import date as _d
        con.execute(
            "INSERT INTO activities (activity_id, start_time_utc, activity_date, "
            " sport, is_swim, environment, distance_m, duration_s, total_strokes, "
            " source_object_id, imported_at) VALUES (?, ?, ?, 'open_water_swimming',"
            " TRUE, 'open_water', ?, ?, ?, 'sha', ?)",
            [activity_id, datetime(2021, 5, 26, 9), _d(2021, 5, 26),
             distanza, durata, bracciate, datetime(2026, 1, 1)])

    def test_a_pace_faster_than_the_world_record_is_flagged(self, connection):
        self._nuotata(connection, 500001, 700, 128, 29)      # 18,2 s/100 m

        segnalate = corrections.flag_automatically(connection)

        assert any(s["activity_id"] == 500001 for s in segnalate)

    def test_a_flag_does_not_exclude_it_from_the_totals(self, connection):
        """`review` significa «non regge una conclusione forte», non «via».

        Escludere in automatico sarebbe decidere al posto dell'atleta su un dato
        che potrebbe essere vero e sorprendente.
        """
        self._nuotata(connection, 500001, 700, 128, 29)
        corrections.flag_automatically(connection)

        assert connection.execute(
            "SELECT count(*) FROM canonical_activities WHERE activity_id = 500001"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT quality_status FROM canonical_activities "
            "WHERE activity_id = 500001").fetchone()[0] == "review"

    def test_the_athlete_decision_always_wins(self, connection):
        """Se l'atleta ha gia' guardato quel record, la macchina tace."""
        corrections.flag_automatically(connection)

        stato = connection.execute(
            "SELECT status, decided_by FROM activity_quality WHERE activity_id = ?",
            [place20]).fetchone()
        assert stato == ("exclude", "athlete"), (
            "la segnalazione automatica ha sovrascritto la decisione umana")

    def test_a_normal_session_is_not_flagged(self, connection):
        """Il costo di un falso allarme e' che l'atleta smetta di guardarli."""
        corrections.flag_automatically(connection)

        assert connection.execute(
            "SELECT count(*) FROM activity_quality WHERE activity_id = 900001"
        ).fetchone()[0] == 0

    def test_running_it_twice_does_not_pile_up_flags(self, connection):
        self._nuotata(connection, 500001, 700, 128, 29)
        corrections.flag_automatically(connection)
        corrections.flag_automatically(connection)

        assert connection.execute(
            "SELECT count(*) FROM activity_quality WHERE decided_by = 'automatic'"
        ).fetchone()[0] == 1
