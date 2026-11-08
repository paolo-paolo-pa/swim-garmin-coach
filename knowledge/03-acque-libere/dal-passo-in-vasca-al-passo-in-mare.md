# Dal passo in vasca al passo in mare

**Ambito:** acque libere
**Solidità:** discusso — la relazione è misurata, ma su nuotatori d'élite
**Aggiornato:** 2026-08-23

## In breve

Per nove mesi questo progetto ha rifiutato di collegare i tempi in piscina a un
obiettivo in mare, e aveva ragione: senza una misura di quel salto, ricavare il
secondo dal primo sarebbe stata un'invenzione. **Ora la misura esiste** [OW-1], e
dice due cose precise: quanto si perde passando dalla vasca al mare, e a che
frazione della propria velocità critica si nuota davvero una 10 km.

Resta una relazione **misurata su altri**, e va usata come banda di riferimento,
mai come il tempo che farai.

## Come funziona

Ai Mondiali 2023, su 65 uomini nella 10 km, la velocità critica di ciascuno è
stata ricavata dai suoi migliori tempi in vasca su 400, 800 e 1500 [OW-1]:

| Chi | Frazione della propria velocità critica tenuta in gara |
|---|---|
| **posti 1-10** | **≈ 92,3%**, tenuto per tutta la gara |
| posti 31-47 | da 97,6% al primo giro a 88,4% all'ultimo |
| posti 48-65 | da 96,1% al primo giro a 85,1% all'ultimo |

Due conclusioni, e la seconda conta più della prima:

1. **Il tetto è attorno al 92%.** Chi va forte in mare non tiene la propria
   soglia da piscina: ne tiene poco più di nove decimi. Onde, sighting,
   traiettoria mai dritta e assenza di muri costano quella quota.
2. **Chi parte sopra il 96% finisce sotto l'88%.** Non è una differenza di
   motore: è una differenza di partenza. Gli ultimi partono più vicini alla
   propria soglia dei primi, e pagano.

Lo stesso studio misura il salto in modo diretto: il tempo stimato dalla
prestazione in vasca risulta **circa 9,5% più veloce** di quello realmente
nuotato in mare.

Sulla forma della gara, [OW-2] aggiunge che chi va a medaglia nuota **regolare**
e accelera dell'**1,5-3% nell'ultimo quarto**, mentre chi parte forte chiude in
calando.

## Come si misura con i dati disponibili

- **La velocità critica c'è**, calcolata da `analysis/critical_speed.py` sulle
  gare in vasca della federazione, ed è aggiornata al 2026.
- **Le gare in mare ci sono**, 25 dal 2016, ma con una differenza che questa
  scheda non può ignorare: in mare **la distanza è dichiarata dagli
  organizzatori, non misurata**. Il passo che se ne ricava è un tempo diviso per
  un numero che nessuno ha verificato, e su tre percorsi su diciannove quel
  numero non regge (vedi la migrazione 0009).
- **Quello che manca:** una gara in mare di questo atleta con distanza
  affidabile *e* vicina nel tempo a una coppia 400/200 in vasca. Senza, la
  frazione del 92% non è verificabile su di lui: è presa in prestito.
- **L'archivio non è la sua storia.** Icron cronometra il proprio circuito e
  nient'altro: place05 è l'unica delle sue gare lunghe che espone. Le altre
  cinque — place23, place19-place28, due edizioni della Traversata del lake01 e place21 — sono in `coach/gare-dichiarate.md`, trovate incrociando
  distanza, nome del luogo e ricognizioni del giorno prima, ma **senza tempo
  ufficiale** non contano ancora come osservazioni: `open_water_pace.py` legge
  solo gare con un tempo, e uno inventato dall'orologio sarebbe peggio di uno
  mancante. Finché quei tempi non arrivano, ogni frase costruita sulle gare in
  mare deve dire **quante ne ha viste il calcolo**, non quante l'atleta ne
  abbia nuotate.

## Implicazione operativa

1. **Il passo obiettivo in mare si esprime come banda, non come numero.**
   Dal CSS in vasca: la banda ragionevole è fra il **90% e il 93%** della
   velocità critica. Sotto il 90% si sta lasciando qualcosa; sopra il 93% si sta
   scrivendo una gara che i dati dicono di non riuscire a tenere.
2. **Non è una previsione del tempo finale.** È il passo con cui ha senso
   *partire*. Il tempo lo fanno anche corrente, temperatura, boe e chi ti sta
   davanti.
3. **Se il passo obiettivo dichiarato dall'atleta è più lento della banda, non
   va corretto in silenzio**: va messo accanto, con la differenza scritta. Un
   obiettivo prudente è una scelta legittima, e può contenere informazioni che i
   dati non hanno.
4. **La regola di gara che vale per lui è la partenza.** Il dato che si
   trasferisce da élite a master non è la tattica di gruppo, è che *partire
   vicino alla propria soglia costa la seconda metà*. Partire nella parte bassa
   della banda e verificare al primo terzo.
5. **La verifica in allenamento esiste ed è specifica:** una frazione della
   distanza di gara, in mare, al passo della banda, osservando se il passo tiene
   e cosa succede a fatica percepita e recupero nelle 24-72 ore. È la prova che
   il coach deve proporre, ed è l'unica che trasformi la banda presa in prestito
   in un numero suo.

## Limiti e cautele

- **La popolazione è sbagliata, ed è il limite principale.** Sono uomini d'élite
  a un Mondiale, non master. Un master allena meno ore e ha un divario maggiore
  fra velocità pura e resistenza specifica: la frazione sostenibile potrebbe
  essere diversa, e nessuno l'ha misurata su questa popolazione.
- **La velocità critica dello studio è ricavata da 400, 800 e 1500**; quella di
  questo progetto da 400 e 200. Sono due stime della stessa cosa, e quella su
  due sole prove è più sensibile alla prova corta [CSS-3]. Fra le due, la
  seconda tende a uscire **più alta** — quindi la banda in metri al secondo
  tende a essere ottimistica.
- **Una gara singola non valida il modello.** Se il passo tenuto a place22 cadrà
  dentro la banda, sarà un caso favorevole, non una conferma.
- Nulla di tutto questo autorizza a **prevedere un tempo finale**. Per quello
  servirebbe un backtest che batta una regola banale, e su una gara sola non si
  può fare.

## Fonti

[OW-1], [OW-2], [OW-3], [CSS-3], [CSS-4] in
[`../_fonti/RIFERIMENTI.md`](../_fonti/RIFERIMENTI.md).

Correlate: [pacing-acque-libere.md](pacing-acque-libere.md) ·
[css-critical-swim-speed.md](../01-fondamenti/css-critical-swim-speed.md) ·
[temperatura-e-muta.md](temperatura-e-muta.md)
