"""I lap e le vasche ricostruiti dai file FIT (D4 e D5).

I FIT veri sono in ``garmin-export/``, che è sola lettura e non si tocca nei
test. Qui si verifica la logica che li interpreta, su messaggi costruiti a mano
nella stessa forma che l'orologio produce davvero — misurata su un Fenix 8.
"""

from datetime import datetime, timedelta, timezone

import pytest

from garmin_coach.ingest import swim_details


class FakeFrame:
    """Un messaggio FIT come lo restituisce fitdecode."""

    frame_type = 4  # FIT_FRAME_DATA

    def __init__(self, name, values):
        self.name = name
        self.fields = [type("F", (), {"name": k, "value": v})()
                       for k, v in values.items()]


def _reader(frames):
    class Reader:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return frames

        def __exit__(self, *_):
            return False

    return Reader


START = datetime(2026, 5, 4, 17, 30, tzinfo=timezone.utc)


def _four_by_hundred():
    """4×100 stile libero in vasca da 25, con recupero fra una e l'altra.

    Ogni 100 è un lap di 4 vasche; fra un 100 e l'altro un lap di recupero
    senza vasche attive.
    """
    frames = []
    length_index = 0
    for repetition in range(4):
        first = length_index
        for _ in range(4):
            frames.append(FakeFrame("length", {
                "message_index": length_index,
                "start_time": START + timedelta(seconds=length_index * 22),
                "total_timer_time": 21.5,
                "total_strokes": 9,
                "avg_speed": 1.16,
                "avg_swimming_cadence": 25,
                "swim_stroke": "freestyle",
                "length_type": "active",
            }))
            length_index += 1
        frames.append(FakeFrame("lap", {
            "message_index": repetition * 2,
            "start_time": START + timedelta(seconds=first * 22),
            "total_timer_time": 86.0, "total_distance": 100.0,
            "total_strokes": 36, "num_lengths": 4, "num_active_lengths": 4,
            "first_length_index": first, "avg_heart_rate": 150,
            "max_heart_rate": 162, "avg_cadence": 25,
            "swim_stroke": "freestyle", "lap_trigger": "manual",
        }))
        frames.append(FakeFrame("lap", {
            "message_index": repetition * 2 + 1,
            "start_time": START + timedelta(seconds=first * 22 + 86),
            "total_timer_time": 24.0, "total_distance": 0.0,
            "num_lengths": 0, "num_active_lengths": 0,
            "first_length_index": length_index, "lap_trigger": "manual",
        }))
    frames.append(FakeFrame("session", {
        "total_distance": 400.0, "total_timer_time": 440.0}))
    return frames


def _open_water():
    """Una nuotata in mare: lap premuti a mano, nessuna vasca, distanze varie."""
    return [
        FakeFrame("lap", {
            "message_index": 0, "start_time": START,
            "total_timer_time": 1012.4, "total_distance": 1000.0,
            "avg_heart_rate": 138, "lap_trigger": "manual",
            "swim_stroke": "freestyle",
        }),
        FakeFrame("lap", {
            "message_index": 1, "start_time": START + timedelta(seconds=1013),
            "total_timer_time": 279.9, "total_distance": 234.2,
            "avg_heart_rate": 141, "lap_trigger": "manual",
            "swim_stroke": "freestyle",
        }),
        FakeFrame("session", {
            "total_distance": 1234.2, "total_timer_time": 1292.3}),
    ]


def _parse(monkeypatch, frames, environment="pool", activity_id=42):
    import fitdecode
    monkeypatch.setattr(fitdecode, "FitReader", _reader(frames))
    return swim_details._parse(b"", activity_id, environment, "sorgente-1",
                               datetime(2026, 5, 5))


def LAP(name: str) -> int:
    return swim_details.LAP_COLUMNS.index(name)


def LENGTH(name: str) -> int:
    return swim_details.LENGTH_COLUMNS.index(name)


# ── Piscina ────────────────────────────────────────────────────────────────

def test_laps_are_separated_from_rest(monkeypatch):
    laps, lengths, _ = _parse(monkeypatch, _four_by_hundred())

    assert len(laps) == 8, "quattro nuotate e quattro recuperi"
    swum = [lap for lap in laps if not lap[LAP("is_rest")]]
    assert len(swum) == 4
    assert all(lap[LAP("distance_m")] == 100.0 for lap in swum)
    assert len(lengths) == 16


