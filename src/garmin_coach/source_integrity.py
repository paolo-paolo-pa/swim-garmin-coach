"""Prova che l'export non è stato toccato.

La Regola Aurea n.4 dice che ``garmin-export/`` è di sola lettura. Una regola
che nessuno verifica è un'intenzione. Questo modulo calcola l'impronta della
sorgente e la confronta con quella registrata alla prima esecuzione, producendo
un report ``invariati / modificati / mancanti / nuovi``.

L'impronta vive in ``data/source_fingerprint.json``: è un artefatto generato,
non versionato, ricostruibile in qualunque momento.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import paths

FINGERPRINT = paths.DATA / "source_fingerprint.json"

# I file che contano davvero: gli archivi e i JSON. Ignorare le cartelle vuote
# lasciate da altri strumenti evita falsi allarmi.
TRACKED_SUFFIXES = {".zip", ".json"}


@dataclass
class IntegrityReport:
    unchanged: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)

    @property
    def is_intact(self) -> bool:
        return not self.changed and not self.missing

    def summary(self) -> str:
        return (f"invariati={len(self.unchanged)} modificati={len(self.changed)} "
                f"mancanti={len(self.missing)} nuovi={len(self.added)}")


def _hash_file(path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def current_fingerprint() -> dict[str, str]:
    """SHA-256 di ogni file rilevante della sorgente."""
    result: dict[str, str] = {}
    for path in sorted(paths.EXPORT.rglob("*")):
        if path.is_file() and path.suffix.lower() in TRACKED_SUFFIXES:
            result[path.relative_to(paths.EXPORT).as_posix()] = _hash_file(path)
    return result


def save_baseline() -> dict[str, str]:
    """Registra l'impronta di riferimento. Si esegue una volta sola."""
    paths.ensure_data_dirs()
    fingerprint = current_fingerprint()
    FINGERPRINT.write_text(json.dumps({
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "file_count": len(fingerprint),
        "files": fingerprint,
    }, indent=2), encoding="utf-8")
    return fingerprint


def verify() -> IntegrityReport:
    """Confronta la sorgente di oggi con l'impronta registrata."""
    if not FINGERPRINT.exists():
        raise FileNotFoundError(
            "Nessuna impronta di riferimento. Eseguire prima 'fingerprint'."
        )
    baseline = json.loads(FINGERPRINT.read_text(encoding="utf-8"))["files"]
    current = current_fingerprint()

    report = IntegrityReport()
    for name, digest in baseline.items():
        if name not in current:
            report.missing.append(name)
        elif current[name] != digest:
            report.changed.append(name)
        else:
            report.unchanged.append(name)
    report.added = [name for name in current if name not in baseline]
    return report
