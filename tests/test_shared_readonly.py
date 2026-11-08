"""La condivisione non deve inoltrare operazioni di scrittura."""
import httpx
from starlette.testclient import TestClient
from garmin_coach.app import shared_readonly


def test_only_read_requests_reach_the_local_dashboard(monkeypatch):
    seen=[]
    original=httpx.AsyncClient

    def upstream(request):
        seen.append((request.method,str(request.url)))
        return httpx.Response(200,json={'available':True,'csrf':'private-token'})

    def fake_client(**kwargs):
        return original(transport=httpx.MockTransport(upstream),**kwargs)

    monkeypatch.setattr(shared_readonly.httpx,'AsyncClient',fake_client)
    with TestClient(shared_readonly.app) as client:
        response=client.get('/api/platform/summary?days=7')
        assert response.status_code==200 and response.json()=={'available':True,'csrf':''}
        assert response.headers['cache-control']=='no-store'
        for method in ('POST','PUT','PATCH','DELETE','OPTIONS'):
            response=client.request(method,'/api/platform/sync')
            assert response.status_code==405
            assert response.headers['allow']=='GET, HEAD'
    assert seen==[('GET','http://127.0.0.1:8766/api/platform/summary?days=7')]
