"""«Come ho risposto a quel blocco?» — rilievo A4.3 dell'audit.

## Cosa c'era prima, e perché non era una risposta

`progress.py` trovava i blocchi storici simili e poi raccontava **quanti
chilometri** e **quante sedute** erano venuti nei 7, 14 e 28 giorni dopo. È
un'informazione vera e non è la risposta a niente: il volume delle settimane
successive lo hanno deciso il programma dell'allenatore, il lavoro e la vita.
Chiamare «risposta» ciò che l'atleta ha *deciso* di fare significa confondere il
carico successivo con l'adattamento — e per un allenatore è l'errore di lettura
peggiore possibile, perché fa sembrare una scelta un effetto.

## Le quattro cose che invece sono una risposta

1. **Prestazione a condizioni comparabili.** Il passo sulla **stessa ripetuta,
   nella stessa vasca**, dentro il blocco e nei 28 giorni dopo. Non il passo
   medio della seduta: quello contiene i riposi, la tecnica e le gambe, quindi
   misura che cosa conteneva la seduta e non quanto forte si andava. Provato
   prima nella versione per seduta, dava «peggiorata» su tutti e quattro i
   precedenti dell'archivio — un risultato troppo uniforme per essere una
   scoperta, e infatti era un artefatto.
2. **Tenuta.** Dentro la singola seduta lunga, il passo del primo terzo contro
   quello dell'ultimo terzo. Un blocco assorbito bene si vede qui prima che
   nella media: la media può restare uguale mentre la seconda metà si sfalda.
3. **Traiettoria fisiologica.** Frequenza cardiaca a riposo e HRV, dentro il
   blocco e dopo.
4. **Recupero.** Sonno, stress medio e Body Battery minima. Rispondono a una
   domanda diversa dalla terza: non come sta il sistema cardiovascolare, ma
   quanto recupero c'è stato **intorno** all'allenamento — che dipende anche
   dal lavoro e dalla vita, e per questo sta su un asse suo invece di
   confondersi con la fisiologia.

## Quello che questo modulo si rifiuta di fare

Non attraversa i confini dei dati. La frequenza cardiaca non esiste prima del
2021 e l'HRV prima del 19/09/2025: per un blocco del 2018 l'asse fisiologico non
è «stabile», è **assente**, e viene dichiarato assente. Un confronto che
attraversa quel confine non viene prodotto con una nota — non viene prodotto.

Non dice mai *perché*. Un miglioramento dopo un blocco carico è un'osservazione;
«quel blocco ti ha fatto migliorare» è una causa, e con un atleta solo e nove
anni le associazioni casuali si trovano da sole.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import duckdb

from ..database import table_exists

# Sotto questa lunghezza una ripetuta non descrive un passo: una singola vasca
# da 25 m è dominata dalla partenza e dalla virata.
MIN_REPEAT_M = 50

# Quante ripetute della stessa lunghezza servono da entrambe le parti. Otto: i
# lap sono abbondanti — nell'archivio ce ne sono 12.543 da 50 m nella sola vasca
# da 25 — quindi la soglia può permettersi di non essere generosa.
MIN_REPEATS_PER_BUCKET = 8

# Quante sedute servono per gli assi che ragionano per seduta e non per lap.
MIN_SESSIONS_PER_BUCKET = 3

# Nove lap in movimento: tre per terzo. Sotto, «primo terzo» e «ultimo terzo»
# sono lo stesso lap chiamato in due modi.
MIN_LAPS_FOR_DURABILITY = 9

# Giorni con misura fisiologica, da entrambe le parti.
MIN_DAYS_FOR_PHYSIOLOGY = 10

# Quando le due grandezze fisiologiche hanno cominciato a esistere in questo
# archivio. Sono le stesse date di `progress.epoch_of`, e il motivo per cui
# stanno anche qui è che qui producono un rifiuto, non un'etichetta.
FIRST_INTENSITY_DAY = date(2021, 1, 1)
FIRST_HRV_DAY = date(2025, 9, 19)

# Quanto deve cambiare una mediana perché valga la pena dirlo. Il passo di una
# seduta oscilla di suo: sotto questa soglia il confronto dice «stabile» invece
# di raccontare rumore come se fosse una tendenza.
NOISE_PACE_PCT = 1.5
NOISE_PHYSIOLOGY_PCT = 2.0

# Il sonno e lo stress oscillano molto più della frequenza a riposo: lavoro,
# viaggi, bambini, caldo. Una soglia stretta come quella fisiologica
# racconterebbe rumore a ogni blocco. **Scelta, non misurata.**
NOISE_RECOVERY_PCT = 5.0

# Da quando lo stress e la Body Battery esistono in questo archivio. Prima non
# sono «stabili»: non ci sono.
FIRST_STRESS_DAY = date(2019, 5, 15)


@dataclass(frozen=True)
class Axis:
    """Un asse della risposta, o il motivo per cui non c'è."""

    name: str
    available: bool
    direction: str = ""          # migliorata | peggiorata | stabile
    display: str = ""
    coverage: str = ""
    why_missing: str = ""
    details: list[str] = field(default_factory=list)


