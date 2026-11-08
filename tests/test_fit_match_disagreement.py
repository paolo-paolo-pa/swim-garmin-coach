"""Agganciato non vuol dire concorde.

## Il caso, riprodotto

place03, 26/08/2023. Il riepilogo dice **6.000 m**, il file FIT ne conta
**7.446**: uno scarto del **24,1%**. Il verdetto registrato era `matched`,
perche' MAX_DISTANCE_MISMATCH valeva 0,25 - e 0,241 sta sotto 0,25.

## Perche' la soglia era sbagliata

Non era calibrata su niente. Misurato sui 1.302 agganci riusciti dell'archivio:
**1.294 concordano esattamente**, mediana dello scarto 0,0 m. Gli unici due
scarti non nulli sono questo, al 24,1%, e uno al -7,7%.

Una tolleranza del 25% su una popolazione che concorda al metro non tollera il
rumore: accetta l'unico caso che avrebbe dovuto far alzare la mano.

## Perche' non basta stringere la soglia

Con una soglia stretta, place03 diventerebbe `incompatible` e perderebbe i propri
lap. Ma i lap sono veri - il file descrive quella nuotata, il timestamp coincide
al secondo - ed e' la nuotata stessa a essere registrata due volte con due
distanze diverse. Buttare il dettaglio per punire il disaccordo toglierebbe
l'unica cosa che permette di capirlo.

Serve un verdetto in piu': **agganciato, e discorde**. I lap entrano, e chi
legge quella seduta sa che i due numeri non dicono la stessa cosa.
"""

import pytest

from garmin_coach.ingest import swim_details


class TestLaSogliaEQuellaCheIDatiMostrano:
    def test_the_tolerance_is_not_wide_enough_to_swallow_a_quarter(self):
        """Su 1.302 agganci, 1.294 concordano al metro. Il 25% non e' rumore."""
        assert swim_details.MAX_DISTANCE_MISMATCH < 0.20

    def test_the_place03_gap_is_no_longer_silently_accepted(self):
        """6.000 dichiarati contro 7.446 nel file: 24,1%."""
        verdetto = swim_details.agreement(distance=6000.0, distance_gap=1446.0,
                                          duration=5200.0, duration_gap=0.0)
        assert verdetto is not None
        assert "24%" in verdetto or "24 %" in verdetto


class TestUnDisaccordoNonButtaIlDettaglio:
    def test_a_disagreeing_match_is_its_own_verdict(self):
        """`incompatible` significa «il file descrive un'altra cosa».

        Qui il file descrive proprio questa nuotata - il timestamp coincide al
        secondo - e sono le due distanze a non coincidere. Sono due situazioni
        diverse e vanno chiamate diversamente.
        """
        assert "discordant" in swim_details.VERDICTS

    def test_a_disagreement_still_imports_its_laps(self):
        """I lap sono veri: buttarli per punire il disaccordo toglierebbe
        l'unica cosa che permette di capirlo."""
        assert swim_details.keeps_detail("discordant")
        assert swim_details.keeps_detail("matched")
        assert not swim_details.keeps_detail("incompatible")
        assert not swim_details.keeps_detail("ambiguous")

    def test_an_exact_match_stays_matched(self):
        """Il divieto e' mirato: 1.294 sedute su 1.302 concordano, e devono
        continuare a essere `matched` senza nessuna nota."""
        assert swim_details.agreement(distance=3000.0, distance_gap=0.0,
                                      duration=3600.0, duration_gap=0.0) is None
