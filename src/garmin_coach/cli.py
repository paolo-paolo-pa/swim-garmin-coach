"""Riga di comando del progetto.

    python -m garmin_coach ingest       importa tutto dall'export
    python -m garmin_coach metrics      ricalcola daily_status
    python -m garmin_coach verify       controlla i criteri di accettazione
    python -m garmin_coach fingerprint  registra l'impronta della sorgente
    python -m garmin_coach integrity    prova che la sorgente non è cambiata
    python -m garmin_coach all          importa, calcola e verifica

    python -m garmin_coach connect      collega l'account, guidato passo passo
    python -m garmin_coach status       a che punto siamo, senza contattare Garmin
    python -m garmin_coach login        accesso a Garmin Connect
    python -m garmin_coach sync         aggiorna dai dati recenti e ricalcola
    python -m garmin_coach schedule     aggiorna da solo, tre volte al giorno
    python -m garmin_coach update       scarica ed elabora tutto: la catena intera
    python -m garmin_coach details      serie e vasche dai file FIT (Fase 5)
    python -m garmin_coach track        la traccia al secondo di mare e gare
    python -m garmin_coach weather      che acqua e che vento c'era in gara
    python -m garmin_coach snapshot     fotografia dello stato, ricalcolata adesso
    python -m garmin_coach backup       copia il database prima di toccarne lo schema
    python -m garmin_coach dictionary   rigenera docs/DIZIONARIO-DATI.md dallo schema
    python -m garmin_coach rebuild      cancella e ricostruisce tutto dalle sorgenti
    python -m garmin_coach digest       l'impronta del contenuto, per confrontarla
    python -m garmin_coach slice        una seduta per ogni caso che puo rompersi

Ogni comando è idempotente: rieseguirlo non crea duplicati.

``login`` è l'unico comando interattivo e va eseguito dall'atleta: le credenziali
non vengono mai scritte su disco né lette da questo progetto.
"""

from __future__ import annotations

import argparse
import sys

from . import database, paths, source_integrity
from .ingest import aquatime, declared_races, health, icron, summaries
from .metrics import daily_status
from .verification import run_checks


def _ingest() -> int:
    with database.connect() as connection:
        print("Import dei riepiloghi attività…")
        report = summaries.load(connection)
        print(f"  activities: {report['rows']:>6,} righe da {report['files']} file")
        for note in report["skipped"][:10]:
            print(f"    scartata — {note}")
        if len(report["skipped"]) > 10:
            print(f"    …e altre {len(report['skipped']) - 10} scartate")

        print("Import di salute, sonno, HRV, carico e peso…")
        for entry in health.load(connection):
            print(f"  {entry['table']:<24} {entry['rows']:>6,} righe "
                  f"da {entry['files']} file")
            for note in entry["skipped"][:3]:
                print(f"    scartata — {note}")

        print("Import dello storico gare della federazione…")
        gare = aquatime.load(connection)
        if not gare["files"]:
            print("  nessun file in coach/aquatime/: niente da importare")
        else:
            print(f"  races          {gare['races']:>6,} gare "
                  f"({gare['relays']} staffette, {gare['disqualified']} squalifiche)")
            print(f"  race_splits    {gare['splits']:>6,} passaggi")
            if gare["duplicates"]:
                print(f"  {gare['duplicates']} righe ripetute nella sorgente, "
                      "contate una volta sola")
            for note in gare["skipped"][:5]:
                print(f"    scartata — {note}")

        print("Import delle gare in acque libere…")
        mare = icron.load(connection)
        if not mare["files"]:
            print("  nessun file in coach/icron/: niente da importare")
        else:
            print(f"  races          {mare['races']:>6,} gare in mare "
                  f"({mare['without_distance']} senza distanza dichiarata)")
            if mare["duplicates"]:
                print(f"  {mare['duplicates']} righe che sono la stessa nuotata "
                      "in due graduatorie, contate una volta sola")
            for note in mare["skipped"][:5]:
                print(f"    scartata — {note}")

        dichiarate = declared_races.load(connection)
        if dichiarate["races"]:
            print("Gare dichiarate dall'atleta…")
            print(f"  races          {dichiarate['races']:>6,} gare "
                  f"({dichiarate['linked_to_garmin']} collegate a una seduta "
                  "Garmin)")
            if dichiarate["without_time"]:
                print(f"  {dichiarate['without_time']} senza tempo ufficiale: "
                      "sono successe, il cronometro non ce l'abbiamo")
            if dichiarate["unreadable_time"]:
                print(f"  {dichiarate['unreadable_time']} con un tempo che non "
                      "si legge: da correggere nel file")
    return 0


