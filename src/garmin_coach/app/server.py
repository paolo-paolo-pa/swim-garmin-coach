"""L'applicazione web locale: ascolta solo su 127.0.0.1 e non esce mai di lì.

## Che cosa questo server non è

Non è un servizio. Non ha account, non ha sessioni, non ha telemetria, non
chiama nessuno. Gira quando l'atleta apre il collegamento e smette quando chiude
la finestra del terminale.

## Perché Starlette e non FastAPI

Deciso nel secondo audit (§4): `starlette` e `uvicorn` sono già installati come
dipendenze di `mcp`, mentre `fastapi` e `jinja2` no. FastAPI serve a esporre una
API JSON con modelli di richiesta e documentazione automatica — questa app rende
HTML dal server e non ha una API pubblica. Due pacchetti in più per un problema
che non c'è.

## Perché il database si apre in sola lettura a ogni richiesta

DuckDB accetta un solo scrittore. Se l'app tenesse il file aperto in scrittura,
il sync automatico delle 10:48 fallirebbe con un errore illeggibile — è già
successo in questo progetto, col server MCP. In sola lettura convivono, e se
proprio il file è occupato da una ricostruzione la pagina lo dice in italiano
invece di rompersi.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse
from starlette.routing import Route

from .. import athlete_files, coach, paths
from ..analysis import doubts as doubts_analysis
from ..analysis import race_history as race_history_analysis
from ..analysis import planned_vs_done
from ..analysis import pool_effort, session_structure
from ..analysis import week_proposal
from ..analysis import progress as progress_analysis
from ..analysis import questions as questions_analysis
from ..analysis import races as races_analysis
from ..analysis import sessions as sessions_analysis
from ..analysis import today as today_analysis
from . import confirmation, pages, security
from .html import Raw, document

# L'unico indirizzo su cui questo server deve mai comparire. Non è una
# configurazione: è un vincolo di sicurezza del §10 della Macro-proposta 4.
HOST = "127.0.0.1"
PORT = 8765

STYLE = (Path(__file__).resolve().parent / "style.css").read_text(encoding="utf-8")


def _read_only():
    """Una connessione di sola lettura al database corrente."""
    return duckdb.connect(str(paths.DATABASE), read_only=True)


def _page(title: str, body: Raw, active: str, status: int = 200,
          script: str = "") -> HTMLResponse:
    return HTMLResponse(
        document(title, body, active=active, style=STYLE, script=script,
                 extra_areas=_area_da_decidere()),
        status_code=status)


def _area_da_decidere() -> tuple:
    """L'area «Da decidere», e il numero di cose che aspettano.

    Compare solo se c'è qualcosa. È la sola frizione che separava una
    segnalazione dalla sua decisione: prima il dubbio esisteva soltanto in tre
    righe stampate durante un import, e per rispondere bisognava sapere che
    esisteva un file markdown e come si compila.

    Se il database è occupato l'area non compare, e va bene così: è una
    scorciatoia, non un'informazione. Farla fallire fermerebbe la pagina che
    l'atleta stava aprendo.
    """
    try:
        with _read_only() as connection:
            quanti = connection.execute(
                "SELECT count(*) FROM activity_quality WHERE status = 'review'"
            ).fetchone()[0]
    except (duckdb.Error, OSError):
        return ()
    return (("/da-decidere", f"Da decidere ({quanti})"),) if quanti else ()


def _unavailable(error: Exception) -> HTMLResponse:
    """Il database non si è potuto leggere. Succede, e si dice come stanno le cose."""
    testo = str(error).lower()
    # Le frasi con cui DuckDB dice «c'e gia qualcuno che scrive». Sono tre
    # perche dipendono da come e stato aperto il file, e quella che si incontra
    # davvero durante un sync e la terza: «different configuration than
    # existing connections», che non contiene la parola lock.
    occupato = ("lock" in testo
                or "being used" in testo
                or "different configuration" in testo)
    if occupato:
        body = pages.errore(
            "Il database è occupato",
            "Un'altra operazione lo sta riscrivendo in questo momento — di "
            "solito è il sync automatico, che dura meno di un minuto.",
            "Ricarica la pagina fra poco.")
    elif not paths.DATABASE.exists():
        body = pages.errore(
            "Il database non esiste ancora",
            "Non è mai stato costruito su questo computer, oppure è stato "
            "cancellato.",
            "Si ricostruisce dalle sorgenti locali, senza rete, con: "
            "garmin_coach rebuild")
    else:
        body = pages.errore(
            "Non sono riuscito a leggere i dati",
            "Il database c'è ma non risponde come dovrebbe. Il dettaglio "
            "tecnico resta sul computer e non compare qui.",
            "Prova con: garmin_coach verify")
    return _page("Problema", body, active="/", status=503)


async def oggi(request: Request) -> HTMLResponse:
    """«Qual è la priorità adesso, e cosa faccio?»

    Non più «c'è qualcosa che merita attenzione»: quella domanda produceva un
    pannello di valori, e un pannello lascia all'atleta il lavoro di capire cosa
    guardare — cioè il lavoro che questo progetto esiste per fare.

    Funziona senza rete e senza modello. Il cervello locale produce un giudizio
    deterministico dagli stessi fatti e dichiara di essere locale: una dashboard
    che senza rete mostra una pagina vuota non si può usare in viaggio.
    """
    try:
        with _read_only() as connection:
            packet = coach.build(
                connection, "Qual è la priorità di allenamento adesso?")
            response = _brain().judge(packet)
    except (duckdb.Error, OSError) as error:
        return _unavailable(error)
    except coach.InvalidResponse as rifiutata:
        # Una risposta che non rispetta il contratto non si mostra corretta:
        # si dice che è stata rifiutata, altrimenti il difetto sparisce.
        return _page("Oggi", pages.errore(
            "Il coach non ha prodotto una risposta valida",
            str(rifiutata),
            "I dati non sono stati toccati. Le altre aree funzionano."),
            active="/", status=503)
    return _page("Oggi", pages.coach_oggi(packet.as_dict(), response.as_dict()),
                 active="/")


def _brain(with_claude: bool = False):
    """Chi giudica, e perché la scelta è per domanda e non una configurazione.

    La homepage risponde **sempre** in locale: si apre da sola ogni mattina, e
    far uscire il pacchetto a ogni apertura sarebbe una spedizione che nessuno
    ha chiesto. Su «Chiedi» decide l'atleta, premendo — e il pulsante è la
    richiesta esplicita che la regola di sicurezza pretende.
    """
    return coach.ClaudeCodeBrain() if with_claude else coach.LocalBrain()


async def osservazione_grezza(request: Request) -> HTMLResponse:
    """La vecchia pagina Oggi, che descrive senza decidere.

    Resta raggiungibile perché serve ancora a una cosa diversa: controllare i
    numeri di un giorno. Non è più la homepage perché non era una risposta.
    """
    try:
        with _read_only() as connection:
            packet = today_analysis.observation(connection).as_dict()
    except (duckdb.Error, OSError) as error:
        return _unavailable(error)
    return _page("Osservazione", pages.oggi(packet), active="/")


# Quello che il coach non sa della settimana, e che non inventa.
#
# L'incarico chiede piano contro eseguito. Il piano non esiste nel sistema: lo
# fa l'allenatore umano, altrove. Inventarlo dai dati e poi confrontarci
# l'eseguito sarebbe la forma piu' elegante di autoinganno — si confronterebbe
# l'atleta con se' stesso e si chiamerebbe aderenza.
PIANO_MANCANTE = (
    "Che cosa avevi in programma. Il piano lo fa il tuo allenatore e questo "
    "sistema non lo conosce, quindi qui trovi l'eseguito e non l'aderenza: "
    "senza il previsto, «hai fatto meno» e «hai fatto quello che dovevi» sono "
    "la stessa riga di numeri. **Da adesso puoi scriverlo tu**, in "
    "coach/programma-settimanale.md: bastano data, metri e una parola "
    "sull'intento.")


async def settimana(request: Request) -> HTMLResponse:
    """«Questa settimana e' andata come doveva?» — meta' della risposta."""
    from datetime import date as _date

    from ..analysis import week as week_analysis

    try:
        with _read_only() as connection:
            oggi_ = _date.today()
            corrente = week_analysis.of_week(connection, oggi_)
            precedenti = week_analysis.recent(connection, oggi_, weeks=4)[1:]
            piano = planned_vs_done.summary(connection, weeks=1, today=oggi_)
            # La proposta compare solo se il programma vero non c'è: quando
            # l'allenatore ha scritto la settimana, una seconda versione
            # accanto è rumore, non una scelta.
            proposta = ({} if piano["available"]
                        else week_proposal.as_page_dict(connection, oggi_))
    except (duckdb.Error, OSError) as error:
        return _unavailable(error)
    return _page("Settimana",
                 pages.settimana(corrente.as_dict(),
                                 [s.as_dict() for s in precedenti],
                                 PIANO_MANCANTE, piano, proposta),
                 active="/settimana")


async def sedute(request: Request) -> HTMLResponse:
    """L'elenco delle sedute, con la profondita del dato subito visibile."""
    try:
        with _read_only() as connection:
            elenco = sessions_analysis.listing(connection)
    except (duckdb.Error, OSError) as error:
        return _unavailable(error)
    return _page("Sedute", pages.sedute(elenco), active="/sedute")


