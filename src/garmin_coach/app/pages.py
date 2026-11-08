"""Le pagine: dispongono, non calcolano.

Ogni funzione qui riceve un ``InsightPacket`` già completo — testi formattati
compresi — e decide soltanto dove mettere le cose. Nessuna divisione, nessuna
soglia, nessun confronto numerico: quelli stanno in ``analysis/`` e il test
``test_app_computes_nothing`` fallisce se rientrano da qui.

## L'ordine è l'argomento

La pagina Oggi mette in cima la freschezza e poi **una sola** osservazione. È
l'unica differenza di sostanza rispetto a un pannello di grafici: un pannello
lascia all'atleta il lavoro di capire cosa guardare, e quel lavoro è
esattamente ciò che non sa fare da solo alle sette del mattino.

Le prove vengono dopo l'osservazione, i contrari subito accanto, i limiti in
fondo e il metodo dentro un ``Perché?`` che si apre. Chi si fida legge tre
righe; chi vuole controllare arriva fino alla formula e alla versione.
"""

from __future__ import annotations

from . import confirmation, security
from .html import (Raw, a, article, button, details, div, form, h1, h2, h3,
                   input_, join, label, li, main, option, p, section, select,
                   span, strong, summary, tag, textarea, ul)

# Le classi CSS che corrispondono ai tre stati. In un dizionario e non in un
# `if` sparso, così aggiungerne uno quarto richiede di passare da qui.
CLASSE_STATO = {
    "informative": "informativo",
    "watch": "da-osservare",
    "insufficient_data": "dati-insufficienti",
}


def _freschezza(packet: dict) -> Raw:
    state = packet.get("freshness")
    if not state:
        return Raw("")
    classe = "freschezza vecchia" if state["is_stale"] else "freschezza"
    return p(state["display"], class_=classe)


def _osservazione(packet: dict) -> Raw:
    return article(
        p(packet["question"], class_="domanda"),
        p(packet["observation"], class_="testo"),
        span(packet["status_it"], class_="etichetta-stato"),
        class_=f"osservazione {CLASSE_STATO.get(packet['status'], '')}")


def _prova(entry: dict) -> Raw:
    """Una riga di evidenza: nome, valore, e il contesto che lo rende leggibile."""
    assente = entry.get("availability") != "available"
    pezzi = [
        span(entry.get("label", entry.get("field")), class_="nome"),
        span(entry.get("display", "—"),
             class_="valore fuori" if entry.get("position") in ("sotto", "sopra")
             else "valore"),
    ]
    banda = entry.get("personal_band")
    if banda:
        pezzi.append(span(banda["display"], class_="fascia"))
    note = entry.get("notes") or []
    # Quando c'è una spiegazione specifica, la categoria generica dell'assenza
    # non aggiunge niente: «la sorgente non lo contiene» e «l'orologio non ha
    # registrato questo valore per il giorno» sono la stessa frase due volte.
    if assente and not note:
        pezzi.append(span(entry.get("why", ""), class_="contesto"))
    for nota in note:
        pezzi.append(span(nota, class_="contesto"))
    return li(join(pezzi), class_="prova assente" if assente else "prova")


def _elenco_prove(voci: list[dict]) -> Raw:
    return ul(join(_prova(entry) for entry in voci), class_="prove")


def _scheda_metrica(entry: dict) -> Raw:
    """Da dove viene un numero: sorgente, formula, unità, versione del metodo.

    È la risposta al «Perché?». Senza la versione, un valore calcolato con la
    formula di sei mesi fa sembra confrontabile con uno di oggi.
    """
    righe = [
        ("sorgente", entry.get("source")),
        ("come si calcola", entry.get("formula")),
        ("unità", entry.get("unit") or "adimensionale"),
        ("natura del dato", entry.get("data_class")),
        ("versione del metodo", entry.get("method_version")),
        ("grado di evidenza", entry.get("evidence_grade")),
    ]
    if entry.get("n") is not None:
        righe.append(("casi considerati", entry.get("coverage_display") or entry["n"]))
    if entry.get("caveat"):
        righe.append(("da sapere", entry["caveat"]))
    return div(
        strong(entry.get("label", entry.get("field"))),
        Raw("".join(
            f"<dt>{title}</dt><dd>{_testo(value)}</dd>"
            for title, value in righe if value not in (None, ""))),
        class_="scheda-metrica")


def _testo(value: object) -> str:
    from .html import escape
    return str(escape(value))


def _perche(voci: list[dict]) -> Raw:
    if not voci:
        return Raw("")
    return details(
        summary("Perché?"),
        Raw("<dl>" + "".join(_scheda_metrica(entry) for entry in voci) + "</dl>"),
        class_="perche")


def _sedute(links: list[dict]) -> Raw:
    if not links:
        return Raw("")
    return section(
        h2("Ultime sedute"),
        ul(join(
            li(a(div(link["display"]),
                 div(link.get("name") or "", class_="nome-seduta")
                 if link.get("name") else Raw(""),
                 href=f"/sedute/{link['activity_id']}"))
            for link in links), class_="sedute"))


def oggi(packet: dict) -> Raw:
    """La pagina Oggi. In dieci secondi: quanto sono freschi i dati, e cosa guardare."""
    parti = [_freschezza(packet), _osservazione(packet)]

    if packet.get("evidence"):
        parti.append(section(h2("Su cosa si basa"), _elenco_prove(packet["evidence"])))
    if packet.get("counter_evidence"):
        parti.append(section(h2("Cosa non concorda"),
                             _elenco_prove(packet["counter_evidence"])))
    if packet.get("limitations"):
        parti.append(section(
            h2("Limiti"),
            ul(join(li(testo) for testo in packet["limitations"]), class_="limiti")))
    if packet.get("next_question"):
        parti.append(p(packet["next_question"], class_="prossima"))

    parti.append(_perche(packet.get("evidence", [])))
    parti.append(_sedute(packet.get("links", [])))
    return main(h1("Oggi"), join(parti))


def errore(titolo: str, spiegazione: str, rimedio: str = "") -> Raw:
    """Un guasto detto in italiano, non un codice.

    Le tre cose che si rompono davvero — database occupato, dati vecchi, sync
    fallito — sono situazioni normali di un programma che gira sul portatile di
    una persona, non eccezioni da mostrare con uno stack trace.
    """
    return main(
        h1(titolo),
        article(p(spiegazione, class_="testo"), class_="osservazione dati-insufficienti"),
        p(rimedio, class_="prossima") if rimedio else Raw(""))


