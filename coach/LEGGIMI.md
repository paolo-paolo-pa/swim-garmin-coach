# `coach/` — la memoria dell'atleta

Il database contiene ciò che è stato **misurato**: metri, battiti, vasche, lap.
Questa cartella contiene ciò che l'atleta **vuole, sente e decide**: obiettivi,
gare, sensazioni, e le correzioni ai dati che solo lui può fare.

> **I fatti nel database, le intenzioni in markdown.**
> *([REGOLE.md](../REGOLE.md), Regola Aurea n.3)*

Non si mettono le gare in una tabella SQL. Non si mettono i battiti in un
markdown.

Il codice legge questi file con
[`src/garmin_coach/athlete_files.py`](../src/garmin_coach/athlete_files.py), che
è anche il posto dove i formati qui sotto sono definiti davvero. Una riga
scritta male viene **saltata**, non fa fallire la lettura delle altre: un file
compilato a mano è quasi sempre un po' sbagliato, e rifiutarlo per intero
significherebbe non usarlo mai.

---

## Versionata qui, assente nella copia pubblica

Sul computer dell'atleta questa cartella è **sotto Git come tutto il resto**:
sono decisioni prese una alla volta, a volte dopo lunghe verifiche, e perderne
una per un salvataggio sbagliato sarebbe un danno vero. La cronologia serve
proprio a questo.

Nella copia destinata a GitHub non c'è. Preso da solo nessuno di questi file è
sensibile; messi insieme sono un profilo personale completo — età, vasca
abituale, giorni e orari fissi di allenamento, zona geografica, prestazioni. È
roba dell'atleta. Dentro ci sono anche i tempi di altre persone e i programmi
scritti dal suo allenatore, che sono lavoro di terzi.

La copia pubblica **si genera**, non si mantiene a mano:

```bash
.\.venv\Scripts\python.exe scripts\build_public_repo.py
```

Questo LEGGIMI è l'unico file della cartella che sopravvive in quella copia,
così chi apre il progetto su GitHub non trova codice che legge una cartella che
non esiste (Regola Aurea n.1).

---

## Cosa c'è dentro

| File | Cosa contiene | Chi lo scrive |
|---|---|---|
| `atleta.md` | chi è, che vasca, che orari, che vincoli | l'atleta |
| `obiettivi.md` | dove vuole arrivare, entro quando | l'atleta |
| `gare.md` | le gare in calendario e i riferimenti di passo | l'atleta |
| `gare-dichiarate.md` | le gare che i circuiti di cronometraggio non hanno | l'atleta |
| `riferimenti.md` | prestazioni confermate, usate come metro | l'atleta e il coach |
| `programma-settimanale.md` | cosa l'allenatore ha **previsto**, seduta per seduta | l'atleta, trascrivendo |
| `correzioni-dati.md` | dove l'orologio ha sbagliato, e come si legge invece | l'atleta |
| `correzioni-gare.md` | quando l'attività Garmin di un giorno **è** la gara di quel giorno | l'atleta |
| `aquatime/` · `icron/` | risultati ufficiali importati, vasca e mare | i circuiti |
| `compagni_squadra/` | tempi di altre persone. Fuori da Git **anche in locale** | i circuiti |
| `programmi/` | i fogli originali dell'allenatore. Fuori da Git **anche in locale** | l'allenatore |

Le ultime due righe sono le sole eccezioni locali, ed entrambe per lo stesso
motivo: contengono lavoro e dati di altre persone, che non sono nostri da
conservare in una cronologia.

---

## I due formati che il codice interroga

Sono tabelle markdown normali. La prima colonna è sempre una data `AAAA-MM-GG`;
una riga che contiene `(esempio)` viene ignorata, così il modello resta nel file.

### Il programma dell'allenatore

```markdown
| Data | Cosa | Intento | Serie | Note |
|---|---|---|---|---|
| 2026-08-24 | 3200 m | misto | 400 sciolti · 3x200 br · 2x(400 A2 + 300 B2) | foglio: A2-B2 |
```

`Intento` accetta otto parole e nessun'altra: `aerobico`, `soglia`, `vo2max`,
`velocità`, `tecnica`, `recupero`, `specifico gara`, `misto`. Sono poche di
proposito — un elenco lungo invita a scegliere l'etichetta più vicina invece di
quella giusta. Qualunque cosa non riconosciuta diventa `non dichiarato`, che è
una risposta onesta. `Cosa` accetta `3000 m` o `3 km`; se il foglio non dichiara
il volume si scrive `non dichiarato`, **mai** zero.

Da qui nasce l'unico confronto che l'archivio da solo non poteva produrre:
*previsto contro eseguito*. L'orologio registra ciò che è stato fatto; nessun
dato al mondo contiene ciò che era **previsto**, perché il previsto vive su un
foglio o nella testa di chi allena.

Il confronto riguarda **presenza e volume**, non intensità: dire se la soglia
era davvero soglia richiederebbe zone cardiache affidabili, e in questo archivio
non lo sono. E non giudica il programma: uno scarto fra previsto ed eseguito è
un fatto da guardare con l'allenatore, non un errore da correggere.

### Le correzioni alle gare

```markdown
| ID gara | Verdetto | Attività Garmin | Distanza | Perché |
|---|---|---|---|---|
| 2026-08-23-place04 | linked | 21044556677 | 1900 | gara la mattina, l'orologio c'era |
```

`linked` — quella nuotata è la gara. `separate` — sono due cose diverse dello
stesso giorno. `exclude` — non conta come gara, ma resta nei dati.

Nessuna regola automatica su questo regge: ne sono state scritte due e sono
state smontate entrambe da esempi reali, in due modi opposti. Il verdetto lo
scrive una persona che guarda luogo, ora e durata.
