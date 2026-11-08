"""Dal dubbio alla decisione, senza aprire un file markdown.

## Il caso che ha reso necessaria questa pagina

Il 26/05/2021 l'archivio dice **700 m in 2 minuti**, cioè 18,2 s/100 m: più del
doppio del record mondiale sui 50 stile. `corrections.flag_automatically` la
marca `review` da subito, e fa bene.

Poi però la segnalazione finiva lì. Compariva in tre righe di terminale durante
un import, con l'identificativo e nient'altro. Per rispondere, l'atleta doveva
sapere che esiste `coach/correzioni-dati.md`, capire una tabella a sei colonne e
ricopiare undici cifre a mano. Risultato misurato: tre attività ferme in
`review` e la homepage che diceva «confidenza bassa» senza offrire un posto in
cui togliere il dubbio.

## Cosa questi test difendono

1. **Il confronto esclude il dubbio da sé stesso.** Se l'attività anomala
   restasse nella popolazione con cui la si confronta, allargherebbe
   l'intervallo fino a contenersi: il controllo direbbe che va tutto bene
   proprio nel caso in cui deve gridare.
2. **Chi scrive e chi legge parlano la stessa lingua.** `add_correction` scrive
   una riga che `corrections.declared()` deve saper rileggere. Sono due moduli
   diversi e nessun test li teneva insieme.
3. **`correct` non si scrive da qui.** Richiede i valori veri, e un modulo che
   chiede «quanto hai nuotato davvero?» a chi sta guardando un numero sbagliato
   invita a inventare — la seconda invenzione che il progetto ha già rifiutato
   per place20.
4. **La conferma resta vincolante.** Manomettere lo stato al momento della
   conferma non deve cambiare ciò che era stato mostrato.
"""

from datetime import date, datetime

import duckdb
import pytest
from starlette.testclient import TestClient

from conftest import NOSTRA_ORIGINE, campi_nascosti, conferma
from garmin_coach import athlete_files, corrections, paths
from garmin_coach.analysis import doubts
from garmin_coach.app import security, server
from garmin_coach.database import SCHEMA

IMPOSSIBILE = 10000000007
NORMALE_UNO = 900001
NORMALE_DUE = 900002

CORREZIONI_VUOTE = """# Correzioni dei dati confermate dall'atleta

## Decisioni

| Activity ID | Stato | Data attività | Ambito | Decisione e motivo | Confermata il |
|---:|---|---|---|---|---|

## Regola di applicazione

Una decisione `exclude` deve propagarsi a ogni superficie.
"""


def _inserisci(con, activity_id, giorno, distanza, durata, bracciate, nome):
    con.execute("""
        INSERT INTO activities (activity_id, start_time_utc, start_time_local,
            activity_date, sport, is_swim, environment, name, distance_m,
            duration_s, total_strokes, lap_count, device_id, source_object_id,
            imported_at)
        VALUES (?, ?, ?, ?, 'open_water_swimming', TRUE, 'open_water', ?, ?, ?,
                ?, 1, 42, 'sha', ?)
    """, [activity_id, datetime.combine(giorno, datetime.min.time()),
          datetime.combine(giorno, datetime.min.time()), giorno, nome,
          distanza, durata, bracciate, datetime(2026, 1, 1)])


@pytest.fixture
def coach_dir(tmp_path, monkeypatch):
    cartella = tmp_path / "coach"
    cartella.mkdir()
    (cartella / "correzioni-dati.md").write_text(CORREZIONI_VUOTE,
                                                 encoding="utf-8")
    monkeypatch.setattr(paths, "COACH", cartella)
    return cartella


@pytest.fixture
def percorso_database(tmp_path, monkeypatch, coach_dir):
    """Una nuotata impossibile e due normali, su disco come in uso vero."""
    percorso = tmp_path / "coach.duckdb"
    con = duckdb.connect(str(percorso))
    con.execute(SCHEMA)
    _inserisci(con, IMPOSSIBILE, date(2021, 5, 26), 700, 127.5, 29,
               "place02 Nuoto in acque libere")
    _inserisci(con, NORMALE_UNO, date(2021, 5, 26), 2505, 3750, 1261,
               "place02 Nuoto in acque libere")
    _inserisci(con, NORMALE_DUE, date(2021, 5, 29), 2055, 2730, 971,
               "place02 Nuoto in acque libere")
    corrections.flag_automatically(con)
    con.close()
    monkeypatch.setattr(paths, "DATABASE", percorso)
    return percorso


