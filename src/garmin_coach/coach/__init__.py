"""Il coach decisionale: fatti, giudizio, e il confine dichiarato fra i due.

``packet`` raccoglie i fatti dai servizi deterministici. ``brain`` li trasforma
in un giudizio. ``contract`` definisce cosa può passare fra i due, e rifiuta ciò
che non rispetta il confine — a cominciare da un numero che il pacchetto non
contiene.
"""

from .brain import ClaudeBrain, LocalBrain
from .claude_code import BrainUnavailable, ClaudeCodeBrain
from .contract import (CoachContextPacket, CoachingResponse, Fact,
                       InvalidResponse, validate)
from .packet import build

__all__ = ["ClaudeBrain", "ClaudeCodeBrain", "BrainUnavailable", "LocalBrain",
           "CoachContextPacket", "CoachingResponse", "Fact", "InvalidResponse",
           "validate", "build"]
