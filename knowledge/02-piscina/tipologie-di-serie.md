# Tipologie di serie in vasca

**Ambito:** piscina
**Solidità:** consolidato
**Aggiornato:** 2026-08-16

## In breve

Una serie è definita da cinque parametri: distanza della ripetuta, numero di
ripetute, andatura, recupero e modalità di partenza. Cambiarne uno cambia lo
stimolo. "10×100" senza gli altri quattro non significa niente.

## Come funziona

**Serie a soglia.** Ripetute da 100 a 400 m attorno al passo CSS, recuperi brevi
(10-20 s), volume totale da 1500 a 3000 m. Obiettivo: sostenere l'andatura senza
degrado. Il segnale di riuscita è la costanza, non la velocità della prima.

**Serie di potenza aerobica (VO2).** Ripetute da 50 a 200 m a 3-6 s/100 sotto il
CSS, recuperi da 1:1 a 1:2 rispetto al lavoro. Volume totale contenuto, 800-1600 m.
Il degrado è atteso e accettabile nell'ultima parte.

**Resistenza specifica.** Ripetute alla velocità di gara sulla distanza obiettivo,
frazionata. Per una 5 km in acque libere: 6×800 al passo gara con 30" di recupero.
È la serie che dice di più sulla preparazione reale.

**Serie di velocità.** 15-50 m massimali, recupero completo (1-3 minuti). Volume
minimo, qualità assoluta. Se il tempo cala di serie in serie, la serie è finita.

**Serie tecnica.** Volume basso, andatura bassa, attenzione alta. Esercizi
specifici, spesso con attrezzatura. Non ha senso misurarla con il passo.

**Fondo continuo.** 1500-4000 m ininterrotti a passo A2. Costruisce ciò che
regge le acque libere.

## Come si misura con i dati disponibili

Oggi si vede la **seduta intera**: volume, passo medio, SWOLF medio, FC media.
Non si vede la struttura interna. Questo significa che il coach:

- **può** valutare volume, continuità, andamento fra sedute simili;
- **non può** dire se le ripetute erano costanti o se sono crollate alla sesta.

La ricostruzione delle serie arriva con la Fase 5. Fino ad allora, l'andamento
delle ripetute è informazione che deve fornire l'atleta, e va annotata nel diario
con `log_write`.

Il campo `lapCount` dà il numero di frazioni della seduta: è un indizio della
struttura, non la struttura.

## Implicazione operativa

1. **Il coach non deduce il tipo di serie dai totali.** Una seduta da 3000 m con
   passo medio 1'35" può essere un fondo continuo o un 10×100 forte con recuperi
   lunghi. Se serve saperlo, si chiede.
2. **Prescrivi sempre tutti e cinque i parametri**, compreso il tempo di partenza.
   "8×100 partenza ogni 1'40"" è una serie; "8×100 forte" è un'intenzione.
3. **Una sola serie di qualità per seduta.** Il resto è riscaldamento, tecnica e
   defaticamento.
4. **La resistenza specifica va introdotta nelle ultime 6-8 settimane** prima
   della gara obiettivo, non prima: è la più costosa da recuperare.

## Limiti e cautele

- Le distanze indicate sono riferimenti per un mezzofondista: uno specialista di
  50 m e un fondista hanno serie diverse a parità di nome.
- Prima di prescrivere andature in secondi serve un CSS aggiornato, altrimenti i
  numeri sono inventati.

## Fonti

Da compilare. Correlate: [densita-e-recuperi.md](densita-e-recuperi.md) ·
[css-critical-swim-speed.md](../01-fondamenti/css-critical-swim-speed.md) ·
[energetica-del-nuoto.md](../01-fondamenti/energetica-del-nuoto.md)