@pytest.fixture
def connection(percorso_database):
    con = duckdb.connect(str(percorso_database), read_only=True)
    yield con
    con.close()


@pytest.fixture
def client(percorso_database):
    return TestClient(server.build())


# ── 1. Il dubbio arriva con le prove per decidere ────────────────────────

class TestTheDoubtCarriesItsEvidence:
    def test_the_flagged_activity_is_listed(self, connection):
        elenco = doubts.pending(connection)

        assert [d.activity_id for d in elenco] == [IMPOSSIBILE]
        assert elenco[0].status == "review"
        assert elenco[0].decided_by == "automatic"

    def test_the_comparison_excludes_the_doubt_from_its_own_population(
            self, connection):
        """La prova non deve contenere l'accusato.

        Con 700 m in 127 s dentro la popolazione, l'intervallo del passo
        arriverebbe fino a 18 s/100 m e conterrebbe il valore da smascherare.
        """
        dubbio = doubts.pending(connection)[0]
        passo = next(c for c in dubbio.against if c.what == "passo medio")

        assert "0:18" in passo.here
        assert "0:18" not in passo.range, (
            f"l'intervallo di confronto contiene il valore anomalo: {passo.range}")
        assert "2 tue nuotate" in passo.population

    def test_it_says_what_else_happened_that_day(self, connection):
        dubbio = doubts.pending(connection)[0]

        assert any("2.505 m" in riga for riga in dubbio.same_day), dubbio.same_day

    def test_it_says_how_much_the_decision_weighs(self, connection):
        dubbio = doubts.pending(connection)[0]

        assert "700 m" in dubbio.weight and "2021" in dubbio.weight

    def test_it_asks_a_question_instead_of_stating_a_correct_distance(
            self, connection):
        """Non deve mai comparire una distanza «giusta» inventata da noi.

        I numeri vicini suggeriscono 70 m, ed è esattamente ciò che il progetto
        ha deciso di non scrivere: sarebbe una seconda invenzione, con
        l'aggravante di sembrare misurata.
        """
        dubbio = doubts.pending(connection)[0]

        assert dubbio.question.endswith("?")
        assert "70 m" not in dubbio.question


# ── 2. Chi scrive e chi legge parlano la stessa lingua ───────────────────

class TestWhatIsWrittenCanBeReadBack:
    def test_a_written_decision_is_read_back_by_corrections(self, coach_dir):
        decisione = athlete_files.validate_correction(
            activity_id=str(IMPOSSIBILE), status="exclude", day="2021-05-26",
            reason="Due minuti in acqua, non 700 m. Ricordo solo la nuotata lunga.")

        athlete_files.add_correction(decisione)
        rilette = corrections.declared()

        assert len(rilette) == 1
        assert rilette[0].activity_id == IMPOSSIBILE
        assert rilette[0].status == "exclude"
        assert rilette[0].confirmed_on == date.today()
        assert "700 m" in rilette[0].reason

    def test_the_previous_decision_is_kept_above_nothing(self, coach_dir):
        """Cambiare idea non cancella la prima decisione: la mette sotto."""
        for motivo in ("Prima idea: non contarla.", "Ripensandoci: era vera."):
            stato = "exclude" if "Prima" in motivo else "keep"
            athlete_files.add_correction(athlete_files.validate_correction(
                activity_id=str(IMPOSSIBILE), status=stato,
                day="2021-05-26", reason=motivo))

        testo = (coach_dir / "correzioni-dati.md").read_text(encoding="utf-8")
        assert "Prima idea" in testo and "Ripensandoci" in testo
        assert corrections.declared()[0].status == "keep", (
            "l'ultima parola deve essere la prima riga")


