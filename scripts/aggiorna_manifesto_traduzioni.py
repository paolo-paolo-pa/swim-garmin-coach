"""Registra nel manifesto quali traduzioni sono valide per il sorgente attuale.

## Perché esiste

`scripts/build_public_repo.py` non traduce da sé: legge una traduzione già
pronta in `data/traduzione-en/files/` e la pubblica solo se il suo hash
registrato in `data/traduzione-en/manifest.json` combacia con il file
italiano *attuale*. Dopo aver scritto o aggiornato una traduzione a mano,
il manifesto va aggiornato di conseguenza — altrimenti la build la tratta
come mancante.

Questo script non traduce niente: prende ogni file già presente sotto
`data/traduzione-en/files/`, trova il sorgente italiano corrispondente nel
repository di lavoro e registra l'hash SHA-256 di quel sorgente, con la
stessa funzione di `build_public_repo.py:_hash`. Se il sorgente italiano non
esiste più, lo segnala invece di inventare una voce.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
TRADUZIONI = RADICE / "data" / "traduzione-en"
CARTELLA_FILE = TRADUZIONI / "files"
MANIFESTO = TRADUZIONI / "manifest.json"


def _hash(testo: str) -> str:
    return hashlib.sha256(testo.encode("utf-8")).hexdigest()


def main() -> int:
    if not CARTELLA_FILE.exists():
        print(f"Non esiste {CARTELLA_FILE.relative_to(RADICE)}.")
        return 1

    manifesto: dict[str, str] = {}
    orfani: list[str] = []

    for tradotto in sorted(CARTELLA_FILE.rglob("*")):
        if not tradotto.is_file():
            continue
        relativo = tradotto.relative_to(CARTELLA_FILE).as_posix()
        sorgente = RADICE / relativo
        if not sorgente.exists():
            orfani.append(relativo)
            continue
        manifesto[relativo] = _hash(sorgente.read_text(encoding="utf-8"))

    MANIFESTO.write_text(
        json.dumps(manifesto, indent=2, ensure_ascii=False, sort_keys=True)
        + "\n",
        encoding="utf-8")

    print(f"Manifesto aggiornato: {len(manifesto)} traduzioni registrate.")
    if orfani:
        print(f"\n{len(orfani)} traduzioni senza un sorgente italiano corrispondente "
              "(non registrate):")
        for uno in orfani:
            print(f"  - {uno}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
