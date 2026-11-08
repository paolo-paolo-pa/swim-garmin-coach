"""Lettura dei markdown dell'atleta: gare, campi mancanti, diario.

Le intenzioni dell'atleta vivono in markdown (Regola Aurea n.3). Se il parser
sbaglia, il coach pianifica verso una gara che non esiste — o ne ignora una vera.
"""

from datetime import date

import pytest

from garmin_coach import athlete_files, paths


@pytest.fixture
def coach_dir(tmp_path, monkeypatch):
    folder = tmp_path / "coach"
    folder.mkdir()
    monkeypatch.setattr(paths, "COACH", folder)
    monkeypatch.setattr(paths, "ROOT", tmp_path)
    return folder


def write_races(folder, body: str) -> None:
    (folder / "gare.md").write_text(
        "# Gare\n\n"
        "| Data | Nome | Distanza | Ambiente | Vasca | Priorità | Obiettivo | Note |\n"
        "|---|---|---|---|---|---|---|---|\n" + body,
        encoding="utf-8")


def test_example_row_is_not_a_real_race(coach_dir):
    write_races(coach_dir,
                "| *(esempio)* 2026-10-12 | Traversata X | 5 km | acque libere | — | A | sotto 1h20 | mare |\n")
    assert athlete_files.races() == []


def test_real_race_is_parsed(coach_dir):
    write_races(coach_dir,
                "| 2026-10-12 | Traversata del Golfo | 5 km | acque libere | — | A | sotto 1h20 | muta ammessa |\n")
    races = athlete_files.races()
    assert len(races) == 1
    race = races[0]
    assert race.race_date == date(2026, 10, 12)
    assert race.name == "Traversata del Golfo"
    assert race.priority == "A"
    assert "traversata" in race.race_id


def test_races_are_sorted_by_date(coach_dir):
    write_races(coach_dir,
                "| 2026-12-01 | Seconda | 1500 m | piscina | 50 | B |  |  |\n"
                "| 2026-09-01 | Prima | 3 km | acque libere | — | A |  |  |\n")
    assert [race.name for race in athlete_files.races()] == ["Prima", "Seconda"]


def test_race_without_priority_defaults_to_c(coach_dir):
    # gare.md dichiara questa regola: una gara senza obiettivo vale C
    write_races(coach_dir, "| 2026-11-01 | Test | 1 km | piscina | 25 |  |  |  |\n")
    assert athlete_files.races()[0].priority == "C"


def test_row_without_a_valid_date_is_ignored(coach_dir):
    write_races(coach_dir, "| prossimamente | Ignota | 5 km | mare | — | A |  |  |\n")
    assert athlete_files.races() == []


def test_missing_fields_use_the_table_label(coach_dir):
    (coach_dir / "atleta.md").write_text(
        "# Profilo\n\n"
        "> Nota di servizio: i campi DA COMPILARE non bloccano le prime fasi.\n\n"
        "## Contesto\n\n"
        "| Campo | Valore |\n|---|---|\n"
        "| Vasca abituale | `DA COMPILARE` — 25 m / 50 m |\n"
        "| Dispositivo | Fenix 8 |\n\n"
        "## Attrezzatura\n\n"
        "`DA COMPILARE` — palette, pull buoy, pinne.\n",
        encoding="utf-8")
    (coach_dir / "obiettivi.md").write_text("# Obiettivi\n", encoding="utf-8")

    missing = athlete_files.profile()["missing_from_profile"]
    assert "Vasca abituale" in missing
    assert "Attrezzatura" in missing
    # la riga di commento spiega il file, non è un campo da compilare
    assert not any("Nota di servizio" in item for item in missing)
    assert not any(item.startswith(">") for item in missing)


def test_diary_entry_creates_the_week_file(coach_dir):
    written = athlete_files.append_to_diary("Sensazioni buone, RPE 6.",
                                            date(2026, 8, 12))
    assert written.startswith("coach/diario/2026-W33")

    content = (coach_dir / "diario" / "2026-W33.md").read_text(encoding="utf-8")
    assert "Sensazioni buone, RPE 6." in content
    assert "2026-W33" in content


def test_diary_appends_without_overwriting(coach_dir):
    athlete_files.append_to_diary("Prima voce.", date(2026, 8, 12))
    athlete_files.append_to_diary("Seconda voce.", date(2026, 8, 13))
    content = (coach_dir / "diario" / "2026-W33.md").read_text(encoding="utf-8")
    assert "Prima voce." in content and "Seconda voce." in content


def test_diary_writes_only_inside_coach(coach_dir):
    written = athlete_files.append_to_diary("Voce.", date(2026, 8, 12))
    assert written.startswith("coach/")
    assert ".." not in written
