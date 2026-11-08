# Struttura della seduta: leggerla dai lap

**Ambito:** piscina
**Solidità:** consolidato (le ripetute) · discusso (l'attribuzione dei blocchi)
**Aggiornato:** 2026-08-23

## In breve

Una seduta di nuoto ha una forma: si scalda, si attiva, si fa il lavoro, si
scioglie. L'orologio non registra quella forma — registra lap. Ricostruirla è
possibile solo se si sa quale forma cercare, e per questo atleta la forma è
**dichiarata**: riscaldamento → parte iniziale o attivazione → parte centrale →
parte finale o defaticamento, quest'ultima non sempre presente.

## Come funziona

Due strati, con due gradi di fiducia diversi, e vanno tenuti distinti.

### Le ripetute: aritmetica

Lap consecutivi con la **stessa distanza** e la **stessa nuotata**, separati da
riposi, sono una serie. «6×100» si legge, non si interpreta. Una serie finisce
in quattro modi, e sono tutti osservabili:

| Finisce quando… | Perché |
|---|---|
| cambia la distanza | un 4×100 e un 4×50 sono due lavori |
| cambia la nuotata | idem |
| il tempo esce dalla fascia del gruppo | dentro lo stesso gruppo stanno succedendo due cose |
| compare un riposo molto più lungo degli altri | due minuti dentro recuperi da venti secondi non sono un recupero |

Sotto **tre** ripetizioni non si parla di serie: due 100 di fila capitano in
qualunque riscaldamento.

### I blocchi: inferenza dichiarata

| Blocco | Regola | Fiducia |
|---|---|---|
| riscaldamento | è il primo, perché l'atleta dice che c'è sempre e viene sempre prima | **dichiarata** |
| parte centrale | è la serie con più metri | inferita |
| defaticamento | è l'ultimo, se sta sotto un quinto della seduta | inferita |
| attivazione | quello che resta in mezzo | per esclusione |

Se il lavoro più lungo è il primo, la struttura dichiarata non regge su quella
seduta e la divisione **non si fa**.

## Come si misura con i dati disponibili

- Servono i **lap** (`activity_laps`), che esistono su 1.302 sedute grazie a D4-D8.
- Serve il campo `is_rest`: senza, i recuperi entrerebbero nel conto dei tempi e
  ogni serie sembrerebbe lentissima.
- **Non si può sapere l'intenzione.** Se il lavoro principale era «a ritmo gara»
  o «a soglia», l'orologio non lo dice e nemmeno i tempi lo rivelano da soli. È
  la metà mancante del ciclo previsto → eseguito → risposta.
- **Non si distingue una serie da due serie uguali di fila.** Un 6×100 a 88" e
  un 5×100 a 92" con lo stesso recupero sono un 11×100 per i dati. Separarli
  richiederebbe di sapere cosa aveva in testa l'allenatore.

## Implicazione operativa

1. **La domanda su una serie è «l'hai tenuta?», non «quanto hai nuotato».**
   Il confronto fra prima e seconda metà della serie risponde; il totale no.
2. **Confronta serie omogenee.** Un 8×100 di oggi si confronta con un 8×100
   passato, non con la media della seduta: la media contiene i recuperi, la
   tecnica e le gambe.
3. **Quando la struttura non si riconosce, dillo.** «Non riconosciuta» è una
   risposta; una divisione inventata somiglia a un allenamento vero e nessuno
   la mette più in dubbio (rischio R1 del piano).
4. **Le due situazioni di fallimento sono diverse e vanno distinte:** «non ci
   sono lap» manda a guardare l'import, «i lap non formano serie» manda a
   guardare la seduta.

## Limiti e cautele

- Le regole dei blocchi valgono **per questo atleta**, perché è la sua struttura
  a essere dichiarata. Su chiunque altro sarebbero congetture.
- Una registrazione frammentata produce lap che non sono ripetute. È già
  successo in questo archivio ed è il motivo per cui esiste lo strato delle
  correzioni confermate.
- Le soglie — tre ripetizioni, 12% di fascia, riposo 2,5 volte il mediano, un
  quinto per il defaticamento — sono **scelte e non misurate**. Vanno guardate
  in audit come le altre.

## Fonti

Nessuna: la struttura è una dichiarazione dell'atleta, registrata in
[`../../coach/atleta.md`](../../coach/atleta.md). Le soglie sono scelte di
implementazione, documentate in `analysis/session_structure.py`.

Correlate: [tipologie-di-serie.md](tipologie-di-serie.md) ·
[densita-e-recuperi.md](densita-e-recuperi.md) ·
[zone-di-intensita.md](../01-fondamenti/zone-di-intensita.md)