def test_rest_keeps_no_stroke(monkeypatch):
    """Il recupero non ha stile. Attribuirgliene uno gonfierebbe i totali per
    stile con metri mai nuotati."""
    laps, _, _ = _parse(monkeypatch, _four_by_hundred())
    for lap in laps:
        if lap[LAP("is_rest")]:
            assert lap[LAP("stroke")] is None


def test_pace_is_computed_per_hundred(monkeypatch):
    laps, _, _ = _parse(monkeypatch, _four_by_hundred())
    swum = [lap for lap in laps if not lap[LAP("is_rest")]][0]
    assert swum[LAP("pace_per_100m_s")] == pytest.approx(86.0)


def test_swolf_is_the_mean_of_the_lengths(monkeypatch):
    """Non si ricalcola sui totali del lap: 21,5 s + 9 bracciate = 30,5 per
    vasca. Sommare i 4 × 100 e dividere darebbe un numero diverso e falso."""
    laps, _, _ = _parse(monkeypatch, _four_by_hundred())
    swum = [lap for lap in laps if not lap[LAP("is_rest")]][0]
    assert swum[LAP("swolf")] == pytest.approx(30.5)


def test_each_length_knows_its_lap(monkeypatch):
    _, lengths, _ = _parse(monkeypatch, _four_by_hundred())
    assert [row[LENGTH("lap_index")] for row in lengths[:4]] == [0, 0, 0, 0]
    # le successive al terzo lap: quello in mezzo è il recupero
    assert [row[LENGTH("lap_index")] for row in lengths[4:8]] == [2, 2, 2, 2]


def test_every_row_carries_its_source(monkeypatch):
    """Le vasche erano le uniche righe granulari senza provenienza: non si
    poteva risalire dal dato al file che lo conteneva."""
    laps, lengths, _ = _parse(monkeypatch, _four_by_hundred())
    assert all(lap[LAP("source_object_id")] == "sorgente-1" for lap in laps)
    assert all(row[LENGTH("source_object_id")] == "sorgente-1" for row in lengths)
    assert all(row[LENGTH("imported_at")] is not None for row in lengths)


def test_a_length_without_index_is_ignored(monkeypatch):
    """Un messaggio incompleto non deve far saltare l'intera seduta."""
    frames = _four_by_hundred()
    frames.insert(0, FakeFrame("length", {"total_timer_time": 20.0}))
    laps, lengths, _ = _parse(monkeypatch, frames)
    assert len(laps) == 8
    assert len(lengths) == 16


# ── Acque libere ───────────────────────────────────────────────────────────

def test_open_water_has_laps_but_never_lengths(monkeypatch):
    """In mare le vasche non esistono. Cercarle sarebbe cercare un'assenza, e
    registrarne la mancanza la trasformerebbe in un difetto."""
    laps, lengths, _ = _parse(monkeypatch, _open_water(), environment="open_water")

    assert len(laps) == 2
    assert lengths == []
    assert all(lap[LAP("environment")] == "open_water" for lap in laps)


def test_an_open_water_lap_without_lengths_is_not_a_rest(monkeypatch):
    """In vasca un lap senza vasche attive è un recupero. In mare quel criterio
    non vale: nessun lap ha vasche, e applicarlo trasformerebbe una nuotata di
    un chilometro in una pausa."""
    laps, _, _ = _parse(monkeypatch, _open_water(), environment="open_water")

    assert not any(lap[LAP("is_rest")] for lap in laps)
    assert laps[0][LAP("distance_m")] == 1000.0


def test_a_length_message_in_open_water_is_ignored(monkeypatch):
    """Se un FIT di mare contenesse per errore dei 'length', non vanno scritti
    in pool_lengths: il nome della tabella promette la piscina."""
    frames = _open_water() + [FakeFrame("length", {
        "message_index": 0, "total_timer_time": 20.0, "length_type": "active"})]
    _, lengths, _ = _parse(monkeypatch, frames, environment="open_water")
    assert lengths == []


# ── Riconciliazione ────────────────────────────────────────────────────────

