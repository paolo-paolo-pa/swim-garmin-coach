"""Un tempo di nuoto non arriva mai a 60 secondi.

``format_swim_time`` arrotonda i centesimi con la formattazione e non riporta il
riporto: 119,999 s diventa ``1:60,00`` invece di ``2:00,00``, e 59,999 s diventa
``60,00`` invece di ``1:00,00``.

Non è un caso di laboratorio. Il passo per 100 m che compare nell'anteprima è
calcolato — ``seconds / distance * 100`` — e cade su valori arbitrari: un 1500
in 21:18,50 dà un passo di 85,2333… s, e ogni divisione può finire a un
millesimo da un multiplo di 60. Un tempo scritto ``1:60,00`` in un file di
riferimenti confermati è un errore che poi qualcuno rilegge come dato buono.
"""

import pytest

from garmin_coach.athlete_files import format_swim_time, parse_swim_time

# Il caso trovato dall'audit, i suoi vicini, e i confini che stanno intorno.
CASI = [
    (0.0, "0,00"),
    (0.004, "0,00"),
    (9.994, "9,99"),
    (59.99, "59,99"),
    (59.994, "59,99"),
    (59.999, "1:00,00"),          # arrotonda a 60: deve diventare un minuto
    (60.0, "1:00,00"),
    (119.999, "2:00,00"),         # il caso dell'audit: era 1:60,00
    (119.994, "1:59,99"),
    (299.995, "5:00,00"),
    (3599.999, "60:00,00"),       # un'ora, che nel nuoto si scrive così
]


@pytest.mark.parametrize("secondi,atteso", CASI)
def test_seconds_never_reach_sixty(secondi, atteso):
    assert format_swim_time(secondi) == atteso


@pytest.mark.parametrize("secondi,_atteso", CASI)
def test_the_written_time_can_always_be_read_back(secondi, _atteso):
    """Ciò che il progetto scrive, il progetto lo deve saper rileggere.

    ``parse_swim_time`` rifiuta i secondi ≥ 60 dopo i due punti — giustamente.
    Se il formattatore ne produce, il file dei riferimenti contiene righe che il
    lettore dei riferimenti scarterà.
    """
    scritto = format_swim_time(secondi)
    riletto = parse_swim_time(scritto)
    assert riletto == pytest.approx(round(secondi, 2), abs=0.005), (
        f"«{scritto}» non si rilegge come il tempo che rappresenta")