# ── Sedute ───────────────────────────────────────────────────────────────

def _riga_seduta(voce: dict) -> Raw:
    """Una riga dell'elenco.

    La cosa che conta non e la distanza, che si vede ovunque: e **quanto in
    profondita si puo guardare**. Saperlo prima di aprire evita un giro a vuoto.
    """
    return li(a(
        div(voce["display"]),
        div(voce.get("name") or "", class_="nome-seduta") if voce.get("name") else Raw(""),
        div(voce["detail_display"],
            class_="dettaglio" if voce["detail_level"] == "laps" else "dettaglio assente"),
        href=f"/sedute/{voce['activity_id']}"))


def sedute(elenco: list[dict]) -> Raw:
    """L'elenco delle sedute."""
    if not elenco:
        return main(h1("Sedute"),
                    p("Non ci sono ancora sedute nell'archivio.", class_="prossima"))
    return main(
        h1("Sedute"),
        ul(join(_riga_seduta(voce) for voce in elenco), class_="sedute"))


def _gruppo(confronto: dict) -> Raw:
    """Un gruppo di ripetute confrontabili. Non si chiama serie, e con ragione."""
    if "repeats" not in confronto:
        # E il confronto con la storia personale, non un gruppo di questa seduta.
        return li(
            span(confronto["label"], class_="nome"),
            span(confronto["median_pace_display"], class_="valore"),
            span(f"su {confronto['sessions']} sedute omogenee", class_="contesto"),
            span(confronto["note"], class_="contesto"),
            class_="prova")
    return li(
        span(confronto["label"], class_="nome"),
        span(confronto["median_pace_display"], class_="valore"),
        span(f"da {confronto['range_display']}", class_="fascia"),
        span(f"raggruppamento {confronto['recognition']}",
             class_="riconoscimento", data_stato=confronto["recognition"]),
        class_="prova")


def _serie(voce: dict) -> Raw:
    return li(
        span(voce["label"], class_="nome"),
        span(voce["held"], class_="valore"),
        span(f"{voce['total_m']} m · {voce['pace']} · migliore {voce['best']} · "
             f"scarto {voce['spread']} · rec {voce['rest']}", class_="contesto"),
        class_="prova")


def _blocco(voce: dict) -> Raw:
    return section(
        h3(f"{voce['name']} — {voce['total_m']} m"),
        p(f"attribuzione {voce['confidence']}", class_="nota"),
        ul(join(_serie(s) for s in voce["sets"]), class_="prove"))


def _struttura(struttura: dict) -> Raw:
    """Come si divide la seduta. Dichiara sempre quanto è solida la divisione."""
    if not struttura:
        return Raw("")
    if not struttura.get("available"):
        parti = [h2("Com'era fatta la seduta"),
                 p(struttura["why"], class_="nota")]
        if struttura.get("sets"):
            parti.append(ul(join(_serie(s) for s in struttura["sets"]),
                            class_="prove"))
        return section(join(parti))
    return section(
        h2("Com'era fatta la seduta"),
        p("Le ripetute si leggono dai lap. La divisione in parti è inferita "
          "dalla struttura che hai dichiarato, e ogni blocco dice quanto è "
          "solida.", class_="nota"),
        join(_blocco(b) for b in struttura["blocks"]))


def _prova_vasca(voce: dict) -> Raw:
    return li(
        span(voce["label"], class_="nome"),
        span(voce["verdict"], class_="valore"),
        span(f"{voce['pace']} · {voce['explanation']}", class_="contesto"),
        class_="prova")


def _prove_vasca(prove: dict) -> Raw:
    """Cosa è successo dentro i tratti lunghi, vasca per vasca.

    Non mostra le singole vasche: sono decine, e un elenco di decine di righe
    è un muro di numeri, non un'osservazione. La frase contiene già la
    conclusione e i numeri che la giustificano; il dettaglio resta nel
    contratto per chi lo interroga.
    """
    if not prove:
        return Raw("")
    if not prove.get("available"):
        return Raw("")
    return section(
        h2("Cosa è ceduto, dentro i tratti lunghi"),
        p("Vasca per vasca. La velocità è ampiezza per frequenza — è "
          "un'identità, non un modello — quindi quando il passo cambia si può "
          "dire di cosa. La soglia si adatta a quanto è regolare la prova.",
          class_="nota"),
        ul(join(_prova_vasca(una) for una in prove["efforts"]), class_="prove"))


def seduta(packet: dict, modulo: Raw = Raw(""), note: list[str] = (),
           scritto: str = "", struttura: dict | None = None,
           prove: dict | None = None) -> Raw:
    """Il dettaglio di una seduta."""
    parti = [_freschezza(packet), _osservazione(packet)]
    if scritto:
        parti.append(p(f"Scritto in {scritto}.", class_="riuscito"))

    parti.append(_struttura(struttura or {}))
    parti.append(_prove_vasca(prove or {}))

    if packet.get("comparisons"):
        parti.append(section(
            h2("Ripetute confrontabili"),
            p("Sono lap raggruppati per stile e distanza. Un lap e un fatto; "
              "«8×100» sarebbe un'interpretazione.", class_="nota"),
            ul(join(_gruppo(c) for c in packet["comparisons"]), class_="prove")))

    if packet.get("evidence"):
        parti.append(section(h2("I totali"), _elenco_prove(packet["evidence"])))
    if packet.get("limitations"):
        parti.append(section(
            h2("Limiti"),
            ul(join(li(testo) for testo in packet["limitations"]), class_="limiti")))
    if packet.get("next_question"):
        parti.append(p(packet["next_question"], class_="prossima"))

    if note:
        parti.append(section(
            h2("Quello che hai gia scritto"),
            ul(join(li(testo) for testo in note), class_="limiti")))
    parti.append(modulo)

    parti.append(_perche(packet.get("evidence", [])))
    parti.append(p(a("Tutte le sedute", href="/sedute"), class_="ritorno"))
    return main(h1("Seduta"), join(parti))


# ── Progressi ────────────────────────────────────────────────────────────

