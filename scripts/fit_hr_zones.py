"""Ricalcola le zone cardiache di una corsa dentro un file FIT, senza toccare altro.

Domanda dell'atleta: «Le mie vecchie corse mostrano le zone sbagliate: come le
correggo senza perdere nulla del file Garmin?»

Cosa fa
-------
* Legge il FIT originale (mai modificato: si lavora su una copia in memoria).
* Ricostruisce il tempo in zona dai campioni di FC, pesando ogni campione per
  l'intervallo di tempo reale che copre (non per il numero di campioni).
* Riscrive, byte per byte nella stessa posizione, soltanto i campi dei messaggi
  `time_in_zone` (mesg 216): `time_in_hr_zone`, `hr_zone_high_boundary`,
  `hr_calc_type`, `max_heart_rate`. Il resto del file resta identico, compresi
  messaggi proprietari Garmin e developer fields. Si ricalcola solo il CRC finale.
* Scrive il nuovo file e un report. Verifica poi che nient'altro sia cambiato.

Regole di calcolo (validate sul file originale: con le vecchie soglie questo
algoritmo riproduce i tempi scritti dall'orologio con scarto <= 1 s)
-----------------------------------------------------------------------------
* Soglie in bpm = percentuale x FC max, arrotondate all'intero piu vicino
  (.5 verso l'alto). Con 204 bpm: 102, 122, 143, 163, 184, 204.
* Un campione appartiene a [soglia_k, soglia_k+1): il valore SULLA soglia va
  nella zona superiore. Indice 0 = sotto Zona 1; indice 6 = pari o sopra la FC
  max; indici 1-5 = Zone 1-5.
* Il campione i vale per [t_i, t_i+1): la FC resta quella finche non ne arriva
  un'altra. Intervalli piu lunghi di MAX_GAP_S, senza FC, fuori dal timer
  (pausa) o con timestamp duplicato non vengono inventati: finiscono in
  «non classificabile» o vengono esclusi.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

MESG_TIME_IN_ZONE = 216
F_TIME_IN_HR_ZONE, F_HR_BOUNDARY, F_HR_CALC_TYPE, F_MAX_HR = 2, 6, 10, 11
HR_CALC_PERCENT_MAX_HR = 1
SLOTS = 7  # sotto Z1, Z1..Z5, pari o sopra FC max
MAX_GAP_S = 10  # oltre questo salto fra due campioni non si assume nulla

DEFAULT_MAX_HR = 204
DEFAULT_PERCENTS = (50, 60, 70, 80, 90, 100)


# --------------------------------------------------------------------------
# Zone
# --------------------------------------------------------------------------
def zone_edges(max_hr: int, percents=DEFAULT_PERCENTS) -> list[int]:
    """Soglie in bpm: percentuale della FC max, arrotondata a intero (.5 su)."""
    return [int((Decimal(max_hr) * p / 100).quantize(Decimal(1), ROUND_HALF_UP))
            for p in percents]


def zone_slot(hr: int, edges: list[int]) -> int:
    """0 = sotto Z1, 1..5 = Zona 1..5, 6 = pari o sopra l'ultima soglia."""
    return sum(1 for e in edges if hr >= e)


# --------------------------------------------------------------------------
# Tempo in zona dai campioni
# --------------------------------------------------------------------------
@dataclass
class ZoneTime:
    slots: list[float] = field(default_factory=lambda: [0.0] * SLOTS)
    unclassifiable_s: float = 0.0  # dentro la finestra e il timer, ma senza FC valida

    @property
    def classified_s(self) -> float:
        return sum(self.slots)


@dataclass
class Samples:
    """Campioni di FC puliti. `gaps` conta le anomalie trovate, non le nasconde."""
    t: list[int]
    hr: list[int | None]
    anomalies: dict


def clean_samples(records: list[dict]) -> Samples:
    """Ordina per tempo, scarta timestamp duplicati (tiene il primo), conta i buchi."""
    seen: set[int] = set()
    rows: list[tuple[int, int | None]] = []
    dup = 0
    for r in records:
        ts = r.get("timestamp")
        if ts is None:
            continue
        if ts in seen:
            dup += 1
            continue
        seen.add(ts)
        hr = r.get("heart_rate")
        rows.append((ts, hr if hr else None))  # 0 o assente = mancante, mai zero reale
    rows.sort(key=lambda x: x[0])
    t = [a for a, _ in rows]
    hr = [b for _, b in rows]
    steps = [b - a for a, b in zip(t, t[1:])]
    return Samples(t, hr, {
        "duplicate_timestamps": dup,
        "records_without_hr": sum(1 for h in hr if h is None),
        "gaps_over_limit": sum(1 for s in steps if s > MAX_GAP_S),
        "max_step_s": max(steps) if steps else 0,
        "records": len(t),
    })


