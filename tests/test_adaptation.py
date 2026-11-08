"""«Come ho risposto a quel blocco?» — rilievo A4.3, e i due artefatti trovati.

## Il rilievo

`Progressi` misurava il **volume successivo** e lo chiamava risposta. Ma quanto
si nuota nelle settimane dopo lo decidono il programma dell'allenatore, il
lavoro e la vita: chiamarlo risposta fa sembrare una scelta un effetto.

## I due artefatti, trovati misurando e non ragionando

1. **Il passo medio della seduta non è una prestazione.** La prima versione
   confrontava proprio quello, e sull'archivio vero dava «peggiorata» su tutti e
   quattro i precedenti: troppo uniforme per essere una scoperta. Il passo medio
   contiene i riposi, la tecnica e le gambe, quindi misura *cosa conteneva la
   seduta*. Ora il confronto è fra ripetute della stessa lunghezza nella stessa
   vasca, e i verdetti smettono di essere tutti uguali.
2. **La tenuta si confronta in punti, non in rapporto.** Un decadimento che
   passa da −8,1% a −6,3% — cioè un finale meno veloce di prima — risultava
   «migliorato», perché dividendo per un numero negativo il segno si ribalta.

Entrambi hanno un test che li rifarebbe rossi.
"""

from datetime import date, datetime, timedelta

import duckdb
import pytest

from garmin_coach.analysis import adaptation
from garmin_coach.database import SCHEMA
from garmin_coach.metrics import daily_status

BLOCCO_INIZIO = date(2026, 3, 2)
BLOCCO_FINE = date(2026, 3, 29)


def _seduta(con, activity_id, giorno, *, vasca=25.0, ambiente="pool",
            distanza=2000.0, durata=3000.0):
    con.execute("""
        INSERT INTO activities (activity_id, start_time_utc, start_time_local,
            activity_date, sport, is_swim, environment, name, distance_m,
            duration_s, pool_length_m, device_id, source_object_id, imported_at)
        VALUES (?, ?, ?, ?, 'lap_swimming', TRUE, ?, 'Nuoto', ?, ?, ?, 7,
                'sha', ?)
    """, [activity_id, datetime.combine(giorno, datetime.min.time()),
          datetime.combine(giorno, datetime.min.time()), giorno, ambiente,
          distanza, durata, vasca, datetime(2026, 1, 1)])


def _lap(con, activity_id, indice, *, metri=100.0, passo=90.0, riposo=False):
    con.execute("""
        INSERT INTO activity_laps (activity_id, lap_index, start_time_utc,
            duration_s, distance_m, pace_per_100m_s, is_rest, source_object_id,
            imported_at, environment)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'sha', ?, 'pool')
    """, [activity_id, indice, datetime(2026, 3, 2), 90.0, metri, passo,
          riposo, datetime(2026, 1, 1)])


@pytest.fixture
def connection():
    con = duckdb.connect(":memory:")
    con.execute(SCHEMA)
    yield con
    con.close()


def _ripetute(con, primo_giorno, quante_sedute, passo, *, da=1000,
              metri=100.0, laps=10):
    """Sedute identiche tranne che nel passo: cambia solo la prestazione."""
    for numero in range(quante_sedute):
        activity_id = da + numero
        giorno = primo_giorno + timedelta(days=numero * 2)
        _seduta(con, activity_id, giorno)
        for indice in range(laps):
            _lap(con, activity_id, indice, metri=metri, passo=passo)


# ── 1. La prestazione si misura sulla stessa ripetuta ────────────────────

