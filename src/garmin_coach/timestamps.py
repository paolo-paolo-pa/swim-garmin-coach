"""Conversione dei timestamp Garmin.

Unico posto del progetto in cui si converte una data. Garmin usa almeno quattro
formati diversi nello stesso export, e il progetto precedente si è bloccato
proprio su questo (15 file di acute load con epoch Unix al posto di date ISO).

Formati osservati nell'export:

| Esempio                       | Dove                                    |
|-------------------------------|-----------------------------------------|
| ``1782086400000``             | ``MetricsAcuteTrainingLoad.calendarDate``|
| ``"2026-03-27"``              | ``UDSFile.calendarDate``                |
| ``"2026-03-29T10:16:06.0"``   | ``sleepData.sleepEndTimestampGMT``      |
| ``"2017-09-05T00:00:00.0"``   | ``userBioMetrics.metaData.calendarDate``|
"""

from __future__ import annotations

from datetime import date, datetime, timezone

# Sotto questa soglia un epoch è certamente in secondi, non in millisecondi:
# 1e11 ms = anno 1973, 1e11 s = anno 5138. Nessun dato Garmin cade nell'ambiguità.
_MILLISECONDS_THRESHOLD = 10**11

# Un timestamp Garmin plausibile sta fra il 2000 e il 2100. Fuori da questo
# intervallo il valore è un artefatto (il vecchio progetto trovò un 1989 nei
# FIT di monitoring) e va trattato come mancante, non come data.
_MIN_YEAR = 2000
_MAX_YEAR = 2100


class TimestampOutOfRange(ValueError):
    """Il valore è interpretabile ma cade fuori dall'intervallo plausibile."""


def to_utc(value: object) -> datetime | None:
    """Qualunque timestamp Garmin → ``datetime`` UTC consapevole del fuso.

    Restituisce ``None`` per valori assenti. Solleva ``TimestampOutOfRange`` per
    valori interpretabili ma implausibili: un dato sbagliato non deve entrare nel
    database travestito da dato buono (Regola Aurea n.5).
    """
    if value is None or value == "":
        return None

    if isinstance(value, datetime):
        result = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return _check_range(result.astimezone(timezone.utc))

    if isinstance(value, (int, float)):
        seconds = value / 1000 if abs(value) >= _MILLISECONDS_THRESHOLD else value
        return _check_range(datetime.fromtimestamp(seconds, tz=timezone.utc))

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        # Garmin scrive i decimali con una cifra sola ("...:06.0"), che
        # fromisoformat accetta; la "Z" finale no, prima di Python 3.11.
        text = text.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            # Ultima possibilità: una stringa che contiene solo cifre è un epoch.
            if text.lstrip("-").isdigit():
                return to_utc(int(text))
            raise
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return _check_range(parsed.astimezone(timezone.utc))

    raise TypeError(f"Tipo di timestamp non gestito: {type(value).__name__}")


def to_date(value: object) -> date | None:
    """Qualunque timestamp Garmin → ``date`` (giorno di calendario, UTC)."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    moment = to_utc(value)
    return moment.date() if moment else None


def _check_range(moment: datetime) -> datetime:
    if not (_MIN_YEAR <= moment.year <= _MAX_YEAR):
        raise TimestampOutOfRange(
            f"{moment.isoformat()} è fuori dall'intervallo plausibile "
            f"{_MIN_YEAR}-{_MAX_YEAR}"
        )
    return moment
