"""L'applicazione web locale del coach.

Cinque aree, un server su 127.0.0.1, nessuna richiesta verso l'esterno.
Il calcolo sta tutto in ``analysis/``: qui si dispone e si serve.
"""

from .server import app, build, serve

__all__ = ["app", "build", "serve"]