def _grafico(grafico) -> Raw:
    """Le barre, gia calcolate da analysis/chart.py.

    L'SVG e testo: nessuna libreria, nessun CDN, e il grafico resta leggibile
    anche da un lettore di schermo grazie al titolo di ogni barra.
    """
    if grafico is None or grafico.is_empty:
        return Raw("")
    barre = "".join(
        tag("g",
            tag("rect", x=b.x, y=b.y, width=b.larghezza, height=b.altezza,
                class_="barra evidenziata" if b.evidenziata else "barra"),
            tag("title", b.titolo))
        for b in grafico.barre)
    return section(
        h2("Volume settimanale"),
        Raw(tag("svg", Raw(barre),
                viewBox=f"0 0 {grafico.larghezza} {grafico.altezza}",
                class_="grafico", role="img",
                aria_label=grafico.descrizione)),
        p(grafico.descrizione, class_="nota"))


def _asse_risposta(asse: dict) -> Raw:
    """Un asse della risposta: la parola, la misura, la copertura, i distinguo."""
    if not asse["available"]:
        return li(span(asse["name"], class_="nome"),
                  span("non misurabile", class_="valore"),
                  span(asse["why_missing"], class_="contesto"),
                  class_="prova assente")
    pezzi = [span(asse["name"], class_="nome"),
             span(asse["direction"], class_="valore"),
             span(f"{asse['display']} — {asse['coverage']}", class_="contesto")]
    if asse["details"]:
        pezzi.append(details(
            summary("Come e' stata misurata"),
            ul(join(li(riga) for riga in asse["details"]), class_="limiti"),
            class_="perche"))
    return li(join(pezzi), class_="prova")


def _caso_storico(caso: dict) -> Raw:
    """Un blocco storico simile: come avevi risposto, e poi cosa avevi fatto.

    L'ordine e' l'argomento. Prima la risposta del corpo, che e' cio' che
    l'atleta stava cercando; poi il volume delle settimane dopo, che e' una
    scelta sua e non un effetto del blocco. Nella versione precedente c'era solo
    il secondo, e stava al posto del primo.
    """
    parti = [
        div(strong(caso["display"]),
            span(f" · {caso['km_per_week_display']} a settimana", class_="valore")),
        div(caso["note"], class_="contesto"),
    ]
    if caso.get("response"):
        parti.append(p(caso.get("response_summary", ""), class_="domanda"))
        parti.append(ul(join(_asse_risposta(a) for a in caso["response"]),
                        class_="prove"))
    parti.append(ul(join(li(esito["display"])
                         for esito in caso.get("what_you_did_after", [])),
                    class_="esiti"))
    return li(join(parti), class_="caso")


def progressi(packet: dict) -> Raw:
    """La memoria storica personale."""
    parti = [_freschezza(packet), _osservazione(packet)]

    parti.append(_grafico(packet.get("chart")))

    if packet.get("comparisons"):
        parti.append(section(
            h2("Quando ci sei gia stato"),
            ul(join(_caso_storico(c) for c in packet["comparisons"]),
               class_="casi")))
    if packet.get("evidence"):
        parti.append(section(h2("Il blocco attuale"), _elenco_prove(packet["evidence"])))
    if packet.get("limitations"):
        parti.append(section(
            h2("Limiti"),
            ul(join(li(testo) for testo in packet["limitations"]), class_="limiti")))
    if packet.get("next_question"):
        parti.append(p(packet["next_question"], class_="prossima"))

    parti.append(_perche(packet.get("evidence", [])))
    return main(h1("Progressi"), join(parti))


# ── Gare e riferimenti ───────────────────────────────────────────────────

# I campi del modulo, con le loro etichette. In una struttura sola perché il
# modulo, l'anteprima e la conferma devono mostrare gli stessi campi: tre
# elenchi separati divergono al primo cambiamento.
CAMPI_RIFERIMENTO = (
    ("day", "Data", "date", True),
    ("distance_m", "Distanza", "scelta", True),
    ("stroke", "Stile", "scelta", True),
    ("pool", "Vasca", "scelta", True),
    ("time", "Tempo", "text", True),
    ("kind", "Tipo di prova", "scelta", False),
    ("context", "Dove, quale gara", "text", False),
    ("activity_id", "Seduta Garmin collegata", "text", False),
    ("notes", "Note", "text", False),
)


def _scelte(nome: str, valori, scelto: str = "") -> Raw:
    return select(
        join(option(str(v), value=str(v), selected=(str(v) == str(scelto)))
             for v in valori),
        name=nome, id_=nome)


def _campo(nome: str, etichetta: str, tipo: str, obbligatorio: bool,
           valore: str, opzioni: dict) -> Raw:
    if tipo == "scelta":
        controllo = _scelte(nome, opzioni[nome], valore)
    else:
        controllo = input_(type=tipo, name=nome, id_=nome, value=valore,
                           required=obbligatorio)
    return div(label(etichetta, for_=nome), controllo, class_="campo")


def modulo_riferimento(gettone: str, valori: dict, opzioni: dict,
                       errore: str = "") -> Raw:
    """Il modulo con cui l'atleta conferma un tempo.

    Non salva: porta a un'anteprima. Una scrittura in `coach/` deve passare da
    una schermata che mostra esattamente cio che verra scritto — e' la regola
    del §6 dell'incarico, ed e' anche il modo in cui un errore di battitura si
    vede prima e non sei mesi dopo.
    """
    return section(
        h2("Aggiungi un tempo confermato"),
        p("Un tempo qui dentro e' un fatto che dichiari tu. Il coach non "
          "promuove da solo una nuotata veloce a prova massimale.", class_="nota"),
        p(errore, class_="errore") if errore else Raw(""),
        form(
            input_(type="hidden", name=security.FIELD, value=gettone),
            join(_campo(nome, etichetta, tipo, obbligatorio,
                        valori.get(nome, ""), opzioni)
                 for nome, etichetta, tipo, obbligatorio in CAMPI_RIFERIMENTO),
            button("Vedi l'anteprima", type="submit"),
            method="post", action="/gare/riferimenti", class_="modulo"))


