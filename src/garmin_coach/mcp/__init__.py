"""Il confine fra i dati e il modello.

Sette strumenti, allow-list. Niente SQL arbitrario, niente filesystem, niente
shell, niente coordinate GPS. Un solo strumento scrive, e solo dentro ``coach/``.
"""

from . import capabilities, planning, queries

__all__ = ["capabilities", "planning", "queries"]
