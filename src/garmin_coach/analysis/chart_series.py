"""«Il cambiamento è reale, oppure il grafico nasconde giorni mancanti?»

Serie giornaliere già normalizzate, aggregate senza interpolare. I bucket
settimanali iniziano il lunedì; quelli mensili il primo del mese. Entrambi
sono tagliati sull'intervallo richiesto, con denominatore in giorni effettivi.

Il trend è retrospettivo. Per le medie è la mediana giornaliera mobile; per
le somme settimanali/mensili è la media dei totali dei quattro periodi
calendar completi precedenti. Nessun dato viene proiettato su giorni senza
osservazioni. Un bucket privo di campioni non riceve nemmeno un trend.
"""
from datetime import date, datetime, timedelta
import math
from numbers import Real
import statistics


LABELS = {"day": "Giornaliero", "week": "Settimanale", "month": "Mensile"}
MIN_TREND_OBSERVATIONS = 14


def _day(value):
    if isinstance(value, datetime):
        return value.date()
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def _value(value):
    return value if isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value) else None


def _bucket_end(day, resolution):
    if resolution == "day":
        return day
    if resolution == "week":
        return day + timedelta(days=6-day.weekday())
    following = date(day.year + (day.month == 12), day.month % 12 + 1, 1)
    return following - timedelta(days=1)


def _bucket_start(day, resolution):
    if resolution == "week":
        return day-timedelta(days=day.weekday())
    return day.replace(day=1) if resolution == "month" else day


def _previous_buckets(day, resolution):
    end = _bucket_start(day, resolution)-timedelta(days=1)
    result = []
    for _ in range(4):
        start = _bucket_start(end, resolution)
        result.append((start, end))
        end = start-timedelta(days=1)
    return result


def _values(observed, key, first, last):
    values = [observed.get(first+timedelta(days=i), {}).get(key)
              for i in range((last-first).days+1)]
    return [value for value in values if value is not None]


def build(rows, start, end, fields, resolution="auto", trend_days=28):
    """Restituisce ``rows`` per TrendChart e metodi leggibili.

    ``rows`` contiene al massimo una riga per giorno nel campo ``date``;
    ``fields`` associa ogni metrica a ``mean`` o ``sum``. I valori non finiti,
    booleani e mancanti non sono osservazioni. Lo zero numerico lo è.

    Possono essere forniti giorni precedenti a ``start`` per inizializzare il
    trend. Nessuna osservazione successiva a ``period_end`` è mai utilizzata.
    ``*_n`` conta giorni osservati, ``*_expected_n`` i giorni del bucket;
    ``*_trend_n`` e ``*_trend_expected_n`` contano giorni per medie e somme
    giornaliere (minimo quattordici). Per somme settimanali/mensili contano
    invece i quattro periodi precedenti, di cui almeno tre con osservazioni.
    Un periodo parziale non mostra il trend delle somme. I totali dei periodi
    precedenti includono solo i valori disponibili: non stimano giorni assenti.
    """
    start, end = _day(start), _day(end)
    if start > end:
        raise ValueError("L'inizio deve precedere la fine del periodo")
    if resolution not in ("auto", *LABELS):
        raise ValueError("Risoluzione non valida")
    if not isinstance(trend_days, int) or isinstance(trend_days, bool) or trend_days < 14:
        raise ValueError("Il trend richiede una finestra di almeno 14 giorni")
    if not fields or any(operation not in ("mean", "sum") for operation in fields.values()):
        raise ValueError("Ogni metrica richiede mean oppure sum")
    days = (end-start).days + 1
    if resolution == "auto":
        resolution = "day" if days <= 90 else "week" if days <= 730 else "month"

    observed = {}
    earliest = start-timedelta(days=trend_days-1)
    if resolution != "day" and "sum" in fields.values():
        earliest = min(earliest, _previous_buckets(start, resolution)[-1][0])
    for row in rows:
        day = _day(row["date"])
        if earliest <= day <= end:
            if day in observed:
                raise ValueError("Le serie richiedono una sola riga per giorno")
            observed[day] = {key: _value(row.get(key)) for key in fields}

    result = []
    current = start
    while current <= end:
        last = min(_bucket_end(current, resolution), end)
        expected = (last-current).days + 1
        bucket = {"date": current.isoformat(), "period_end": last.isoformat()}
        for key, operation in fields.items():
            values = _values(observed, key, current, last)
            recent = _values(observed, key, last-timedelta(days=trend_days-1), last)
            bucket[key] = (statistics.mean(values) if operation == "mean" else sum(values)) if values else None
            bucket[key+"_n"] = len(values)
            bucket[key+"_expected_n"] = expected
            bucket[key+"_coverage_pct"] = len(values)/expected*100
            bucket[key+"_trend_n"] = len(recent)
            bucket[key+"_trend_expected_n"] = trend_days
            bucket[key+"_trend"] = None
            if operation == "sum" and resolution != "day":
                totals, observed_days, expected_days = [], 0, 0
                for first, previous_end in _previous_buckets(current, resolution):
                    previous_values = _values(observed, key, first, previous_end)
                    if previous_values:
                        totals.append(sum(previous_values))
                    observed_days += len(previous_values)
                    expected_days += (previous_end-first).days+1
                bucket[key+"_trend_n"] = len(totals)
                bucket[key+"_trend_expected_n"] = 4
                bucket[key+"_trend_observed_days_n"] = observed_days
                bucket[key+"_trend_expected_days_n"] = expected_days
                complete = current == _bucket_start(current, resolution) and last == _bucket_end(current, resolution)
                if complete and values and len(totals) >= 3:
                    bucket[key+"_trend"] = statistics.mean(totals)
            elif values and len(recent) >= MIN_TREND_OBSERVATIONS:
                bucket[key+"_trend"] = statistics.median(recent) if operation == "mean" else statistics.mean(recent)
        result.append(bucket)
        if last == end:
            break
        current = last+timedelta(days=1)

    sum_method = (f"Media mobile di {trend_days} giorni registrati; almeno 14 giorni osservati" if resolution == "day" else
                  "Media mobile di 4 "+("settimane" if resolution == "week" else "mesi")+
                  " precedenti delle somme registrate; almeno 3 periodi con osservazioni. Nessun trend nei periodi parziali")
    methods = {key: f"Mediana mobile sui {trend_days} giorni terminanti alla fine del periodo; almeno 14 osservazioni" if operation == "mean" else sum_method
               for key, operation in fields.items()}
    return {"rows": result, "resolution": resolution, "resolution_label": LABELS[resolution],
            "trend_days": trend_days, "trend_min_n": MIN_TREND_OBSERVATIONS,
            "trend_min_n_by_field": {key: 3 if operation == "sum" and resolution != "day" else MIN_TREND_OBSERVATIONS
                                     for key, operation in fields.items()},
            "trend_method": "Mediana mobile giornaliera per le metriche medie. "+sum_method+
                            ". Nessun trend nei periodi completamente privi di campioni; giorni mancanti mai stimati.",
            "trend_methods": methods,
            "trend_count_units": {key: "periodi" if operation == "sum" and resolution != "day" else "giorni" for key, operation in fields.items()},
            "aggregation": dict(fields)}