async def _pagina_seduta(activity_id: int, errore: str = "",
                         valori: dict | None = None,
                         scritto: str = "") -> HTMLResponse:
    """La pagina di una seduta. La usano l'apertura e le due route di scrittura."""
    try:
        with _read_only() as connection:
            packet = sessions_analysis.detail(connection, activity_id).as_dict()
            struttura = session_structure.as_page_dict(connection, activity_id)
            prove = pool_effort.as_page_dict(connection, activity_id)
    except (duckdb.Error, OSError) as error:
        return _unavailable(error)

    # Una seduta che esiste porta sempre se stessa fra i collegamenti: e
    # l'invariante che distingue «non trovata» da «trovata e senza dettaglio»,
    # e non dipende dal testo di una frase.
    if not packet["links"]:
        return _page("Seduta", pages.errore(
            "Seduta non trovata",
            "Nessuna attivita con questo identificativo nell'archivio.",
            "Torna all'elenco delle sedute."), active="/sedute", status=404)

    giorno = packet["links"][0]["date"]
    modulo = pages.modulo_nota(security.TOKEN, activity_id, giorno,
                               valori or {}, _opzioni_nota(), errore)
    return _page("Seduta",
                 pages.seduta(packet, modulo,
                              athlete_files.session_notes(activity_id), scritto,
                              struttura, prove),
                 active="/sedute", status=400 if errore else 200)


