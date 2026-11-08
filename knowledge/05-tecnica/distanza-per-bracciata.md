# Distanza per bracciata (DPS)

**Ambito:** entrambi
**Solidità:** consolidato
**Aggiornato:** 2026-08-16

## In breve

La distanza per bracciata dice quanti metri si avanzano a ogni ciclo. Insieme
alla frequenza determina la velocità: `velocità = DPS × frequenza`. È il termine
tecnico più direttamente allenabile, e anche il più facile da migliorare in modo
inutile.

## Come funziona

Aumentare la DPS a parità di frequenza fa andare più forte. Ma la DPS si può
gonfiare rallentando e scivolando: si ottiene un numero migliore e un passo
peggiore. Per questo **non va mai letta da sola**.

Le due letture che contano:

- **DPS a parità di passo.** Se il passo per 100 m è lo stesso e la DPS è
  cresciuta, l'efficienza è migliorata davvero.
- **DPS dentro una serie.** Se cala dalla prima all'ultima ripetuta, la tecnica sta
  cedendo per fatica.

## Come si misura con i dati disponibili

⚠️ **Attenzione: la copertura è molto peggiore di quanto sembri.**

Il campo `avgStrokeDistance` risulta presente su 1.298 sedute di nuoto su 1.306,
ma **735 di quei valori sono zero** — Garmin scrive zero quando non ha il dato.
La copertura reale è quindi **563 sedute su 1.306, cioè il 43%**, e si concentra
nei primi anni: dopo il luglio 2024 il campo smette di essere valorizzato.

Nel progetto gli zeri sono già trattati come valori mancanti: le medie non ne
sono contaminate. Ma il coach deve sapere che su molte sedute recenti la DPS
semplicemente non c'è.

La DPS **dentro** la seduta, ripetuta per ripetuta, richiede i file FIT: arriva
con la Fase 5.

## Implicazione operativa

1. **Non commentare mai la DPS senza il passo.** DPS in aumento con passo in
   peggioramento significa che si sta scivolando, non migliorando.
2. **Prima di dire che la DPS è cambiata, verifica che il dato esista** in
   entrambi i periodi. Su gran parte delle sedute recenti non c'è.
3. **Confronta solo a parità di vasca, stile e attrezzatura.** Le palette alzano
   la DPS artificialmente: una serie con palette non si confronta con una senza.
4. **Il lavoro sulla DPS si fa a bassa intensità**, dove l'atleta può controllare
   il gesto. A velocità alta si allena la frequenza, non la presa.
5. **L'obiettivo non è la DPS massima**, è la combinazione DPS/frequenza più
   economica per la distanza di gara. Su 5 km in mare una frequenza leggermente
   più alta e una DPS più bassa possono essere la scelta giusta.

## Limiti e cautele

- Il conteggio delle bracciate al polso è stimato: sbaglia con acqua mossa,
  palette e stili non a stile libero.
- In acque libere la traiettoria imperfetta gonfia la distanza percorsa e quindi
  la DPS apparente.
- Il valore assoluto dipende dalla statura e dall'apertura delle braccia: ha senso
  solo confrontato con sé stessi.

## Fonti

Da compilare. Correlate: [swolf-lettura-onesta.md](swolf-lettura-onesta.md) ·
[zone-di-intensita.md](../01-fondamenti/zone-di-intensita.md)
