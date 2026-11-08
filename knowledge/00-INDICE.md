# Knowledge — la competenza di nuoto del coach

Questa cartella è ciò che trasforma un lettore di dati in un allenatore. I dati dicono
*cosa è successo*; questa cartella dice *cosa significa e cosa farne*.

Il coach legge questi file come contesto. Sono markdown: si aggiungono e si correggono
scrivendo testo, senza toccare una riga di codice.

---

## Regola d'oro della knowledge

> **Nessuna scheda entra qui se non finisce con un'implicazione operativa.**

Una nozione che non cambia una decisione di allenamento non serve al coach: occupa
contesto e diluisce quello che conta. Se non sai scrivere l'implicazione operativa,
la nozione non è ancora stata capita abbastanza.

Corollario: **il PDF non è conoscenza.** Un articolo scaricato in `_fonti/` non viene
letto dal coach. Diventa utile solo quando qualcuno lo distilla in una scheda.

---

## Formato obbligatorio di una scheda

Un file = un concetto. Nome del file in kebab-case, descrittivo.

```markdown
# Titolo del concetto

**Ambito:** piscina | acque libere | entrambi
**Solidità:** consolidato | discusso | sperimentale
**Aggiornato:** AAAA-MM-GG

## In breve
Due o tre righe. Cosa è, in italiano piano.

## Come funziona
Il meccanismo. Formule se ci sono, con unità di misura esplicite.

## Come si misura con i dati disponibili
Quali campi Garmin servono, quali no. Cosa NON si può misurare
con i dati che abbiamo — questa parte è importante quanto le altre.

## Implicazione operativa          ← OBBLIGATORIA
Cosa deve fare o dire il coach quando osserva X. In forma di regola:
"se ... allora ...". Meglio 3 righe nette che 30 di contesto.

## Limiti e cautele
Quando questa regola non vale. Errori tipici di interpretazione.

## Fonti
Riferimenti in `_fonti/`, con anno e tipo (studio / libro / prassi allenatoriale).
```

**Livello di solidità** — va dichiarato sempre, il coach lo usa per calibrare il tono:

| Etichetta | Significato | Come lo usa il coach |
|---|---|---|
| `consolidato` | Prassi condivisa, base fisiologica solida | Lo afferma |
| `discusso` | Evidenza contrastante o dibattito aperto | Lo propone dichiarando l'incertezza |
| `sperimentale` | Frontiera, poche prove, promettente | Lo menziona come ipotesi, mai come base di un piano |

---

## Mappa della cartella