def anteprima_riferimento(gettone: str, conferma: str, riga: dict) -> Raw:
    """Cosa verra scritto, prima che venga scritto.

    Il modulo non rimanda i campi. Porta solo il gettone dell'anteprima: i
    valori li tiene il server, esattamente come sono elencati qui sopra. Cosi
    quello che si legge e quello che si scrive sono per costruzione la stessa
    cosa, e non due cose che si somigliano.
    """
    return main(
        h1("Conferma"),
        article(
            p("Sto per aggiungere questa riga a coach/riferimenti.md:",
              class_="testo"),
            class_="osservazione"),
        ul(join(li(span(etichetta, class_="nome"), span(valore, class_="valore"))
                for etichetta, valore in riga.items()), class_="prove"),
        form(
            input_(type="hidden", name=security.FIELD, value=gettone),
            input_(type="hidden", name=confirmation.FIELD, value=conferma),
            button("Scrivi nel file", type="submit"),
            method="post", action="/gare/riferimenti/conferma", class_="modulo"),
        p(a("Annulla, torna indietro", href="/gare"), class_="ritorno"))


def _riferimento(prova: dict) -> Raw:
    return li(
        span(prova["label"], class_="nome"),
        span(prova["time_display"], class_="valore"),
        span(f"{prova['pace_display']} per 100 m · {prova['kind']} del "
             f"{prova['date']}"
             + (f" · {prova['context']}" if prova["context"] else ""),
             class_="contesto"),
        class_="prova")


def _record(voce: dict) -> Raw:
    return _riga_valore(voce["label"], voce["time"],
                        f"{voce['day']} · {voce['pace']} · {voce['races']}")


def _distribuzione_gara(voce: dict) -> Raw:
    return li(
        span(f"{voce['day']} · {voce['label']}", class_="nome"),
        span(voce["verdict"], class_="valore"),
        span(voce["detail"], class_="contesto"),
        class_="prova")


def _stagione(voce: dict) -> Raw:
    return li(
        span(voce["label"], class_="nome"),
        span(voce["time"] + (" ★" if voce["is_best"] else ""), class_="valore"),
        span(f"{voce['pace']} · {voce['races']} · {voce['day']}",
             class_="contesto"),
        class_="prova")


def _progressione(voce: dict) -> Raw:
    """Una specialità negli anni. Chiusa di default: sono molte, e la sintesi
    basta a capire se vale la pena aprirla."""
    return details(
        summary(f"{voce['label']} — {voce['verdict']}"),
        p(voce["summary"], class_="contesto"),
        ul(join(_stagione(s) for s in voce["seasons"]), class_="prove"),
        class_="perche")


def _gara_in_mare(voce: dict) -> Raw:
    corpo = [
        span(f"{voce['day']} · {voce['meet']}", class_="nome"),
        span(voce["time"], class_="valore"),
        span(" · ".join(pezzo for pezzo in
                        (voce["distance"], voce["pace"], voce["place"],
                         voce["venue"]) if pezzo and pezzo != "—"),
             class_="contesto"),
    ]
    # Le condizioni stanno sotto al tempo e non accanto: sono contesto, non
    # prestazione. Servono a rendere confrontabili due gare che il solo passo
    # non confronta — un'acqua a 19 gradi con mezzo metro d'onda e un'acqua a
    # 24 piatta non sono la stessa gara.
    if voce.get("conditions"):
        corpo.append(span(voce["conditions"], class_="contesto"))
    if voce["warning"]:
        corpo.append(span(voce["warning"], class_="contesto attenzione"))
    return li(join(corpo), class_="prova")


def _storico_gare(storico: dict) -> Raw:
    """I tempi della federazione: i soli numeri di questo progetto che non
    vengono da un orologio al polso di chi nuota."""
    if not storico or not storico.get("bests"):
        return Raw("")
    parti = [h2("I tuoi tempi ufficiali"), p(storico["coverage"], class_="contesto")]

    if storico.get("last"):
        parti.append(p(storico["last"], class_="prossima"))
    if storico.get("endurance"):
        parti.append(p(storico["endurance"], class_="testo"))

    parti.append(h3("Record personali"))
    parti.append(ul(join(_record(v) for v in storico["bests"]), class_="prove"))

    if storico.get("progressions"):
        parti.append(h3("Gli stessi metri, negli anni"))
        parti.append(join(_progressione(v) for v in storico["progressions"]))

    if storico.get("open_water"):
        parti.append(h3("Le gare in mare"))
        parti.append(p("Il tempo è cronometrato. La distanza è quella che "
                       "l'organizzazione ha dichiarato, e non una misura: i "
                       "passi qui sotto vanno letti sapendolo.",
                       class_="contesto"))
        parti.append(ul(join(_gara_in_mare(v) for v in storico["open_water"]),
                        class_="prove"))

    if storico.get("pacings"):
        parti.append(h3("Come hai distribuito le gare"))
        parti.append(ul(join(_distribuzione_gara(v) for v in storico["pacings"]),
                        class_="prove"))
    if storico.get("limitations"):
        parti.append(ul(join(li(testo) for testo in storico["limitations"]),
                        class_="limiti"))
    return section(join(parti))


def gare(packet: dict, gettone: str, opzioni: dict, valori: dict | None = None,
         errore: str = "", scritto: str = "", storico: dict | None = None) -> Raw:
    """La pagina Gare: quadro, tempi ufficiali, riferimenti confermati, modulo."""
    parti = [_freschezza(packet), _osservazione(packet)]
    parti.append(_storico_gare(storico or {}))

    if scritto:
        parti.append(p(f"Scritto in {scritto}.", class_="riuscito"))

    if packet.get("comparisons"):
        parti.append(section(
            h2("I tuoi riferimenti confermati"),
            ul(join(_riferimento(prova) for prova in packet["comparisons"]),
               class_="prove")))
    else:
        parti.append(section(
            h2("I tuoi riferimenti confermati"),
            p("Nessuno, ancora. E' l'unica cosa che il progetto non puo "
              "procurarsi da solo.", class_="nota")))

    parti.append(modulo_riferimento(gettone, valori or {}, opzioni, errore))

    if packet.get("evidence"):
        parti.append(section(h2("Il lavoro osservato"),
                             _elenco_prove(packet["evidence"])))
    if packet.get("limitations"):
        parti.append(section(
            h2("Cosa non posso dirti, e perche"),
            ul(join(li(testo) for testo in packet["limitations"]), class_="limiti")))
    if packet.get("next_question"):
        parti.append(p(packet["next_question"], class_="prossima"))

    parti.append(_perche(packet.get("evidence", [])))
    return main(h1("Gare"), join(parti))


# ── Chiedi ───────────────────────────────────────────────────────────────

