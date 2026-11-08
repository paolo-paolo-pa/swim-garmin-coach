# REGOLE AUREE

> Queste regole vincono su qualsiasi altra considerazione: eleganza tecnica,
> completezza, performance, "si fa sempre così". Se una scelta viola una regola
> aurea, la scelta è sbagliata anche se il codice funziona.

---

## REGOLA AUREA N.1 — Chiarezza per un umano

**Tutto deve essere sempre pulito, ordinato e immediatamente comprensibile da un
essere umano che apre la cartella per la prima volta.**

Test di verifica, da applicare a ogni modifica:

> Una persona competente ma che non conosce il progetto apre
> `%USERPROFILE%\Desktop\Claude\Garmin`.
> In **2 minuti**, senza chiedere niente a nessuno, capisce cosa fa il progetto,
> dove sono i dati, dove si mette mano e come si esegue?
>
> Se no, la struttura è sbagliata. Si sistema la struttura, non si aggiunge
> documentazione per spiegare il disordine.

Conseguenze operative, non negoziabili:

0. **Una sola radice.** Tutto il progetto — codice, dati sorgente, database, documenti,
   memoria — vive in `%USERPROFILE%\Desktop\Claude\Garmin` e in nessun altro posto.
   Un file utile al progetto trovato fuori da questa cartella è un errore da correggere
   subito, non una comodità. Se serve una copia, quella è un **backup**: sta su un disco
   esterno o in cloud, mai come secondo albero di lavoro sullo stesso computer.
1. **Un file, uno scopo.** Se devi usare "e" per descrivere cosa fa un file, va diviso.
2. **Il nome dice il contenuto.** Niente `utils.py`, `misc/`, `varie.md`, `temp2_final.py`.
3. **Niente prefissi numerici sulle cartelle di progetto** (`00_CONFIG`, `01_INVENTORY`…).
   Ordinano l'occhio ma nascondono il significato. Eccezione ammessa: la cartella
   `knowledge/`, dove la numerazione è un indice didattico voluto.
4. **Niente file orfani.** Ogni file è raggiungibile da `README.md` in massimo 2 salti.
5. **Niente artefatti generati nel repo.** Database, report, snapshot privati, `.venv`,
   `__pycache__` e pacchetti vendorizzati stanno in `data/` o fuori, mai mescolati al
   codice. Dentro `data/`, `raw/` è append-only e `staging/` è cancellabile: non sono la
   stessa cosa.
6. **Niente cartelle vuote "per il futuro".** Si creano quando servono.
7. **Niente doppioni.** Un file esiste in un posto solo. Se serve altrove, si linka.
8. **Si cancella.** Codice morto, documenti superati, tentativi abbandonati vengono
   rimossi, non commentati e non rinominati `_old`. La cronologia sta in git.

---

## REGOLA AUREA N.2 — Prima il coach, poi i dati

**Ogni riga di codice deve essere giustificabile da una domanda che l'atleta
fa davvero.**

Prima di costruire qualcosa, si scrive la domanda a cui risponde. Se la domanda
non esiste, non si costruisce.

| ✅ Si costruisce | ❌ Non si costruisce |
|---|---|
| "Come sto oggi?" → `daily_status` | Un sistema di audit trail completo |
| "Come è andata la serie di 10×100?" → `swim_sets` | La classificazione di 38.000 file di monitoring |
| "Sono meglio di marzo?" → `compare` | Un versioning formale delle formule |

Il progetto precedente è fallito su questa regola: ha speso il 90% dello sforzo
in governance del dato e ha prodotto zero coaching. Vedi
[docs/SCOPERTE-DATI.md](docs/SCOPERTE-DATI.md).

---

## REGOLA AUREA N.3 — I fatti nel database, le intenzioni in markdown

- **Sorgenti**: `garmin-export/` per lo storico e `data/raw/` per gli snapshot acquisiti
  dal sync. Sono immutabili per il processo normale; ogni risposta live viene salvata
  prima della trasformazione.
