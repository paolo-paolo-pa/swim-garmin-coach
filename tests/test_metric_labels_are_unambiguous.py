"""Una stessa etichetta non può rappresentare quattro grandezze.

## Cosa è stato trovato

«Nuoto 7 giorni» compariva su tre numeri diversi, e «Nuoto 28 giorni» su due:

| Dove | Valore osservato | Cosa era davvero |
|---|---|---|
| Oggi | 21,78 km | i metri degli ultimi sette giorni — **giusto** |
| Progressi | 15,04 km | media settimanale di un blocco di quattro settimane |
| Gare | 8,9 km | mediana storica delle settimane osservate |
| Gare | 36,28 km | volume in acque libere di **otto** settimane |

Non è un difetto di forma. La scheda «Perché?» mostrava per tutti la formula di
``swim_km_7d`` — «somma dei metri nuotati sugli ultimi 7 giorni» — cioè una
formula che non era quella usata. Chi apriva il dettaglio per controllare
riceveva una conferma falsa, che è peggio di nessun dettaglio.

E rende confrontabili agli occhi due numeri che non lo sono: 21,78 di Oggi e
8,9 di Gare portavano lo stesso nome, quindi sembravano dire che il volume è
crollato. Uno è una somma di sette giorni, l'altro una mediana di nove anni.

## Cosa impedisce che ricapiti

Ogni grandezza ha il proprio ``metric_id``. Un identificativo si prende in
prestito in un attimo e non si restituisce mai.
"""

import pytest

from garmin_coach.metrics.catalog import BY_COLUMN, CATALOG


class TestOgniNomeAppartieneAUnaCosaSola:
    def test_no_two_metrics_share_a_user_facing_label(self):
        """Due metriche con la stessa etichetta sono indistinguibili in pagina.

        L'atleta non vede il `metric_id`: vede l'etichetta. Se due grandezze la
        condividono, per lui sono la stessa cosa.
        """
        visti: dict[str, str] = {}
        collisioni = []
        for metrica in CATALOG:
            if metrica.label in visti:
                collisioni.append(
                    f"«{metrica.label}» è {visti[metrica.label]} e {metrica.column}")
            visti[metrica.label] = metrica.column
        assert not collisioni, collisioni

    @pytest.mark.parametrize("metric_id", [
        "swim_km_7d", "swim_km_28d", "swim_km_per_week_block",
        "swim_km_week_median", "open_water_km_8w",
    ])
    def test_every_volume_metric_declares_its_own_window(self, metric_id):
        """La formula deve dire su quale finestra si calcola.

        È l'unica cosa che distingue queste cinque, e senza di essa il
        «Perché?» non risponde alla domanda per cui esiste.
        """
        formula = BY_COLUMN[metric_id].formula.lower()
        finestre = ("7 giorni", "28 giorni", "quattro settimane",
                    "settimanali", "8 settimane", "settimane")
        assert any(f in formula for f in finestre), (
            f"«{metric_id}» non dice su che finestra si calcola: «{formula}»")


class TestLeQuattroSuperficiNonSiPrestanoIlNome:
    """Le tre grandezze che prendevano in prestito `swim_km_7d`/`swim_km_28d`.

    Il test guarda il sorgente e non la pagina di proposito: il difetto sta nel
    gesto di riusare un identificativo, e va fermato lì — dopo, in pagina,
    sembra soltanto un numero un po' basso.
    """

    PRESTITI_VIETATI = {
        "analysis/progress.py": ["swim_km_7d"],
        "analysis/races.py": ["swim_km_7d", "swim_km_28d"],
    }

    @pytest.mark.parametrize("modulo", sorted(PRESTITI_VIETATI))
    def test_the_module_does_not_borrow_a_window_it_does_not_use(self, modulo):
        import pathlib

        import garmin_coach

        percorso = pathlib.Path(garmin_coach.__file__).parent / modulo
        testo = percorso.read_text(encoding="utf-8")
        for prestito in self.PRESTITI_VIETATI[modulo]:
            assert f'evidence("{prestito}"' not in testo, (
                f"{modulo} etichetta un proprio numero come «{prestito}», che "
                "è la finestra di un'altra grandezza")

    def test_today_still_uses_the_seven_day_window_because_it_really_is_one(self):
        """Il divieto è mirato: Oggi usa `swim_km_7d` e ha ragione.

        Un test che vietasse l'identificativo ovunque avrebbe tolto anche
        l'unico uso corretto, ed è il modo in cui una correzione diventa un
        danno.
        """
        import pathlib

        import garmin_coach

        percorso = (pathlib.Path(garmin_coach.__file__).parent
                    / "analysis" / "today.py")
        assert 'evidence("swim_km_7d"' in percorso.read_text(encoding="utf-8")