def _show_pace(seconds: float | None) -> str:
    if seconds is None:
        return "non calcolabile"
    minuti, resto = divmod(seconds, 60)
    return f"{int(minuti)}:{resto:04.1f}/100 m"


def _direction(prima: float, dopo: float, soglia: float,
               meno_e_meglio: bool = True) -> str:
    """Da due numeri a una parola, con una zona morta dichiarata."""
    if not prima:
        return "stabile"
    variazione = (dopo - prima) / prima * 100
    if abs(variazione) < soglia:
        return "stabile"
    migliorata = variazione < 0 if meno_e_meglio else variazione > 0
    return "migliorata" if migliorata else "peggiorata"


def _direction_of_difference(prima: float, dopo: float, soglia: float) -> str:
    """La stessa parola, ma per due grandezze che possono essere negative.

    `_direction` divide per il valore di partenza, e quando quel valore è
    negativo il rapporto cambia segno: un decadimento che passa da -8,1% a
    -6,3% — cioè un finale meno veloce di prima — risultava «migliorato»
    perché il numero si avvicinava a zero. Qui si guarda la differenza in punti,
    che non ha quel problema.
    """
    differenza = dopo - prima
    if abs(differenza) < soglia:
        return "stabile"
    return "migliorata" if differenza < 0 else "peggiorata"


def _repeat_name(pool_length: float | None, repeat_m: float) -> str:
    vasca = f"vasca da {pool_length:.0f} m" if pool_length else "vasca"
    return f"{repeat_m:.0f} m in {vasca}"


def _repeats(connection: duckdb.DuckDBPyConnection, first: date,
             last: date) -> list[tuple]:
    """Le ripetute utilizzabili in una finestra, con la loro condizione esatta.

    ## Perché i lap e non le sedute

    La prima versione confrontava il **passo medio della seduta**. Misurato
    sull'archivio vero, dava «prestazione peggiorata» su tutti e quattro i
    precedenti trovati: un risultato troppo uniforme per essere una scoperta.
    Non lo era — il passo medio di una seduta contiene i riposi, la tecnica e le
    gambe, quindi misura **che cosa conteneva la seduta**, non quanto forte si
    andava. Un blocco carico fatto di nuotate continue seguito da settimane di
    tecnica «peggiora» senza che nessuno sia peggiorato.

    Il lap risolve il problema alla radice: 100 m in vasca da 25 sono 100 m in
    vasca da 25, nel 2018 come nel 2026.

    ## Perché solo la vasca

    In acque libere i lap li preme l'atleta a mano e la loro lunghezza non è
    costante — è già scritto in `sessions.py`. Due lap «da 1.000 m» non sono la
    stessa prova, quindi il confronto per distanza esatta lì non esiste.

    `quality_status = 'valid'` e non la sola vista canonica: `review` significa
    «non regge conclusioni forti», e un confronto di prestazione è esattamente
    una conclusione forte.
    """
    return connection.execute(f"""
        SELECT a.pool_length_m, l.distance_m, l.pace_per_100m_s, a.device_id
        FROM activity_laps l
        JOIN canonical_activities a USING (activity_id)
        WHERE a.is_swim AND a.quality_status = 'valid'
          AND a.environment = 'pool' AND a.pool_length_m IS NOT NULL
          AND a.activity_date BETWEEN ? AND ?
          AND NOT coalesce(l.is_rest, FALSE)
          AND l.pace_per_100m_s IS NOT NULL
          AND coalesce(l.distance_m, 0) >= {MIN_REPEAT_M}
    """, [first, last]).fetchall()


def _percentile(valori: list[float], quota: float) -> float | None:
    if not valori:
        return None
    ordinati = sorted(valori)
    indice = min(int(quota * len(ordinati)), len(ordinati) - 1)
    return ordinati[indice]