async def seduta(request: Request) -> HTMLResponse:
    """Una seduta sola: cosa e successo dentro."""
    return await _pagina_seduta(request.path_params["activity_id"])


async def progressi(request: Request) -> HTMLResponse:
    """«Quando mi sono trovato in una situazione simile, cosa e successo?»"""
    try:
        with _read_only() as connection:
            packet = progress_analysis.observation(connection).as_dict()
    except (duckdb.Error, OSError) as error:
        return _unavailable(error)
    return _page("Progressi", pages.progressi(packet), active="/progressi")


# ── Gare: le uniche route che scrivono ───────────────────────────────────

# Le scelte dei menu vengono dal modulo che valida, non da un elenco copiato
# qui: due elenchi divergono, e il secondo diventa quello sbagliato.
def _opzioni() -> dict:
    return {
        "distance_m": athlete_files.KNOWN_DISTANCES,
        "stroke": athlete_files.KNOWN_STROKES,
        "pool": athlete_files.KNOWN_POOLS,
        "kind": athlete_files.KNOWN_KINDS,
    }


def _campi(form) -> dict:
    return {nome: str(form.get(nome, "")).strip()
            for nome, _e, _t, _o in pages.CAMPI_RIFERIMENTO}


def _quadro_gare(errore: str = "", valori: dict | None = None,
                 scritto: str = "") -> HTMLResponse:
    try:
        with _read_only() as connection:
            packet = races_analysis.observation(connection).as_dict()
            storico = race_history_analysis.as_page_dict(
                race_history_analysis.history(connection))
    except (duckdb.Error, OSError) as error:
        return _unavailable(error)
    return _page("Gare",
                 pages.gare(packet, security.TOKEN, _opzioni(), valori,
                            errore, scritto, storico=storico),
                 active="/gare",
                 status=400 if errore else 200)


async def gare(request: Request) -> HTMLResponse:
    return _quadro_gare()


