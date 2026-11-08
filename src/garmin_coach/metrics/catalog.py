"""Che cos'è ogni colonna di ``daily_status``, e da dove viene.

Serve al criterio C10: ogni numero che il coach mostra deve essere tracciabile
a una definizione esplicita. Il server MCP legge questo catalogo per dichiarare
la provenienza insieme al valore, invece di lasciarla implicita.

``origin`` distingue tre nature diverse, che non vanno mai confuse
(Regola Aurea n.5):

- ``garmin``   — valore proprietario Garmin, esposto così com'è, mai ricalcolato
- ``measured`` — valore misurato, solo normalizzato di unità
- ``computed`` — calcolato da una formula deterministica di questo progetto

``unit`` e ``method_version`` completano il contratto delle metriche (D7): il
primo perché un numero senza unità è un numero su cui si può sbagliare in
silenzio, il secondo perché un valore calcolato con la formula di sei mesi fa
non è confrontabile con uno di oggi, e nessuno se ne accorgerebbe.

La parte del contratto che dipende dalla singola risposta — disponibilità,
numerosità, copertura, grado di evidenza — sta in ``evidence.py``: cambia a ogni
chiamata e non può vivere in una tabella di definizioni.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Metric:
    column: str
    label: str
    origin: str          # 'garmin' | 'measured' | 'computed'
    formula: str
    source: str
    caveat: str = ""
    unit: str = ""       # dedotta dal nome della colonna se non dichiarata
    method_version: str = "1"

    def __post_init__(self):
        if not self.unit:
            object.__setattr__(self, "unit", unit_from_name(self.column))

    @property
    def data_class(self) -> str:
        """Il nome che la Macro-proposta 3 dà a queste tre nature."""
        return {"garmin": "garmin_proprietary", "measured": "measured",
                "computed": "calculated"}[self.origin]


# Le unità stanno nel nome della colonna: è la convenzione del progetto e
# dedurle da lì evita che nome e unità dichiarata possano divergere.
UNIT_SUFFIXES = {
    "_m": "metri", "_s": "secondi", "_ms": "millisecondi", "_bpm": "bpm",
    "_spm": "bracciate/min", "_kcal": "kcal", "_km": "km", "_pct": "%",
    "_c": "°C", "_kg": "kg", "_ratio": "rapporto",
}


# Colonne la cui unità il nome non porta. Non sono eccezioni alla convenzione:
# sono grandezze senza unità (conteggi, rapporti, punteggi proprietari Garmin).
# Dichiararle qui evita che "nessun suffisso" significhi due cose diverse —
# "adimensionale" e "unità dimenticata".
EXPLICIT_UNITS = {
    "sessions_count": "sedute", "swim_sessions_count": "sedute",
    "swim_sessions_7d": "sedute", "swim_sessions_28d": "sedute",
    "days_since_last_swim": "giorni",
    "swim_km_7d": "km", "swim_km_28d": "km",
    "swim_km_per_week_block": "km", "swim_km_week_median": "km",
    "open_water_km_8w": "km",
    "critical_swim_speed_pace_s_per_100m": "secondi per 100 m",
    "open_water_target_pace_s_per_100m": "secondi per 100 m",
    "hrv_baseline_28": "millisecondi",
    "resting_hr_baseline_28": "bpm", "resting_hr_delta": "bpm",
    "swolf_28d_pool25": "SWOLF", "swolf_28d_pool50": "SWOLF",
    "technique_devices_28d": "dispositivi",
    "dps_28d_pool25": "metri", "dps_28d_pool50": "metri",
    "load_acute_7": "carico Garmin", "load_chronic_28": "carico Garmin",
    "strain_7": "carico Garmin",
    "garmin_acute_load": "carico Garmin", "garmin_chronic_load": "carico Garmin",
    # Adimensionali per natura: un rapporto, un punteggio, un booleano.
    "acwr": "rapporto", "garmin_acwr": "rapporto", "monotony_7": "rapporto",
    "sleep_score": "punteggio Garmin 0-100",
    "garmin_readiness_score": "punteggio Garmin 0-100",
    "body_battery_min": "Body Battery 0-100", "body_battery_max": "Body Battery 0-100",
    "stress_avg": "stress Garmin 0-100",
    "garmin_training_status": "etichetta Garmin",
    "has_hrv": "vero/falso", "has_intensity": "vero/falso", "has_load": "vero/falso",
    "device_ids": "elenco",
}


def unit_from_name(column: str) -> str:
    if column in EXPLICIT_UNITS:
        return EXPLICIT_UNITS[column]
    for suffix, unit in sorted(UNIT_SUFFIXES.items(), key=lambda x: -len(x[0])):
        if column.endswith(suffix):
            return unit
    return ""


# Le due avvertenze delle metriche tecniche. Scritte una volta e riusate perché
# valgono per tutte e quattro allo stesso modo: quattro copie divergono, e la
# quarta diventa quella che nessuno aggiorna.
STILE_MESCOLATO = (
    "Mescola gli stili: avg_swolf è un valore per attività e lo stile sta nei "
    "lap, quindi qui una seduta mista e una tutta a stile libero hanno la "
    "stessa forma. ")

PIU_DISPOSITIVI = (
    "Può attraversare più dispositivi: su questo archivio due orologi danno "
    "28,9 e 30,7 di SWOLF medio a parità di vasca, cioè quanto un vero "
    "cambiamento tecnico. Quanti ne ha attraversati la finestra sta in "
    "technique_devices_28d. ")

GARE_SENZA_OROLOGIO = (
    "In mare l'orologio spesso non è ammesso: 18 gare entrano nel volume dalla "
    "tabella races, con la distanza dichiarata dall'evento e non misurata. "
    "Restano fuori solo le gare che l'atleta ha dichiarato essere una nuotata "
    "già registrata, così nulla è contato due volte — la decisione la prende "
    "una persona, perché dedurla dal giorno sbagliava in due modi opposti "
    "(vedi race_quality). Cinque di quelle gare non dichiarano una distanza e "
    "lasciano il giorno parzialmente sconosciuto, non a zero: su quante "
    "nuotate è calcolato il totale sta in swim_distance_known_n. ")

CATALOG: tuple[Metric, ...] = (
    # ── Attività del giorno ────────────────────────────────────────────────
    Metric("sessions_count", "Sedute totali", "measured",
           "conteggio delle attività con quella data locale, più le gare in "
           "mare dei giorni in cui l'orologio non ha registrato nulla",
           "activities + races", caveat=GARE_SENZA_OROLOGIO),
    Metric("swim_sessions_count", "Sedute di nuoto", "measured",
           "conteggio delle attività con is_swim = true, più le gare in mare "
           "dei giorni in cui l'orologio non ha registrato nessuna nuotata",
           "activities + races", caveat=GARE_SENZA_OROLOGIO),
    Metric("swim_distance_m", "Metri nuotati", "measured",
           "somma di distance_m sulle sedute di nuoto, o la distanza "
           "dichiarata delle gare nei giorni senza orologio",
           "activities + races", caveat=GARE_SENZA_OROLOGIO),
    Metric("session_duration_s", "Durata allenata", "measured",
           "somma di duration_s su tutte le attività, più il tempo di gara "
           "dei giorni senza orologio", "activities + races",
           caveat=GARE_SENZA_OROLOGIO),

    # ── Recupero, valori Garmin ────────────────────────────────────────────
    Metric("hrv_ms", "HRV notturna", "garmin",
           "valore Garmin del giorno", "health_status",
           "Disponibile solo dal 2025-09-19: copre il 9% della storia (R5)."),
    Metric("resting_hr_bpm", "FC a riposo", "garmin",
           "valore Garmin del giorno", "daily_health",
           "Assente nei primi anni: i file UDS del 2017 non contengono il campo."),
    Metric("sleep_total_s", "Sonno totale", "measured",
           "deep + light + rem; le fasi di veglia sono escluse", "sleep"),
    Metric("sleep_score", "Punteggio sonno", "garmin",
           "sleepScores.overallScore", "sleep"),
    Metric("body_battery_min", "Body Battery minima", "garmin",
           "statistica LOWEST della giornata", "daily_health",
           "Algoritmo proprietario Garmin: esposto, mai ricalcolato."),
    Metric("body_battery_max", "Body Battery massima", "garmin",
           "statistica HIGHEST della giornata", "daily_health",
           "Algoritmo proprietario Garmin: esposto, mai ricalcolato."),
    Metric("stress_avg", "Stress medio", "garmin",
           "allDayStress, aggregato di tipo TOTAL", "daily_health"),
    Metric("garmin_readiness_score", "Training Readiness", "garmin",
           "punteggio Garmin", "garmin_readiness",
           "Disponibile dal 2024-06."),
    Metric("garmin_training_status", "Training Status", "garmin",
           "stato Garmin del giorno", "garmin_training_status",
           "Disponibile dal 2021-07."),
    Metric("garmin_acute_load", "Carico acuto Garmin", "garmin",
           "dailyTrainingLoadAcute", "garmin_training_load"),
    Metric("garmin_chronic_load", "Carico cronico Garmin", "garmin",
           "dailyTrainingLoadChronic", "garmin_training_load"),
    Metric("garmin_acwr", "ACWR Garmin", "garmin",
           "dailyAcuteChronicWorkloadRatio", "garmin_training_load",
           "Non è un indicatore di rischio infortunio. Vietato usarlo come tale."),

    # ── Baseline personali calcolate ───────────────────────────────────────
    Metric("hrv_baseline_28", "Baseline HRV 28 giorni", "computed",
           "media di hrv_ms sui 28 giorni precedenti, giorno corrente escluso; "
           "richiede almeno 14 giorni con dato", "health_status",
           "Prima del 2025-10 non esistono 28 giorni di storico: resta NULL."),
    Metric("hrv_delta_pct", "Scostamento HRV", "computed",
           "100 * (hrv_ms - hrv_baseline_28) / hrv_baseline_28", "health_status"),
    Metric("resting_hr_baseline_28", "Baseline FC riposo 28 giorni", "computed",
           "media di resting_hr_bpm sui 28 giorni precedenti, giorno escluso; "
           "richiede almeno 14 giorni con dato", "daily_health"),
    Metric("resting_hr_delta", "Scostamento FC riposo", "computed",
           "resting_hr_bpm - resting_hr_baseline_28", "daily_health"),
    Metric("sleep_baseline_28_s", "Baseline sonno 28 giorni", "computed",
           "media di sleep_total_s sui 28 giorni precedenti, giorno escluso; "
           "richiede almeno 14 giorni con dato", "sleep"),

    # ── Carico calcolato ───────────────────────────────────────────────────
    Metric("load_acute_7", "Carico acuto 7 giorni", "computed",
           "somma del carico giornaliero sugli ultimi 7 giorni, giorno incluso",
           "activities.garmin_training_load",
           "Il carico per attività manca prima del 2021: cieco sul 40% delle sedute (R9)."),
    Metric("load_chronic_28", "Carico cronico 28 giorni", "computed",
           "somma del carico sugli ultimi 28 giorni divisa per 4, per renderla "
           "confrontabile con una settimana", "activities.garmin_training_load",
           "Stesso limite di copertura del carico acuto."),
    Metric("acwr", "Rapporto acuto/cronico", "computed",
           "load_acute_7 / load_chronic_28; NULL se il cronico è nullo o se meno "
           "di 21 dei 28 giorni hanno dato",
           "activities.garmin_training_load",
           "Non è una previsione di infortunio. Va letto come descrizione, mai come diagnosi."),
    Metric("monotony_7", "Monotonia 7 giorni", "computed",
           "media del carico giornaliero su 7 giorni divisa per la sua deviazione "
           "standard campionaria; NULL se la deviazione è zero",
           "activities.garmin_training_load"),
    Metric("strain_7", "Strain 7 giorni", "computed",
           "load_acute_7 * monotony_7", "activities.garmin_training_load"),

    # ── Volume ─────────────────────────────────────────────────────────────
    Metric("swim_km_7d", "Nuoto 7 giorni", "computed",
           "somma dei metri nuotati sugli ultimi 7 giorni, divisa per 1000",
           "activities", "Copertura 100% su tutti e nove gli anni."),
    Metric("swim_km_28d", "Nuoto 28 giorni", "computed",
           "somma dei metri nuotati sugli ultimi 28 giorni, divisa per 1000",
           "activities", "Copertura 100% su tutti e nove gli anni."),
    # ── Tre grandezze che prendevano in prestito il nome di un'altra ──────
    #
    # Fino all'audit del 22/08/2026 queste tre comparivano etichettate «Nuoto 7
    # giorni» o «Nuoto 28 giorni». Sono medie e mediane su finestre diverse, e
    # la scheda «Perché?» mostrava per tutte la formula di `swim_km_7d`, cioè
    # una formula che non era quella usata.
    #
    # Un'etichetta che rappresenta quattro grandezze non è un'imprecisione di
    # forma: è il modo in cui due numeri diventano confrontabili agli occhi di
    # chi legge senza esserlo.
    Metric("swim_km_per_week_block", "Nuoto, media settimanale del blocco",
           "computed",
           "metri nuotati nelle quattro settimane del blocco, divisi per 1000 "
           "e per il numero di settimane",
           "canonical_activities",
           "Non è il volume degli ultimi 7 giorni: è la media di un blocco di "
           "quattro settimane, e serve a confrontare blocchi fra loro."),
    Metric("swim_km_week_median", "Nuoto, mediana settimanale storica",
           "computed",
           "mediana dei chilometri settimanali sulle settimane osservate nel "
           "periodo di riferimento",
           "canonical_activities",
           "Descrive quello che l'atleta ha già sostenuto, non quello che può "
           "sostenere. La mediana e non la media perché una settimana di gara "
           "sposta la media e non la mediana."),
    Metric("open_water_km_8w", "Nuoto in acque libere, 8 settimane", "computed",
           "metri nuotati in ambiente open_water nelle ultime 8 settimane, "
           "divisi per 1000",
           "canonical_activities",
           "Finestra di otto settimane e non di quattro: la specificità in mare "
           "si costruisce su un orizzonte più lungo del carico."),

    Metric("critical_swim_speed_pace_s_per_100m",
           "Velocità critica, passo per 100 m", "computed",
           "100 / ((400 − 200) / (t400 − t200)), dalle due prove massimali più "
           "vicine nel tempo nella stessa vasca",
           "pool_races",
           "È il passo di soglia da cui si costruiscono le serie lunghe, non "
           "un tempo di gara e non un passo per il mare. Nasce da due gare, "
           "quindi da due prove massimali vere; quando fra le due ce ne sono "
           "altre il valore è prudente, perché la seconda è stata nuotata su "
           "gambe già usate."),

    Metric("open_water_target_pace_s_per_100m",
           "Passo obiettivo in mare", "computed",
           "velocità critica moltiplicata per la quota che questo atleta ha "
           "tenuto nelle proprie gare in mare su distanze paragonabili",
           "open_water_races + pool_races",
           "Non viene dalla letteratura. Esiste uno studio che dà la quota dei "
           "primi dieci ai Mondiali (92%), e applicarla qui darebbe un passo "
           "molto più veloce di qualunque cosa questo atleta abbia tenuto in "
           "mare: la quota usata è la sua, misurata sulle sue gare."),

    Metric("swim_sessions_7d", "Sedute di nuoto, 7 giorni", "computed",
           "conteggio sedute di nuoto sugli ultimi 7 giorni", "activities"),
    Metric("swim_sessions_28d", "Sedute di nuoto, 28 giorni", "computed",
           "conteggio sedute di nuoto sugli ultimi 28 giorni", "activities"),
    Metric("days_since_last_swim", "Giorni dall'ultima nuotata", "computed",
           "differenza fra la data e l'ultima data con almeno una seduta di nuoto",
           "activities"),

    # ── Tecnica, separata per vasca ────────────────────────────────────────
    # Lo SWOLF si confronta solo a parità di vasca: due colonne distinte, mai
    # una media che le mescoli.
    Metric("swolf_28d_pool25", "SWOLF medio 28 giorni, vasca 25 m", "computed",
           "media di avg_swolf pesata sui metri, sulle sedute in vasca da 25 m "
           "degli ultimi 28 giorni",
           "canonical_activities",
           "Confrontabile solo con altre vasche da 25 m. " + PIU_DISPOSITIVI + STILE_MESCOLATO),
    Metric("swolf_28d_pool50", "SWOLF medio 28 giorni, vasca 50 m", "computed",
           "media di avg_swolf pesata sui metri, sulle sedute in vasca da 50 m "
           "degli ultimi 28 giorni",
           "canonical_activities",
           "Confrontabile solo con altre vasche da 50 m. " + PIU_DISPOSITIVI + STILE_MESCOLATO),
    Metric("dps_28d_pool25", "Distanza per bracciata 28 giorni, vasca 25 m", "computed",
           "media di avg_stroke_distance_m pesata sui metri, in vasca da 25 m, "
           "ultimi 28 giorni",
           "canonical_activities",
           "Garmin scrive 0 al posto del dato mancante su 735 sedute su 1.306: "
           "la copertura reale è del 43%. " + PIU_DISPOSITIVI + STILE_MESCOLATO),
    Metric("dps_28d_pool50", "Distanza per bracciata 28 giorni, vasca 50 m", "computed",
           "media di avg_stroke_distance_m pesata sui metri, in vasca da 50 m, "
           "ultimi 28 giorni",
           "canonical_activities",
           "Stesso limite di copertura. " + PIU_DISPOSITIVI + STILE_MESCOLATO),
    Metric("technique_devices_28d", "Orologi nella finestra tecnica", "computed",
           "quanti dispositivi diversi hanno prodotto un numero tecnico negli "
           "ultimi 28 giorni",
           "canonical_activities",
           "Sopra uno, le medie tecniche della finestra attraversano orologi "
           "diversi e la differenza fra due periodi non è tutta dell'atleta."),

    # ── Copertura, sempre dichiarata ───────────────────────────────────────
    Metric("has_hrv", "HRV disponibile", "computed",
           "vero se hrv_ms non è nullo", "health_status"),
    Metric("has_intensity", "Intensità disponibile", "computed",
           "vero se almeno una seduta del giorno ha la frequenza cardiaca media",
           "activities",
           "Falso su tutte le sedute fra il 2017 e il 2020."),
    Metric("has_load", "Carico disponibile", "computed",
           "vero se almeno una seduta del giorno ha il carico Garmin", "activities"),
    # -- Grandezze della singola seduta -------------------------------------
    # Non sono colonne di daily_status: descrivono una seduta, non un giorno.
    # Stanno qui lo stesso perche il catalogo e il posto dove un numero prende
    # unita, formula e versione, e averne due sarebbe averne zero.
    Metric("pace_per_100m_s", "Passo per 100 m", "computed",
           "durata diviso distanza, moltiplicato per cento", "activity_laps",
           "Confrontabile solo a parita di stile, distanza, vasca e dispositivo. "
           "L'attrezzo (palette, pinne, pull buoy) non e registrato dall'orologio "
           "ed e la prima spiegazione alternativa di un passo anomalo."),
    Metric("pool_length_m", "Lunghezza vasca", "measured",
           "valore dichiarato nella seduta", "activities",
           "In vasca da 50 m il peso della virata e dimezzato: SWOLF e passo non "
           "sono paragonabili a quelli in vasca da 25 m."),
    Metric("pool_lengths_count", "Vasche nuotate", "measured",
           "conteggio delle vasche registrate dal file FIT", "pool_lengths",
           "In acque libere non si applica: le vasche non esistono.",
           unit="vasche"),
    Metric("avg_hr_bpm", "Frequenza cardiaca media", "garmin",
           "media della seduta registrata dall'orologio", "activities",
           "Assente su tutte le sedute fra il 2017 e il 2020 (R9)."),
    Metric("lap_count", "Lap registrati", "measured",
           "conteggio dei messaggi 'lap' del file FIT", "activity_laps",
           "Un lap e un fatto; una serie e un'interpretazione. I due non "
           "coincidono per definizione.",
           unit="lap"),
    Metric("repeat_spread_pct", "Regolarita delle ripetute", "computed",
           "deviazione standard dei passi divisa per la loro mediana, in "
           "percentuale", "activity_laps",
           "Ha senso da tre ripetute in su: sotto, descrive due valori."),

    Metric("device_ids", "Dispositivi del giorno", "measured",
           "elenco dei device_id distinti fra le attività del giorno", "activities",
           "Fino a 4 dispositivi diversi nello stesso anno: ogni confronto nel "
           "tempo deve controllarlo (R2)."),
)

BY_COLUMN = {metric.column: metric for metric in CATALOG}


def describe(column: str) -> Metric | None:
    return BY_COLUMN.get(column)
