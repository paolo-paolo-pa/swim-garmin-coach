"""Il riuso dell'istanza non può diventare una richiesta a Internet."""
from garmin_coach import launcher


def test_instance_probe_is_fixed_to_loopback_and_does_not_follow_redirect(monkeypatch):
    calls=[]
    class Connection:
        def __init__(self,*args,**kwargs):calls.append((args,kwargs))
        def request(self,*args):calls.append(args)
        def getresponse(self):return type('Response',(),{'status':302})()
        def close(self):calls.append('closed')
    monkeypatch.setattr(launcher,'HTTPConnection',Connection)
    assert launcher.existing_dashboard(8766) is False
    assert calls[0] == (('127.0.0.1',8766),{'timeout':2})
    assert calls[1] == ('GET','/api/platform/summary?days=7')
    assert calls[2] == 'closed'


def test_invalid_port_cannot_introduce_a_host_or_url():
    for port in ('example.com:80',True,-1,65536):
        assert launcher.existing_dashboard(port) is False