# Il minimo JavaScript di tutta l'applicazione: copia negli appunti. Non
# calcola niente, non manda niente da nessuna parte, e se non gira la pagina
# resta usabile perche il testo e in un campo selezionabile.
COPIA_JS = """
document.addEventListener('click', function (evento) {
  var bottone = evento.target.closest('[data-copia]');
  if (!bottone) return;
  var campo = document.getElementById(bottone.dataset.copia);
  if (!campo) return;
  campo.select();
  if (navigator.clipboard) {
    navigator.clipboard.writeText(campo.value).then(function () {
      bottone.textContent = 'Copiata';
    });
  }
});
"""


def _domanda(indice: int, domanda: dict) -> Raw:
    identificativo = f"domanda-{indice}"
    return li(
        div(domanda["text"], class_="testo-domanda"),
        div(f"Perche: {domanda['why']}", class_="contesto"),
        div(f"Strumento: {domanda['tool']}", class_="contesto"),
        textarea(domanda["text"], id_=identificativo, readonly=True, rows="3",
                 aria_label="Testo della domanda, pronto da copiare"),
        button("Copia", type="button", data_copia=identificativo,
               aria_label=f"Copia la domanda {indice + 1}"),
        class_="caso")


def chiedi(packet: dict, domande: list[dict], come_funziona: str) -> Raw:
    """Le domande contestuali, pronte da incollare in Claude."""
    return main(
        h1("Chiedi"),
        _freschezza(packet),
        article(
            p("Queste domande sono gia scritte con dentro il periodo e gli "
              "identificativi giusti.", class_="testo"),
            class_="osservazione"),
        p(come_funziona, class_="nota"),
        ul(join(_domanda(indice, domanda)
                for indice, domanda in enumerate(domande)), class_="casi"),
        section(
            h2("Cosa esce da questo computer"),
            ul(
                li("Da questa pagina: niente. Non c'e nessuna chiamata verso "
                   "l'esterno, e la pagina funziona senza rete."),
                li("Quando incolli una domanda in Claude: il testo che hai "
                   "copiato, e nient'altro. Gli strumenti MCP leggono il "
                   "database da qui, sul tuo computer."),
                li("Mai: l'export Garmin, il database, le credenziali, le "
                   "coordinate GPS."),
                class_="limiti")))


# ── La nota su una seduta ────────────────────────────────────────────────

CAMPI_NOTA = (
    ("rpe", "Fatica percepita, da 1 a 10", "number", False),
    ("purpose", "Finalita della seduta", "scelta", False),
    ("feeling", "Come e andata, in una riga", "text", False),
)


def modulo_nota(gettone: str, activity_id: int, day: str, valori: dict,
                opzioni: dict, errore: str = "") -> Raw:
    """Quello che sai tu e i dati non sanno.

    Finisce nel diario in `coach/`, non nel database: il database si ricostruisce
    da zero e una nota scritta li dentro sparirebbe alla prima ricostruzione.
    """
    return section(
        h2("Aggiungi quello che i dati non sanno"),
        p("La finalita di una serie la sai tu e il tuo allenatore, l'orologio "
          "no. Senza, il coach puo dire «passo rallentato» ma non «cedimento».",
          class_="nota"),
        p(errore, class_="errore") if errore else Raw(""),
        form(
            input_(type="hidden", name=security.FIELD, value=gettone),
            input_(type="hidden", name="activity_id", value=str(activity_id)),
            input_(type="hidden", name="day", value=day),
            join(_campo(nome, etichetta, tipo, obbligatorio,
                        valori.get(nome, ""), opzioni)
                 for nome, etichetta, tipo, obbligatorio in CAMPI_NOTA),
            button("Vedi l'anteprima", type="submit"),
            method="post", action="/sedute/nota", class_="modulo"))


def anteprima_nota(gettone: str, conferma: str, riepilogo: str,
                   activity_id: int, dove: str) -> Raw:
    """Cosa verra scritto nel diario, prima che venga scritto."""
    return main(
        h1("Conferma"),
        article(
            p(f"Sto per aggiungere questa nota a {dove}:", class_="testo"),
            class_="osservazione"),
        p(riepilogo, class_="prossima"),
        form(
            input_(type="hidden", name=security.FIELD, value=gettone),
            input_(type="hidden", name=confirmation.FIELD, value=conferma),
            button("Scrivi nel diario", type="submit"),
            method="post", action="/sedute/nota/conferma", class_="modulo"),
        p(a("Annulla, torna alla seduta", href=f"/sedute/{activity_id}"),
          class_="ritorno"))


# ── Il coach decisionale ─────────────────────────────────────────────────
#
# L'ordine di questa pagina e' l'argomento, e non e' negoziabile: obiettivo,
# verdetto, focus, deriva, cosa fare, cosa evitare, recupero, confidenza, e
# soltanto in fondo i numeri.
#
# La versione precedente metteva i valori in cima. Un pannello di valori lascia
# all'atleta il lavoro di capire cosa guardare, e quel lavoro e' esattamente
# quello che non sa fare da solo alle sette del mattino - che e' il motivo per
# cui questo progetto esiste invece di aprire Garmin Connect.

def _obiettivo(goal: dict, phase: dict) -> Raw:
    if not goal.get("event_name"):
        return article(
            p("Nessuna gara dichiarata.", class_="testo"),
            p(goal.get("why_missing", ""), class_="contesto"),
            class_="obiettivo")
    return article(
        p(f"{goal['event_name']} — {goal['distance']}", class_="domanda"),
        p(f"fra {goal['days_to_event']} giorni · {goal.get('declared_target') or ''}",
          class_="testo"),
        span(f"fase: {phase.get('name', '—')}", class_="etichetta-stato"),
        class_="obiettivo")


def _elenco(titolo: str, voci: list, classe: str = "limiti") -> Raw:
    if not voci:
        return Raw("")
    return section(h2(titolo), ul(join(li(testo) for testo in voci), class_=classe))


def _deriva(response: dict) -> Raw:
    etichette = {"sì": "Sì, stai decentrando", "no": "No, il lavoro è sul pezzo",
                 "incerto": "Non abbastanza dati per dirlo"}
    classi = {"sì": "da-osservare", "no": "informativo",
              "incerto": "dati-insufficienti"}
    stato = response.get("focus_drift", "incerto")
    return article(
        p("Stai decentrando il focus?", class_="domanda"),
        p(etichette.get(stato, stato), class_="testo"),
        p(response.get("focus_drift_why") or "", class_="contesto"),
        class_=f"osservazione {classi.get(stato, '')}")


