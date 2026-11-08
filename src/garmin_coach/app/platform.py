"""API interna Nuxt: un archivio e un solo strato analitico."""
import asyncio
import json
import threading
from datetime import date

import duckdb
from starlette.responses import JSONResponse, FileResponse
from starlette.routing import Route, Mount
from starlette.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .. import paths, coach, athlete_files
from ..analysis import dashboard, workout_builder
from . import security, confirmation

SYNC_LOCK = threading.Lock()
MEMORY_LOCK = threading.Lock()
SYNC_STATE = {"running": False}


def response(data, status=200):
    return JSONResponse(json.loads(json.dumps(data, default=str, ensure_ascii=False, allow_nan=False)), status_code=status)


def read():
    return duckdb.connect(str(paths.DATABASE), read_only=True)


def period(request):
    from ..analysis.periods import parse
    return parse(request.query_params)


async def monitoring(request):
    from ..analysis import monitoring_history
    try:
        with read() as connection:
            data=monitoring_history.build(connection,request.query_params)
            start,end=data['start'],data['end']
            data["activities"]=dashboard.rows(connection,"SELECT activity_id,activity_date,name,distance_m,duration_s,environment,garmin_training_load FROM canonical_activities WHERE activity_date BETWEEN ? AND ? ORDER BY activity_date DESC",[start,end])
        data["wellness"]=[r for r in athlete_files.current_structured_entries("wellness","date") if start.isoformat()<=r["date"]<=end.isoformat()]
        data["csrf"]=security.TOKEN
        return response(data)
    except (ValueError,TypeError):
        return response({"error":"Periodo non valido"},400)
    except duckdb.Error:
        return response({"error":"Archivio temporaneamente occupato"},503)


async def intraday(request):
    from ..analysis import intraday as service
    from ..ingest.health_samples import pull
    try:
        if request.method=="POST":
            data=await checked_json(request)
            day=date.fromisoformat(str(data["date"]))
            await asyncio.to_thread(pull,day)
        else:
            day=date.fromisoformat(request.query_params.get("date") or date.today().isoformat())
        with read() as connection:
            result=service.report(connection,day)
        return response(result)
    except security.Rejected as error:
        return response({"error":str(error)},403)
    except (ValueError,TypeError,KeyError):
        return response({"error":"Giorno non valido"},400)
    except Exception as error:
        return response({"error":"Profilo giornaliero non disponibile: "+type(error).__name__},503)


async def training(request):
    from ..analysis import training_workspace
    try:
        if request.method=="GET":
            from ..analysis import calendar_view
            start,end=period(request)
            with read() as connection:
                data=calendar_view.build(connection,start,end)
            return response(dict(data,csrf=security.TOKEN))
        data=await checked_json(request)
        if data.get("confirm"):
            pending=confirmation.redeem("training-blocks",str(data.get("preview_token", "")))
            saved=athlete_files.add_structured_entry("training-blocks",pending.payload)
            confirmation.remember(str(data["preview_token"]),saved)
            return response({"saved":saved})
        with read() as connection:
            proposal=training_workspace.propose(connection,data)
        proposal["title"]="Blocco di allenamento proposto"
        return response({"preview":proposal,"preview_token":confirmation.issue("training-blocks",proposal)})
    except (security.Rejected,confirmation.Rejected) as error:
        return response({"error":str(error)},403)
    except confirmation.AlreadyConfirmed as done:
        return response({"saved":done.outcome})
    except (ValueError,TypeError,KeyError) as error:
        return response({"error":str(error)},400)
    except duckdb.Error:
        return response({"error":"Archivio temporaneamente occupato"},503)