async def riferimento_anteprima(request: Request) -> HTMLResponse:
    """Controlla il modulo e mostra cosa verra scritto. Non scrive niente."""
    form = await request.form()
    try:
        security.check(request, form)
    except security.Rejected as rifiuto:
        return _rifiuto(rifiuto)

    valori = _campi(form)
    try:
        riferimento = athlete_files.validate_reference(**valori)
    except athlete_files.InvalidReference as errore:
        return _quadro_gare(errore=str(errore), valori=valori)

    riga = {
        "Data": riferimento.day.isoformat(),
        "Prova": f"{riferimento.distance_m} m {riferimento.stroke}",
        "Vasca": riferimento.pool,
        "Tempo": athlete_files.format_swim_time(riferimento.seconds),
        "Passo per 100 m": athlete_files.format_swim_time(
            round(riferimento.pace_per_100m_s, 2)),
        "Tipo": riferimento.kind,
        "Contesto": riferimento.context or "—",
        "Seduta collegata": str(riferimento.activity_id or "—"),
        "Note": riferimento.notes or "—",
    }
    gettone = confirmation.issue("riferimento", valori)
    return _page("Conferma",
                 pages.anteprima_riferimento(security.TOKEN, gettone, riga),
                 active="/gare")


async def riferimento_conferma(request: Request) -> HTMLResponse:
    """Scrive davvero, e solo ciò che un'anteprima ha mostrato.

    Non legge i campi dal modulo: legge il gettone, e i campi li tiene il
    server. Non c'è niente da manomettere fra l'anteprima e la scrittura,
    perché fra l'anteprima e la scrittura non viaggia niente.
    """
    form = await request.form()
    try:
        security.check(request, form)
        atteso = confirmation.redeem("riferimento",
                                     str(form.get(confirmation.FIELD, "")))
    except (security.Rejected, confirmation.Rejected) as rifiuto:
        return _rifiuto(rifiuto)
    except confirmation.AlreadyConfirmed as gia:
        # Ricaricare la pagina di conferma non scrive una seconda riga: rivede
        # l'esito della prima.
        return _quadro_gare(scritto=gia.outcome)

    valori = atteso.payload
    try:
        riferimento = athlete_files.validate_reference(**valori)
        scritto = athlete_files.add_reference(riferimento)
    except athlete_files.InvalidReference as errore:
        return _quadro_gare(errore=str(errore), valori=valori)
    except OSError:
        return _quadro_gare(
            errore="Non sono riuscito a scrivere il file. Controlla che "
                   "coach/riferimenti.md non sia aperto in un altro programma.",
            valori=valori)
    confirmation.remember(str(form.get(confirmation.FIELD, "")), scritto)
    return _quadro_gare(scritto=scritto)


async def chiedi(request: Request) -> HTMLResponse:
    """La conversazione, dentro la pagina.

    Il pulsante «Copia» non era il prodotto: chiedeva all'atleta di portare una
    domanda in un'altra applicazione e di riportare indietro la risposta a
    mente. Qui la domanda entra e la risposta compare, sulla stessa pagina.

    Oggi risponde il cervello locale e nessuna richiesta lascia il computer. Il
    giorno in cui il ponte verso Claude sarà autorizzato, cambia una funzione —
    ``_brain()`` — e questa pagina non se ne accorge.
    """
    domanda = ""
    a_claude = False
    if request.method == "POST":
        form = await request.form()
        try:
            security.check(request, form)
        except security.Rejected as rifiuto:
            return _rifiuto(rifiuto)
        # La domanda deve essere una di quelle che il coach sa affrontare.
        # Accettare testo libero qui vorrebbe dire accettare testo non fidato
        # in un campo destinato, un giorno, a un modello.
        scelta = str(form.get("domanda", ""))
        if scelta not in pages.DOMANDE_ESEGUIBILI:
            return _rifiuto(security.Rejected(
                "Questa domanda non è fra quelle che il coach sa affrontare. "
                "Scegline una dall'elenco."))
        domanda = scelta
        a_claude = str(form.get("chi", "")) == "claude"

    avviso = ""
    try:
        with _read_only() as connection:
            packet = coach.build(
                connection, domanda or "Qual è la priorità di allenamento adesso?")
            try:
                response = _brain(with_claude=a_claude).judge(packet)
            except coach.BrainUnavailable as fermo:
                # Il ripiego non è silenzioso: la pagina resta utile e dice
                # con quale voce sta parlando e cosa manca per l'altra.
                avviso = str(fermo)
                response = coach.LocalBrain().judge(packet)
    except (duckdb.Error, OSError) as error:
        return _unavailable(error)
    except coach.InvalidResponse as rifiutata:
        return _page("Chiedi", pages.errore(
            "Il coach non ha prodotto una risposta valida", str(rifiutata),
            "I dati non sono stati toccati."), active="/chiedi", status=503)

    return _page("Chiedi",
                 pages.conversazione(packet.as_dict(), response.as_dict(),
                                     domanda, security.TOKEN, avviso=avviso),
                 active="/chiedi")


