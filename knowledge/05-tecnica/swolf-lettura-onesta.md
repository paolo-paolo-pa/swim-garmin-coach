# SWOLF — lettura onesta

**Ambito:** piscina
**Solidità:** consolidato (per il calcolo) · discusso (per l'interpretazione)
**Aggiornato:** 2026-08-16

> Scheda di esempio, scritta per fissare il formato. Vedi [00-INDICE.md](../00-INDICE.md).

## In breve

SWOLF = secondi impiegati per una vasca + numero di bracciate in quella vasca.
È un indice grezzo di efficienza: a parità di tempo, meno bracciate è meglio.
È anche una delle metriche più abusate del nuoto, perché sembra confrontabile
sempre e invece lo è quasi mai.

## Come funziona

```
SWOLF = tempo_vasca_s + bracciate_vasca
```

Somma due grandezze di natura diversa (tempo e conteggio) senza normalizzarle.
Questo è voluto: penalizza sia chi va piano sia chi bracceggia troppo. Ma implica
che il numero non ha unità di misura e non è confrontabile fuori contesto.

## Come si misura con i dati disponibili

Disponibile su due livelli:

- **Aggregato per seduta** — campo `avgSwolf` nei riepiloghi Garmin. Presente su tutte
  le sedute di piscina dal 2017. Utile per trend lunghi, inutile per l'analisi fine.
- **Per singola vasca** — ricalcolabile dai FIT (`length`: `total_elapsed_time` + `total_strokes`).
  È il livello che serve per vedere il degrado dentro una serie.

**Cosa NON si può misurare:**
- lo SWOLF non distingue una bracciata efficace da una scivolata passiva;
- non tiene conto della fase subacquea dopo la virata (chi scivola di più abbassa
  lo SWOLF senza essere più efficiente a nuoto);
- in vasca da 50 m il peso della partenza/virata sul totale è dimezzato rispetto ai 25 m,
  quindi i valori non sono paragonabili tra le due vasche.

## Implicazione operativa

Regole per il coach:

1. **Mai confrontare SWOLF tra condizioni diverse.** Confronto lecito solo a parità di:
   vasca (25 vs 50), stile, tipo di serie e attrezzatura. In caso di dubbio, il coach
   dichiara che il confronto non è valido invece di produrlo.
2. **SWOLF isolato non è un giudizio.** Va sempre presentato insieme al passo per 100 m.
   SWOLF che scende con passo che peggiora = sta scivolando, non migliorando.
3. **Il segnale utile è la deriva dentro la serie**, non il valore assoluto. Uno SWOLF
   che sale di >8-10% tra la prima e l'ultima ripetuta indica cedimento tecnico:
   la serie è troppo lunga, troppo intensa o il recupero è insufficiente.
4. **Su base pluriennale, controllare il dispositivo.** Un salto di SWOLF che coincide
   con un cambio orologio va attribuito al sensore finché non è dimostrato il contrario
   (vedi rischio R2 in [PIANO.md](../../docs/PIANO.md)).

## Limiti e cautele

- Il conteggio bracciate del polso è stimato, non contato: sbaglia su stili con
  bracciate ampie, in acque mosse e con le palette.
- Nei recuperi e nelle vasche di tecnica lo SWOLF non ha significato: vanno esclusi
  dal calcolo, non mediati insieme al resto.
- Non esiste un "buon valore" universale di SWOLF. Esiste solo il proprio, nel proprio
  contesto, nel tempo.

## Fonti

Da compilare. Candidati: manuali di metodologia del nuoto, documentazione Garmin sul
calcolo dello SWOLF, prassi allenatoriale corrente. Materiale grezzo in `../_fonti/`.