def _median(valori: list[float]) -> float | None:
    if not valori:
        return None
    ordinati = sorted(valori)
    meta = len(ordinati) // 2
    if len(ordinati) % 2:
        return ordinati[meta]
    return (ordinati[meta - 1] + ordinati[meta]) / 2


def performance(connection: duckdb.DuckDBPyConnection, block_start: date,
                block_end: date, follow_up_days: int = 28) -> Axis:
    """Il passo sulla stessa ripetuta, nella stessa vasca, dentro e dopo."""
    dentro = _repeats(connection, block_start, block_end)
    dopo = _repeats(connection, block_end + timedelta(days=1),
                    block_end + timedelta(days=follow_up_days))
    if not dentro or not dopo:
        return Axis("prestazione", False, why_missing=(
            "Non ci sono ripetute in vasca da confrontare da entrambe le "
            f"parti: servono lap di almeno {MIN_REPEAT_M} m con un passo "
            "registrato. In acque libere i lap li premi tu a mano e non hanno "
            "una lunghezza costante, quindi non entrano in questo confronto."))

    def per_condizione(righe):
        gruppi: dict[tuple, dict] = {}
        for vasca, ripetuta, passo, orologio in righe:
            chiave = (vasca, ripetuta)
            voce = gruppi.setdefault(chiave, {"passi": [], "orologi": set()})
            voce["passi"].append(passo)
            voce["orologi"].add(orologio)
        return gruppi

    prima_gruppi, dopo_gruppi = per_condizione(dentro), per_condizione(dopo)
    confrontabili, scartate = [], []
    for chiave in sorted(set(prima_gruppi) & set(dopo_gruppi)):
        a, b = prima_gruppi[chiave], dopo_gruppi[chiave]
        if (len(a["passi"]) < MIN_REPEATS_PER_BUCKET
                or len(b["passi"]) < MIN_REPEATS_PER_BUCKET):
            scartate.append(f"{_repeat_name(*chiave)}: {len(a['passi'])} nel "
                            f"blocco e {len(b['passi'])} dopo, troppo poche")
            continue
        confrontabili.append((chiave, a, b))

    if not confrontabili:
        return Axis("prestazione", False, why_missing=(
            "Nessuna ripetuta compare abbastanza volte da entrambe le parti "
            "per reggere un confronto."), details=scartate[:4])

    # La ripetuta più frequente decide la parola; le altre restano nel
    # dettaglio. Mediare fra i 50 e i 400 produrrebbe un numero che non
    # descrive nessuna delle due prove.
    confrontabili.sort(key=lambda voce: -min(len(voce[1]["passi"]),
                                             len(voce[2]["passi"])))
    (chiave, a, b) = confrontabili[0]
    prima, poi = _median(a["passi"]), _median(b["passi"])

    dettagli = []
    for (altra, x, y) in confrontabili[:4]:
        dettagli.append(
            f"{_repeat_name(*altra)}: da {_show_pace(_median(x['passi']))} "
            f"({len(x['passi'])} ripetute) a {_show_pace(_median(y['passi']))} "
            f"({len(y['passi'])} ripetute)")

    # Il capo veloce, accanto alla mediana. La mediana dice come andavi di
    # solito; il quarto più veloce dice cosa riuscivi a fare quando spingevi, ed
    # è lì che un adattamento si vede prima.
    veloce_prima = _percentile(a["passi"], 0.25)
    veloce_dopo = _percentile(b["passi"], 0.25)
    dettagli.append(
        f"Il quarto più veloce di quelle stesse ripetute: da "
        f"{_show_pace(veloce_prima)} a {_show_pace(veloce_dopo)} "
        f"({_direction(veloce_prima, veloce_dopo, NOISE_PACE_PCT)}).")

    orologi = a["orologi"] | b["orologi"]
    if len(orologi) > 1:
        dettagli.append(
            f"Attenzione: il confronto attraversa {len(orologi)} orologi "
            "diversi, e il passo in vasca dipende anche da come l'orologio "
            "riconosce la virata.")
    dettagli.append(
        "Una ripetuta della stessa lunghezza non è sempre la stessa prova: "
        "può essere riscaldamento, soglia o gambe. La finalità la sai tu.")

    return Axis(
        "prestazione", True,
        direction=_direction(prima, poi, NOISE_PACE_PCT),
        display=(f"Sui {_repeat_name(*chiave)} il passo mediano è passato da "
                 f"{_show_pace(prima)} a {_show_pace(poi)}."),
        coverage=(f"{len(a['passi'])} ripetute nel blocco, {len(b['passi'])} "
                  f"nei {follow_up_days} giorni dopo"),
        details=dettagli)