def _metrics() -> int:
    """Applica le correzioni dell'atleta e ricalcola.

    Le due cose stanno insieme e in quest'ordine perché `daily_status` aggrega:
    un'attività esclusa che entra nell'aggregato non ne esce più da sola, e il
    suo carico resta dentro le finestre a 28 giorni per quattro settimane.
    """
    from . import corrections, race_corrections

    with database.connect() as connection:
        decisioni = corrections.apply(connection)
        if decisioni["decisioni"]:
            print(f"Correzioni confermate dall'atleta: "
                  f"{decisioni['decisioni']} ({decisioni['escluse']} esclusioni)")
        gare = race_corrections.apply(connection)
        if gare["decisioni"]:
            print(f"Correzioni sulle gare: {gare['decisioni']} "
                  f"({gare['collegate']} collegate a una nuotata, "
                  f"{gare['escluse']} escluse)")
        segnalate = corrections.flag_automatically(connection)
        if segnalate:
            print(f"Da guardare: {len(segnalate)} attività superano un limite "
                  "fisico e non reggono conclusioni forti finché non decidi")
            for una in segnalate[:5]:
                print(f"    {una['day']}  seduta {una['activity_id']} — "
                      f"{una['check']}")
            if len(segnalate) > 5:
                print(f"    …e altre {len(segnalate) - 5}")
            # Senza questa riga la segnalazione era un vicolo cieco: diceva che
            # c'era qualcosa da decidere e non diceva dove si decide.
            print("    Per guardarle e decidere: garmin_coach app → «Da decidere»")
        report = daily_status.build(connection)
        print(f"daily_status: {report['rows']:,} giorni "
              f"({report['first_day']} → {report['last_day']})")
    return 0


def _verify() -> int:
    with database.connect(read_only=True) as connection:
        results = run_checks(connection)
    failures = [check for check in results if not check.passed]
    for check in results:
        mark = "OK  " if check.passed else "FALLITO"
        print(f"[{mark}] {check.identifier} — {check.description}")
        print(f"         atteso: {check.expected}")
        print(f"         ottenuto: {check.actual}")
    print(f"\n{len(results) - len(failures)}/{len(results)} controlli superati")
    return 1 if failures else 0


def _fingerprint() -> int:
    fingerprint = source_integrity.save_baseline()
    print(f"Impronta registrata su {len(fingerprint)} file di garmin-export/")
    print(f"  {source_integrity.FINGERPRINT}")
    return 0


def _integrity() -> int:
    report = source_integrity.verify()
    print(f"Integrità della sorgente: {report.summary()}")
    for name in report.changed:
        print(f"  MODIFICATO  {name}")
    for name in report.missing:
        print(f"  MANCANTE    {name}")
    for name in report.added:
        print(f"  nuovo       {name}")
    if report.is_intact:
        print("La sorgente non è stata modificata (Regola Aurea n.4 rispettata).")
        return 0
    print("ATTENZIONE: la sorgente è cambiata.", file=sys.stderr)
    return 1


