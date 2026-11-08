"""Chi giudica: un'interfaccia, e un cervello che funziona senza rete.

## Perché un'interfaccia e non una chiamata diretta

Il giudizio è la parte del sistema che cambierà di più: modello diverso, via di
accesso diversa, un giorno magari nessun modello. Tutto il resto — i fatti, il
contratto, la pagina — non deve accorgersene.

## Chi giudica, oggi

Le vie possibili erano tre. **La scelta è fatta e non va riaperta:** il giudizio
passa dall'eseguibile di Claude Code e dall'abbonamento che l'atleta già paga.

| | Claude Code (`claude.exe`) | Messages API | MCP |
|---|---|---|---|
| in uso | **sì** | no | sì, ma altrove |
| costo | **abbonamento già pagato** | a consumo, per token | abbonamento |
| chat dentro l'app | **sì** | sì | **no**, vive nell'app di Claude |
| chiave da custodire | **nessuna** | sì | nessuna |

La Messages API era la raccomandazione dell'audit, perché non richiedeva
installazioni. **L'atleta l'ha scartata**: niente API a consumo, si usano gli
strumenti già pagati. MCP non soddisfa il requisito perché la conversazione
avviene nell'applicazione di Claude e non nella dashboard.

Il ponte, i suoi argomenti e le ragioni di ognuno stanno in ``claude_code.py``.
Qui resta soltanto l'interfaccia: il giudizio è la parte del sistema che
cambierà di più — modello diverso, via d'accesso diversa, un giorno magari
nessun modello — e i fatti, il contratto e la pagina non devono accorgersene.

## Perché esiste comunque un cervello locale

Non come ripiego di cortesia. Una dashboard che senza rete mostra una pagina
vuota è una dashboard che non si può usare in piscina, in viaggio, o il giorno
in cui l'accesso scade — cosa già successa il 22/08/2026. ``LocalBrain``
produce un giudizio deterministico dagli stessi fatti, dichiara di essere
locale, e non pretende di essere quello buono: non propone scenari a 42 giorni
e non risponde a domande libere, perché quelle due cose richiedono davvero un
modello.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol

from .contract import CoachContextPacket, CoachingResponse, validate


class ClaudeBrain(Protocol):
    """Chi trasforma i fatti in un giudizio.

    Una sola funzione, di proposito: tutto ciò che serve a giudicare è nel
    pacchetto, e ciò che non è nel pacchetto non deve essere raggiungibile.
    Nessun accesso a SQL, shell, filesystem o dati grezzi.
    """

    name: str

    def judge(self, packet: CoachContextPacket) -> CoachingResponse:
        ...


# Soglie del giudizio locale. Sono scritte qui e non sparse nelle frasi, perché
# cambiarle deve essere una decisione visibile.
#
# Nessuna è una scoperta: sono il minimo per distinguere «i dati dicono
# qualcosa» da «i dati non bastano», ed è esattamente ciò che un cervello senza
# modello può fare onestamente.
FOCUS_DRIFT_SPECIFIC_SHARE = 0.30   # quota di lavoro specifico sotto cui c'è deriva
TAPER_WINDOW_DAYS = 21              # dentro questi giorni il volume non è più la leva


class LocalBrain:
    """Il giudizio deterministico, senza rete e senza modello.

    Non è un modello e non finge di esserlo. Applica regole scritte, dichiara
    quali fatti ha usato, e dove servirebbe interpretazione dice che serve
    interpretazione invece di produrne una finta.
    """

    name = "locale (nessun modello, nessuna rete)"

    def judge(self, packet: CoachContextPacket) -> CoachingResponse:
        risposta = CoachingResponse(
            verdict="", primary_focus="",
            packet_digest=packet.digest, model=self.name,
            generated_on=packet.observation_date)

        giorni = packet.goal.get("days_to_event")
        gara = packet.goal.get("event_name")
        appigli: list[str] = []

        # ── Verdetto ──────────────────────────────────────────────────────
        specifica = packet.fact("specific_share")
        volume = packet.fact("swim_km_7d")
        if volume:
            appigli.append("swim_km_7d")

        # Il riferimento cronometrato, quando c'è. Per nove mesi questo coach ha
        # detto «non esiste una prova al passo obiettivo» a ogni risposta, ed era
        # vero finché l'archivio conteneva solo l'orologio. Adesso c'è un tempo
        # della federazione, e continuare a dire che manca sarebbe falso.
        prova = packet.fact("race_endurance_pace_s_per_100m")
        eta = packet.fact("days_since_endurance_reference")

        if gara and giorni is not None and prova and prova.availability == "available":
            appigli.append(prova.fact_id)
            quando = f" e risale a {eta.display} fa" if eta else ""
            risposta.verdict = (
                f"{gara} è l'unico appuntamento dichiarato e ci sono "
                f"{giorni} giorni. Un riferimento cronometrato ce l'hai: "
                f"{prova.display}{quando}. È misurato in piscina, quindi va "
                "messo accanto all'obiettivo dichiarato, non usato per "
                "ricavarlo.")
            if eta:
                appigli.append(eta.fact_id)
            risposta.next_check = (
                "Concordare con l'allenatore una prova nell'ambiente della gara "
                "al passo obiettivo, e osservare qualità, fatica percepita e "
                "recupero nelle 24-72 ore successive.")
        elif gara and giorni is not None:
            risposta.verdict = (
                f"{gara} è l'unico appuntamento dichiarato e ci sono "
                f"{giorni} giorni. Quello che l'archivio dimostra è il lavoro "
                "svolto; quello che non dimostra è una prova recente al passo "
                "obiettivo, e senza quella la prontezza resta un'ipotesi.")
            risposta.next_check = (
                "Concordare con l'allenatore una prova al passo obiettivo, e "
                "osservare qualità, fatica percepita e recupero nelle 24-72 ore "
                "successive.")
        else:
            risposta.verdict = (
                "Non c'è nessuna gara futura dichiarata, quindi non esiste un "
                "riferimento rispetto a cui dire se il lavoro sta andando dove "
                "deve. È la prima cosa da scrivere in coach/gare.md.")
            risposta.next_check = "Dichiarare l'obiettivo e la sua data."

        # ── Focus e deriva ────────────────────────────────────────────────
        if specifica and specifica.availability == "available":
            appigli.append("specific_share")
            quota = specifica.value or 0
            if quota < FOCUS_DRIFT_SPECIFIC_SHARE and gara:
                risposta.focus_drift = "sì"
                risposta.focus_drift_why = (
                    f"La quota di lavoro nell'ambiente della gara è "
                    f"{specifica.display}, sotto la soglia che questo coach usa "
                    "per parlare di preparazione specifica.")
                risposta.primary_focus = (
                    "Spostare parte del lavoro nell'ambiente della gara, invece "
                    "di aggiungere volume generico.")
                risposta.actions_next_7_days.append(
                    "Portare almeno una seduta della settimana nell'ambiente "
                    "della gara, sostituendone una in vasca invece di "
                    "aggiungerla.")
            else:
                risposta.focus_drift = "no"
                risposta.primary_focus = (
                    "Mantenere la specificità raggiunta e verificarne la tenuta "
                    "sulla distanza, non aumentarla ancora.")
                risposta.actions_next_7_days.append(
                    "Tenere il volume dov'è e usare una delle sedute "
                    "nell'ambiente della gara per verificare la tenuta del "
                    "passo obiettivo su una frazione della distanza.")
        else:
            risposta.focus_drift = "incerto"
            risposta.focus_drift_why = (
                "Non ci sono abbastanza sedute nell'ambiente della gara per "
                "dire se il lavoro è specifico o generico.")
            risposta.primary_focus = (
                "Costruire il minimo di sedute nell'ambiente della gara che "
                "renda giudicabile la specificità.")
            risposta.actions_next_7_days.append(
                "Programmare con l'allenatore una seduta nell'ambiente della "
                "gara: finché non ce ne sono, questa pagina non può dire se il "
                "lavoro è specifico o generico.")

        # ── Recupero come modificatore, non come verdetto ─────────────────
        recupero = packet.recovery.get("summary")
        if recupero:
            risposta.what_is_working.append(recupero)
        for identificativo in packet.recovery.get("fact_ids", []):
            if identificativo in packet.known_ids:
                appigli.append(identificativo)

        # ── Cosa evitare ──────────────────────────────────────────────────
        if giorni is not None and giorni <= TAPER_WINDOW_DAYS:
            risposta.what_to_avoid.append(
                "Aggiungere volume adesso: dentro le ultime tre settimane il "
                "volume non è più la leva che cambia il risultato.")
        else:
            risposta.what_to_avoid.append(
                "Aumentare il volume generico per sentirsi a posto: è la cosa "
                "più facile da misurare e la meno legata all'obiettivo.")

        # ── Qualità del dato: entra nel giudizio, non in fondo ────────────
        escluse = packet.data_quality.get("excluded", 0)
        da_guardare = packet.data_quality.get("review", 0)
        if escluse:
            risposta.what_needs_attention.append(
                "Ci sono registrazioni che hai escluso: le conclusioni qui "
                "sopra non le contano.")
        if da_guardare:
            risposta.questions_for_athlete.append(
                "Ci sono registrazioni che superano un limite fisico e "
                "aspettano una tua decisione. Finché non le guardi, non "
                "sostengono nessuna conclusione forte.")

        # ── Confidenza ────────────────────────────────────────────────────
        risposta.confidence = self._confidence(packet)
        risposta.why = list(dict.fromkeys(appigli))
        risposta.counterpoints = [
            f.fact_id for f in packet.facts
            if f.availability != "available" and f.fact_id in packet.known_ids][:3]

        risposta.boundary.append(
            "Questo non è un parere medico. Dolore che non passa, o che cambia "
            "il modo in cui nuoti, si guarda con un fisioterapista.")
        risposta.questions_for_athlete.append(
            "Che cosa ha previsto il tuo allenatore per questa settimana?")

        # Il limite dichiarato, non taciuto: senza modello questi tre campi
        # resterebbero riempiti di frasi generiche, e una frase generica in un
        # campo che promette uno scenario è peggio del campo vuoto.
        risposta.direction_next_21_days = []
        risposta.scenario_next_42_days = []

        validate(risposta, packet)
        return risposta

    def _confidence(self, packet: CoachContextPacket) -> str:
        disponibili = sum(1 for f in packet.facts
                          if f.availability == "available")
        if not packet.goal.get("event_name"):
            return "low"
        if disponibili >= 5 and not packet.data_quality.get("review"):
            return "moderate"
        return "low"