def durability(connection: duckdb.DuckDBPyConnection, block_start: date,
               block_end: date, follow_up_days: int = 28) -> Axis:
    """Quanto rallenta l'ultimo terzo rispetto al primo, dentro e dopo.

    È l'asse che la media nasconde: due sedute con lo stesso passo medio, una
    tenuta e una che si sfalda a metà, non sono la stessa seduta.
    """
    if not table_exists(connection, "activity_laps"):
        return Axis("tenuta", False, why_missing=(
            "Il dettaglio dei lap non è stato importato: si ottiene con "
            "«garmin_coach details»."))

    def decadimenti(primo: date, ultimo: date) -> list[float]:
        righe = connection.execute(f"""
            WITH utili AS (
                SELECT l.activity_id, l.lap_index, l.pace_per_100m_s,
                       row_number() OVER (PARTITION BY l.activity_id
                                          ORDER BY l.lap_index) AS posizione,
                       count(*)   OVER (PARTITION BY l.activity_id) AS quanti
                FROM activity_laps l
                JOIN canonical_activities a USING (activity_id)
                WHERE a.is_swim AND a.quality_status = 'valid'
                  AND a.activity_date BETWEEN ? AND ?
                  AND NOT coalesce(l.is_rest, FALSE)
                  AND l.pace_per_100m_s IS NOT NULL
                  AND coalesce(l.distance_m, 0) > 0
            )
            SELECT activity_id,
                   median(pace_per_100m_s) FILTER (WHERE posizione * 3 <= quanti),
                   median(pace_per_100m_s) FILTER (WHERE posizione * 3 > quanti * 2)
            FROM utili
            WHERE quanti >= {MIN_LAPS_FOR_DURABILITY}
            GROUP BY activity_id
        """, [primo, ultimo]).fetchall()
        return [(fine - inizio) / inizio * 100
                for _, inizio, fine in righe if inizio and fine]

    dentro = decadimenti(block_start, block_end)
    dopo = decadimenti(block_end + timedelta(days=1),
                       block_end + timedelta(days=follow_up_days))
    if len(dentro) < MIN_SESSIONS_PER_BUCKET or len(dopo) < MIN_SESSIONS_PER_BUCKET:
        return Axis("tenuta", False, why_missing=(
            f"Servono almeno {MIN_SESSIONS_PER_BUCKET} sedute con almeno "
            f"{MIN_LAPS_FOR_DURABILITY} lap in movimento da entrambe le parti: "
            f"ce ne sono {len(dentro)} nel blocco e {len(dopo)} dopo."))

    prima, poi = _median(dentro), _median(dopo)
    return Axis(
        "tenuta", True,
        direction=_direction_of_difference(prima, poi, NOISE_PACE_PCT),
        display=(f"L'ultimo terzo delle sedute lunghe andava del "
                 f"{prima:+.1f}% rispetto al primo; dopo, del {poi:+.1f}% "
                 "(negativo vuol dire più veloce in fondo)."),
        coverage=f"{len(dentro)} sedute nel blocco, {len(dopo)} dopo",
        details=["Una serie progressiva o uno scarico finale producono lo "
                 "stesso segno di una seduta che si sfalda: la finalità la sai "
                 "tu, l'orologio no."])