def _fatti(facts: list) -> Raw:
    """I numeri, in fondo e dentro un dettaglio che si apre.

    Sono prove secondarie: servono a controllare il giudizio, non a sostituirlo.
    Ogni riga porta la propria finestra, perche' senza quella due numeri diversi
    sembrano la stessa grandezza.
    """
    if not facts:
        return Raw("")
    righe = []
    for fatto in facts:
        assente = fatto.get("availability") != "available"
        pezzi = [span(fatto["label"], class_="nome"),
                 span(fatto["display"], class_="valore"),
                 span(fatto["window"], class_="contesto")]
        if assente and fatto.get("why"):
            pezzi.append(span(fatto["why"], class_="contesto"))
        righe.append(li(join(pezzi), class_="prova assente" if assente else "prova"))
    return details(summary("Perché? I numeri su cui si basa"),
                   ul(join(righe), class_="prove"), class_="perche")


def coach_oggi(packet: dict, response: dict, chat: Raw = None) -> Raw:
    """La homepage: giudizio, priorita', azione, limite. I valori in fondo."""
    parti = [
        _obiettivo(packet.get("goal", {}), packet.get("phase", {})),
        article(p("Il verdetto del coach", class_="domanda"),
                p(response["verdict"], class_="testo"),
                class_="osservazione informativo"),
        article(p("Su cosa concentrarsi", class_="domanda"),
                p(response["primary_focus"], class_="testo"),
                class_="osservazione"),
        _deriva(response),
        _elenco("Cosa fare nei prossimi 7 giorni",
                response.get("actions_next_7_days", [])),
        _elenco("Cosa evitare", response.get("what_to_avoid", [])),
        _elenco("Cosa sta funzionando", response.get("what_is_working", [])),
        _elenco("Cosa merita attenzione", response.get("what_needs_attention", [])),
    ]

    # La confidenza si mostra in italiano: «low» è il nome del campo nel
    # contratto, non una parola che l'atleta debba leggere alle sette del
    # mattino.
    quanto = {"high": "alta", "moderate": "discreta", "low": "bassa"}
    appigli = len(response.get("why", []))
    parti.append(article(
        p("Quanto è solida questa lettura", class_="domanda"),
        p(f"Confidenza {quanto.get(response.get('confidence'), '—')}, "
          + (f"su {appigli} evidenze." if appigli != 1 else "su una evidenza."),
          class_="testo"),
        class_="osservazione dati-insufficienti"))

    if response.get("questions_for_athlete"):
        parti.append(_elenco("Quello che i dati non sanno e tu sì",
                             response["questions_for_athlete"]))
    if response.get("next_check"):
        parti.append(p(response["next_check"], class_="prossima"))
    if chat is not None:
        parti.append(chat)
    if packet.get("limitations"):
        parti.append(_elenco("Limiti dichiarati", packet["limitations"]))
    if response.get("boundary"):
        parti.append(_elenco("Confine", response["boundary"]))

    parti.append(_fatti(packet.get("facts", [])))
    parti.append(p(f"Prodotto da: {response.get('model', '—')} · "
                   f"impronta dei dati {response.get('packet_digest', '')}",
                   class_="contesto"))
    return main(h1("Il coach oggi"), join(parti))


# ── La conversazione, dentro la pagina ───────────────────────────────────

# Le domande che il coach sa davvero eseguire. Non sono suggerimenti di cortesia:
# ognuna corrisponde a fatti che il pacchetto contiene, e proporne una che il
# sistema non sa affrontare sarebbe peggio che non proporne nessuna.
DOMANDE_ESEGUIBILI = (
    "Su cosa devo concentrarmi questa settimana?",
    "Sto facendo troppo volume generico rispetto alla gara?",
    "Posso spingere o conviene consolidare?",
    "Quale dato manca per decidere meglio?",
)


def _payload_visibile(packet: dict) -> Raw:
    """Cosa uscirebbe dal computer, prima che esca.

    Non un elenco di categorie: il contenuto vero, aperto e leggibile. Una
    promessa sulla privacy che chiede fiducia e' una promessa; questa si
    controlla.
    """
    import json

    testo = json.dumps(packet, ensure_ascii=False, indent=2, default=str)
    return details(
        summary(f"Cosa uscirebbe da questo computer ({len(testo):,} byte)"),
        p("Il coach locale non manda niente a nessuno. Se premi «Chiedi a "
          "Claude», esce esattamente questo e nient'altro: niente coordinate, "
          "niente nomi, niente file grezzi.", class_="nota"),
        tag("pre", testo, class_="payload"),
        class_="perche")


def conversazione(packet: dict, response: dict, domanda: str,
                  gettone: str, avviso: str = "") -> Raw:
    """La chat: la domanda entra qui e la risposta compare qui.

    Non c'e nessun testo da copiare e nessuna finestra da aprire altrove. Il
    modello, quando sara' collegato, prendera' il posto del cervello locale
    senza che questa pagina cambi.
    """
    scelte = [li(form(
        input_(type="hidden", name=security.FIELD, value=gettone),
        input_(type="hidden", name="domanda", value=testo),
        button("Leggi in locale", type="submit", name="chi", value="locale"),
        button("Chiedi a Claude", type="submit", name="chi", value="claude"),
        span(testo, class_="testo-domanda"),
        method="post", action="/chiedi", class_="modulo-domanda"))
        for testo in DOMANDE_ESEGUIBILI]

    parti = [
        h1("Chiedi al coach"),
        article(
            p("La conversazione avviene qui, sul tuo computer.", class_="testo"),
            p(f"Risponde: {response.get('model', '—')}", class_="contesto"),
            class_="osservazione"),
        section(h2("Domande che il coach sa affrontare"),
                ul(join(scelte), class_="casi")),
    ]

    if avviso:
        # Il ripiego si dichiara. Una risposta locale spacciata per quella di
        # Claude sarebbe la bugia piu' comoda del progetto: la pagina
        # sembrerebbe funzionare e l'atleta non saprebbe mai di leggere altro.
        parti.append(p(avviso, class_="errore"))

    if domanda:
        parti.append(article(
            p(domanda, class_="domanda"),
            p(response["verdict"], class_="testo"),
            class_="osservazione informativo"))
        # Il limite vero del cervello locale, detto dove si vede.
        #
        # Applica regole scritte agli stessi fatti, quindi la lettura non
        # cambia con la domanda: puo' dire cosa dicono i dati, non puo'
        # rispondere *a questa* domanda invece che a un'altra. Lasciarlo
        # credere sarebbe la bugia piu' facile di tutto il progetto - la pagina
        # sembrerebbe un modello e non lo e'.
        if "locale" in response.get("model", ""):
            parti.append(p(
                "Sto rispondendo in locale, con regole scritte: la lettura e' "
                "la stessa per tutte e quattro le domande. Per una risposta "
                "che segua davvero la domanda, premi «Chiedi a Claude».",
                class_="nota"))
        if response.get("primary_focus"):
            parti.append(p(response["primary_focus"], class_="prossima"))
        parti.append(_elenco("Cosa fare", response.get("actions_next_7_days", [])))
        parti.append(_elenco("Cosa evitare", response.get("what_to_avoid", [])))
        parti.append(_elenco("Quello che i dati non sanno e tu si",
                             response.get("questions_for_athlete", [])))

    parti.append(_payload_visibile(packet))
    parti.append(_fatti(packet.get("facts", [])))
    # L'impronta dei dati su cui questa risposta e' stata data. Serve a
    # riconoscere una risposta vecchia quando i dati sono cambiati: senza, "il
    # coach aveva detto" non e' verificabile.
    parti.append(p(f"Risposta prodotta da: {response.get('model', '—')} · "
                   f"impronta dei dati {response.get('packet_digest', '')}",
                   class_="contesto"))
    return main(join(parti))