def _status() -> int:
    """A che punto siamo: connessione, dati, prossima mossa.

    Non contatta Garmin: risponde da quello che c'e sul disco.
    """
    from datetime import date

    from .ingest import garmin_login

    state = garmin_login.status()
    print("  CONNESSIONE A GARMIN")
    print(f"    {state.headline()}")
    if state.last_attempt:
        print(f"    Ultimo tentativo: {state.last_attempt.astimezone():%d/%m/%Y %H:%M}")

    print()
    print("  DATI")
    try:
        with database.connect(read_only=True) as connection:
            latest = connection.execute(
                "SELECT max(status_date) FROM daily_status").fetchone()[0]
            swims = connection.execute(
                "SELECT count(*) FROM activities WHERE is_swim").fetchone()[0]
    except Exception:  # noqa: BLE001
        print("    Database non ancora creato. Eseguire: garmin_coach all")
        return 0

    if latest is None:
        print("    Database vuoto. Eseguire: garmin_coach all")
        return 0
    behind = (date.today() - latest).days
    print(f"    {swims:,} sedute di nuoto in archivio")
    print(f"    Ultimo giorno con dati: {latest} ({behind} giorni fa)")

    print()
    print("  PROSSIMA MOSSA")
    if not state.connected:
        if state.can_try_now:
            print("    Collegare l'account:  garmin_coach connect")
        else:
            minutes = max(1, int(state.cooldown_remaining.total_seconds() // 60))
            print(f"    Attendere {minutes} minuti, poi:  garmin_coach connect")
    elif behind > 1:
        print("    Aggiornare i dati:  garmin_coach sync")
    else:
        print("    Niente: i dati sono aggiornati.")
    return 0


def _connect(force: bool = False) -> int:
    """Collegamento a Garmin dall'inizio alla fine, in un comando solo.

    Non dipende dall'esecuzione di script PowerShell: su molti sistemi Windows
    e disabilitata per sicurezza, e non e una cosa da cambiare per far girare
    un progetto personale.
    """
    print()
    print("  GARMIN COACH - collegamento a Garmin Connect")
    print("  " + "-" * 44)
    print()

    if _status() != 0:
        return 1

    from .ingest import garmin_login

    state = garmin_login.status()
    if state.connected:
        print()
        print("  Gia collegato: non serve altro.")
        return _sync()

    if not state.can_try_now and not force:
        return 1

    print()
    print("  PRIMA DI CONTINUARE")
    print("    Garmin puo mandarti un codice di verifica via email, perche")
    print("    questo computer per lui e nuovo. Apri ORA la casella di posta:")
    print("    il codice scade in pochi minuti.")
    print()
    if input("    Pronto? (invio per continuare, 'n' per annullare) ").strip().lower() == "n":
        print("    Annullato. Niente e stato modificato.")
        return 0

    print()
    if _login(force=force) != 0:
        print()
        print("  Il progetto continua a funzionare sui dati locali.", file=sys.stderr)
        print("  Per rivedere la situazione:  garmin_coach status", file=sys.stderr)
        return 1

    print()
    print("  SCARICO DEI DATI MANCANTI")
    if _sync() != 0:
        print()
        print("  Il collegamento funziona ma lo scarico si e fermato.", file=sys.stderr)
        print("  I dati gia presenti non sono stati toccati.", file=sys.stderr)
        return 1

    print()
    _status()
    return 0


def _login(force: bool = False) -> int:
    """Accesso a Garmin Connect. Da eseguire dall'atleta.

    Le credenziali vanno direttamente alla libreria Garmin e non vengono
    conservate: sul disco resta soltanto un token, gia escluso da Git.
    """
    import getpass

    from .ingest import garmin_login

    state = garmin_login.status()
    if state.connected:
        print("Risulta gia un accesso salvato. Verifico che funzioni...")
        try:
            check = garmin_login.verify_connection()
            print(f"  Connessione valida (account: {check['account']}).")
            print("  Non serve rifare l'accesso.")
            return 0
        except Exception:  # noqa: BLE001
            print("  Il token salvato non funziona piu: rifacciamo l'accesso.")
            print()

    pending = garmin_login.cooldown_remaining()
    if pending and not force:
        remaining, reason = pending
        minutes = max(1, int(remaining.total_seconds() // 60))
        print(f"L'ultimo tentativo e fallito ({reason}).", file=sys.stderr)
        print(f"Riprovare fra circa {minutes} minuti.", file=sys.stderr)
        print("Bussare di nuovo adesso allunga il blocco invece di superarlo.",
              file=sys.stderr)
        return 1

    print("ACCESSO A GARMIN CONNECT")
    print("Le credenziali non vengono salvate: resta solo un token locale.")
    print()
    print("Garmin puo chiedere un codice di verifica via email, perche questo")
    print("computer per lui e nuovo. Tieni la casella aperta: il codice scade in fretta.")
    print()

    email = input("  Email Garmin: ").strip()
    if not email:
        print("Accesso annullato.", file=sys.stderr)
        return 2
    password = getpass.getpass("  Password (non viene mostrata mentre digiti): ")
    if not password:
        print("Accesso annullato.", file=sys.stderr)
        return 2

    def ask_mfa() -> str:
        print()
        print("  Garmin ha inviato un codice di verifica.")
        print("  Controlla la casella di " + email + " (anche nello spam).")
        return input("  Codice ricevuto: ").strip()

    print()
    print("Accesso in corso, un solo tentativo...")
    try:
        where = garmin_login.log_in(email, password, mfa_prompt=ask_mfa, force=force)
    except garmin_login.RateLimited:
        print()
        print("GARMIN HA BLOCCATO IL TENTATIVO (errore 429).", file=sys.stderr)
        print("Non e la password sbagliata: e un blocco per numero di richieste",
              file=sys.stderr)
        print("dallo stesso indirizzo internet.", file=sys.stderr)
        print("  1. aspetta un'ora;", file=sys.stderr)
        print("  2. riprova una volta sola;", file=sys.stderr)
        print("  3. se persiste, prova dall'hotspot del telefono.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print()
        print("Accesso interrotto. Non e rimasto niente a meta.", file=sys.stderr)
        return 130
    except Exception as error:  # noqa: BLE001
        print()
        print(f"Accesso non riuscito: {type(error).__name__}", file=sys.stderr)
        print(f"  {error}", file=sys.stderr)
        return 1

    print()
    print("Accesso riuscito. Verifico che il collegamento funzioni davvero...")
    try:
        check = garmin_login.verify_connection()
        print(f"  Confermato. Account: {check['account']}")
    except Exception as error:  # noqa: BLE001
        print(f"  Token salvato ma la verifica non riesce: {type(error).__name__}",
              file=sys.stderr)
        return 1

    print(f"  Token in {where}")
    print()
    print("Ora si puo aggiornare:  garmin_coach sync")
    return 0


def _rebuild() -> int:
    """Cancella il database e lo ricostruisce dalle sorgenti.

    Distruttivo solo in apparenza: il database e interamente generato e le
    sorgenti sono immutabili. Una copia viene comunque salvata prima.
    """
    import time

    from . import rebuild as rebuilder, state_report

    print("  RICOSTRUZIONE COMPLETA")
    print("  Il database viene cancellato e rifatto dalle sorgenti.")
    where = state_report.backup_database("prima-del-rebuild")
    print(f"  Copia di sicurezza: {where.name}")
    print()

    started = time.time()
    try:
        with rebuilder.single_writer("ricostruzione"):
            report = rebuilder.rebuild()
    except rebuilder.DatabaseBusy as error:
        print(str(error), file=sys.stderr)
        return 1

    print(f"  attivita       {report['activities']:>8,}   dall'export")
    snapshots = report.get("snapshots", {})
    if snapshots.get("days"):
        print(f"  rigiocate      {report.get('replayed_activities', 0):>8,}   "
              f"dalle catture del sync ({snapshots['days']} giorni, "
              f"{snapshots['first']} → {snapshots['last']})")
    else:
        print("  rigiocate             0   nessuna cattura del sync su disco")
    print(f"  salute         {report['health']:>8,}")
    print(f"  daily_status   {report['daily_status']:>8,}")
    print(f"  lap            {report.get('laps', 0):>8,}")
    print(f"  vasche         {report.get('lengths', 0):>8,}")
    print()
    print(f"  digest  {report['digest']}")
    print(f"  in {time.time() - started:.0f} secondi")
    print()
    print("  Per dimostrare che e riproducibile: rilanciare e confrontare il digest.")
    return 0


def _slice() -> int:
    from . import vertical_slice

    with database.connect(read_only=True) as connection:
        cases = vertical_slice.run(connection)
    print(vertical_slice.render(cases))
    return 1 if any(case.problems for case in cases) else 0


def _digest() -> int:
    from . import rebuild as rebuilder

    with database.connect(read_only=True) as connection:
        digest = rebuilder.canonical_digest(connection)
    print(digest["overall"])
    for table, value in sorted(digest["tables"].items()):
        print(f"  {table:<28} {value}")
    return 0


def _dictionary() -> int:
    from . import data_dictionary

    with database.connect(read_only=True) as connection:
        undocumented, phantom = data_dictionary.missing_documentation(connection)
        if undocumented:
            print(f"Tabelle senza descrizione: {', '.join(sorted(undocumented))}",
                  file=sys.stderr)
            print("Vanno descritte in data_dictionary.TABLES prima di generare.",
                  file=sys.stderr)
            return 1
        if phantom:
            print(f"Descritte ma inesistenti: {', '.join(sorted(phantom))}",
                  file=sys.stderr)
            return 1
        text = data_dictionary.render(connection)

    target = paths.DOCS / "DIZIONARIO-DATI.md"
    target.write_text(text, encoding="utf-8")
    print(f"Dizionario rigenerato: {target}")
    print(f"  {len(data_dictionary.TABLES)} tabelle descritte")
    return 0


def _snapshot() -> int:
    from . import state_report

    with database.connect(read_only=True) as connection:
        print(state_report.take(connection).text())
    return 0


def _backup() -> int:
    from . import state_report

    where = state_report.backup_database("manuale")
    size = where.stat().st_size / 1024 / 1024
    print(f"Copia salvata in {where} ({size:.1f} MB)")
    print("Il database resta comunque ricostruibile da zero con: garmin_coach all")
    return 0


def _sync() -> int:
    """Aggiorna dai dati recenti.

    L'esito finisce sempre in ``data/sync.log``, che il comando sia stato
    lanciato a mano o dall'aggiornamento automatico: un sync fallito in
    silenzio lascia credere che i dati siano freschi, ed è peggio di un sync
    mancato.
    """
    import os
    from .ingest.personal_api import STORE, update as personal_update
    if os.environ.get("GARMIN_PERSONAL_API_KEY") or (STORE / "api-key").exists():
        report = personal_update()
        print(f"Garmin Personal API: {report['outcome']}")
        return 1 if report['outcome'] == 'failed' else 0
    from . import corrections, race_corrections, rebuild as rebuilder, scheduling
    from .ingest import sync

    with rebuilder.single_writer("sync"), database.connect() as connection:
        report = sync.pull(connection)
        print(report.summary())
        for note in report.skipped[:5]:
            print(f"  giorno saltato — {note}")
        if not report.succeeded:
            scheduling.append_to_log(report.summary())
            for error in report.errors:
                print(f"  {error}", file=sys.stderr)
            return 1
        # Il sync riscarica sempre qualche giorno all'indietro e può riportare
        # dentro un'attività esclusa. La correzione si riapplica prima del
        # calcolo, ogni volta, altrimenti dura fino al prossimo aggiornamento.
        corrections.apply(connection)
        race_corrections.apply(connection)
        daily_status.build(connection)
        latest = connection.execute(
            "SELECT max(status_date) FROM daily_status").fetchone()[0]
        print(f"daily_status aggiornata fino al {latest}")
    scheduling.append_to_log(f"{report.summary()} · daily_status fino al {latest}")
    return 0


def _weather() -> int:
    """Che acqua e che vento c'era, il giorno delle nuotate in mare."""
    from . import rebuild as rebuilder
    from .ingest import weather

    with rebuilder.single_writer("meteo"), database.connect() as connection:
        print("Condizioni delle nuotate in mare (Open-Meteo)…")
        report = weather.pull(connection)
        print(f"  {report.fetched} scaricate su {report.candidates} candidate")
        if report.failed:
            print(f"  {report.failed} non hanno risposto: si riprova al "
                  "prossimo passaggio")
    return 0


def _update() -> int:
    """La catena intera: scarica, archivia ed elabora, senza passaggi a mano.

    È quello che l'aggiornamento automatico esegue tre volte al giorno, ed è la
    risposta a una richiesta precisa dell'atleta: *«quando ho nuovi allenamenti
    vengono archiviati, elaborati e registrate correttamente tutte le info,
    senza passaggi manuali»*.

    Prima esisteva solo `sync`, che porta i riepiloghi. Il dettaglio — lap,
    vasche, traccia — arrivava soltanto dagli ZIP dell'export, fermi al 4 luglio
    2026: **36 nuotate su 36 successive a quella data non avevano un solo lap**.
    Tutte le analisi costruite in queste settimane funzionavano sul passato e
    non sulla settimana scorsa.

    Ogni anello è saltabile senza far cadere quelli prima: se Garmin non
    risponde per il download, i riepiloghi sono comunque entrati, e il dettaglio
    si recupera al passaggio successivo.
    """
    import os
    from .ingest.personal_api import STORE, update as personal_update
    if os.environ.get("GARMIN_PERSONAL_API_KEY") or (STORE / "api-key").exists():
        report = personal_update()
        print(f"Garmin Personal API: {report['outcome']}")
        return 1 if report['outcome'] == 'failed' else 0
    from . import corrections, race_corrections, rebuild as rebuilder, scheduling
    from .ingest import (fit_download, garmin_login, garmin_read_only, sync,
                         swim_details, track, weather)

    passi: list[str] = []
    with rebuilder.single_writer("aggiornamento"), database.connect() as connection:
        report = sync.pull(connection)
        print(report.summary())
        if not report.succeeded:
            scheduling.append_to_log(report.summary())
            for error in report.errors:
                print(f"  {error}", file=sys.stderr)
            return 1
        passi.append(report.summary())

        corrections.apply(connection)
        race_corrections.apply(connection)
        daily_status.build(connection)

        # I file originali delle sedute che non hanno ancora un dettaglio. È
        # l'anello che mancava: senza, `details` e `track` girerebbero a vuoto
        # su tutto ciò che è successo dopo l'export.
        nuovi = 0
        try:
            # Passa dallo stesso muro di sola lettura del sync: il download
            # dei file non è una scorciatoia per parlare con Garmin senza
            # controllo, è un metodo in più nella stessa allow-list.
            client = garmin_read_only.wrap(garmin_login.connect_client(),
                                           capture=False)
            scarico = fit_download.pull(connection, client)
            nuovi = scarico.downloaded
            print(f"File attività: {scarico.downloaded} scaricati, "
                  f"{scarico.still_missing} ancora da prendere")
            passi.append(f"{scarico.downloaded} file scaricati")
        except Exception as errore:  # noqa: BLE001
            # Un download che non parte non deve far fallire un aggiornamento
            # in cui i riepiloghi sono già entrati.
            print(f"  file attività non scaricati: {errore}", file=sys.stderr)
            passi.append("file attività non scaricati")

        if nuovi:
            dettaglio = swim_details.load(connection)
            traccia = track.load(connection)
            print(f"Dettaglio: {dettaglio.laps:,} lap, "
                  f"{dettaglio.lengths:,} vasche")
            print(f"Traccia:   {traccia.points:,} punti")
            passi.append(f"{dettaglio.laps} lap, {traccia.points} punti")

        # Il meteo delle nuotate in mare nuove. Sta in fondo perché dipende
        # dalla posizione, che nasce con la traccia, e perché è l'unico anello
        # che parla con un servizio diverso da Garmin: se non risponde, tutto
        # il resto è già a posto.
        try:
            condizioni = weather.pull(connection)
            if condizioni.fetched:
                print(f"Meteo:     {condizioni.fetched} nuotate in mare")
                passi.append(f"{condizioni.fetched} condizioni meteo")
        except Exception as errore:  # noqa: BLE001
            print(f"  meteo non scaricato: {errore}", file=sys.stderr)

        latest = connection.execute(
            "SELECT max(status_date) FROM daily_status").fetchone()[0]
        print(f"daily_status aggiornata fino al {latest}")

    scheduling.append_to_log(" · ".join(passi) + f" · daily_status al {latest}")
    return 0


def _schedule(remove: bool = False) -> int:
    from . import scheduling

    try:
        if remove:
            if scheduling.remove():
                print("Aggiornamento automatico rimosso.")
            else:
                print("Non era programmato niente da rimuovere.")
            return 0
        hours = scheduling.install()
        print(f"Aggiornamento automatico programmato: {hours}.")
        print(f"Esito di ogni esecuzione in {scheduling.LOG}")
        print()
        print("Serve che il computer sia acceso all'ora prevista. Se è spento,")
        print("il prossimo passaggio utile recupera comunque i giorni saltati.")
        print()
        print("Per toglierlo:  garmin_coach schedule --remove")
        return 0
    except scheduling.SchedulerUnavailable as error:
        print(f"Windows non ha accettato la programmazione: {error}",
              file=sys.stderr)
        print("I dati restano aggiornabili a mano con:  garmin_coach sync",
              file=sys.stderr)
        return 1


def _details() -> int:
    from . import rebuild as rebuilder
    from .ingest import swim_details

    with rebuilder.single_writer("import del dettaglio FIT"), database.connect() as connection:
        print("Lettura dei file FIT (serie, vasche, stili)…")
        report = swim_details.load(connection)
        print(f"  {report.fit_files_scanned:,} file FIT letti, di cui "
              f"{report.fit_activities:,} attività")
        print(f"  {report.matched:,} sedute su {report.swims:,} hanno il loro FIT")
        print(f"  activity_laps  {report.laps:>7,} lap")
        print(f"  pool_lengths   {report.lengths:>7,} vasche")
        if report.without_detail:
            print(f"  {report.without_detail:,} sedute senza dettaglio "
                  "(normale per quelle successive all'export)")
            for verdetto, quante in sorted(report.verdicts.items()):
                if verdetto != "matched":
                    print(f"    {verdetto:<14} {quante:>7,}")
    return 0


def _track() -> int:
    """La traccia al secondo delle nuotate in mare e delle gare collegate."""
    from . import rebuild as rebuilder
    from .ingest import track

    with rebuilder.single_writer("import della traccia"), database.connect() as connection:
        print("Lettura dei punti registrati (mare e gare)…")
        report = track.load(connection)
        print(f"  {report.imported:,} registrazioni su {report.eligible:,} "
              "candidate")
        print(f"  activity_track {report.points:>8,} punti")
        print(f"  {report.passing_gate:,} reggono una lettura a tratti, "
              f"{report.failing_gate:,} no")
        if report.without_source:
            print(f"  {report.without_source:,} senza un file FIT agganciato "
                  "(normale per le sedute successive all'export)")
        if report.without_points:
            print(f"  {report.without_points:,} agganciate ma senza punti "
                  "registrati")
    return 0


def _app(port: int, open_browser: bool = True) -> int:
    """Apre l'applicazione locale. E il comando che sta dietro al doppio clic."""
    if not paths.DATABASE.exists():
        print("Il database non esiste ancora: si costruisce con 'all'.",
              file=sys.stderr)
        return 2
    from .app import serve
    try:
        serve(port=port, open_browser=open_browser)
    except KeyboardInterrupt:
        print("\nChiuso.")
    return 0


def _readable_console() -> None:
    """La console di Windows usa cp1252 e soffoca su una freccia.

    Scoperto quando il sync e riuscito ma non e riuscito a raccontarlo: i dati
    erano a posto e l'utente ha visto solo un errore di codifica. Peggio, lo
    scheduler ci sarebbe inciampato tre volte al giorno registrando un fallimento
    che non c'era.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                pass


def main(argv: list[str] | None = None) -> int:
    _readable_console()
    parser = argparse.ArgumentParser(prog="garmin_coach", description=__doc__)
    parser.add_argument("command",
                        choices=["ingest", "metrics", "verify", "fingerprint",
                                 "integrity", "status", "connect", "login",
                                 "sync", "update", "schedule", "details",
                                 "track", "weather", "snapshot",
                                 "backup", "dictionary", "rebuild", "digest",
                                 "slice", "app",
                                 "all", "reset"])
    parser.add_argument("--force", action="store_true",
                        help="ignora l'attesa dopo un tentativo fallito")
    parser.add_argument("--remove", action="store_true",
                        help="con 'schedule': toglie l'aggiornamento automatico")
    parser.add_argument("--port", type=int, default=None,
                        help="con 'app': la porta locale, se 8765 e occupata")
    parser.add_argument("--no-browser", action="store_true",
                        help="con 'app': non aprire il browser da solo")
    arguments = parser.parse_args(argv)

    if not paths.EXPORT.exists():
        print(f"Sorgente non trovata: {paths.EXPORT}", file=sys.stderr)
        return 2

    if arguments.command == "reset":
        database.reset()
        print("Database cancellato. È interamente ricostruibile con 'all'.")
        return 0
    if arguments.command == "ingest":
        return _ingest()
    if arguments.command == "metrics":
        return _metrics()
    if arguments.command == "verify":
        return _verify()
    if arguments.command == "fingerprint":
        return _fingerprint()
    if arguments.command == "integrity":
        return _integrity()
    if arguments.command == "status":
        return _status()
    if arguments.command == "connect":
        return _connect(force=arguments.force)
    if arguments.command == "login":
        return _login(force=arguments.force)
    if arguments.command == "sync":
        return _sync()
    if arguments.command == "update":
        return _update()
    if arguments.command == "schedule":
        return _schedule(remove=arguments.remove)
    if arguments.command == "details":
        return _details()
    if arguments.command == "track":
        return _track()
    if arguments.command == "weather":
        return _weather()
    if arguments.command == "snapshot":
        return _snapshot()
    if arguments.command == "backup":
        return _backup()
    if arguments.command == "dictionary":
        return _dictionary()
    if arguments.command == "rebuild":
        return _rebuild()
    if arguments.command == "digest":
        return _digest()
    if arguments.command == "slice":
        return _slice()
    if arguments.command == "app":
        from .app.server import PORT
        return _app(port=arguments.port or PORT,
                    open_browser=not arguments.no_browser)
    return _all()


def _all() -> int:
    """Importa, rigioca le catture, calcola e verifica.

    Il passo delle catture non c'era, e la sua assenza costava dati: l'export si
    ferma al 4 luglio, le settimane successive esistono solo in
    ``data/raw/garmin-connect/``, e ``all`` le ignorava. Ora ``all`` e
    ``rebuild`` fanno la stessa cosa sulle stesse sorgenti — la differenza è
    soltanto che ``rebuild`` parte da un database vuoto.

    Prende anche il lucchetto di scrittura: senza, l'aggiornamento automatico
    delle 14:30 può partire in mezzo e i due si contendono il file.
    """
    from . import rebuild as rebuilder

    try:
        with rebuilder.single_writer("import completo"):
            esito = _ingest() or _replay() or _metrics()
    except rebuilder.DatabaseBusy as error:
        print(str(error), file=sys.stderr)
        return 1
    return esito or _verify()


def _replay() -> int:
    """Rimette nel database le settimane che vivono solo nelle catture del sync."""
    from .ingest import snapshot_replay, sync

    replay = snapshot_replay.SnapshotClient()
    coverage = replay.coverage()
    if not coverage["days"]:
        print("Catture del sync: nessuna su disco, niente da rigiocare.")
        return 0

    print(f"Rigioco {coverage['days']} giorni catturati dal sync "
          f"({coverage['first']} → {coverage['last']})…")
    with database.connect() as connection:
        report = sync.pull(connection, client=replay)
    print(f"  {report.summary()}")
    if not report.succeeded:
        for error in report.errors:
            print(f"  {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