def physiology(connection: duckdb.DuckDBPyConnection, block_start: date,
               block_end: date, follow_up_days: int = 28) -> Axis:
    """Frequenza cardiaca a riposo e HRV, dentro il blocco e dopo.

    Il confine dei dati non si attraversa. Per un blocco del 2018 questo asse è
    assente, e lo dice: una frase come «stabile» su un dato che non esiste è
    peggio del silenzio, perché è indistinguibile da una misura.
    """
    if block_start < FIRST_INTENSITY_DAY:
        return Axis("fisiologia", False, why_missing=(
            "In quel periodo l'orologio non registrava la frequenza cardiaca: "
            f"nell'archivio compare dal {FIRST_INTENSITY_DAY.strftime('%d/%m/%Y')}. "
            "Non è un dato stabile, è un dato che non esiste."))

    def misure(primo: date, ultimo: date) -> tuple[list[float], list[float]]:
        righe = connection.execute("""
            SELECT resting_hr_bpm, hrv_ms FROM daily_status
            WHERE status_date BETWEEN ? AND ?
        """, [primo, ultimo]).fetchall()
        return ([r[0] for r in righe if r[0] is not None],
                [r[1] for r in righe if r[1] is not None])

    fc_dentro, hrv_dentro = misure(block_start, block_end)
    fc_dopo, hrv_dopo = misure(block_end + timedelta(days=1),
                               block_end + timedelta(days=follow_up_days))

    if (len(fc_dentro) < MIN_DAYS_FOR_PHYSIOLOGY
            or len(fc_dopo) < MIN_DAYS_FOR_PHYSIOLOGY):
        return Axis("fisiologia", False, why_missing=(
            f"Servono almeno {MIN_DAYS_FOR_PHYSIOLOGY} giorni con la frequenza "
            f"a riposo da entrambe le parti: ce ne sono {len(fc_dentro)} nel "
            f"blocco e {len(fc_dopo)} dopo."))

    prima, poi = _median(fc_dentro), _median(fc_dopo)
    verso_fc = _direction(prima, poi, NOISE_PHYSIOLOGY_PCT)
    direzione = verso_fc
    dettagli = []
    if (len(hrv_dentro) >= MIN_DAYS_FOR_PHYSIOLOGY
            and len(hrv_dopo) >= MIN_DAYS_FOR_PHYSIOLOGY):
        hrv_prima, hrv_poi = _median(hrv_dentro), _median(hrv_dopo)
        verso_hrv = _direction(hrv_prima, hrv_poi, NOISE_PHYSIOLOGY_PCT,
                               meno_e_meglio=False)
        versi = {verso_fc, verso_hrv} - {"stabile"}
        direzione = ("discordante" if len(versi) > 1
                     else next(iter(versi), "stabile"))
        dettagli.append(f"HRV: da {hrv_prima:.0f} a {hrv_poi:.0f} ms ({verso_hrv}), "
                        f"su {len(hrv_dentro)} e {len(hrv_dopo)} notti misurate.")
    elif block_start < FIRST_HRV_DAY:
        dettagli.append(
            "L'HRV in quel periodo non veniva registrata: compare "
            f"dal {FIRST_HRV_DAY.strftime('%d/%m/%Y')}.")
    else:
        dettagli.append("Notti con HRV troppo poche per un confronto.")

    return Axis(
        "fisiologia", True,
        direction=direzione,
        display=(f"La frequenza a riposo è passata da {prima:.0f} a "
                 f"{poi:.0f} bpm."),
        coverage=(f"{len(fc_dentro)} giorni misurati nel blocco, "
                  f"{len(fc_dopo)} dopo"),
        details=dettagli)