class TestPerformanceIsMeasuredOnComparableRepeats:
    def test_a_faster_repeat_after_the_block_reads_as_improved(self, connection):
        _ripetute(connection, BLOCCO_INIZIO, 5, passo=90.0)
        _ripetute(connection, BLOCCO_FINE + timedelta(days=2), 5, passo=84.0,
                  da=2000)

        asse = adaptation.performance(connection, BLOCCO_INIZIO, BLOCCO_FINE)

        assert asse.available
        assert asse.direction == "migliorata"
        assert "100 m in vasca da 25 m" in asse.display

    def test_a_session_full_of_rest_does_not_look_like_a_worse_athlete(
            self, connection):
        """L'artefatto che ha fatto riscrivere questo modulo.

        Le ripetute sono identiche prima e dopo: stesso passo, stessa
        lunghezza. Dopo il blocco le sedute contengono molto più riposo, quindi
        il **passo medio della seduta** crolla. Una prestazione misurata sulla
        seduta direbbe «peggiorata»; misurata sulla ripetuta dice la verità,
        cioè che non è cambiato niente.
        """
        _ripetute(connection, BLOCCO_INIZIO, 5, passo=90.0)
        for numero in range(5):
            activity_id = 3000 + numero
            giorno = BLOCCO_FINE + timedelta(days=2 + numero * 2)
            # Stessi metri, il doppio del tempo: tutta la differenza è riposo.
            _seduta(connection, activity_id, giorno, distanza=1000.0,
                    durata=6000.0)
            for indice in range(10):
                _lap(connection, activity_id, indice, metri=100.0, passo=90.0)
                _lap(connection, activity_id, indice + 100, metri=0.0,
                     passo=None, riposo=True)

        asse = adaptation.performance(connection, BLOCCO_INIZIO, BLOCCO_FINE)

        assert asse.direction == "stabile", (
            "il riposo dentro la seduta viene letto come un peggioramento: è "
            "l'artefatto del passo medio di seduta")

    def test_repeats_of_different_lengths_are_never_mixed(self, connection):
        """I 50 e i 200 non si mediano: non sono la stessa prova."""
        _ripetute(connection, BLOCCO_INIZIO, 5, passo=70.0, metri=50.0)
        _ripetute(connection, BLOCCO_FINE + timedelta(days=2), 5, passo=95.0,
                  da=2000, metri=200.0)

        asse = adaptation.performance(connection, BLOCCO_INIZIO, BLOCCO_FINE)

        assert not asse.available, (
            "ha confrontato ripetute di lunghezza diversa fra loro")

    def test_open_water_stays_out_and_says_why(self, connection):
        for numero in range(6):
            activity_id = 5000 + numero
            giorno = BLOCCO_INIZIO + timedelta(days=numero * 2)
            _seduta(connection, activity_id, giorno, ambiente="open_water",
                    vasca=None)

        asse = adaptation.performance(connection, BLOCCO_INIZIO, BLOCCO_FINE)

        assert not asse.available
        assert "acque libere" in asse.why_missing


# ── 2. La tenuta, e il segno che si ribaltava ────────────────────────────

class TestDurability:
    def _sedute_con_decadimento(self, con, primo_giorno, decadimento_pct,
                                quante=4, da=1000):
        for numero in range(quante):
            activity_id = da + numero
            _seduta(con, activity_id, primo_giorno + timedelta(days=numero * 2))
            for indice in range(12):
                # Primo terzo a 90, ultimo terzo a 90 * (1 + decadimento).
                if indice < 4:
                    passo = 90.0
                elif indice >= 8:
                    passo = 90.0 * (1 + decadimento_pct / 100)
                else:
                    passo = 90.0
                _lap(con, activity_id, indice, passo=passo)

    def test_a_final_third_that_holds_better_reads_as_improved(self, connection):
        self._sedute_con_decadimento(connection, BLOCCO_INIZIO, 8.0)
        self._sedute_con_decadimento(connection, BLOCCO_FINE + timedelta(days=2),
                                     1.0, da=2000)

        asse = adaptation.durability(connection, BLOCCO_INIZIO, BLOCCO_FINE)

        assert asse.available and asse.direction == "migliorata"

    def test_a_negative_decay_that_gets_less_negative_is_not_an_improvement(
            self, connection):
        """L'artefatto del segno.

        Da −8% a −6% significa che l'ultimo terzo va **meno** forte di prima.
        Dividendo per un valore di partenza negativo il rapporto si ribaltava e
        il verdetto usciva «migliorata».
        """
        self._sedute_con_decadimento(connection, BLOCCO_INIZIO, -8.0)
        self._sedute_con_decadimento(connection, BLOCCO_FINE + timedelta(days=2),
                                     -6.0, da=2000)

        asse = adaptation.durability(connection, BLOCCO_INIZIO, BLOCCO_FINE)

        assert asse.direction == "peggiorata", (
            "un finale meno veloce di prima è stato letto come un miglioramento")