def _rifiuto(rifiuto) -> HTMLResponse:
    """La stessa risposta per ogni scrittura respinta: una sola frase, in italiano."""
    return _page("Richiesta rifiutata",
                 pages.errore("Richiesta rifiutata", rifiuto.reason,
                              "Torna indietro e riprova."),
                 active="/", status=403)


def _opzioni_nota() -> dict:
    return {"purpose": athlete_files.KNOWN_PURPOSES}


def _campi_nota(form) -> dict:
    return {nome: str(form.get(nome, "")).strip()
            for nome in ("activity_id", "day", "rpe", "purpose", "feeling")}


def _seduta_esiste(activity_id: int) -> bool:
    """Se questa seduta è davvero in archivio.

    Una nota che punta a una seduta inesistente non comparirà mai nella pagina
    di quella seduta, e resterà nel diario a dire una cosa che l'archivio non
    conferma. Meglio non scriverla.
    """
    try:
        with _read_only() as connection:
            return connection.execute(
                "SELECT count(*) FROM canonical_activities WHERE activity_id = ?",
                [activity_id]).fetchone()[0] > 0
    except (duckdb.Error, OSError):
        # Se il database non si legge non si può nemmeno smentire la seduta:
        # la scrittura si ferma comunque, ma per l'altro motivo.
        return False


async def nota_anteprima(request: Request) -> HTMLResponse:
    """Controlla la nota e mostra cosa verra scritto nel diario."""
    form = await request.form()
    try:
        security.check(request, form)
    except security.Rejected as rifiuto:
        return _rifiuto(rifiuto)

    valori = _campi_nota(form)
    try:
        nota = athlete_files.validate_session_note(**valori)
    except athlete_files.InvalidReference as errore:
        return await _pagina_seduta(int(valori["activity_id"] or 0),
                                    errore=str(errore), valori=valori)

    if not _seduta_esiste(nota.activity_id):
        return _page("Seduta", pages.errore(
            "Seduta non trovata",
            f"Nessuna attivita con identificativo {nota.activity_id} "
            "nell'archivio: la nota non viene scritta.",
            "Torna all'elenco delle sedute."), active="/sedute", status=404)

    anno, settimana, _ = nota.day.isocalendar()
    gettone = confirmation.issue("nota", valori)
    return _page("Conferma",
                 pages.anteprima_nota(security.TOKEN, gettone, nota.summary,
                                      nota.activity_id,
                                      f"coach/diario/{anno}-W{settimana:02d}.md"),
                 active="/sedute")


async def nota_conferma(request: Request) -> HTMLResponse:
    """Scrive la nota nel diario della settimana, e solo quella approvata."""
    form = await request.form()
    try:
        security.check(request, form)
        atteso = confirmation.redeem("nota", str(form.get(confirmation.FIELD, "")))
    except (security.Rejected, confirmation.Rejected) as rifiuto:
        return _rifiuto(rifiuto)
    except confirmation.AlreadyConfirmed as gia:
        return await _pagina_seduta(int(_campi_nota(form)["activity_id"] or 0),
                                    scritto=gia.outcome)

    valori = atteso.payload
    try:
        nota = athlete_files.validate_session_note(**valori)
        scritto = athlete_files.add_session_note(nota)
    except athlete_files.InvalidReference as errore:
        return await _pagina_seduta(int(valori["activity_id"] or 0),
                                    errore=str(errore), valori=valori)
    except OSError:
        return await _pagina_seduta(
            nota.activity_id,
            errore="Non sono riuscito a scrivere il diario. Controlla che il "
                   "file non sia aperto in un altro programma.",
            valori=valori)
    confirmation.remember(str(form.get(confirmation.FIELD, "")), scritto)
    return await _pagina_seduta(nota.activity_id, scritto=scritto)


async def da_decidere(request: Request,
                      scritto: str = "", errore: str = "") -> HTMLResponse:
    """«Quali miei numeri non reggono, e cosa devo dire perché reggano?»"""
    try:
        with _read_only() as connection:
            dubbi = doubts_analysis.pending(connection)
            disaccordi = doubts_analysis.disagreements(connection)
    except (duckdb.Error, OSError) as error:
        return _unavailable(error)
    return _page("Da decidere",
                 pages.da_decidere(dubbi, disaccordi, security.TOKEN,
                                   scritto=scritto, errore=errore),
                 active="/da-decidere")