# ── La settimana ─────────────────────────────────────────────────────────

def _riga_valore(nome: str, valore: str, contesto: str = "") -> Raw:
    pezzi = [span(nome, class_="nome"), span(valore, class_="valore")]
    if contesto:
        pezzi.append(span(contesto, class_="contesto"))
    return li(join(pezzi), class_="prova")


def _distribuzione(settimana: dict) -> Raw:
    """I metri per finalita', con la copertura accanto e non in fondo.

    Una distribuzione in cui meta' dei metri e' "non dichiarata" non e' una
    distribuzione: e' meta' di una. Dirlo accanto ai numeri, e non sotto,
    e' la differenza fra un dato letto e un dato creduto.
    """
    voci = settimana.get("by_purpose") or {}
    if not voci:
        return Raw("")
    quota = settimana.get("declared_share")
    testa = ("Nessuna seduta ha una finalita' dichiarata: sotto c'e' il volume, "
             "non la sua distribuzione." if not quota else
             f"{settimana['declared_n']} sedute su {settimana['sessions']} hanno "
             "una finalita' dichiarata. Le altre stanno in "
             "«non dichiarata», e ci restano finche' non le scrivi.")
    return section(
        h2("Che lavoro e' stato"),
        p(testa, class_="nota"),
        ul(join(_riga_valore(nome, f"{km} km") for nome, km in voci.items()),
           class_="prove"))


def _prevista(voce: dict) -> Raw:
    return li(
        span(f"{voce['day']} · {voce['purpose']}", class_="nome"),
        span(voce["status"], class_="valore"),
        span(voce["display"], class_="contesto"),
        class_="prova")


def _piano(piano: dict) -> Raw:
    """Previsto contro eseguito. La meta' che all'archivio mancava."""
    if not piano:
        return Raw("")
    if not piano.get("available"):
        return article(p("Previsto contro eseguito", class_="domanda"),
                       p(piano["why"], class_="testo"),
                       class_="osservazione dati-insufficienti")
    return section(
        h2("Previsto contro eseguito"),
        p(piano["headline"], class_="testo"),
        ul(join(_prevista(v) for v in piano["sessions"]), class_="prove"),
        p(piano["caveat"], class_="nota"))


def _proposta_riga(voce: dict) -> Raw:
    return li(
        span(f"{voce['purpose']} · {voce['environment']}", class_="nome"),
        span(voce["distance"], class_="valore"),
        span(voce["pace"], class_="contesto"),
        class_="prova")


def _proposta(proposta: dict) -> Raw:
    """La distribuzione proposta. Sempre etichettata come proposta."""
    if not proposta:
        return Raw("")
    if not proposta.get("available"):
        return Raw("")
    return details(
        summary("Se il programma non ce l'hai: come distribuirei la settimana"),
        p(proposta["headline"], class_="testo"),
        ul(join(_proposta_riga(v) for v in proposta["sessions"]),
           class_="prove"),
        h3("Su cosa si basa"),
        ul(join(li(testo) for testo in proposta["basis"]), class_="prove"),
        ul(join(li(testo) for testo in proposta["caveats"]), class_="limiti"),
        class_="perche")


def settimana(corrente: dict, precedenti: list, mancante: str,
              piano: dict | None = None, proposta: dict | None = None) -> Raw:
    """Cosa e' stato fatto questa settimana, e cosa il sistema non sa."""
    parti = [
        h1("La settimana"),
        article(
            p(f"{corrente['start']} - {corrente['end']}", class_="domanda"),
            p(f"{corrente['sessions']} sedute, {corrente['distance_km']} km, "
              f"su {corrente['days_trained']} giorni", class_="testo"),
            class_="osservazione informativo"),
        _piano(piano or {}),
        _proposta(proposta or {}),
        article(p("Cosa il coach non sa di questa settimana", class_="domanda"),
                p(mancante, class_="testo"),
                class_="osservazione dati-insufficienti"),
        section(
            h2("Dove sono stati nuotati"),
            ul(join([
                _riga_valore("In vasca", f"{corrente['pool_km']} km"),
                _riga_valore("In acque libere", f"{corrente['open_water_km']} km"),
            ] + ([_riga_valore("Altri sport",
                               f"{corrente['other_sports_sessions']} sedute",
                               "contate a parte, mai sommate al nuoto")]
                 if corrente["other_sports_sessions"] else [])),
               class_="prove")),
        _distribuzione(corrente),
    ]

    if corrente.get("avg_rpe") is not None:
        parti.append(section(h2("Come l'hai sentita"), ul(_riga_valore(
            "Fatica percepita media", f"{corrente['avg_rpe']:.1f}/10",
            "solo sulle sedute che hai annotato"), class_="prove")))

    if precedenti:
        parti.append(section(
            h2("Le settimane prima"),
            ul(join(_riga_valore(f"{s['start']}", f"{s['distance_km']} km",
                                 f"{s['sessions']} sedute")
                    for s in precedenti), class_="prove")))
    return main(join(parti))


