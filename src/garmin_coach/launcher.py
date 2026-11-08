"""Riconosce soltanto un'istanza della dashboard sul loopback locale."""
import json
from http.client import HTTPConnection


def existing_dashboard(port):
    if type(port) is not int or not 1<=port<=65535:
        return False
    # HTTPConnection non usa proxy e non segue redirect: nessuna destinazione
    # esterna può essere introdotta dalla risposta di un altro server locale.
    connection=HTTPConnection('127.0.0.1',port,timeout=2)
    try:
        connection.request('GET','/api/platform/summary?days=7')
        response=connection.getresponse()
        if response.status!=200:
            return False
        current=json.loads(response.read(512000))
        return isinstance(current,dict) and 'inventory' in current
    except Exception:
        return False
    finally:
        connection.close()
