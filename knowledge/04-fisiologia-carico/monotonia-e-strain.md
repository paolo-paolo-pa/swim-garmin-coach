# Monotonia e strain

**Ambito:** entrambi
**Solidità:** discusso
**Aggiornato:** 2026-08-16

## In breve

La monotonia misura quanto una settimana è uniforme. Lo strain combina quanto si
è caricato con quanto poco si è variato. Sono spesso più informativi dell'ACWR,
perché catturano l'errore più comune nel nuoto: allenarsi sempre uguale, sempre
al medio, senza né stimoli veri né recuperi veri.

## Come funziona

```
monotonia = media del carico giornaliero (7 gg) / deviazione standard (7 gg)
strain    = carico acuto 7 giorni × monotonia
```

I giorni di riposo contano come zero: sono ciò che genera la variabilità. Una
settimana con un giorno di riposo vero ha monotonia più bassa — e migliore — di
una settimana in cui si nuota poco tutti i giorni.

| Monotonia | Lettura |
|---|---|
| < 1,5 | settimana ben articolata, carichi differenziati |
| 1,5 - 2,0 | uniforme, da tenere d'occhio |
| > 2,0 | molto uniforme: stimoli poco distinti, recuperi poco veri |

## Come si misura con i dati disponibili

Dipende dal carico Garmin, quindi vale **dal 2021 in poi**, su circa metà della
storia. Il valore è calcolato su finestre di calendario, non su righe: i giorni
senza attività entrano nel conto.

La deviazione standard nulla — carico identico per sette giorni — non produce
monotonia infinita ma **nessun valore**: una grandezza non definita non va
pubblicata come numero enorme.

## Implicazione operativa

1. **Monotonia alta + carico alto è il segnale da prendere sul serio**, più
   dell'ACWR isolato. È la combinazione che precede l'accumulo di fatica.
2. **La cura è la variazione, non la riduzione.** Prima di tagliare il volume,
   differenzia: una seduta davvero dura, una davvero blanda, un giorno di riposo
   completo.
3. **Un giorno di riposo abbassa la monotonia e migliora la settimana** anche a
   parità di volume totale. È l'argomento più semplice contro il "nuoto un po'
   tutti i giorni".
4. **Se la monotonia sale mentre il volume sale, fermare l'incremento** e
   ridistribuire prima di aggiungere altro.

## Limiti e cautele

- Su una finestra di sette valori la deviazione standard è instabile: piccole
  variazioni cambiano molto il risultato. Leggi la tendenza su più settimane, non
  il valore del giorno.
- Le soglie 1,5 e 2,0 sono convenzioni riprese dalla letteratura sul training
  monitoring, non costanti fisiologiche.
- Come per l'ACWR: nessuna previsione di infortunio.

## Fonti

Da compilare. Il concetto risale al lavoro di Foster sul monitoraggio del carico
con session-RPE. Correlate: [carico-acuto-cronico.md](carico-acuto-cronico.md) ·
[progressione-del-volume.md](../02-piscina/progressione-del-volume.md)
