"""«Quanto ho davvero nuotato, tolto quello che non era nuoto?»

## Da dove nasce

L'orologio parte quando si preme e si ferma quando si preme. Fra i due momenti
ci sono l'attesa sulla riva, la camminata in acqua, la risalita alla fine — e
nessuno di quei minuti è la gara.

L'atleta lo ha detto il 24/08/2026 chiedendo di usare comunque i tempi
dell'orologio per le gare senza risultato ufficiale: *«non differiscono di
molto, massimo di 1/2 minuti, che non cambiano una 10 km; se riesci a calcolarlo
tu depurando i minuti in cui a inizio e fine gara noti un numero di bracciate
anomale, fallo»*.

Si può, e il modo di farlo è più solido di quanto sembri.

## Come si riconosce «non stavo nuotando»

Non da una soglia assoluta di cadenza: cambia con lo stile, con la stanchezza e
con l'orologio. Si riconosce **rispetto alla gara stessa** — metà della cadenza
mediana di quella nuotata. Sotto quella soglia, all'inizio o alla fine, non si
sta nuotando: si sta aspettando o si sta uscendo.

Si taglia **solo alle estremità**. Un tratto lento in mezzo è un ristoro, una
boa o una medusa: fa parte della gara, e toglierlo trasformerebbe un tempo in
una somma di pezzi scelti.

## Perché il risultato non è «il tempo ufficiale»

Non lo è, e il modulo non lo pretende. Resta una misura dell'orologio, ripulita
di ciò che l'orologio ha registrato senza che fosse gara. Sull'archivio vero
toglie 1-2 minuti quasi ovunque — place23 1,9, place21 2,0, place19-place28 3,5
su dieci ore — cioè l'ordine di grandezza che l'atleta aveva previsto a memoria.

L'eccezione dice perché il calcolo serve: sulla Traversata del lake01 del
2018 toglie **8 minuti**, quasi tutti all'inizio, perché quel giorno l'orologio
è partito ben prima del via. Un minuto e mezzo si poteva ignorare; otto no.

## Il controesempio che tiene aperto il dubbio

Su place05 2019 l'orologio dice 6.975 m in 2h13' e il cronometro ufficiale
10 km in 3h00'46". Lì lo scarto è di quarantasette minuti, e nessuna ripulitura
delle estremità lo spiega: l'orologio è stato fermato e ripreso, o si è spento.
Per questo il tempo che esce da qui non diventa mai «il tempo della gara» senza
dire da dove viene.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb

from ..database import table_exists

# Quanto sotto la cadenza mediana della nuotata un tratto smette di essere
# nuoto. Metà è una scelta, non una misura, e va guardata: sull'archivio vero
# separa nettamente l'attesa (cadenza 0-3) dal nuoto vero (26-32), e in mezzo
# non c'è quasi niente da sbagliare.
SLOW_FRACTION = 0.5

# Sotto questo numero di punti con cadenza la mediana non descrive la nuotata,
# descrive i pochi punti che ci sono.
MIN_POINTS = 60


@dataclass(frozen=True)
class SwimmingTime:
    """Il tempo di nuoto, e quanto è stato tolto alle due estremità."""

    activity_id: int
    recorded_s: float
    swimming_s: float
    trimmed_start_s: float
    trimmed_end_s: float
    median_cadence_spm: float
    points: int

    @property
    def trimmed_s(self) -> float:
        return self.trimmed_start_s + self.trimmed_end_s

    @property
    def matters(self) -> bool:
        """Se vale la pena dirlo.

        Sotto il minuto la ripulitura è dentro l'incertezza di quando si è
        premuto il pulsante, e annunciarla darebbe l'impressione di una
        precisione che non c'è.
        """
        return self.trimmed_s >= 60


def available(connection: duckdb.DuckDBPyConnection) -> bool:
    return table_exists(connection, "activity_track")


def of(connection: duckdb.DuckDBPyConnection,
       activity_id: int) -> SwimmingTime | None:
    """Il tempo di nuoto di una registrazione, o niente se non si può dire.

    Restituisce `None` quando la traccia manca o la cadenza non è stata
    registrata: sono i casi in cui «non stavo nuotando» non si riconosce, e
    inventare un taglio sarebbe peggio che lasciare il tempo intero.
    """
    if not available(connection):
        return None

    righe = connection.execute("""
        SELECT elapsed_s, cadence_spm FROM activity_track
        WHERE activity_id = ? AND elapsed_s IS NOT NULL
        ORDER BY point_index
    """, [activity_id]).fetchall()
    if len(righe) < MIN_POINTS:
        return None

    cadenze = sorted(riga[1] for riga in righe if riga[1] and riga[1] > 0)
    if len(cadenze) < MIN_POINTS:
        return None
    mediana = cadenze[len(cadenze) // 2]
    soglia = mediana * SLOW_FRACTION

    nuotando = [riga[0] for riga in righe if riga[1] and riga[1] >= soglia]
    if not nuotando:
        return None

    totale = righe[-1][0] - righe[0][0]
    inizio, fine = nuotando[0], nuotando[-1]
    return SwimmingTime(
        activity_id=activity_id,
        recorded_s=totale,
        swimming_s=fine - inizio,
        trimmed_start_s=inizio - righe[0][0],
        trimmed_end_s=righe[-1][0] - fine,
        median_cadence_spm=mediana,
        points=len(righe))


def _minuti(secondi: float) -> str:
    """Minuti con la virgola decimale, senza toccare la punteggiatura.

    `f"...".replace(".", ",")` su una frase intera mangia anche il punto
    finale. È già successo due volte in questo progetto, ed è il genere di
    difetto che si vede solo leggendo l'output vero.
    """
    return f"{secondi / 60:.1f}".replace(".", ",")


def describe(misura: SwimmingTime | None) -> str:
    """La misura in una frase, con dentro i numeri che la giustificano."""
    if misura is None:
        return ("Non posso separare il nuoto dall'attesa: manca la traccia o "
                "la cadenza non è stata registrata.")
    if not misura.matters:
        return ("Il tempo registrato è tutto nuoto: alle estremità c'è meno "
                "di un minuto a cadenza bassa.")
    return (f"Tolti {_minuti(misura.trimmed_s)} minuti a cadenza sotto la metà "
            f"della mediana ({misura.median_cadence_spm:.0f} bracciate al "
            f"minuto): {_minuti(misura.trimmed_start_s)} all'inizio e "
            f"{_minuti(misura.trimmed_end_s)} alla fine.")
