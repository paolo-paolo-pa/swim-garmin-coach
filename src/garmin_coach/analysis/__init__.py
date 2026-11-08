"""Le domande dell'atleta, non le tabelle del database.

Questo strato è l'unico posto dove si calcola. Sopra ci sono due adattatori che
non calcolano niente: i sette strumenti MCP e l'applicazione web locale. Sotto
c'è DuckDB.

I moduli sono divisi **per domanda** e non per tabella, perché è la divisione
che regge nel tempo: una domanda dell'atleta resta la stessa anche quando cambia
lo schema, mentre un modulo chiamato ``activities.py`` invita a metterci dentro
tutto ciò che tocca quella tabella.

| Modulo | Domanda |
|---|---|
| ``today`` | «C'è qualcosa che merita la mia attenzione oggi?» |
| ``volume`` | «Quanto ho nuotato in questo periodo?» |
| ``freshness`` | «Fino a quando arrivano i dati che sto guardando?» |
| ``insight`` | il formato in cui ogni risposta viene consegnata |
"""

from . import freshness, insight, today, volume

__all__ = ["freshness", "insight", "today", "volume"]
