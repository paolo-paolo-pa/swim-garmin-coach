# Temperatura dell'acqua e muta

**Ambito:** acque libere
**Solidità:** consolidato (effetti) · discusso (soglie individuali)
**Aggiornato:** 2026-08-16

## In breve

La temperatura dell'acqua cambia la prestazione più di quasi ogni altra variabile
ambientale, e cambia anche la sicurezza. La muta modifica assetto, galleggiamento
e dispersione termica: una prova con muta e una senza non sono confrontabili.

## Come funziona

**Effetti del freddo.** Sotto i 18-20 °C aumentano la frequenza cardiaca iniziale,
la frequenza respiratoria e la rigidità della bracciata. Nei primi 2-5 minuti la
risposta al freddo può dare iperventilazione: è normale e passa, ma va attesa con
calma, non combattuta.

**Effetti del caldo.** Sopra i 26-28 °C la dispersione termica diventa difficile
anche in acqua. Su prove lunghe è il caso in cui l'idratazione conta davvero.

**Effetti della muta.** Aumenta il galleggiamento e migliora l'assetto: il passo
migliora, tipicamente in modo apprezzabile, senza che l'atleta sia migliorato.
Riduce la mobilità della spalla: su prove lunghe può cambiare la meccanica e
affaticare in modo diverso.

I regolamenti fissano soglie di obbligo e divieto della muta che variano per
federazione e per manifestazione: vanno lette per la gara specifica, non assunte.

## Come si misura con i dati disponibili

**Non si misura.** I riepiloghi contengono `maxTemperature` e `minTemperature`, ma
sulle sedute di nuoto sono quasi sempre assenti o riferiti alla temperatura del
dispositivo, non dell'acqua. Il campo `waterEstimated` esiste ma non è affidabile
per questo uso.

L'uso della muta non è registrato da nessuna parte.

Entrambi sono **input dell'atleta**: vanno scritti nelle note della gara in
`coach/gare.md` o nel diario con `log_write`. Senza, il confronto fra due prove in
mare non è valido e il coach deve dirlo.

## Implicazione operativa

1. **Prima di commentare una prova in acque libere, chiedi temperatura e muta.**
   Senza, non si confronta con niente.
2. **Non attribuire all'atleta un miglioramento ottenuto con la muta.** Se una
   prova era con muta e l'altra no, il confronto tecnico va rifiutato, come si
   rifiuta un confronto fra dispositivi diversi.
3. **In acqua fredda, i primi minuti vanno programmati:** ingresso graduale,
   partenza sotto ritmo, aspettare che la respirazione si stabilizzi prima di
   cercare il passo.
4. **Se si gareggia con la muta, ci si allena con la muta** almeno alcune volte:
   la mobilità di spalla vincolata va abituata, non scoperta in gara.
5. **La sicurezza viene prima della prestazione.** Acqua fredda, sola, senza
   assistenza o senza boa di segnalazione è una scelta che il coach non asseconda.

## Limiti e cautele

- La tolleranza al freddo è molto individuale e cambia con la composizione
  corporea e l'abitudine: le soglie indicate sono orientative.
- Il tempo di esposizione conta quanto la temperatura: 19 °C per 20 minuti e per
  due ore sono situazioni diverse.
- Nulla in questa scheda è un parere medico. L'ipotermia è un'emergenza sanitaria.

## Fonti

Da compilare. Servono i regolamenti specifici delle gare a cui l'atleta partecipa.
Correlate: [pacing-acque-libere.md](pacing-acque-libere.md)
