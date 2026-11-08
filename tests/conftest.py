"""Quello che serve a più file di test, scritto una volta sola.

Per ora una cosa sola: inviare una conferma come la invierebbe il browser.

Da quando l'anteprima vincola la scrittura, una conferma non è più «gli stessi
campi verso un'altra route»: è il gettone che l'anteprima ha emesso. Ricostruirlo
a mano in ogni file di test significherebbe scrivere quattro volte la conoscenza
di come è fatto quel modulo — e la quinta volta sbagliarla.

Questi aiutanti leggono la pagina di anteprima e ne rispediscono i campi
nascosti, esattamente come fa il browser. Se un giorno il modulo di conferma
tornasse a rimandare i valori dell'atleta invece del solo gettone, i test che li
usano se ne accorgerebbero da soli.
"""

from __future__ import annotations

import re

from garmin_coach.app import security

# I moduli dell'app li invia una pagina dell'app: senza questa intestazione il
# controllo antifalsificazione rifiuta, ed è giusto che rifiuti.
NOSTRA_ORIGINE = {"origin": "http://127.0.0.1:8765"}


def campi_nascosti(risposta) -> dict:
    """I campi nascosti di una pagina, come li leggerebbe il browser."""
    return {nome: valore for nome, valore in re.findall(
        r'<input\b[^>]*type="hidden"[^>]*name="([^"]+)"[^>]*value="([^"]*)"',
        risposta.text)}


def conferma(client, dove: str, anteprima, **sovrascrivi):
    """Invia la conferma di un'anteprima.

    ``sovrascrivi`` serve ai test che devono provare a manometterla: cambiare un
    campo qui deve **non** cambiare quello che viene scritto.
    """
    return client.post(dove, data={**campi_nascosti(anteprima), **sovrascrivi},
                       headers=NOSTRA_ORIGINE)


def scrivi_riferimento(client, campi: dict, gettone: str):
    """Il giro completo di una scrittura: anteprima, poi conferma."""
    anteprima = client.post("/gare/riferimenti",
                            data={**campi, security.FIELD: gettone},
                            headers=NOSTRA_ORIGINE)
    return conferma(client, "/gare/riferimenti/conferma", anteprima)


def scrivi_nota(client, campi: dict, gettone: str):
    anteprima = client.post("/sedute/nota", data={**campi, security.FIELD: gettone},
                            headers=NOSTRA_ORIGINE)
    return conferma(client, "/sedute/nota/conferma", anteprima)