# ── 3. La fisiologia non attraversa i confini dei dati ───────────────────

class TestPhysiologyRefusesToCrossTheDataBoundary:
    def test_before_2021_the_axis_is_absent_not_stable(self, connection):
        asse = adaptation.physiology(connection, date(2018, 3, 1),
                                     date(2018, 3, 28))

        assert not asse.available
        assert "non esiste" in asse.why_missing, (
            "un dato che non esiste è stato descritto come stabile")

    def test_with_enough_days_it_reads_the_resting_heart_rate(self, connection):
        for offset in range(56):
            giorno = BLOCCO_INIZIO + timedelta(days=offset)
            connection.execute(
                "INSERT INTO daily_health (health_date, resting_hr_bpm, "
                " source_object_id, imported_at) VALUES (?, ?, 'sha', ?)",
                [giorno, 58 if giorno <= BLOCCO_FINE else 52,
                 datetime(2026, 1, 1)])
        daily_status.build(connection)

        asse = adaptation.physiology(connection, BLOCCO_INIZIO, BLOCCO_FINE)

        assert asse.available
        assert asse.direction == "migliorata"
        assert "58" in asse.display and "52" in asse.display

    def test_opposite_resting_hr_and_hrv_are_declared_discordant(
            self, connection):
        for offset in range(56):
            giorno = BLOCCO_INIZIO + timedelta(days=offset)
            dentro = giorno <= BLOCCO_FINE
            connection.execute(
                "INSERT INTO daily_health (health_date, resting_hr_bpm, "
                " source_object_id, imported_at) VALUES (?, ?, 'sha', ?)",
                [giorno, 58 if dentro else 52, datetime(2026, 1, 1)])
            connection.execute(
                "INSERT INTO health_status (status_date, hrv_ms, source_object_id, "
                " imported_at) VALUES (?, ?, 'sha', ?)",
                [giorno, 50 if dentro else 40, datetime(2026, 1, 1)])
        daily_status.build(connection)

        asse = adaptation.physiology(connection, BLOCCO_INIZIO, BLOCCO_FINE)

        assert asse.direction == "discordante"
        assert any("peggiorata" in dettaglio for dettaglio in asse.details)


# ── 4. La frase finale dice anche cosa non sa ────────────────────────────

class TestTheSummaryAdmitsWhatIsMissing:
    def test_it_names_the_axes_it_could_not_measure(self):
        assi = [adaptation.Axis("prestazione", True, direction="migliorata"),
                adaptation.Axis("tenuta", False, why_missing="pochi lap"),
                adaptation.Axis("fisiologia", False, why_missing="niente FC")]

        frase = adaptation.summary(assi)

        assert "prestazione migliorata" in frase
        assert "Non misurabile: tenuta, fisiologia" in frase

    def test_with_nothing_measurable_it_says_so_instead_of_staying_silent(self):
        assi = [adaptation.Axis("prestazione", False),
                adaptation.Axis("tenuta", False),
                adaptation.Axis("fisiologia", False)]

        assert "non si può dire" in adaptation.summary(assi)


# ── Il quarto asse: il recupero intorno all'allenamento ──────────────────
#
# Sonno, stress e Body Battery rispondono a una domanda diversa dalla
# fisiologia: non come sta il sistema cardiovascolare, ma quanto recupero c'è
# stato **intorno** al lavoro. Dipende anche dalla vita, e per questo sta su un
# asse suo invece di confondersi con la frequenza a riposo.

