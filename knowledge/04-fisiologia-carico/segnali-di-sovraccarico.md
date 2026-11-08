# Segnali di sovraccarico

**Ambito:** entrambi
**Solidità:** consolidato (i segnali) · discusso (le soglie)
**Aggiornato:** 2026-08-16

## In breve

Nessun singolo numero dice che si sta accumulando troppa fatica. La convergenza di
più segnali indipendenti sì. Questa scheda serve a decidere **quando ridurre**,
non a diagnosticare: la diagnosi non è compito del coach.

## Come funziona

Segnali che, se concordi, contano:

| Segnale | Dove si vede | Da quando è disponibile |
|---|---|---|
| FC a riposo sopra la baseline di 3-5 bpm per più giorni | `resting_hr_delta` | 2021 |
| HRV sotto la banda per 3 giorni consecutivi | `hrv_delta_pct` | set. 2025 |
| Sonno sotto la baseline con punteggio in calo | `sleep_total_s`, `sleep_score` | 2017 / 2021 |
| Monotonia alta con carico alto | `monotony_7`, `load_acute_7` | 2021 |
| Passo che peggiora a parità di fatica percepita | `swim_history`, RPE | RPE dal 2021, 38% |
| SWOLF che sale a parità di vasca e dispositivo | `swolf_28d_pool25` | 2017 |
| Voglia di allenarsi in calo, irritabilità, sonno disturbato | diario dell'atleta | sempre |

**La regola è la convergenza:** tre o più segnali nella stessa direzione per più
di tre giorni. Un solo indicatore fuori riga non è nulla.

## Come si misura con i dati disponibili

L'ultimo segnale della tabella — quello soggettivo — è spesso il primo ad
apparire e **non è nei dati Garmin**. Va raccolto dall'atleta e annotato con
`log_write`. Un coach che guarda solo i numeri se ne accorge dopo.

## Implicazione operativa

1. **Regola conservativa: nel dubbio, si riduce.** Il costo di una settimana più
   leggera è basso; quello di due settimane perse è alto.
2. **Si riduce prima il volume, poi l'intensità.** Mantenere qualche stimolo
   breve e intenso a volume ridotto conserva la condizione meglio del contrario.
3. **Un giorno di riposo completo vale più di due giorni blandi**, e abbassa anche
   la monotonia.
4. **Ordine delle domande all'atleta**, prima di guardare qualunque numero:
   come dormi, che voglia hai di andare in acqua, quanto ti costa il passo di
   sempre. Se le risposte sono buone, i numeri fuori riga pesano meno.
5. **Dolore è una categoria a parte.** Non è sovraccarico da gestire con il
   carico: richiede un professionista. Il coach non interpreta e non minimizza.

## Limiti e cautele

- Le soglie numeriche (3-5 bpm, 3 giorni) sono convenzioni pratiche, non costanti.
- Prima del 2021 esistono solo sonno e segnali soggettivi: la convergenza a tre
  indicatori non è ottenibile, e va detto.
- Nessuno di questi segnali autorizza a parlare di sovrallenamento come condizione
  clinica, né a prevedere un infortunio.

## Fonti

Da compilare. Correlate: [hrv-interpretazione.md](hrv-interpretazione.md) ·
[monotonia-e-strain.md](monotonia-e-strain.md) ·
[sonno-e-recupero.md](sonno-e-recupero.md)
