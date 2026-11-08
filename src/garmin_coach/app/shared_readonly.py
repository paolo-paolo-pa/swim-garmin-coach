"""Proxy locale di sola lettura per la condivisione tramite link temporaneo.

Il tunnel viene collegato a questo processo, mai direttamente alla dashboard.
Le richieste non-GET/HEAD sono rifiutate prima di raggiungere l'applicazione.
"""
import json
import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

UPSTREAM = 'http://127.0.0.1:8766'


async def readonly(request: Request) -> Response:
    if request.method not in ('GET', 'HEAD'):
        # Consumare un corpo piccolo evita che Windows resetti la connessione
        # prima che il tunnel riceva il 405; nessun byte viene inoltrato.
        size=0
        async for chunk in request.stream():
            size+=len(chunk)
            if size>65536:
                break
        return Response('Condivisione in sola lettura',status_code=405,headers={'Allow':'GET, HEAD','Cache-Control':'no-store'})
    raw = request.scope.get('raw_path',b'/')
    query = request.scope.get('query_string',b'')
    target = httpx.URL(UPSTREAM).copy_with(raw_path=raw+(b'?'+query if query else b''))
    try:
        async with httpx.AsyncClient(trust_env=False,follow_redirects=False,timeout=30) as client:
            result=await client.request(request.method,target,headers={'Accept-Encoding':'identity'})
    except httpx.HTTPError:
        return Response('Dashboard locale non disponibile',status_code=503,headers={'Cache-Control':'no-store'})
    headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer'}
    for name in ('content-type','location'):
        if name in result.headers:headers[name]=result.headers[name]
    content=result.content
    if 'application/json' in result.headers.get('content-type',''):
        try:
            data=result.json()
            if isinstance(data,dict) and 'csrf' in data:
                data['csrf']=''
                content=json.dumps(data,ensure_ascii=False,allow_nan=False).encode('utf-8')
        except (ValueError,UnicodeError):
            pass
    return Response(content,status_code=result.status_code,headers=headers)


app=Starlette(routes=[Route('/{path:path}',readonly,methods=['GET','HEAD','POST','PUT','PATCH','DELETE','OPTIONS'])])
