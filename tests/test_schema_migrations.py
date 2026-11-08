"""Le migrazioni dello schema (D1).

Il cancello di D1 è: «database nuovo e database esistente arrivano allo stesso
schema». Non è una frase da credere, è una cosa da eseguire — ed è quello che
fa `test_a_fresh_database_and_a_migrated_one_match`.
"""

import duckdb
import pytest

from garmin_coach import data_dictionary, schema_migrations


@pytest.fixture
def fresh():
    con = duckdb.connect(":memory:")
    yield con
    con.close()


def _schema_of(connection) -> dict:
    """Tabelle e colonne, con i tipi. È l'unica definizione di «stesso schema»
    che non dipenda da come ci si è arrivati."""
    rows = connection.execute(
        "SELECT table_name, column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = 'main' ORDER BY 1, 2").fetchall()
    result = {}
    for table, column, kind in rows:
        result.setdefault(table, {})[column] = kind
    return result


def test_applying_twice_changes_nothing(fresh):
    first = schema_migrations.apply(fresh)
    second = schema_migrations.apply(fresh)

    assert first, "la prima esecuzione deve applicare qualcosa"
    assert second == [], "la seconda non deve applicare niente"


def test_a_fresh_database_and_a_migrated_one_match():
    """Il cancello D1.

    A sinistra un database costruito applicando le migrazioni una per volta,
    come succede a chi ce l'ha già. A destra uno costruito da zero in un colpo
    solo. Se i due schemi divergessero, il codice funzionerebbe su una macchina
    e non sull'altra — che è esattamente il difetto che D1 elimina.
    """
    stepwise = duckdb.connect(":memory:")
    schema_migrations.apply(stepwise)

    from_scratch = duckdb.connect(":memory:")
    from_scratch.execute(schema_migrations.combined_sql())

    assert _schema_of(stepwise) == _schema_of(from_scratch)
    stepwise.close()
    from_scratch.close()


def test_a_migration_that_changed_after_being_applied_is_refused(fresh, monkeypatch):
    """Una migrazione applicata è storia. Se il file cambia, il database reale
    e il file non descrivono più la stessa cosa e nessuno se ne accorge."""
    original = schema_migrations.discover()
    schema_migrations.apply(fresh)

    tampered = [schema_migrations.Migration(m.identifier, m.sql + "\n-- modificata")
                for m in original]
    monkeypatch.setattr(schema_migrations, "discover", lambda: tampered)

    with pytest.raises(schema_migrations.MigrationChanged, match="già stata applicata"):
        schema_migrations.apply(fresh)


def test_every_migration_is_recorded_with_its_own_hash(fresh):
    schema_migrations.apply(fresh)
    recorded = dict(fresh.execute(
        "SELECT migration_id, sha256 FROM schema_migrations").fetchall())

    for migration in schema_migrations.discover():
        assert recorded[migration.identifier] == migration.sha256
        assert len(migration.sha256) == 64, "uno SHA-256 vero, non un URI"


def test_migrations_are_ordered_by_name(fresh):
    names = [m.identifier for m in schema_migrations.discover()]
    assert names == sorted(names)
    assert names[0].startswith("0001")


def test_the_laps_table_no_longer_pretends_to_hold_sets(fresh):
    """Il rilievo semantico dell'audit: un lap non è una serie."""
    schema_migrations.apply(fresh)
    tables = set(_schema_of(fresh))

    assert "activity_laps" in tables
    assert "pool_lengths" in tables
    assert "swim_sets" not in tables, (
        "swim_sets tornerà quando esisterà il codice che ricostruisce le serie")
    assert "swim_lengths" not in tables


def test_no_column_called_sha_holds_something_that_is_not_a_sha(fresh):
    schema_migrations.apply(fresh)
    columns = [(table, column)
               for table, cols in _schema_of(fresh).items() for column in cols
               if column.endswith("_sha") or column == "sha256" or column.endswith("_sha256")]
    # Dopo la migrazione 0005 l'unica colonna che si chiama come un hash è
    # `source_objects.sha256`, che contiene davvero un SHA-256 (criterio C8b).
    # Tutto il resto è `source_object_id`: un riferimento alla sorgente, che può
    # essere uno SHA o un URI, e il cui nome non promette nessuna delle due.
    for table, column in columns:
        assert column == "sha256", (
            f"{table}.{column} si chiama come un hash: se può contenere anche un "
            "URI, va chiamato source_object_id (Regola Aurea n.5)")


def test_the_data_dictionary_describes_exactly_the_real_schema(fresh):
    """Il contratto dichiarato e lo schema reale devono coincidere: un
    dizionario che descrive una tabella inesistente, o che ne dimentica una,
    è peggio di nessun dizionario perché sembra affidabile."""
    schema_migrations.apply(fresh)
    undocumented, phantom = data_dictionary.missing_documentation(fresh)

    assert not undocumented, f"tabelle senza descrizione: {undocumented}"
    assert not phantom, f"descrizioni senza tabella: {phantom}"


def test_the_rendered_dictionary_mentions_every_table(fresh):
    schema_migrations.apply(fresh)
    text = data_dictionary.render(fresh)

    for table in data_dictionary.TABLES:
        assert f"`{table}`" in text
    assert "Una riga è:" in text
