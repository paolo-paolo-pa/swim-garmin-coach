"""La geometria di un grafico, calcolata qui e disegnata altrove.

## Perché la matematica di un grafico sta in ``analysis/``

Perché è matematica. L'altezza di una barra è ``valore / massimo * altezza``, e
quella divisione dentro una pagina sarebbe una formula in un template — la cosa
che la Regola Aurea n.8 vieta, e che il test sull'albero sintattico fa fallire.

Quindi qui si producono rettangoli con coordinate già pronte, e la pagina
emette un SVG che non calcola niente.

## Un grafico, non un pannello

Non c'è un motore di grafici configurabile. C'è una funzione che disegna
settimane, perché la settimana è l'unità in cui ragionano l'atleta e il suo
allenatore. Quando servirà un secondo tipo di grafico si aggiungerà una seconda
funzione, e si vedrà chiaramente che sono due.

Nessuna libreria: l'SVG è testo, e il testo non ha bisogno di un CDN.
"""

from __future__ import annotations

from dataclasses import dataclass

# Misure in unità SVG. La larghezza è quella di una colonna stretta: il grafico
# deve stare in 360 px senza scorrere.
LARGHEZZA = 320
ALTEZZA = 120
BASE = 100          # dove poggiano le barre
SPAZIO = 2          # fra una barra e l'altra


@dataclass(frozen=True)
class Barra:
    """Una barra, con tutto già calcolato."""

    x: float
    y: float
    larghezza: float
    altezza: float
    valore: float
    etichetta: str
    evidenziata: bool
    titolo: str      # il testo che un lettore di schermo legge


@dataclass(frozen=True)
class Grafico:
    barre: tuple[Barra, ...]
    larghezza: int
    altezza: int
    massimo: float
    descrizione: str

    @property
    def is_empty(self) -> bool:
        return not self.barre


def weekly_bars(settimane: list, evidenzia_ultime: int = 4) -> Grafico:
    """Le settimane come barre.

    ``settimane`` sono oggetti con ``week_start`` e ``km``. Le ultime vengono
    evidenziate perché sono quelle di cui si sta parlando: senza, il grafico
    sarebbe una decorazione invece di una prova.
    """
    if not settimane:
        return Grafico((), LARGHEZZA, ALTEZZA, 0.0,
                       "Nessuna settimana con nuotate nel periodo.")

    massimo = max((s.km for s in settimane), default=0.0) or 1.0
    passo = LARGHEZZA / len(settimane)
    larghezza_barra = max(passo - SPAZIO, 1.0)
    soglia = len(settimane) - evidenzia_ultime

    barre = []
    for indice, settimana in enumerate(settimane):
        altezza = settimana.km / massimo * BASE
        barre.append(Barra(
            x=round(indice * passo, 2),
            y=round(BASE - altezza, 2),
            larghezza=round(larghezza_barra, 2),
            altezza=round(altezza, 2),
            valore=settimana.km,
            etichetta=settimana.week_start.strftime("%d/%m"),
            evidenziata=indice >= soglia,
            titolo=(f"settimana del {settimana.week_start.strftime('%d/%m/%Y')}: "
                    f"{settimana.km} km in {settimana.sessions} sedute"),
        ))

    return Grafico(
        barre=tuple(barre),
        larghezza=LARGHEZZA,
        altezza=ALTEZZA,
        massimo=massimo,
        descrizione=(
            f"Volume settimanale di {len(settimane)} settimane, da "
            f"{settimane[0].week_start.strftime('%d/%m/%Y')} a "
            f"{settimane[-1].week_start.strftime('%d/%m/%Y')}. "
            f"Massimo {massimo} km."),
    )