async def memory(request):
    from ..analysis.training_workspace import validate_entry
    try:
        data=await checked_json(request)
        kind=data.get("kind")
        if kind not in ("wellness","training-settings","plan-links","plan-revisions","session-annotations"):
            raise ValueError("Tipo non consentito")
        if data.get("confirm"):
            with MEMORY_LOCK:
                pending=confirmation.redeem(kind,str(data.get("preview_token", "")))
                # Il contenuto resta quello approvato; l'integrità del legame
                # va verificata di nuovo se altre conferme sono avvenute intanto.
                with read() as connection:
                    validate_entry(kind,pending.payload,connection)
                saved=athlete_files.add_structured_entry(kind,pending.payload)
                confirmation.remember(str(data["preview_token"]),saved)
            return response({"saved":saved})
        with read() as connection:
            validated=validate_entry(kind,data,connection)
        return response({"preview":validated,"preview_token":confirmation.issue(kind,validated)})
    except (security.Rejected,confirmation.Rejected) as error:
        return response({"error":str(error)},403)
    except confirmation.AlreadyConfirmed as done:
        return response({"saved":done.outcome})
    except (ValueError,TypeError,KeyError) as error:
        return response({"error":str(error)},400)
    except duckdb.Error:
        return response({"error":"Archivio temporaneamente occupato"},503)


async def compare_swims(request):
    from ..analysis import swim_comparison
    try:
        start,end=period(request)
        with read() as connection:
            data=swim_comparison.compare(connection,start,end,
                request.query_params.get("stroke","freestyle"),int(request.query_params.get("distance",100)),
                int(request.query_params.get("pool",25)),request.query_params.get("device"))
        return response(data)
    except (ValueError,TypeError):
        return response({"error":"Filtri di confronto non validi"},400)
    except duckdb.Error:
        return response({"error":"Archivio temporaneamente occupato"},503)


async def summary(request):
    try:
        days = int(request.query_params.get("days", 28))
        if days not in (0, 7, 28, 42, 90, 365, 730, 1825):
            return response({"error": "Periodo non valido"}, 400)
        env = request.query_params.get("environment") or None
        if env not in (None, "pool", "open_water"):
            return response({"error": "Ambiente non valido"}, 400)
        end = date.fromisoformat(request.query_params["end"]) if request.query_params.get("end") else None
        with read() as connection:
            since=date.fromisoformat(request.query_params['start']) if request.query_params.get('start') else None
            result = dashboard.overview(connection, days, env, end,since,request.query_params.get('resolution','auto'))
        result.update({"csrf": security.TOKEN, "plans": athlete_files.structured_entries("workouts"),
                       "css_tests": athlete_files.structured_entries("css-tests")})
        return response(result)
    except (ValueError, KeyError):
        return response({"error": "Filtri non validi"}, 400)
    except duckdb.Error:
        return response({"error": "Database temporaneamente occupato. Riprova tra poco."}, 503)


async def detail(request):
    try:
        with read() as connection:
            result = dashboard.activity(connection, request.path_params["activity_id"])
        return response(result or {"error": "Attività non trovata"}, 200 if result else 404)
    except duckdb.Error:
        return response({"error": "Dettaglio temporaneamente non disponibile"}, 503)


async def checked_json(request):
    if int(request.headers.get("content-length", "0")) > 64000:
        raise ValueError("Richiesta troppo grande")
    data = await request.json()
    security.check(request, {security.FIELD: request.headers.get("x-csrf-token", "")})
    return data


async def coach_reply(request):
    try:
        if request.method=="GET":
            from ..analysis import coaching_context
            from ..coach.codex_cli import executable
            question=str(request.query_params.get("question","Come sto oggi?"))[:2000]
            with read() as connection:
                packet,sources=coaching_context.build(connection,question)
            return response({"context":packet.as_dict(),"sources":sources,"csrf":security.TOKEN,
                             "openai_available":executable() is not None})
        data = await checked_json(request)
        question = str(data.get("question", "Come sto oggi?"))[:2000]
        from ..analysis import coaching_context
        with read() as connection:
            packet,sources = coaching_context.build(connection, question)
        provider=data.get("provider","local")
        if provider=="openai":
            from ..coach.codex_cli import CodexBrain
            brain=CodexBrain()
        elif provider=="local":
            brain=coach.LocalBrain()
        else:
            return response({"error":"Provider non configurato. Scegli OpenAI o lettura locale."},400)
        result = await asyncio.to_thread(brain.judge, packet)
        value={"context":packet.as_dict(),"answer":result.as_dict(),"sources":sources}
        if provider=="openai":
            from ..coach.reply_history import save
            save(value)
        return response(value)
    except security.Rejected as error:
        return response({"error": str(error)}, 403)
    except coach.BrainUnavailable as error:
        return response({"error":str(error)},503)
    except Exception as error:
        return response({"error": "Coach non disponibile: " + type(error).__name__,
                         "action": "Usa la lettura locale oppure verifica accesso Codex e connessione."}, 503)