def _headers(*times):
    return [swim_details.FitHeader(t, "archivio.zip", f"{n}.fit")
            for n, t in enumerate(times)]


def test_a_single_candidate_is_returned():
    headers = _headers(datetime(2026, 5, 4, 17, 29, 58),
                       datetime(2026, 5, 4, 18, 30, 0))
    found = swim_details.candidates_for(
        datetime(2026, 5, 4, 17, 30, 0), headers, [h.created for h in headers])

    assert len(found) == 1
    assert found[0].member == "0.fit"


def test_all_candidates_are_returned_not_just_the_nearest():
    """Restituire solo il migliore nasconderebbe l'unica cosa che conta quando
    la scelta non è ovvia: che c'era una scelta."""
    headers = _headers(datetime(2026, 5, 4, 17, 29, 40),
                       datetime(2026, 5, 4, 17, 30, 5))
    found = swim_details.candidates_for(
        datetime(2026, 5, 4, 17, 30, 0), headers, [h.created for h in headers])

    assert len(found) == 2


def test_nothing_is_returned_beyond_the_tolerance():
    headers = _headers(datetime(2026, 5, 4, 12, 0, 0))
    found = swim_details.candidates_for(
        datetime(2026, 5, 4, 17, 30, 0), headers, [h.created for h in headers])
    assert found == []


def test_a_small_distance_gap_is_a_quality_problem_not_a_wrong_file():
    """Su quattro sedute reali l'orologio conta nel totale qualche vasca che poi
    non assegna a nessun lap. È un difetto del dato, non il file sbagliato.

    200 m su 2.600 sono otto vasche da 25: è il caso vero dell'08/05/2026, ed è
    il secondo scarto più grande di tutto l'archivio. Resta sotto la tolleranza
    del 10% di proposito — sopra c'è soltanto place03, al 24,1%.
    """
    assert swim_details.agreement(2600.0, -200.0, 3600.0, 0.0) is None


def test_a_large_distance_gap_is_declared_instead_of_swallowed():
    reason = swim_details.agreement(2600.0, -2000.0, 3600.0, 0.0)
    assert reason is not None and "distanza" in reason


def test_a_large_duration_gap_is_caught_too():
    reason = swim_details.agreement(2600.0, 0.0, 3600.0, 3000.0)
    assert reason is not None and "durata" in reason


# ── Aggancio per identità ──────────────────────────────────────────────────

def test_a_downloaded_file_is_matched_by_its_name(tmp_path, monkeypatch):
    """Il nome di un file scaricato è l'identità dell'attività, non un indizio.

    Il caso vero: quattro nuotate del 2018 e del 2023 restavano senza dettaglio
    perché l'export contiene due file plausibili entro la tolleranza. Il file
    scaricato porta il numero dell'attività addosso e scioglie la scelta.
    """
    (tmp_path / "10000000006.fit").write_bytes(b"...")
    monkeypatch.setattr(swim_details.source_catalog, "RAW_FIT", tmp_path)

    per_nome = swim_details._downloaded_by_activity()

    assert list(per_nome) == [10000000006]
    assert per_nome[10000000006].member == "10000000006.fit"
    assert per_nome[10000000006].archive == swim_details.DOWNLOADED


def test_two_files_for_the_same_activity_do_not_claim_an_identity(tmp_path,
                                                                  monkeypatch):
    """Quando il contenuto cambia il nome prende in coda l'impronta: allora il
    numero non basta più a scegliere e la decisione torna all'orario."""
    (tmp_path / "10000000006.fit").write_bytes(b"...")
    (tmp_path / "10000000006-a1b2c3d4.fit").write_bytes(b"altro")
    monkeypatch.setattr(swim_details.source_catalog, "RAW_FIT", tmp_path)

    assert swim_details._downloaded_by_activity() == {}


def test_a_swim_with_a_disagreeing_total_still_has_its_detail():
    """``discordant`` porta dentro lap e vasche: contarla fra le sedute senza
    dettaglio dichiarava mancante un dettaglio che sta nel database."""
    report = swim_details.DetailReport(
        fit_files_scanned=0, fit_activities=0, census={}, swims=3,
        verdicts={"matched": 1, "discordant": 1, "ambiguous": 1},
        laps=0, lengths=0, sources_registered=0)

    assert report.without_detail == 1
