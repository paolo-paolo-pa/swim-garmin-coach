"""Elenca (e, solo se richiesto, scarica) i FIT originali delle corse da correggere.

Domanda: «Quali corse posso correggere e mi mancano i file originali?»
Predefinito = prova a secco: stampa l'elenco e non contatta Garmin.
Con --download N scarica al massimo N file mancanti, uno ogni --pause secondi,
in sola lettura, e si ferma al primo 401/403/429. Mai sovrascrive un file.
Da eseguire con il venv del progetto (serve il database e il client Garmin).
"""
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
BACKUP = ROOT / "data" / "fit-hr-zones" / "original_backup"


def candidates(since, device):
    import duckdb
    con = duckdb.connect(str(ROOT / "data" / "coach.duckdb"), read_only=True)
    q = """SELECT activity_id, activity_date, sport, device_id, round(avg_hr_bpm), name
           FROM activities WHERE sport IN ('running','treadmill_running')
           AND avg_hr_bpm IS NOT NULL AND activity_date >= ?"""
    args = [since]
    if device:
        q += " AND device_id = ?"
        args.append(device)
    return con.execute(q + " ORDER BY activity_date DESC", args).fetchall()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--since", default="2000-01-01", help="data minima AAAA-MM-GG")
    ap.add_argument("--device", type=int, help="solo questo device_id (vedi elenco)")
    ap.add_argument("--download", type=int, default=0, help="quanti file scaricare (0 = prova a secco)")
    ap.add_argument("--pause", type=float, default=5.0)
    a = ap.parse_args()
    rows = candidates(a.since, a.device)
    todo = [r for r in rows if not (BACKUP / f"{r[0]}.fit").exists()]
    for r in rows:
        print(("MANCA  " if r in todo else "presente"), *r)
    print(f"\n{len(rows)} corse con FC, {len(todo)} senza FIT locale.")
    if not a.download:
        return
    from garmin_coach.ingest.fit_download import _fit_from, looks_like_fit
    from garmin_coach.ingest.personal_api import PersonalApiFailure, PersonalGarmin
    client = PersonalGarmin()
    done = 0
    try:
        for r in todo[: a.download]:
            try:
                fit = _fit_from(client.download_activity(r[0]))
            except PersonalApiFailure as e:
                print("ERRORE", r[0], e)
                if e.stop_sync:
                    break
                continue
            if not fit or not looks_like_fit(fit):
                print("NON FIT", r[0])
                continue
            path = BACKUP / f"{r[0]}.fit"
            path.write_bytes(fit) if not path.exists() else None
            path.chmod(0o444)
            done += 1
            print("scaricato", path.name, len(fit))
            time.sleep(a.pause)
    finally:
        client.close()
    print(f"scaricati {done}")


if __name__ == "__main__":
    main()
