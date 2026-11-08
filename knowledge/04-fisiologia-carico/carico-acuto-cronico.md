# Carico acuto e cronico (ACWR)

**Ambito:** entrambi
**Solidità:** discusso — e contestato nella sua applicazione originale
**Aggiornato:** 2026-08-16

## In breve

L'ACWR mette a confronto quanto si è allenato di recente (7 giorni) con quanto si
è abituati ad allenarsi (28 giorni). È una descrizione utile della direzione in
cui si sta andando. **Non è un predittore di infortunio**, per quanto sia nato e
sia stato diffuso come tale.

## Come funziona

Nel progetto:

```
carico acuto   = somma del carico degli ultimi 7 giorni
carico cronico = somma degli ultimi 28 giorni / 4      (per renderla settimanale)
ACWR           = acuto / cronico
```

I giorni di riposo entrano come **carico zero**: escluderli gonfierebbe le medie.
L'ACWR viene pubblicato solo se almeno 21 dei 28 giorni ricadono nel periodo in cui
il carico è registrato.

Letture indicative, da usare come descrizione:

| ACWR | Significato descrittivo |
|---|---|
| < 0,8 | si sta facendo meno del solito: scarico, pausa o calo |
| 0,8 - 1,3 | continuità con l'abitudine |
| > 1,5 | salto rapido rispetto all'abitudine |

## Come si misura con i dati disponibili

Il carico per attività (`activityTrainingLoad`) è una metrica **proprietaria
Garmin**, disponibile **solo dal 2021** e su circa il 60% delle sedute. Di
conseguenza:

- l'ACWR calcolato copre poco più della metà della storia;
- prima del 2021 non esiste, e nessuna approssimazione va tentata;
- esiste anche un ACWR calcolato da Garmin (`garmin_acwr`), esposto a parte: i due
  non coincidono perché usano finestre diverse. Vanno mostrati separati, mai fusi.

## Implicazione operativa

1. **Non dire mai che un ACWR alto significa rischio di infortunio.** Non è
   supportato e non è compito di questo sistema. Descrivi il cambiamento e basta.
2. **Un ACWR alto dopo una settimana di riposo non è un allarme**: il denominatore
   è sceso. Leggilo sempre insieme ai valori assoluti di acuto e cronico.
3. **Il numero da guardare per primo è il cronico**, non il rapporto: un cronico
   in crescita lenta è una base che si costruisce; un cronico che crolla è forma
   che si perde.
4. **Se l'ACWR non è disponibile** (prima del 2021, o copertura insufficiente),
   usa volume 7/28 giorni e continuità: sono coperti al 100%.
5. **Non combinarlo con l'HRV in un "punteggio di rischio".** Sommare due
   indicatori deboli non ne produce uno forte.

## Limiti e cautele

- L'evidenza originale sull'ACWR come predittore di infortunio è stata
  ampiamente criticata su basi metodologiche. Trattarlo come descrittivo.
- Dipende interamente da una metrica proprietaria di cui non conosciamo la formula.
- La finestra di 28 giorni è convenzione, non fisiologia.
- Nel nuoto il carico articolare è basso: il modello nasce su sport a impatto.

## Fonti

**L'ACWR non predice gli infortuni, ed è dimostrato.** Impellizzeri 2020
[ACWR-1] elenca i problemi: si costruisce un rapporto fra due grandezze che
condividono i dati, le finestre a 7 e 28 giorni sono scelte senza motivo, e
quando si tolgono gli outlier e si tratta la variabile come continua **la
relazione con gli infortuni sparisce**. L'editoriale del 2021 [ACWR-2] conferma
che manipolarlo per ridurre il rischio è una congettura.

Questa scheda resta perché l'ACWR **descrive** bene un cambio di carico. Il
progetto lo usa così e non altrimenti: nessun output di questo coach dice o
suggerisce che un valore alto significhi rischio di infortunio — sarebbe una
previsione di infortunio, vietata dalla Regola Aurea n.5 e ora anche priva di
supporto.

Elenco completo in [`../_fonti/RIFERIMENTI.md`](../_fonti/RIFERIMENTI.md).
