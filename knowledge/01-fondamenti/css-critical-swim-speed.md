# CSS — Critical Swim Speed

**Ambito:** entrambi
**Solidità:** consolidato (calcolo) · discusso (uso come unica soglia)
**Aggiornato:** 2026-08-16

## In breve

Il CSS è il passo per 100 m che si stima sostenibile a lungo senza cedimento
progressivo. Si ricava da due prove a distanza diversa, ed è il riferimento più
pratico che un nuotatore abbia per impostare le andature senza laboratorio.

## Come funziona

Protocollo classico: 400 m e 200 m a tutta, con recupero completo fra le due
(almeno 10-15 minuti di nuoto blando).

```
CSS (m/s)      = (400 − 200) / (t400 − t200)          con i tempi in secondi
passo CSS/100m = 100 / CSS
```

Esempio: 400 m in 5'20" (320 s), 200 m in 2'32" (152 s).
CSS = 200 / 168 = 1,19 m/s → passo CSS ≈ 1'24"/100 m.

Il modello sottostante è la relazione lineare fra distanza e tempo su prove di
durata media: la pendenza è la velocità critica, l'intercetta la capacità
anaerobica. Con due sole prove l'errore è sensibile alla qualità della più corta.

## Come si misura con i dati disponibili

Serve una prova **dedicata**: due sforzi massimali registrati come attività, nella
stessa vasca e nello stesso giorno. Nei dati storici non esiste un campo "CSS":
va calcolato dalle due sedute o dai loro lap.

Cosa **non** si può fare: dedurre il CSS dalle sedute normali. Un allenamento
misto ha andature troppo diverse perché la media significhi qualcosa.

Finché la Fase 5 non ricostruisce le serie, la prova va registrata come due
attività separate, altrimenti i due tempi non sono estraibili.

## Implicazione operativa

1. **Senza CSS aggiornato, il coach non prescrive andature in secondi.** Parla di
   percezione e di riferimenti relativi, e propone il test.
2. **Ritestare ogni 8-12 settimane**, e comunque dopo un blocco di lavoro
   specifico o una pausa lunga. Un CSS di sei mesi fa descrive un altro atleta.
3. **Il test va fatto nella vasca in cui ci si allena.** Un CSS misurato in 50 m
   non si applica tale e quale agli allenamenti in 25 m: le virate cambiano il
   tempo, non la condizione.
4. **Se il 200 non è davvero massimale, il CSS esce troppo alto** e tutte le
   andature derivate saranno troppo veloci. Un CSS che rende impossibili le serie
   a soglia è quasi sempre un test fatto male, non un calo di forma.

## Limiti e cautele

- Il CSS è una stima di sostenibilità, non una soglia fisiologica misurata.
- Su distanze molto lunghe (5 km e oltre) il passo sostenibile reale è più lento
  del CSS: il modello è tarato su sforzi di 3-30 minuti.
- In acque libere il CSS della piscina non è direttamente applicabile: mancano le
  virate, cambiano il sighting e la resistenza dell'acqua mossa.
- È un solo numero: non descrive la capacità di sprint né la resistenza specifica.

## Fonti

Il metodo nasce da Wakayoshi 1992 [CSS-1]: la velocità critica correla con la
velocità a OBLA (r = 0,949) e con la media del 400 stile (r = 0,864), e
approssima il massimo stato stazionario del lattato [CSS-2]. Non è una
convenzione da bordo vasca.

Il protocollo a due prove è affidabile per l'uso allenante, con la prova corta
come punto più fragile [CSS-3]. **Un modello a due parametri scientificamente
valido vorrebbe 3-7 prove fra 2 e 15 minuti** [CSS-4]: con due sole prove si
ottiene un riferimento di allenamento, non un modello con cui prevedere. È
esattamente il confine che questo progetto tiene fra la velocità critica, che
calcola, e la previsione del tempo di gara, che rifiuta.

Gli scarti in secondi delle andature derivate sono prassi diffusa e concordante
fra le scuole [CSS-5], non un risultato sperimentale.

Elenco completo in [`../_fonti/RIFERIMENTI.md`](../_fonti/RIFERIMENTI.md).

Correlate: [zone-di-intensita.md](zone-di-intensita.md) ·
[tipologie-di-serie.md](../02-piscina/tipologie-di-serie.md)