# ── Da decidere: i dati che non reggono ──────────────────────────────────
#
# L'ordine di ogni scheda e' un ragionamento, non un modulo: cosa dice
# l'orologio, come sta rispetto a te, cosa c'era quel giorno, quanto pesa la
# decisione, e solo alla fine i tre pulsanti. Chiedere prima e spiegare dopo
# produce risposte a caso.

def _riga_registrata(voce: tuple) -> Raw:
    etichetta, valore = voce
    return _riga_valore(etichetta, valore)


def _confronto(voce) -> Raw:
    return _riga_valore(
        voce.what, voce.here,
        f"il tuo tipico è {voce.typical}, l'intervallo va {voce.range} "
        f"— su {voce.population}")


def _decisione(dubbio, gettone: str) -> Raw:
    """I tre pulsanti, e la casella del motivo che li accompagna.

    Il motivo e' obbligatorio in `athlete_files.validate_correction`, e qui e'
    obbligatorio anche nel modulo: scoprire che serviva dopo aver premuto e'
    una frizione che si toglie con un attributo.
    """
    return form(
        input_(type="hidden", name=security.FIELD, value=gettone),
        input_(type="hidden", name="activity_id", value=str(dubbio.activity_id)),
        input_(type="hidden", name="day", value=dubbio.day.isoformat()),
        label("Cos'era, davvero?", for_=f"motivo-{dubbio.activity_id}"),
        textarea(id_=f"motivo-{dubbio.activity_id}",
                 name="reason", rows="2", required=True,
                 placeholder="Una riga basta. Fra un anno sarà l'unica cosa "
                             "che spiega questa decisione."),
        div(
            button("Non contarla", type="submit", name="status", value="exclude"),
            button("È vera, tienila", type="submit", name="status", value="keep"),
            button("Non lo so ancora", type="submit", name="status", value="review"),
            class_="scelte-decisione"),
        method="post", action="/da-decidere/decisione", class_="modulo")


def _scheda_dubbio(dubbio, gettone: str) -> Raw:
    parti = [
        h2(f"{dubbio.day.strftime('%d/%m/%Y')} — {dubbio.title}"),
        p(dubbio.flag, class_="contesto"),
        p(dubbio.question, class_="domanda"),
        section(h3("Cosa dice l'orologio"),
                ul(join(_riga_registrata(v) for v in dubbio.recorded),
                   class_="prove")),
    ]
    if dubbio.against:
        parti.append(section(
            h3("Come sta rispetto a te"),
            ul(join(_confronto(c) for c in dubbio.against), class_="prove")))
    if dubbio.same_day:
        parti.append(section(
            h3("Quel giorno hai anche nuotato"),
            ul(join(li(t, class_="prova") for t in dubbio.same_day),
               class_="prove")))
    parti.append(p(dubbio.weight, class_="contesto"))
    if dubbio.decided:
        parti.append(p("Hai già deciso su questa.", class_="prossima"))
    else:
        parti.append(_decisione(dubbio, gettone))
    return article(join(parti), class_="dubbio")


def _disaccordo(voce: dict) -> Raw:
    return article(
        h2(f"{voce['day'].strftime('%d/%m/%Y')} — {voce['title']}"),
        p(voce["reason"], class_="contesto"),
        ul(_riga_valore("il riepilogo Garmin dice", voce["summary"]),
           _riga_valore("il file dell'orologio dice", voce["file"]),
           class_="prove"),
        p(f"Hai già deciso: {voce['decision']}", class_="prossima")
        if voce.get("decided") else
        p("Nessuno dei due è impossibile e non ho modo di sapere quale sia "
          "giusto. Il dettaglio della seduta viene dal file, il totale dal "
          "riepilogo.", class_="testo"),
        p(a("Apri la seduta", href=f"/sedute/{voce['activity_id']}"),
          class_="ritorno"),
        class_="dubbio")


def da_decidere(dubbi: list, disaccordi: list, gettone: str,
                scritto: str = "", errore: str = "") -> Raw:
    parti: list = [h1("Da decidere")]
    if errore:
        parti.append(p(errore, class_="errore"))
    if scritto:
        parti.append(p(f"Scritto in {scritto}. Diventa effettivo al prossimo "
                       "aggiornamento dei dati.", class_="prossima"))

    if not dubbi and all(v.get("decided") for v in disaccordi):
        parti.insert(1, p("Non c'è più niente in attesa di una tua decisione.",
                          class_="prossima"))

    if not dubbi and not disaccordi:
        parti.append(p("Nessun dato in dubbio. Ogni attività in archivio o è "
                       "stata guardata, o non ha superato nessun limite "
                       "fisico.", class_="testo"))
        return main(join(parti))

    if dubbi:
        parti.append(p("Queste attività superano un limite fisico o si "
                       "contraddicono da sole. Restano nei totali — non tolgo "
                       "niente da solo — ma il coach non ci appoggia sopra "
                       "nessuna conclusione forte finché non dici cos'erano.",
                       class_="testo"))
        parti.extend(_scheda_dubbio(d, gettone) for d in dubbi)

    if disaccordi:
        aperti = [v for v in disaccordi if not v.get("decided")]
        parti.append(h2("Due numeri per la stessa nuotata"))
        parti.append(p("Qui non c'è niente di impossibile: ci sono due misure "
                       "della stessa seduta che non coincidono."
                       if aperti else
                       "Due misure della stessa seduta non coincidevano, e hai "
                       "già detto tu quale vale.", class_="testo"))
        parti.extend(_disaccordo(v) for v in disaccordi)
    return main(join(parti))


def anteprima_decisione(gettone: str, conferma: str, riepilogo: str,
                        dove: str) -> Raw:
    return main(
        h1("Conferma"),
        article(p(f"Sto per scrivere questa decisione in {dove}:",
                  class_="testo"), class_="osservazione"),
        p(riepilogo, class_="prossima"),
        p("I dati originali non vengono toccati: la decisione vive nel tuo "
          "file e si applica come strato sopra, quindi si può cambiare idea.",
          class_="contesto"),
        form(
            input_(type="hidden", name=security.FIELD, value=gettone),
            input_(type="hidden", name=confirmation.FIELD, value=conferma),
            button("Scrivi la decisione", type="submit"),
            method="post", action="/da-decidere/decisione/conferma",
            class_="modulo"),
        p(a("Annulla, torna all'elenco", href="/da-decidere"), class_="ritorno"))