def running_periods(events: list[dict], first_t: int, last_t: int) -> list[tuple[float, float]]:
    """Intervalli in cui il timer era acceso, dagli eventi `timer` start/stop."""
    periods: list[tuple[float, float]] = []
    start = None
    for e in sorted((e for e in events if e.get("event") == "timer"), key=lambda e: e["timestamp"]):
        kind = e.get("event_type")
        if kind == "start" and start is None:
            start = e["timestamp"]
        elif kind in ("stop", "stop_all", "stop_disable", "stop_disable_all") and start is not None:
            periods.append((start, e["timestamp"]))
            start = None
    if start is not None:  # timer mai fermato: fino all'ultimo campione
        periods.append((start, last_t))
    return periods or [(first_t, last_t)]


def zone_time(samples: Samples, edges: list[int], window: tuple[float, float],
              running: list[tuple[float, float]]) -> ZoneTime:
    """Secondi per zona dentro `window`, contando solo il timer acceso."""
    zt = ZoneTime()
    w0, w1 = window
    t, hr = samples.t, samples.hr
    for i, ti in enumerate(t):
        if i + 1 < len(t):
            step = t[i + 1] - ti
        else:
            continue  # l'ultimo campione non ha un intervallo successivo
        gap_ok = 0 < step <= MAX_GAP_S
        a0, a1 = ti, ti + step
        for r0, r1 in running:
            lo, hi = max(a0, w0, r0), min(a1, w1, r1)
            if hi <= lo:
                continue
            if hr[i] is None or not gap_ok:
                zt.unclassifiable_s += hi - lo
            else:
                zt.slots[zone_slot(hr[i], edges)] += hi - lo
    return zt


def to_ms(seconds: float) -> int:
    return int(round(seconds * 1000))


# --------------------------------------------------------------------------
# FIT binario: individua e riscrive solo i campi voluti
# --------------------------------------------------------------------------
def fit_crc(data: bytes) -> int:
    table = []
    for i in range(256):
        crc = i
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
        table.append(crc)
    crc = 0
    for b in data:
        crc = table[(crc ^ b) & 0xFF] ^ (crc >> 8)
    return crc


@dataclass
class DataMessage:
    global_num: int
    big_endian: bool
    fields: dict[int, tuple[int, int, int]]  # numero campo -> (offset, size, base_type)


def scan_data_messages(data: bytes) -> list[DataMessage]:
    """Percorre i record del file. Rifiuta file concatenati o troncati."""
    hsize = data[0]
    if hsize not in (12, 14) or data[8:12] != b".FIT":
        raise ValueError("non e un file FIT")
    dsize = struct.unpack_from("<I", data, 4)[0]
    end = hsize + dsize
    if len(data) != end + 2:
        raise ValueError("FIT concatenato o troncato: non supportato")
    defs: dict[int, tuple[int, bool, list, int]] = {}
    out: list[DataMessage] = []
    pos = hsize
    while pos < end:
        h = data[pos]
        pos += 1
        if h & 0x80:  # timestamp compresso: e sempre un messaggio dati
            local = (h >> 5) & 0x03
        elif h & 0x40:  # definizione
            local = h & 0x0F
            big = data[pos + 1] == 1
            glob = struct.unpack_from(">H" if big else "<H", data, pos + 2)[0]
            n = data[pos + 4]
            pos += 5
            flds = [tuple(data[pos + 3 * k: pos + 3 * k + 3]) for k in range(n)]
            pos += 3 * n
            dev_size = 0
            if h & 0x20:
                nd = data[pos]
                pos += 1
                dev_size = sum(data[pos + 3 * k + 1] for k in range(nd))
                pos += 3 * nd
            defs[local] = (glob, big, flds, dev_size)
            continue
        else:
            local = h & 0x0F
        glob, big, flds, dev_size = defs[local]
        offs, fmap = pos, {}
        for num, size, base in flds:
            fmap[num] = (offs, size, base)
            offs += size
        out.append(DataMessage(glob, big, fmap))
        pos = offs + dev_size
    if pos != end:
        raise ValueError("struttura FIT incoerente")
    return out