- **Database** (`data/coach.duckdb`): fatti misurati o normalizzati nelle tabelle
  canoniche; calcoli deterministici soltanto in viste/tabelle chiaramente derivate.
  Generato, ricostruibile da zero, mai modificato a mano.
- **Markdown** (`coach/`): ciò che l'atleta *vuole, sente e decide*. Gare, obiettivi,
  vincoli, RPE, sensazioni, decisioni prese. Scritto da umano e da Claude, leggibile
  da entrambi, versionato in git.

Non si mettono le gare in una tabella SQL. Non si mettono i battiti in un markdown.

---

## REGOLA AUREA N.4 — I dati originali non si toccano

`garmin-export/` è **sola lettura, sempre**. Non si rinomina, non si sposta, non si
corregge, non si estrae dentro la cartella sorgente. Ogni estrazione va in
`data/staging/`, che è cancellabile e rigenerabile.

Le nuove risposte Garmin vengono catturate in `data/raw/garmin-connect/` con hash e
senza sovrascrivere il payload precedente. Non sono una scusa per modificare l'export e
non contengono credenziali o token.

Unica eccezione già applicata: l'estrazione della Parte 2 che il progetto precedente
aveva lasciato *dentro* la sorgente è stata spostata in `data/staging/`, ripristinando
l'integrità di `garmin-export/`.

---

## REGOLA AUREA N.5 — Onestà del dato

- Un valore mancante resta mancante. Mai sostituito con zero.
- Valore Garmin, valore normalizzato e valore calcolato restano distinti e riconoscibili.
- Lap registrato, vasca e serie inferita restano entità distinte e riconoscibili.
- Ogni riga canonica risale a una sorgente reale; un URI non viene chiamato hash.
- Ogni numero che il coach mostra porta con sé **su quanti giorni** e **con quale copertura**
  è stato calcolato.
- `missing`, `not_applicable`, `insufficient_data`, `invalid` e `stale` non sono
  sinonimi e non vengono compressi in un generico zero.
- Nessun output è una diagnosi medica o una previsione di infortunio.
- Se il dato non basta per rispondere, la risposta corretta è "non lo so ancora", non una stima.

---

## REGOLA AUREA N.6 — Il calcolo è deterministico, il giudizio è del modello

Python calcola. Il modello interpreta. Mai il contrario.

Nessuna metrica viene mai stimata dall'LLM. Se un numero appare nel briefing,
esiste una funzione Python testata che lo produce, sempre uguale a parità di input e
versione del metodo.

---

## REGOLA AUREA N.7 — Ogni fase è usabile da sola

Il progetto non ha un "big bang" finale. Alla fine di ogni fase esiste qualcosa
che funziona e che si può usare quel giorno stesso. Se una fase non produce
valore utilizzabile, la fase è mal tagliata.

---

## REGOLA AUREA N.8 — Una sola verità, più modi per leggerla

MCP, interfaccia locale e report non ricalcolano la stessa metrica in posti diversi.
Chiamano un'unica funzione deterministica e ricevono lo stesso contratto di evidenza.

- Nessuna formula nei template, nei route HTTP o nel JavaScript.
- Ogni osservazione o interpretazione permette di aprire periodo, sedute, copertura e
  versione del metodo.
- L'interfaccia mette prima l'osservazione utile e poi il dettaglio: un muro di grafici
  non è un insight. L'interpretazione del modello resta etichettata e separata.
- Le scritture dell'atleta richiedono anteprima e conferma e passano dall'unico modulo
  autorizzato per `coach/`.
- L'uso normale resta possibile senza rete; un modello esterno è un'estensione
  esplicitamente autorizzata, non una dipendenza nascosta.

---

## Lingua

- **Documentazione, knowledge, contenuti coach**: italiano.
- **Codice, nomi di tabelle, colonne, funzioni, file sorgente**: inglese.

Nessuna eccezione: mescolare le due lingue dentro lo stesso strato è la prima
causa di confusione a distanza di sei mesi.

---

## Come si usa questo documento

Questo file va riletto prima di ogni intervento strutturale. Se una regola risulta
sbagliata alla prova dei fatti, si **modifica la regola in modo esplicito**,
motivandolo — non la si aggira in silenzio.