class TestRecoveryAxis:
    def _tabella(self, connection):
        # `daily_status` la costruisce il passo `metrics`, non lo schema: nei
        # test va creata a mano, con le sole colonne che questo asse legge.
        connection.execute("""
            CREATE TABLE IF NOT EXISTS daily_status (
                status_date DATE PRIMARY KEY,
                resting_hr_bpm DOUBLE, hrv_ms DOUBLE,
                sleep_total_s DOUBLE, stress_avg DOUBLE,
                body_battery_min DOUBLE)
        """)

    def _giorni(self, connection, primo, ultimo, sonno_h, stress, batteria):
        from datetime import timedelta as _td
        self._tabella(connection)
        giorno = primo
        while giorno <= ultimo:
            connection.execute("""
                INSERT INTO daily_status (status_date, sleep_total_s,
                    stress_avg, body_battery_min)
                VALUES (?, ?, ?, ?)
            """, [giorno, sonno_h * 3600, stress, batteria])
            giorno += _td(days=1)

    def test_before_2019_the_axis_is_absent_not_stable(self, connection):
        asse = adaptation.recovery(connection, date(2018, 5, 1),
                                   date(2018, 6, 15))

        assert not asse.available
        assert "non esistono" in asse.why_missing, (
            "«stabile» su un dato che non esiste è peggio del silenzio: è "
            "indistinguibile da una misura")

    def test_worse_sleep_after_the_block_is_read_as_worse(self, connection):
        self._giorni(connection, date(2026, 5, 1), date(2026, 6, 15), 8.0, 25, 25)
        self._giorni(connection, date(2026, 6, 16), date(2026, 7, 13), 6.5, 25, 25)

        asse = adaptation.recovery(connection, date(2026, 5, 1),
                                   date(2026, 6, 15))

        assert asse.available
        assert asse.direction == "peggiorata"
        assert any("sonno" in una for una in asse.details)

    def test_the_sentence_agrees_with_its_subject(self, connection):
        self._giorni(connection, date(2026, 5, 1), date(2026, 6, 15), 8.0, 25, 25)
        self._giorni(connection, date(2026, 6, 16), date(2026, 7, 13), 6.5, 25, 25)

        asse = adaptation.recovery(connection, date(2026, 5, 1),
                                   date(2026, 6, 15))

        assert "Recupero peggiorato" in asse.display, (
            "«recupero peggiorata» è la frase che tradisce un'etichetta "
            "incollata a una parola invece di una frase scritta")

    def test_grandezze_that_move_apart_are_declared_discordant(self, connection):
        self._giorni(connection, date(2026, 5, 1), date(2026, 6, 15), 8.0, 20, 25)
        # Sonno giù, stress giù: uno peggiora e l'altro migliora.
        self._giorni(connection, date(2026, 6, 16), date(2026, 7, 13), 6.5, 14, 25)

        asse = adaptation.recovery(connection, date(2026, 5, 1),
                                   date(2026, 6, 15))

        assert asse.direction == "discordante", (
            "un'unica etichetta su tre grandezze che vanno in direzioni "
            "diverse nasconde quale si sia mossa")

    def test_a_missing_measure_is_named_not_hidden(self, connection):
        from datetime import timedelta as _td
        self._tabella(connection)
        giorno = date(2026, 5, 1)
        while giorno <= date(2026, 7, 13):
            connection.execute("""
                INSERT INTO daily_status (status_date, sleep_total_s)
                VALUES (?, ?)
            """, [giorno, 8 * 3600])
            giorno += _td(days=1)

        asse = adaptation.recovery(connection, date(2026, 5, 1),
                                   date(2026, 6, 15))

        assert asse.available, "il sonno da solo basta per un confronto"
        assert any("stress" in una and "troppo pochi" in una
                   for una in asse.details), (
            "le tre grandezze hanno coperture diverse: va detto quale manca")

    def test_the_axis_is_part_of_the_answer(self, connection):
        self._tabella(connection)
        assi = adaptation.how_the_body_answered(connection, date(2026, 5, 1),
                                                date(2026, 6, 15))

        assert [uno.name for uno in assi] == [
            "prestazione", "tenuta", "fisiologia", "recupero"]