def recovery(connection: duckdb.DuckDBPyConnection, block_start: date,
             block_end: date, follow_up_days: int = 28) -> Axis:
    """Sonno, stress e Body Battery, dentro il blocco e dopo.

    ## Perché un asse a parte e non tre righe dentro la fisiologia

    Perché rispondono a una domanda diversa. La frequenza a riposo e l'HRV
    dicono come sta il sistema cardiovascolare; sonno e stress dicono **quanto
    recupero c'è stato intorno all'allenamento**, e quello dipende anche dal
    lavoro, dai viaggi e dal caldo. Mescolarli produrrebbe un'unica etichetta
    che nasconde quale dei due si è mosso.

    ## Le tre grandezze, e perché queste

    - **Sonno**: l'unico dato di recupero coperto quasi ovunque nell'archivio.
    - **Stress medio Garmin**: un punteggio proprietario, quindi confrontabile
      con se stesso e con nient'altro. Serve la direzione, non il valore.
    - **Body Battery minima**: quanto in basso è arrivata la giornata. È più
      informativa del massimo, che dice solo quanto bene si è dormito.

    Nessuna delle tre è una diagnosi, e la loro convergenza non è una prova:
    un blocco carico che alza lo stress e abbassa il sonno è un'osservazione,
    e la causa può essere altrove.
    """
    if block_start < FIRST_STRESS_DAY:
        return Axis("recupero", False, why_missing=(
            "In quel periodo l'orologio non registrava stress e Body Battery: "
            f"nell'archivio compaiono dal {FIRST_STRESS_DAY.strftime('%d/%m/%Y')}. "
            "Non sono dati stabili, sono dati che non esistono."))

    def misure(primo: date, ultimo: date) -> dict:
        righe = connection.execute("""
            SELECT sleep_total_s, stress_avg, body_battery_min
            FROM daily_status WHERE status_date BETWEEN ? AND ?
        """, [primo, ultimo]).fetchall()
        return {
            "sonno": [r[0] / 3600 for r in righe if r[0] is not None],
            "stress": [r[1] for r in righe if r[1] is not None],
            "batteria": [r[2] for r in righe if r[2] is not None],
        }

    dentro = misure(block_start, block_end)
    dopo = misure(block_end + timedelta(days=1),
                  block_end + timedelta(days=follow_up_days))

    # Le tre grandezze hanno coperture diverse: una può esserci e le altre no,
    # e va detto quale invece di tacere tutto o fingere che ci siano tutte.
    confronti, versi, mancanti = [], [], []
    for nome, unita, meno_e_meglio in (("sonno", "h", False),
                                       ("stress", "", True),
                                       ("batteria", "", False)):
        prima_lista, dopo_lista = dentro[nome], dopo[nome]
        if (len(prima_lista) < MIN_DAYS_FOR_PHYSIOLOGY
                or len(dopo_lista) < MIN_DAYS_FOR_PHYSIOLOGY):
            mancanti.append(
                f"{nome}: {len(prima_lista)} giorni nel blocco e "
                f"{len(dopo_lista)} dopo, troppo pochi per un confronto")
            continue
        prima, poi = _median(prima_lista), _median(dopo_lista)
        verso = _direction(prima, poi, NOISE_RECOVERY_PCT,
                           meno_e_meglio=meno_e_meglio)
        versi.append(verso)
        cifre = 1 if nome == "sonno" else 0
        confronti.append(
            f"{nome}: da {prima:.{cifre}f}{unita} a {poi:.{cifre}f}{unita} "
            f"({verso}), su {len(prima_lista)} e {len(dopo_lista)} giorni")

    if not confronti:
        return Axis("recupero", False,
                    why_missing="; ".join(mancanti) or "nessuna misura di recupero")

    distinti = set(versi) - {"stabile"}
    direzione = ("discordante" if len(distinti) > 1
                 else next(iter(distinti), "stabile"))
    # «Recupero peggiorata» è la frase che tradisce un'etichetta incollata a
    # una parola: gli assi usano il femminile perché parlano di «prestazione»,
    # qui il soggetto è maschile e la frase va concordata.
    concordato = {"migliorata": "migliorato", "peggiorata": "peggiorato"}.get(
        direzione, direzione)
    return Axis(
        "recupero", True,
        direction=direzione,
        display=f"Recupero {concordato} nei {follow_up_days} giorni dopo.",
        coverage=f"{len(confronti)} grandezze su 3 confrontabili",
        details=confronti + mancanti)


def how_the_body_answered(connection: duckdb.DuckDBPyConnection,
                          block_start: date, block_end: date,
                          follow_up_days: int = 28) -> list[Axis]:
    """I quattro assi della risposta, nell'ordine in cui si leggono.

    Prestazione e tenuta dicono **cosa è cambiato nel nuotare**; fisiologia e
    recupero dicono **a che prezzo**. L'ordine non è estetico: un miglioramento
    pagato con sonno in calo e stress in salita è una lettura diversa dallo
    stesso miglioramento a recupero invariato, e chi legge deve incontrare
    prima il risultato e poi il costo.
    """
    return [performance(connection, block_start, block_end, follow_up_days),
            durability(connection, block_start, block_end, follow_up_days),
            physiology(connection, block_start, block_end, follow_up_days),
            recovery(connection, block_start, block_end, follow_up_days)]


def summary(axes: list[Axis]) -> str:
    """Una frase sola, che dice anche quando non sa."""
    misurati = [asse for asse in axes if asse.available]
    if not misurati:
        return ("Di questo blocco non si può dire come il corpo abbia risposto: "
                "nessuno dei tre assi ha abbastanza dati.")
    parole = ", ".join(f"{asse.name} {asse.direction}" for asse in misurati)
    mancanti = [asse.name for asse in axes if not asse.available]
    frase = f"Risposta al blocco: {parole}."
    if mancanti:
        frase += f" Non misurabile: {', '.join(mancanti)}."
    return frase


def as_dicts(axes: list[Axis]) -> list[dict]:
    """Gli assi come li riceve una pagina: già formattati, niente da calcolare."""
    return [{"name": asse.name, "available": asse.available,
             "direction": asse.direction, "display": asse.display,
             "coverage": asse.coverage, "why_missing": asse.why_missing,
             "details": list(asse.details)} for asse in axes]
