"""Corregge le zone di tutti i FIT di corsa in original_backup/, uno per uno.

Non scarica nulla, non tocca gli originali, non sovrascrive uscite esistenti.
Un file che non si puo correggere (non e corsa, niente time_in_zone, CRC
rotto, nessuna FC) viene saltato con il motivo scritto nel riepilogo CSV.
Da eseguire con il venv isolato di data/fit-hr-zones.
"""
import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fit_hr_zones as z  # noqa: E402

BASE = Path(__file__).resolve().parents[1] / "data" / "fit-hr-zones"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--max-hr", type=int, default=z.DEFAULT_MAX_HR)
    a = ap.parse_args()
    rows = []
    for fit in sorted((BASE / "original_backup").glob("*.fit")):
        out = BASE / "output" / f"{fit.stem}_HRZONES_CORRECTED.fit"
        if out.exists():
            rows.append((fit.name, "gia_fatto", ""))
            continue
        try:
            sports = {s.get("sport") for s in z.decode(fit)[0].get("session_mesgs", [])}
            if sports != {"running"}:
                rows.append((fit.name, "saltato", f"sport non corsa: {sports}"))
                continue
            _, ok = z.process(fit, BASE / "output", BASE / "reports", a.max_hr)
            rows.append((fit.name, "ok" if ok else "validazione_fallita", ""))
        except Exception as e:  # noqa: BLE001 - il motivo finisce nel riepilogo
            rows.append((fit.name, "saltato", f"{type(e).__name__}: {e}"))
    summary = BASE / "reports" / "batch_summary.csv"
    with summary.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["file", "esito", "motivo"])
        w.writerows(rows)
    for r in rows:
        print(*r)
    print(f"riepilogo: {summary}")
    return 0 if all(r[1] in ("ok", "gia_fatto") for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