async def builder(request):
    if request.method == "GET":
        return response({"library": workout_builder.library(),
                         "plans": athlete_files.structured_entries("workouts"),
                         "css_tests": athlete_files.structured_entries("css-tests")})
    try:
        data = await checked_json(request)
        kind = data.get("kind", "workouts")
        if kind not in ("workouts", "css-tests"):
            raise ValueError("Tipo non valido")
        if data.get("confirm"):
            pending = confirmation.redeem("platform-" + kind, str(data.get("preview_token", "")))
            saved = athlete_files.add_structured_entry(kind, pending.payload)
            confirmation.remember(str(data["preview_token"]), saved)
            return response({"saved": saved})
        value = workout_builder.workout(data) if kind == "workouts" else workout_builder.css_test(data)
        token = confirmation.issue("platform-" + kind, value)
        return response({"preview": value, "preview_token": token})
    except (security.Rejected, confirmation.Rejected) as error:
        return response({"error": str(error)}, 403)
    except confirmation.AlreadyConfirmed as done:
        return response({"saved": done.outcome})
    except (ValueError, TypeError, KeyError) as error:
        return response({"error": str(error)}, 400)


def sync_job():
    try:
        from ..ingest.personal_api import update
        SYNC_STATE.update(result=update(), error=None)
    except Exception as error:
        SYNC_STATE.update(error=type(error).__name__)
    finally:
        SYNC_STATE["running"] = False
        SYNC_LOCK.release()


async def sync(request):
    if request.method == "POST":
        try:
            await checked_json(request)
        except security.Rejected as error:
            return response({"error": str(error)}, 403)
        if SYNC_LOCK.acquire(blocking=False):
            SYNC_STATE["running"] = True
            threading.Thread(target=sync_job, daemon=True).start()
    saved = paths.DATA / "personal-sync-status.json"
    return response(dict(SYNC_STATE, last=json.loads(saved.read_text(encoding="utf-8")) if saved.exists() else None))


def install(app):
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
    routes = [Route("/api/platform/summary", summary),
              Route("/api/platform/monitoring", monitoring),
              Route("/api/platform/intraday", intraday, methods=["GET","POST"]),
              Route("/api/platform/training", training, methods=["GET","POST"]),
              Route("/api/platform/memory", memory, methods=["POST"]),
              Route("/api/platform/compare", compare_swims),
              Route("/api/platform/activity/{activity_id:int}", detail),
              Route("/api/platform/coach", coach_reply, methods=["GET","POST"]),
              Route("/api/platform/builder", builder, methods=["GET", "POST"]),
              Route("/api/platform/sync", sync, methods=["GET", "POST"])]
    app.router.routes[0:0] = routes
    public = paths.ROOT / "frontend" / ".output" / "public"
    if (public / "index.html").is_file() and (public / "_nuxt").is_dir():
        # Original Python views remain as analysis drill-downs; new UI is main app.
        app.router.routes = [r for r in app.router.routes if getattr(r, "path", None) != "/"]
        async def spa(request):
            return FileResponse(public / "index.html")
        app.router.routes.append(Mount("/_nuxt", StaticFiles(directory=public / "_nuxt")))
        app.router.routes.append(Route("/", spa))
        app.router.routes.append(Route("/{path:path}", spa))