@dataclass
class PatchLog:
    ranges: list[tuple[int, int]] = field(default_factory=list)  # [inizio, fine) byte toccati

    def add(self, start: int, size: int) -> None:
        self.ranges.append((start, start + size))


def apply_patch(data: bytes, tz_msgs: list[DataMessage], new_values: list[dict],
                edges: list[int], max_hr: int, decoded_tz: list[dict]) -> tuple[bytes, PatchLog]:
    """Riscrive i campi nei punti esatti e ricalcola il CRC finale.

    Un campo previsto dalla definizione ma con valore "non valido" (come nei
    messaggi degli split) resta com'e: non si introducono dati dove non c'erano.
    """
    buf = bytearray(data)
    log = PatchLog()
    for msg, vals, dec in zip(tz_msgs, new_values, decoded_tz):
        endian = ">" if msg.big_endian else "<"
        off, size, _ = msg.fields[F_TIME_IN_HR_ZONE]
        if size != 4 * SLOTS:
            raise ValueError("time_in_hr_zone con lunghezza inattesa")
        struct.pack_into(f"{endian}{SLOTS}I", buf, off, *vals["time_in_hr_zone_ms"])
        log.add(off, size)
        if F_HR_BOUNDARY in msg.fields and "hr_zone_high_boundary" in dec:
            off, size, _ = msg.fields[F_HR_BOUNDARY]
            if size != len(edges):
                raise ValueError("hr_zone_high_boundary con lunghezza inattesa")
            buf[off:off + size] = bytes(edges)
            log.add(off, size)
        if F_HR_CALC_TYPE in msg.fields and "hr_calc_type" in dec:
            off, size, _ = msg.fields[F_HR_CALC_TYPE]
            buf[off] = HR_CALC_PERCENT_MAX_HR
            log.add(off, 1)
        if F_MAX_HR in msg.fields and "max_heart_rate" in dec:
            off, size, _ = msg.fields[F_MAX_HR]
            buf[off] = max_hr
            log.add(off, 1)
    crc = fit_crc(bytes(buf[:-2]))
    struct.pack_into("<H", buf, len(buf) - 2, crc)
    log.add(len(buf) - 2, 2)
    return bytes(buf), log


# --------------------------------------------------------------------------
# Decodifica con l'SDK ufficiale Garmin
# --------------------------------------------------------------------------
def decode(path_or_bytes) -> tuple[dict, list]:
    from garmin_fit_sdk import Decoder, Stream
    def new_stream():
        return Stream.from_byte_array(bytearray(path_or_bytes)) if isinstance(
            path_or_bytes, (bytes, bytearray)) else Stream.from_file(str(path_or_bytes))
    check = Decoder(new_stream())
    if not check.is_fit() or not check.check_integrity():
        raise ValueError("FIT non valido secondo l'SDK Garmin")
    # check_integrity() consuma il flusso: la lettura vera usa un decoder nuovo
    return Decoder(new_stream()).read(apply_scale_and_offset=False, convert_datetimes_to_dates=False,
                    convert_types_to_strings=True, merge_heart_rates=False,
                    expand_sub_fields=False, expand_components=False)


def segment_window(msg: dict, kind: str, sess_window: tuple[float, float]) -> tuple[float, float]:
    """Finestra temporale coperta da un riepilogo (sessione, lap o split)."""
    if kind == "session":
        return sess_window
    start = msg["start_time"]
    elapsed = msg.get("total_elapsed_time")
    if elapsed is None:
        elapsed = msg.get("total_timer_time", 0)
    return (start, start + elapsed / 1000)


def plan_new_values(decoded: dict, edges: list[int]) -> tuple[list[dict], dict]:
    samples = clean_samples(decoded["record_mesgs"])
    running = running_periods(decoded.get("event_mesgs", []), samples.t[0], samples.t[-1])
    sess_window = (running[0][0], running[-1][1])
    by_kind = {"session": decoded.get("session_mesgs", []),
               "lap": decoded.get("lap_mesgs", []),
               "split": decoded.get("split_mesgs", [])}
    plans = []
    for m in decoded["time_in_zone_mesgs"]:
        kind, idx = m["reference_mesg"], m["reference_index"]
        pool = by_kind.get(kind)
        if pool is None:
            raise ValueError(f"time_in_zone riferito a '{kind}': non supportato")
        seg = next((s for s in pool if s.get("message_index", 0) == idx), None) \
            if kind != "session" else pool[idx]
        if seg is None:
            raise ValueError(f"{kind} {idx} non trovato")
        zt = zone_time(samples, edges, segment_window(seg, kind, sess_window), running)
        plans.append({"reference": f"{kind}:{idx}", "zone_time": zt,
                      "time_in_hr_zone_ms": [to_ms(s) for s in zt.slots]})
    return plans, {"samples": samples, "running": running}


