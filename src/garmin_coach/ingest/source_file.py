"""Un file sorgente dell'export, con il suo hash.

La provenienza del progetto è tutta qui: percorso relativo e SHA-256. Bastano a
dimostrare che ogni riga del database viene da ``garmin-export/`` (criterio C6d)
e a garantire l'idempotenza dell'import.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .. import paths


@dataclass(frozen=True)
class SourceFile:
    path: Path

    @property
    def sha256(self) -> str:
        digest = hashlib.sha256()
        with self.path.open("rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
        return digest.hexdigest()

    @property
    def relative_path(self) -> str:
        """Percorso relativo alla radice del progetto, con separatori POSIX."""
        return self.path.relative_to(paths.ROOT).as_posix()

    def load_json(self) -> object:
        """I file Garmin sono a volte salvati con BOM: ``utf-8-sig`` li gestisce
        entrambi senza doverli distinguere."""
        return json.loads(self.path.read_text(encoding="utf-8-sig"))


# Come si riconosce una riga che viene da un file dell'export: la sua
# provenienza è lo SHA-256 di quel file, cioè 64 cifre esadecimali. L'altra
# forma lecita è un URI ``garmin-connect://…`` per le risposte del sync, e il
# criterio C9 verifica che non ne esista una terza.
FROM_EXPORT = "source_object_id ~ '^[0-9a-f]{64}$'"


def replace_export_rows(connection, table: str, columns: list[str],
                        rows: list[tuple]) -> int:
    """Riscrive le righe che l'export possiede, **e soltanto quelle**.

    Prima era ``DELETE FROM tabella`` e via. Sembra la cosa più semplice, e per
    un po' lo è stata: finché l'unica sorgente era l'export, cancellare tutto e
    riscrivere era davvero equivalente a un import idempotente.

    Da quando esiste il sync non lo è più. L'export è un file fermo al 4 luglio;
    le settimane successive esistono soltanto perché il sync le ha scritte.
    Rileggere l'export le cancellava tutte: l'audit indipendente lo ha
    riprodotto sul database vero — 1.508 attività diventate 1.471, l'ultimo
    giorno con dati arretrato a luglio — e ``verify`` continuava a dire 21/21,
    perché i suoi conteggi si fermano al 4 luglio e quindi l'archivio tornava
    esattamente **atteso** proprio perché era stato accorciato.

    L'idempotenza resta: si cancellano e si riscrivono le righe di questa
    sorgente. Quello che cambia è che una sorgente non cancella più il lavoro
    di un'altra. Dove le due si sovrappongono vince l'export, che è il record
    più completo: il sync non scarica zone cardiache, calorie e temperature.
    """
    connection.execute(f"DELETE FROM {table} WHERE {FROM_EXPORT}")
    if not rows:
        return 0
    placeholders = ", ".join("?" * len(columns))
    connection.executemany(
        f"INSERT OR REPLACE INTO {table} ({', '.join(columns)}) "
        f"VALUES ({placeholders})", rows)
    return len(rows)


def discover(subfolder: str, pattern: str) -> list[SourceFile]:
    """Tutti i file di una categoria, in ordine cronologico di nome.

    L'ordine conta: quando due file coprono lo stesso giorno (gli intervalli
    Garmin si toccano agli estremi), vince l'ultimo letto.
    """
    folder = paths.connect_dir(subfolder)
    return [SourceFile(p) for p in sorted(folder.glob(pattern))]