| Cartella | Contenuto | Domande a cui serve |
|---|---|---|
| **01-fondamenti/** | Energetica del nuoto, zone, CSS, terminologia | "Cosa vuol dire soglia per un nuotatore?" |
| **02-piscina/** | Metodologia in vasca, tipologie di serie, densità, recuperi | "Che serie ha senso oggi?" |
| **03-acque-libere/** | Pacing, sighting, temperatura, correnti, alimentazione, drafting | "Come imposto una 5 km in mare?" |
| **04-fisiologia-carico/** | ACWR, monotonia, HRV, sonno, supercompensazione, sovrallenamento | "Sto accumulando troppo?" |
| **05-tecnica/** | SWOLF, DPS, stroke rate, lettura onesta dei dati tecnici | "Il mio SWOLF è peggiorato: è vero?" |
| **06-gara-e-taper/** | Periodizzazione, scarico, strategia gara, riscaldamento | "Come arrivo alla gara del 12 ottobre?" |
| **07-frontiera/** | Ricerca recente non ancora consolidata | "Vale la pena provare X?" |
| **_fonti/** | [`RIFERIMENTI.md`](_fonti/RIFERIMENTI.md) è la bibliografia, con sigle e peso di ogni fonte. Il resto è materiale grezzo | il coach legge i riferimenti, non il grezzo |

---

## Indice delle schede

> Si aggiorna a ogni scheda aggiunta. Se una scheda non è qui, per il coach non esiste.

**20 schede scritte** su ~25 previste, più la bibliografia. Le schede spuntate sono utilizzabili dal
coach; quelle senza spunta non esistono ancora e vanno dichiarate come mancanti
se una domanda le tocca.

### 01 — Fondamenti
- [x] [`energetica-del-nuoto.md`](01-fondamenti/energetica-del-nuoto.md) — sistemi energetici e loro peso per durata
- [x] [`css-critical-swim-speed.md`](01-fondamenti/css-critical-swim-speed.md) — protocollo, calcolo, quando ritestare
- [x] [`zone-di-intensita.md`](01-fondamenti/zone-di-intensita.md) — zone sul passo; perché in acqua la FC mente
- [x] [`nuoto-master-e-eta.md`](01-fondamenti/nuoto-master-e-eta.md) — 0,5-0,6% l'anno: quanto l'età spiega davvero
- [ ] `terminologia.md` — glossario condiviso atleta/coach

### 02 — Piscina
- [x] [`tipologie-di-serie.md`](02-piscina/tipologie-di-serie.md) — soglia, VO2max, velocità, resistenza specifica, tecnica
- [x] [`densita-e-recuperi.md`](02-piscina/densita-e-recuperi.md) — come il recupero cambia lo stimolo a parità di serie
- [x] [`progressione-del-volume.md`](02-piscina/progressione-del-volume.md) — quanto e come si sale, sulla propria storia
- [x] [`struttura-della-seduta.md`](02-piscina/struttura-della-seduta.md) — leggere serie e blocchi dai lap, e quando rifiutarsi
- [ ] `attrezzatura.md` — palette, pull buoy, pinne, snorkel: quando servono davvero

### 03 — Acque libere
- [x] [`pacing-acque-libere.md`](03-acque-libere/pacing-acque-libere.md) — strategia, sighting, limiti del GPS
- [x] [`temperatura-e-muta.md`](03-acque-libere/temperatura-e-muta.md) — effetti su FC, pacing, sicurezza
- [x] [`dal-passo-in-vasca-al-passo-in-mare.md`](03-acque-libere/dal-passo-in-vasca-al-passo-in-mare.md) — il 92% della velocità critica, e perché è preso in prestito
- [ ] `alimentazione-e-idratazione.md` — lunghe distanze
- [ ] `drafting.md` — posizioni, risparmio energetico

### 04 — Fisiologia e carico
- [x] [`carico-acuto-cronico.md`](04-fisiologia-carico/carico-acuto-cronico.md) — ACWR: cosa dice davvero e cosa no
- [x] [`monotonia-e-strain.md`](04-fisiologia-carico/monotonia-e-strain.md) — l'indicatore più utile e meno guardato
- [x] [`hrv-interpretazione.md`](04-fisiologia-carico/hrv-interpretazione.md) — baseline personale, cosa NON significa
- [x] [`sonno-e-recupero.md`](04-fisiologia-carico/sonno-e-recupero.md) — l'unico dato di recupero coperto quasi ovunque
- [x] [`segnali-di-sovraccarico.md`](04-fisiologia-carico/segnali-di-sovraccarico.md) — la regola della convergenza

### 05 — Tecnica
- [x] [`swolf-lettura-onesta.md`](05-tecnica/swolf-lettura-onesta.md) — confrontabile solo a parità di condizioni
- [x] [`distanza-per-bracciata.md`](05-tecnica/distanza-per-bracciata.md) — DPS e il compromesso con la frequenza
- [ ] `stroke-rate.md`
- [ ] `decadimento-tecnico-in-fatica.md` — richiede la Fase 5

### 06 — Gara e taper
- [x] [`periodizzazione.md`](06-gara-e-taper/periodizzazione.md) — macro, meso, micro
- [x] [`taper.md`](06-gara-e-taper/taper.md) — durata e riduzione di volume per priorità
- [ ] `strategia-gara.md`
- [ ] `riscaldamento-pre-gara.md`

### 07 — Frontiera
- [ ] `da-valutare.md` — parcheggio di idee non ancora verificate

### Cosa manca di più

Le lacune che il coach incontrerà per prime:

1. **Alimentazione e idratazione** in acque libere lunghe — serve prima di una
   gara oltre l'ora.
2. **Attrezzatura** — l'atleta usa palette e pull buoy, e cambiano la lettura di
   SWOLF e distanza per bracciata.
3. **Fonti — non più la lacuna principale.** Il 23/08/2026 è stata scritta la
   bibliografia in [`_fonti/RIFERIMENTI.md`](_fonti/RIFERIMENTI.md), con sigle,
   anno, link e il **peso** di ogni fonte rispetto a *questo* atleta: diretto,
   trasferito o prassi. Sei schede la citano. Le altre restano da agganciare.

   Due cose sono cambiate di sostanza, non di forma: `carico-acuto-cronico`
   adesso dichiara che **l'ACWR non predice gli infortuni** [ACWR-1], e `taper`
   ha numeri veri al posto di una convenzione [TAPER-1].

---

## Come alimentare questa cartella

1. **Materiale grezzo** → `_fonti/` (PDF, link, appunti, screenshot). Nessun vincolo di formato.
2. **Distillazione** → si chiede al coach: *"leggi `_fonti/X` e proponi una scheda per `04-fisiologia-carico/`"*.
3. **Revisione umana** → l'atleta corregge, soprattutto l'implicazione operativa.
4. **Indicizzazione** → la scheda va spuntata qui sopra.

Le schede possono **contraddirsi** se la letteratura è in disaccordo: in quel caso si
dichiara `discusso` e si espongono entrambe le posizioni. Il coach preferisce
un'incertezza dichiarata a una certezza inventata (Regola Aurea n.5).

---

## Cosa NON mettere qui

- Dati dell'atleta (vanno in `coach/`)
- Piani di allenamento specifici (vanno in `coach/piano.md`)
- Copie integrali di libri o articoli protetti da copyright — in `_fonti/` vanno
  riferimenti, estratti brevi e appunti propri