# --------------------------------------------------------------------------
# Validazione
# --------------------------------------------------------------------------
ALLOWED_TZ_FIELDS = {"time_in_hr_zone", "hr_zone_high_boundary", "hr_calc_type", "max_heart_rate"}


def validate(original: bytes, corrected: bytes, log: PatchLog, edges, max_hr) -> list[dict]:
    checks: list[dict] = []

    def add(name, ok, detail=""):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    add("Lunghezza identica", len(original) == len(corrected), f"{len(original)} byte")
    allowed = set()
    for a, b in log.ranges:
        allowed.update(range(a, b))
    diff = [i for i in range(min(len(original), len(corrected))) if original[i] != corrected[i]]
    outside = [i for i in diff if i not in allowed]
    add("Nessun byte modificato fuori dai campi autorizzati e dal CRC", not outside,
        f"{len(diff)} byte diversi, {len(outside)} fuori area")
    add("Intestazione FIT identica", original[:14 if original[0] == 14 else 12] ==
        corrected[:14 if corrected[0] == 14 else 12])
    add("CRC finale corretto", struct.unpack_from("<H", corrected, len(corrected) - 2)[0]
        == fit_crc(corrected[:-2]))
    a, _ = decode(original)
    b, errs = decode(corrected)
    add("Decodifica SDK Garmin senza errori", not errs, "integrita e CRC verificati dall'SDK")
    add("Stessi tipi e conteggi di messaggi", {k: len(v) for k, v in a.items()} ==
        {k: len(v) for k, v in b.items()})
    changed: dict[str, int] = {}
    unauthorized = []
    for key, msgs in a.items():
        for i, (ma, mb) in enumerate(zip(msgs, b.get(key, []))):
            for f in set(ma) | set(mb):
                if ma.get(f) != mb.get(f):
                    changed[f"{key}.{f}"] = changed.get(f"{key}.{f}", 0) + 1
                    if not (key == "time_in_zone_mesgs" and f in ALLOWED_TZ_FIELDS):
                        unauthorized.append(f"{key}[{i}].{f}")
    add("Nessun campo modificato oltre ai quattro autorizzati", not unauthorized,
        f"non autorizzati: {unauthorized[:5]}" if unauthorized else "")
    for label, key, fields in [
        ("Timestamp, FC, GPS e distanza dei record", "record_mesgs", None),
        ("Lap", "lap_mesgs", None), ("Sessione", "session_mesgs", None),
        ("Eventi (pause/riprese)", "event_mesgs", None),
        ("Sensori e dispositivi", "device_info_mesgs", None),
        ("Messaggi non documentati/proprietari", None, None)]:
        if key:
            add(f"Conservati: {label}", a.get(key) == b.get(key))
        else:
            known = {k for k in a if k.endswith("_mesgs")}
            raw_keys = [k for k in a if k not in known]
            add(f"Conservati: {label}", all(a[k] == b[k] for k in raw_keys),
                f"{len(raw_keys)} tipi sconosciuti all'SDK")
    # Rilettura indipendente: i valori scritti devono coincidere con un ricalcolo dal file nuovo
    plans, _ = plan_new_values(b, edges)
    stored = [m["time_in_hr_zone"] for m in b["time_in_zone_mesgs"]]
    add("Ricalcolo indipendente dal file nuovo coincide con i valori scritti",
        stored == [p["time_in_hr_zone_ms"] for p in plans])
    bounds_ok = all(m.get("hr_zone_high_boundary", edges) == edges and
                    m.get("hr_calc_type", "percent_max_hr") == "percent_max_hr" and
                    m.get("max_heart_rate", max_hr) == max_hr for m in b["time_in_zone_mesgs"])
    add("Soglie, metodo e FC max coerenti in tutti i messaggi", bounds_ok)
    checks.append({"check": "_campi_cambiati", "ok": True, "detail": changed})
    return checks


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------
ZONE_NAMES = ["Sotto Z1", "Z1", "Z2", "Z3", "Z4", "Z5", "Sopra FC max"]


