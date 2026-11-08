# Guida — apri, guarda, approfondisci, correggi

Una pagina sola. Se serve di più, è l'applicazione a essere sbagliata.

Versione integrata ottobre 2026: calendario, programmazione, monitoraggio
approfondito e coach OpenAI sono descritti nel [RUNBOOK](../RUNBOOK.md).

---

## Aprire

**Doppio clic su `Garmin Coach.cmd`**, nella cartella del progetto.

Si apre una finestra nera e, subito dopo, il browser su `http://127.0.0.1:8766`.
La finestra nera è il programma: finché resta aperta, l'app funziona. Per
chiudere tutto, chiudi quella finestra.

La consultazione e la lettura locale funzionano offline. Sincronizzazione
Garmin e coach OpenAI richiedono Internet e usano gli accessi gia configurati;
il pacchetto analitico OpenAI e stato autorizzato dall'atleta.

> Se la porta 8766 è occupata da qualcos'altro:
> `.\.venv\Scripts\python.exe -m garmin_coach app --port 8790`

---

## Guardare

Sei aree in cima, sempre le stesse. Una settima compare solo quando serve.

| Area | Risponde a |
|---|---|
| **Oggi** | C'è qualcosa che merita la mia attenzione? |
| **Settimana** | Com'è andata la settimana, e cosa cambio nella prossima? |
| **Sedute** | Che cosa è successo davvero in questa seduta? |
| **Progressi** | Quando mi sono trovato in una situazione simile, cosa è successo? |
| **Gare** | Quali tempi ho fatto davvero, in vasca e in mare, e come vado nel tempo? |
| **Chiedi** | Posso fare una domanda non prevista dal menu? |
| **Da decidere** | C'è un dato che non torna e su cui devo dire io come stanno le cose? |

**«Da decidere» compare nel menu solo quando c'è qualcosa da decidere.** Se non
lo vedi, non c'è niente in sospeso: non è nascosto, è vuoto.

**La prima riga di ogni pagina dice fino a quando arrivano i dati.** Se c'è
scritto «i dati si fermano al 15/08», il resto della pagina parla del 15 agosto,
non di oggi. È l'informazione più importante della schermata.

**Ogni pagina mette una sola osservazione in cima.** Sotto ci sono le prove, poi
cosa non concorda, poi i limiti. Se hai fretta, ti bastano le prime tre righe.

**Il pulsante `Perché?`** in fondo apre, per ogni numero, da dove viene, con che
formula, in quale unità, su quanti casi e con quale versione del metodo.

---

## Approfondire

Nella pagina **Chiedi** trovi due o tre domande già scritte, con dentro il
periodo e gli identificativi giusti. **La risposta arriva nella pagina**: non
c'è niente da copiare e niente da incollare altrove.

Prima che parta, la pagina ti mostra **esattamente cosa uscirebbe dal computer**
— il pacchetto di evidenze, aperto, in chiaro. Esce solo quando premi il
pulsante, e passa dall'abbonamento a Claude che hai già: nessuna chiave,
nessuna spesa a consumo.

Se l'accesso a Claude è scaduto, la pagina risponde lo stesso con il **cervello
locale** e te lo dice. Il cervello locale applica regole scritte agli stessi
fatti: sa dire cosa dicono i dati, non sa rispondere *a questa* domanda invece
che a un'altra. La pagina dichiara sempre chi sta rispondendo.

Il campo della domanda non è libero, ed è voluto: un campo libero verso un
modello è il posto naturale in cui qualcun altro può scrivere istruzioni.

---

## Correggere

Nella pagina **Gare** c'è il modulo per confermare un tempo — gara, test o
allenamento a tutta. Le gare ufficiali entrano già da sole: quelle in vasca da
`coach/aquatime/`, quelle in mare da `coach/icron/`. Il modulo serve per i tempi
che non stanno in nessun archivio ufficiale.

**Le gare che nessun archivio contiene** — un event02 all'estero, un circuito
che Icron non cronometra — si scrivono in
[coach/gare-dichiarate.md](../coach/gare-dichiarate.md). Non è un ripiego: sono
gare vere, e senza di esse il coach conta quello che vede invece di quello che
hai nuotato. In fondo a quel file trovi già l'elenco delle tue nuotate in mare
oltre i 5 km che l'archivio non conosce come gare.

Nella pagina **Da decidere**, quando compare, trovi le registrazioni su cui il
coach ha un dubbio: cosa dice l'orologio, come sta rispetto a tutte le altre
tue sedute, e tre pulsanti per dire come stanno le cose.

Funziona così: compili, vedi **l'anteprima di quello che verrà scritto**, e solo
allora confermi. Finisce in `coach/riferimenti.md`, che puoi anche aprire e
modificare a mano.

Un tempo lì dentro è un fatto che dichiari tu. Il coach può proporti un
candidato che ha visto nei dati, ma non promuove da solo una nuotata veloce a
prova massimale: quel giudizio è tuo.

---

## Quando qualcosa non va

| Cosa vedi | Cosa vuol dire | Cosa fare |
|---|---|---|
| «Il database è occupato» | il sync automatico lo sta riscrivendo | ricarica fra un minuto |
| «Il database non esiste ancora» | mai costruito, o cancellato | `.\.venv\Scripts\python.exe -m garmin_coach rebuild` |
| «i dati si fermano al …» | il sync non gira da un po' | `.\.venv\Scripts\python.exe -m garmin_coach sync` |
| «Il modulo è scaduto» | l'app è stata riavviata mentre il modulo era aperto | ricarica la pagina |
| La pagina non si apre | il programma non è partito | guarda la finestra nera: l'errore è lì |

Per capire come sta il progetto, senza contattare Garmin:

```
.\.venv\Scripts\python.exe -m garmin_coach snapshot
```

---

## Cosa questa applicazione non fa, per scelta

- **Non ti dice cosa allenare.** Gli allenamenti li decide il tuo allenatore.
  Questo è un secondo parere sui dati, e serve a darti le domande giuste da
  portargli.
- **Non fa diagnosi e non prevede infortuni.** Descrive scostamenti, e dice su
  quanti casi.
- **Non inventa numeri.** Quando i dati non bastano, scrive «dati insufficienti»
  e spiega cosa manca.
- **Non scrive su Garmin.** Mai, in nessun caso.
- **Non manda niente a nessuno.** Nessuna telemetria, nessun account, nessuna
  chiamata verso l'esterno.
