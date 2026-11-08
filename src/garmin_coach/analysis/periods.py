"""Intervalli espliciti condivisi dalle API analitiche."""
from datetime import date,timedelta


def parse(params):
    end=date.fromisoformat(params.get("end") or date.today().isoformat())
    days=int(params.get("days",28))
    start=date.fromisoformat(params["start"]) if params.get("start") else end-timedelta(days=days-1)
    if start>end or (end-start).days>20000:
        raise ValueError("Periodo non valido")
    return start,end
