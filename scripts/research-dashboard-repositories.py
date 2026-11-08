"""Ricognizione ripetibile di repository pubblici, senza dati dell'atleta."""
import concurrent.futures
import json
from pathlib import Path
import requests

REPOS=["watt-mind/coach","jimmykane/quantified-self","endurain-project/endurain",
"arin-jaff/TrainingGeeks","cggmx/garmin-health-dashboard","samr1/FitTrackee",
"thomaschampagne/elevate","GoldenCheetah/GoldenCheetah","bepcyc/wattwise-core",
"dreeveapp/dreeve","tcgoetz/GarminDB","arpanghosh8453/garmin-grafana",
"alarboulletmarin/zoned","diegoscarabelli/garmin-health-data","dwedigital/claude-coach",
"OpenAthleteOrg/openathlete","dandwhelan/garmin-stats-ai","fiddur/aurboda",
"alexgasconn/StravaStats","brunothesatellite/grafana-dashboard"]
FOLDER=Path(__file__).resolve().parents[1]/"data"/"research-dashboards"

def inspect(repo):
    session=requests.Session()
    session.headers.update({"Accept":"application/vnd.github+json","User-Agent":"GarminCoach-local-research"})
    info=session.get(f"https://api.github.com/repos/{repo}",timeout=30)
    if info.status_code!=200:
        return {"repo":repo,"status":info.status_code}
    meta=info.json()
    result={k:meta.get(k) for k in ("full_name","description","html_url","stargazers_count","pushed_at","archived","language","default_branch","size")}
    result["repo"]=repo
    result["license"]=(meta.get("license") or {}).get("spdx_id")
    folder=FOLDER/repo.replace("/","--")
    folder.mkdir(parents=True,exist_ok=True)
    readme=session.get(f"https://api.github.com/repos/{repo}/readme",headers={"Accept":"application/vnd.github.raw+json"},timeout=30)
    if readme.status_code==200:
        (folder/"README.md").write_text(readme.text,encoding="utf-8")
    tree=session.get(f"https://api.github.com/repos/{repo}/git/trees/{meta['default_branch']}?recursive=1",timeout=45)
    if tree.status_code==200:
        contents=tree.json()
        paths=[r["path"] for r in contents.get("tree",[]) if r["type"]=="blob"]
        result["tree_truncated"]=contents.get("truncated")
        (folder/"files.json").write_text(json.dumps(paths,indent=2),encoding="utf-8")
        terms=("swim","wellness","recovery","sleep","hrv","calendar","dashboard","health","training-workspace")
        result["relevant_files"]=[p for p in paths if any(term in p.lower() for term in terms)][:100]
    (folder/"metadata.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    return result

if __name__=="__main__":
    FOLDER.mkdir(parents=True,exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        results=list(executor.map(inspect,REPOS))
    (FOLDER/"inventory.json").write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8")
    for r in results:
        print(r["repo"],r.get("license",r.get("status")),r.get("language"),r.get("pushed_at"),r.get("archived"))