def fmt(s: float) -> str:
    return f"{int(s // 60)}:{s % 60:04.1f}"


def build_report(src: Path, sha_before: str, sha_after: str, out: Path, decoded: dict,
                 plans: list[dict], ctx: dict, edges, max_hr, checks, old_check) -> str:
    tz0 = decoded["time_in_zone_mesgs"][0]
    s = ctx["samples"]
    sess = plans[0]["zone_time"]
    old = [v / 1000 for v in tz0["time_in_hr_zone"]]
    ok = all(c["ok"] for c in checks)
    L = [f"# Zone cardiache ricalcolate — {src.name}", "",
         f"**Esito validazione: {'SUPERATA' if ok else 'FALLITA'}**", "",
         "## Parametri", f"- FC max: {max_hr} bpm; metodo % FC max (la soglia lattato 177 NON viene usata).",
         f"- Soglie (bpm): {edges}", "- Arrotondamento: percentuale x FC max, intero piu vicino, .5 verso l'alto "
         "(122,4->122; 142,8->143; 163,2->163; 183,6->184).",
         "- Confine: un valore SULLA soglia appartiene alla zona superiore "
         "(122 bpm = Z2; 101 bpm = sotto Z1; 204 bpm = sopra/pari FC max).",
         f"- Salti oltre {MAX_GAP_S} s tra due campioni, campioni senza FC e tempo a timer fermo non vengono inventati.", "",
         "## File", f"- Originale: `{src.name}` SHA-256 `{sha_before}` (invariato dopo l'esecuzione: "
         f"{'si' if sha_before == sha_after else 'NO'})",
         f"- Corretto: `{out.name}`", "",
         "## Zone originali scritte nel file",
         f"- Metodo `{tz0['hr_calc_type']}`, FC max {tz0['max_heart_rate']}, riposo {tz0['resting_heart_rate']}, "
         f"soglie {tz0['hr_zone_high_boundary']}", "",
         "## Sessione: originali vs ricalcolate", "",
         "| Zona | Soglie | Originale | Ricalcolato | Differenza | % durata nuova |", "|---|---|---|---|---|---|"]
    tot = sess.classified_s or 1
    ranges = ["< 102"] + [f"{edges[i]}-{edges[i + 1] - 1}" for i in range(5)] + [f">= {edges[5]}"]
    for i in range(SLOTS):
        n = sess.slots[i]
        L.append(f"| {ZONE_NAMES[i]} | {ranges[i]} | {fmt(old[i])} | {fmt(n)} | {n - old[i]:+.1f} s | {100 * n / tot:.1f}% |")
    L += ["", f"Non classificabile: {sess.unclassifiable_s:.1f} s. Totale classificato: {sess.classified_s:.1f} s.", "",
          "Nota: nelle zone originali la colonna 'Sotto Z1' contiene tutto cio che e sotto la prima soglia del vecchio schema, "
          "quindi non e confrontabile 1:1 con le nuove zone: il confronto utile e per zona nuova vs distribuzione per FC.", "",
          "## Verifica dell'algoritmo sul file originale",
          f"Applicato alle vecchie soglie, l'algoritmo da {old_check['recomputed']} s contro "
          f"{old_check['garmin']} s scritti dall'orologio (scarto massimo {old_check['max_diff']:.1f} s).", "",
          "## Lap", "", "| Lap | " + " | ".join(ZONE_NAMES[:6]) + " |", "|---|" + "---|" * 6]
    for p in plans:
        if p["reference"].startswith("lap:"):
            L.append(f"| {p['reference']} | " + " | ".join(fmt(x) for x in p["zone_time"].slots[:6]) + " |")
    L += ["", "## Anomalie rilevate", f"- Campioni: {s.anomalies['records']}, passo massimo {s.anomalies['max_step_s']} s, "
          f"senza FC: {s.anomalies['records_without_hr']}, duplicati: {s.anomalies['duplicate_timestamps']}, "
          f"salti oltre il limite: {s.anomalies['gaps_over_limit']}.",
          f"- Periodi a timer acceso: {len(ctx['running'])}.", ""]
    split0_old = next((m for m in decoded['time_in_zone_mesgs'] if m['reference_mesg'] == 'split'
                       and m['reference_index'] == 0), None)
    if split0_old:
        tot0 = sum(split0_old['time_in_hr_zone']) / 1000
        L.append(f"- Lo split 0 originale somma {tot0:.0f} s, piu del timer ({sess.classified_s:.0f} s): "
                 "Garmin conta due volte parte del tempo. Il ricalcolo usa la durata reale.")
    L += ["", "## Controlli di validazione", ""]
    for c in checks:
        if c["check"].startswith("_"):
            continue
        L.append(f"- [{'OK' if c['ok'] else 'FALLITO'}] {c['check']}" + (f" — {c['detail']}" if c["detail"] else ""))
    changed = next(c for c in checks if c["check"] == "_campi_cambiati")["detail"]
    L += ["", "## Campi cambiati (tutti e soli)", ""] + [f"- `{k}`: {v} messaggi" for k, v in sorted(changed.items())]
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------------
# Programma principale
# --------------------------------------------------------------------------
def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def process(src: Path, out_dir: Path, report_dir: Path, max_hr: int) -> tuple[Path, bool]:
    original = src.read_bytes()
    sha_before = sha256(original)
    if struct.unpack_from("<H", original, len(original) - 2)[0] != fit_crc(original[:-2]):
        raise ValueError("CRC dell'originale non valido: non lo tocco")
    out = out_dir / f"{src.stem}_HRZONES_CORRECTED.fit"
    if out.exists():
        raise FileExistsError(f"{out} esiste: non sovrascrivo")
    if out.resolve() == src.resolve():
        raise ValueError("uscita uguale all'ingresso")

    edges = zone_edges(max_hr)
    decoded, errs = decode(original)
    if errs or not decoded.get("time_in_zone_mesgs"):
        raise ValueError("nessun messaggio time_in_zone da correggere (o errori di decodifica)")
    plans, ctx = plan_new_values(decoded, edges)

    tz_msgs = [m for m in scan_data_messages(original) if m.global_num == MESG_TIME_IN_ZONE]
    if len(tz_msgs) != len(plans):
        raise ValueError("messaggi time_in_zone non allineati")
    # allineamento: i valori letti dai byte devono coincidere con quelli decodificati
    for m, d in zip(tz_msgs, decoded["time_in_zone_mesgs"]):
        off, size, _ = m.fields[F_TIME_IN_HR_ZONE]
        raw = struct.unpack_from(("<" if not m.big_endian else ">") + f"{SLOTS}I", original, off)
        if list(raw) != d["time_in_hr_zone"]:
            raise ValueError("allineamento byte/SDK fallito")

    corrected, log = apply_patch(original, tz_msgs, plans, edges, max_hr, decoded["time_in_zone_mesgs"])

    # prova dell'algoritmo: con le vecchie soglie riproduce i tempi Garmin?
    tz0 = decoded["time_in_zone_mesgs"][0]
    old_plans, _ = plan_new_values(decoded, tz0["hr_zone_high_boundary"])
    diffs = [abs(a - b / 1000) for a, b in zip(old_plans[0]["zone_time"].slots, tz0["time_in_hr_zone"])]
    old_check = {"recomputed": [round(x) for x in old_plans[0]["zone_time"].slots[:3]],
                 "garmin": [round(x / 1000) for x in tz0["time_in_hr_zone"][:3]], "max_diff": max(diffs)}

    checks = validate(original, corrected, log, edges, max_hr)
    ok = all(c["ok"] for c in checks) and sha256(src.read_bytes()) == sha_before
    out_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    if ok:
        out.write_bytes(corrected)
    report = build_report(src, sha_before, sha256(src.read_bytes()), out, decoded, plans, ctx,
                          edges, max_hr, checks, old_check)
    (report_dir / f"{src.stem}_zones_report.md").write_text(report, encoding="utf-8")
    (report_dir / f"{src.stem}_validation.json").write_text(
        json.dumps({"ok": ok, "checks": checks, "edges": edges}, indent=2, ensure_ascii=False), encoding="utf-8")
    return out, ok


def main(argv=None) -> int:
    root = Path(__file__).resolve().parents[1] / "data" / "fit-hr-zones"
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("fit", type=Path, help="FIT originale (resta intatto)")
    ap.add_argument("--max-hr", type=int, default=DEFAULT_MAX_HR)
    ap.add_argument("--out-dir", type=Path, default=root / "output")
    ap.add_argument("--report-dir", type=Path, default=root / "reports")
    a = ap.parse_args(argv)
    out, ok = process(a.fit, a.out_dir, a.report_dir, a.max_hr)
    print(("FILE SCRITTO: " if ok else "VALIDAZIONE FALLITA, nessun file scritto: ") + str(out))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
