# Zone di intensità nel nuoto

**Ambito:** entrambi
**Solidità:** consolidato (principio) · discusso (numero e confini delle zone)
**Aggiornato:** 2026-08-16

## In breve

Nel nuoto l'intensità si governa con il **passo**, non con la frequenza cardiaca.
L'acqua cambia la risposta cardiaca — posizione orizzontale, pressione idrostatica,
apnea parziale, termoregolazione — e il polso al polso bagnato misura male. Il
passo per 100 m riferito al CSS è il riferimento primario; la FC è un controllo,
non un obiettivo.

## Come funziona

Cinque zone costruite sul passo CSS, con i secondi riferiti a 100 m:

| Zona | Passo rispetto al CSS | Cosa allena | Durata tipica delle ripetute |
|---|---|---|---|
| **A1** recupero | CSS + 10 s o più | recupero attivo, tecnica | 100-400 m continui |
| **A2** aerobico | CSS + 5-10 s | base aerobica, volume | 200-800 m |
| **A3** soglia | CSS ± 2 s | tolleranza al lattato stabile | 100-400 m, serie lunghe |
| **VO2** massimale | CSS − 3-6 s | potenza aerobica | 50-200 m, recuperi ampi |
| **SP** velocità | massimale | reclutamento, tecnica in velocità | 15-50 m, recupero completo |

I confini sono convenzionali: cambiano per specialità e per storia dell'atleta.
Vanno usati come punti di riferimento, non come frontiere.

## Come si misura con i dati disponibili

- **Passo:** ricavabile da `distance_m` e `duration_s` di ogni seduta, disponibile
  al 100% su tutti e nove gli anni. È il dato più solido che l'atleta abbia.
- **Frequenza cardiaca:** presente solo dal 2021, e su circa il 60% delle sedute.
  Le zone cardiache (`hrTimeInZone`) esistono di fatto solo dal 2025.
- **Zone Garmin memorizzate:** la tabella `hr_zones` contiene i limiti impostati
  sull'orologio, calcolati sulla riserva cardiaca. Sono tarati per la corsa, non
  per il nuoto.

Cosa **non** si può fare finché le serie non sono ricostruite (Fase 5): sapere
quanto di una seduta è stato nuotato in ciascuna zona. Il passo medio di una
seduta mista non dice in che zone si è lavorato.

## Implicazione operativa

1. **Prescrivi in passo, controlla in percezione.** "8×100 al passo CSS, partenza
   ogni 1'45"" è verificabile; "8×100 in zona 3" non lo è, in acqua.
2. **Non usare le zone cardiache Garmin per giudicare una seduta di nuoto.** Sono
   costruite su parametri di corsa e in acqua la FC è compressa di 5-15 bpm a
   parità di sforzo.
3. **Se manca il CSS, l'unica zonizzazione onesta è per percezione** (CR10) e per
   confronto con sedute simili recenti.
4. **La distribuzione dell'intensità è una questione di volume, non di singola
   seduta.** Il grosso del lavoro sta in A2; le zone alte occupano una quota
   piccola e vanno protette con recuperi veri.

## Limiti e cautele

- La FC in acqua è indicativa: usare le variazioni, non i valori assoluti.
- Il numero di zone (3, 5, 7) è convenzione: cambiare sistema cambia le etichette,
  non la fisiologia.
- Il passo in acque libere non è confrontabile con quello in piscina: corrente,
  onde e traiettoria imperfetta lo alterano più della condizione dell'atleta.

## Fonti

I numeri sulla compressione della frequenza cardiaca in acqua sono misurati, non
stimati: la FC massima in nuoto è **6,7 ± 5,3 bpm più bassa** che nella corsa in
nuotatori allenati [FC-1], la raccomandazione pratica su nuotatori amatoriali è
di togliere **12 bpm** [FC-2], e a parità di consumo di ossigeno la FC in acqua
è **10-15 bpm più bassa** [FC-3]. È la ragione per cui le zone dell'orologio,
tarate a secco, non descrivono una seduta di nuoto.

La nomenclatura A1/A2/B1/B2/C1 viene dalla classificazione British Swimming
[ZONE-1]; sul fatto che i confini vadano individualizzati e non presi come
numeri fissi, [ZONE-2]. Gli scarti in secondi rispetto al CSS sono prassi
concordante [CSS-5].

Elenco completo in [`../_fonti/RIFERIMENTI.md`](../_fonti/RIFERIMENTI.md).

Correlate: [css-critical-swim-speed.md](css-critical-swim-speed.md) ·
[energetica-del-nuoto.md](energetica-del-nuoto.md) ·
[pacing-acque-libere.md](../03-acque-libere/pacing-acque-libere.md)