def _campi_decisione(form) -> dict:
    return {nome: str(form.get(nome, "")).strip()
            for nome in ("activity_id", "status", "day", "reason")}


async def decisione_anteprima(request: Request) -> HTMLResponse:
    """Mostra la riga esatta prima di scriverla nel file dell'atleta."""
    form = await request.form()
    try:
        security.check(request, form)
    except security.Rejected as rifiuto:
        return _rifiuto(rifiuto)

    valori = _campi_decisione(form)
    try:
        decisione = athlete_files.validate_correction(**valori)
    except athlete_files.InvalidReference as errore:
        return await da_decidere(request, errore=str(errore))

    if not _seduta_esiste(decisione.activity_id):
        return await da_decidere(request, errore=(
            f"Nessuna attività {decisione.activity_id} nell'archivio: la "
            "decisione non viene scritta."))

    gettone = confirmation.issue("decisione", valori)
    return _page("Conferma",
                 pages.anteprima_decisione(
                     security.TOKEN, gettone, decisione.summary,
                     f"coach/{athlete_files.CORRECTIONS_FILE}"),
                 active="/da-decidere")


async def decisione_conferma(request: Request) -> HTMLResponse:
    """Scrive la decisione, e solo quella che è stata mostrata."""
    form = await request.form()
    try:
        security.check(request, form)
        atteso = confirmation.redeem("decisione",
                                     str(form.get(confirmation.FIELD, "")))
    except (security.Rejected, confirmation.Rejected) as rifiuto:
        return _rifiuto(rifiuto)
    except confirmation.AlreadyConfirmed as gia:
        return await da_decidere(request, scritto=gia.outcome)

    try:
        decisione = athlete_files.validate_correction(**atteso.payload)
        scritto = athlete_files.add_correction(decisione)
    except athlete_files.InvalidReference as errore:
        return await da_decidere(request, errore=str(errore))
    except OSError:
        return await da_decidere(request, errore=(
            "Non sono riuscito a scrivere il file delle correzioni. Controlla "
            "che non sia aperto in un altro programma."))
    confirmation.remember(str(form.get(confirmation.FIELD, "")), scritto)
    return await da_decidere(request, scritto=scritto)


async def in_costruzione(request: Request) -> HTMLResponse:
    """Le aree non ancora costruite lo dicono, invece di dare pagina bianca."""
    quale = request.url.path.strip("/") or "questa"
    body = pages.errore(
        quale.capitalize(),
        "Quest'area non è ancora costruita.",
        "Oggi funziona. Le altre arrivano nelle fasi successive.")
    return _page(quale.capitalize(), body, active=f"/{quale}", status=404)


def build() -> Starlette:
    return Starlette(routes=[
        Route("/", oggi),
        Route("/osservazione", osservazione_grezza),
        Route("/settimana", settimana),
        Route("/sedute", sedute),
        Route("/sedute/nota", nota_anteprima, methods=["POST"]),
        Route("/sedute/nota/conferma", nota_conferma, methods=["POST"]),
        Route("/sedute/{activity_id:int}", seduta),
        Route("/progressi", progressi),
        Route("/gare", gare),
        Route("/gare/riferimenti", riferimento_anteprima, methods=["POST"]),
        Route("/gare/riferimenti/conferma", riferimento_conferma, methods=["POST"]),
        Route("/chiedi", chiedi, methods=["GET", "POST"]),
        Route("/da-decidere", da_decidere),
        Route("/da-decidere/decisione", decisione_anteprima,
              methods=["POST"]),
        Route("/da-decidere/decisione/conferma", decisione_conferma,
              methods=["POST"]),
    ])


app = build()
from .platform import install as install_platform
install_platform(app)


def serve(port: int = PORT, open_browser: bool = True) -> None:
    """Avvia il server e apre il browser. È ciò che fa il doppio clic."""
    import threading
    import webbrowser

    import uvicorn

    indirizzo = f"http://{HOST}:{port}/"
    # Il doppio clic deve riaprire la stessa app se è già stata avviata.
    from ..launcher import existing_dashboard
    if existing_dashboard(port):
        if open_browser:
            webbrowser.open(indirizzo)
        print(f"Garmin Coach è già aperto su {indirizzo}")
        return
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(indirizzo)).start()
    print(f"Garmin Coach è aperto su {indirizzo}")
    print("Per chiuderlo: Ctrl+C in questa finestra.")
    uvicorn.run(app, host=HOST, port=port, log_level="warning")
