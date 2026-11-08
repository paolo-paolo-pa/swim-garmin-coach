"""Risposte generate conservate come artefatti, separate dai fatti dell'atleta."""
import json
from datetime import datetime,timezone
from uuid import uuid4

from .. import paths


def save(value):
    folder=paths.DATA/'coach-replies'
    folder.mkdir(parents=True,exist_ok=True)
    identifier=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:8]
    (folder/(identifier+'.json')).write_text(json.dumps(dict(value,
        saved_at=datetime.now(timezone.utc).isoformat(),kind='generated_interpretation_not_measured_fact'),
        default=str,ensure_ascii=False,indent=2),encoding='utf-8')
    return identifier
