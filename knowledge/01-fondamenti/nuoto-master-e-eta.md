# Nuoto master: cosa cambia con l'età, e cosa no

**Ambito:** entrambi
**Solidità:** consolidato
**Aggiornato:** 2026-08-23

## In breve

L'età non è una spiegazione buona per tutto. Nel nuoto master il calo è
**lento e regolare — circa 0,5-0,6% l'anno fino ai 70 anni** [MAS-1] [MAS-3] — e
non tocca tutte le distanze allo stesso modo. Prima dei 70 anni, un
peggioramento marcato **non è l'età**: è l'allenamento, o qualcos'altro che
merita di essere guardato.

Serve al coach per una cosa precisa: non archiviare come «fisiologico» un calo
che invece è un segnale.

## Come funziona

Tre numeri, tutti da studi longitudinali su campioni master:

- **~0,6% l'anno** fino ai 70-75, poi la curva accelera [MAS-1].
- Fra i **35 e i 60 anni**, ~0,5% l'anno per prova [MAS-3].
- **I 50 m calano più lentamente dei 1500 m** [MAS-2]: la velocità pura si
  conserva meglio della capacità aerobica.

E un dato che vale quanto i tre precedenti: **si può migliorare per decenni.**
Nei dati longitudinali ci sono atleti che diventano primatisti di categoria dopo
anni di pratica continua [MAS-4]. Il calo è la traiettoria di chi allena
costante, non un tetto.

### Il caso che questo archivio mostra

Un ordine di grandezza per capire quanto sia piccolo lo 0,5% l'anno: su un 100
stile da 55"32, sono **0,28 secondi all'anno**. Su otto anni, 2,2 secondi.

Un peggioramento di 3-4 secondi sui 100 in otto anni è quindi *più* di quanto
l'età spieghi. Non è un allarme — la spiegazione più probabile è che il lavoro
si sia spostato altrove — ma non va chiamato invecchiamento.

## Come si misura con i dati disponibili

- **`analysis/race_history.progressions()`** dà il miglior tempo per stagione su
  ogni specialità con almeno tre gare in due stagioni. È la serie storica su cui
  questo confronto si fa.
- Il confronto onesto è **a parità di vasca**: 25 e 50 m non si mescolano.
- **Cosa non si può fare:** separare l'effetto dell'età da quello del volume di
  allenamento. Sono confusi fra loro in qualunque archivio di una persona sola,
  e nessuna analisi di questo progetto può districarli.

## Implicazione operativa

1. **Non attribuire all'età un calo prima dei 70 anni senza confrontarlo con lo
   0,5-0,6% l'anno.** Se il calo osservato è più grande, la spiegazione è
   altrove: volume, specificità, continuità, o una pausa.
2. **Sprint e fondo si leggono separatamente.** Un calo sui 50-100 con un
   miglioramento sul 400-1500 non è un peggioramento: è uno spostamento di
   specialità, e se l'obiettivo dichiarato è il fondo è la direzione giusta.
3. **Un miglioramento a 30 anni non è un'anomalia da spiegare.** [MAS-4] dice
   che è normale in chi allena costante. Il coach non deve trattarlo come un
   dato sospetto.
4. **Quando l'atleta chiede «sto peggiorando?», la risposta ha due parti:**
   quanto è cambiato il tempo, e quanto ne spiegherebbe l'età. Solo la seconda
   trasforma un numero in un'informazione.

## Limiti e cautele

- Le percentuali vengono da **campioni master di alto livello**, che allenano
  con continuità. Su chi si allena a intermittenza il rumore è molto più grande
  del segnale annuale.
- Il calo è **lineare in media**: la traiettoria di una singola persona ha salti
  legati a infortuni, pause, cambi di lavoro e di vita.
- Le differenze fra i sessi esistono sui 50 m e non sui 1500 [MAS-2]: le
  percentuali sopra sono quelle maschili.
- Un anno solare con **una sola gara** su una distanza non è una stagione
  misurata: è un'osservazione.

## Fonti

[MAS-1], [MAS-2], [MAS-3], [MAS-4] in
[`../_fonti/RIFERIMENTI.md`](../_fonti/RIFERIMENTI.md).

Correlate: [css-critical-swim-speed.md](css-critical-swim-speed.md) ·
[periodizzazione.md](../06-gara-e-taper/periodizzazione.md)