class TestWhatCannotBeWrittenFromHere:
    def test_correct_needs_the_real_values_and_stays_manual(self):
        with pytest.raises(athlete_files.InvalidReference) as rifiuto:
            athlete_files.validate_correction(
                activity_id="1", status="correct", day="2021-05-26",
                reason="erano settanta metri")
        assert "correct" in str(rifiuto.value)

    def test_a_decision_without_a_reason_is_refused(self):
        with pytest.raises(athlete_files.InvalidReference):
            athlete_files.validate_correction(
                activity_id="1", status="exclude", day="2021-05-26", reason="no")

    def test_an_unknown_status_is_refused(self):
        with pytest.raises(athlete_files.InvalidReference):
            athlete_files.validate_correction(
                activity_id="1", status="cancella", day="2021-05-26",
                reason="un motivo abbastanza lungo")


# ── 3. La pagina, e la conferma che resta vincolante ─────────────────────

class TestThePageAndItsWriteFlow:
    def test_the_area_appears_only_when_something_is_pending(self, client):
        assert "Da decidere (1)" in client.get("/").text

    def test_the_page_shows_the_doubt_and_offers_the_three_answers(self, client):
        corpo = client.get("/da-decidere").text

        assert "26/05/2021" in corpo
        assert 'value="exclude"' in corpo
        assert 'value="keep"' in corpo
        assert 'value="review"' in corpo

    def test_the_preview_shows_the_line_before_writing_it(self, client,
                                                          coach_dir):
        anteprima = client.post("/da-decidere/decisione", data={
            security.FIELD: security.TOKEN, "activity_id": str(IMPOSSIBILE),
            "status": "exclude", "day": "2021-05-26",
            "reason": "Due minuti in acqua, non settecento metri."},
            headers=NOSTRA_ORIGINE)

        assert anteprima.status_code == 200
        assert "esclusa da ogni metrica" in anteprima.text
        assert "| `exclude` |" not in (
            coach_dir / "correzioni-dati.md").read_text(encoding="utf-8"), (
            "l'anteprima ha già scritto: non era un'anteprima")

    def test_the_confirmation_writes_what_was_shown(self, client, coach_dir):
        anteprima = client.post("/da-decidere/decisione", data={
            security.FIELD: security.TOKEN, "activity_id": str(IMPOSSIBILE),
            "status": "exclude", "day": "2021-05-26",
            "reason": "Due minuti in acqua, non settecento metri."},
            headers=NOSTRA_ORIGINE)

        risposta = conferma(client, "/da-decidere/decisione/conferma", anteprima)

        assert risposta.status_code == 200
        assert corrections.declared()[0].status == "exclude"

    def test_tampering_the_status_at_confirmation_changes_nothing(
            self, client, coach_dir):
        """I campi non viaggiano più alla conferma: viaggia il gettone.

        Questo test rifarebbe rosso il rilievo A0.6 se qualcuno rimettesse i
        valori dell'atleta dentro il modulo di conferma.
        """
        anteprima = client.post("/da-decidere/decisione", data={
            security.FIELD: security.TOKEN, "activity_id": str(IMPOSSIBILE),
            "status": "keep", "day": "2021-05-26",
            "reason": "Era vera, me la ricordo."}, headers=NOSTRA_ORIGINE)

        conferma(client, "/da-decidere/decisione/conferma", anteprima,
                 status="exclude", activity_id=str(NORMALE_UNO))

        scritte = corrections.declared()
        assert len(scritte) == 1
        assert scritte[0].status == "keep"
        assert scritte[0].activity_id == IMPOSSIBILE

    def test_a_decision_about_an_unknown_activity_is_not_written(self, client,
                                                                 coach_dir):
        risposta = client.post("/da-decidere/decisione", data={
            security.FIELD: security.TOKEN, "activity_id": "1234567890",
            "status": "exclude", "day": "2021-05-26",
            "reason": "una decisione su una seduta che non esiste"},
            headers=NOSTRA_ORIGINE)

        assert "non viene scritta" in risposta.text
        assert corrections.declared() == []

    def test_the_hidden_fields_do_not_carry_the_athlete_values(self, client):
        anteprima = client.post("/da-decidere/decisione", data={
            security.FIELD: security.TOKEN, "activity_id": str(IMPOSSIBILE),
            "status": "exclude", "day": "2021-05-26",
            "reason": "Due minuti in acqua, non settecento metri."},
            headers=NOSTRA_ORIGINE)

        nascosti = campi_nascosti(anteprima)
        assert "status" not in nascosti and "reason" not in nascosti
