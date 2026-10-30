"""Control panel for the daily job pipelines (Telegram channels + LinkedIn).

Run: python -m telegram_apply.web  ->  http://localhost:5055   (login: admin / the password in dashboard_password.txt)
For a public link use: python -m telegram_apply.live
"""
import hmac
import json
import os
import secrets
import threading
import time
from datetime import datetime, timedelta
from flask import Flask, Response, jsonify, request, send_from_directory
from . import linkedin, pipeline, settings_store

app = Flask(__name__)
status = {"running": False, "waiting": 0, "log": []}
li_status = {"log": []}
_lock = threading.Lock()
PASSWORD_FILE = "telegram_apply/dashboard_password.txt"


def dashboard_password() -> str:
    """Password for the dashboard (Basic auth, user 'admin'). Generated once and kept in a git-ignored file."""
    if not os.path.exists(PASSWORD_FILE):
        with open(PASSWORD_FILE, "w") as f:
            f.write(secrets.token_urlsafe(12))
    with open(PASSWORD_FILE) as f:
        return f.read().strip()


@app.before_request
def require_login():
    auth = request.authorization
    if auth and auth.username == "admin" and hmac.compare_digest(auth.password or "", dashboard_password()):
        return None
    return Response("Login required", 401, {"WWW-Authenticate": 'Basic realm="Job dashboard"'})


def log(msg: str) -> None:
    status["log"] = (status["log"] + [f"{datetime.now():%H:%M:%S}  {msg}"])[-200:]
    print(msg, flush=True)


def li_log(msg: str) -> None:
    li_status["log"] = (li_status["log"] + [f"{datetime.now():%H:%M:%S}  {msg}"])[-300:]
    print("[linkedin]", msg, flush=True)


def run_pipeline(reprocess: bool = False, window=None, on_success=None) -> bool:
    if not _lock.acquire(blocking=False):
        return False

    def work():
        status["running"] = True
        try:
            pipeline.run_once(log, reprocess, window)
            if on_success:
                on_success()
        except Exception as e:
            log(f"ERROR: {e}")
        finally:
            status["running"] = False
            _lock.release()

    threading.Thread(target=work, daemon=True).start()
    return True


def apply_now(text: str, link: str, force: bool) -> None:
    """Apply to one job you added on the page. Waits for a run in progress (they share the browser profile)."""
    def work():
        status["waiting"] += 1
        with _lock:
            status["waiting"] -= 1
            status["running"] = True
            try:
                for rec in pipeline.apply_one(text, link, force, log):
                    log(f"{rec['job']} -> {rec['status']}")
            except Exception as e:
                log(f"ERROR: {e}")
            finally:
                status["running"] = False

    if _lock.locked():
        log("A run is in progress: your job starts as soon as it finishes")
    threading.Thread(target=work, daemon=True).start()


def watch_tick(s: dict, now: datetime) -> None:
    """Watch mode: every few minutes, check the posts since the last check and apply to the new ones."""
    every = max(int(s["watch_every_min"] or 15), 5)
    last = datetime.fromisoformat(s["watch_last_check"]) if s["watch_last_check"] else None
    tried = status.get("watch_tried")
    if any(t and (now - t).total_seconds() < every * 60 for t in (last, tried)):
        return
    start = max(last or now - timedelta(minutes=every), now - timedelta(days=3))  # PC was off: catch up, but not forever
    window = (start, now)
    if run_pipeline(window=window, on_success=lambda: settings_store.save({"watch_last_check": now.isoformat(timespec="seconds")})):
        status["watch_tried"] = now  # a failed check (no internet...) is retried next interval, from the same start
        log(f"Watch: checking new posts since {start:%d %b %H:%M}")


def run_linkedin() -> bool:
    if linkedin.is_running():
        return False
    threading.Thread(target=linkedin.run_once, args=(li_log,), daemon=True).start()
    return True


def scheduler() -> None:
    """Start each daily run once its time has passed and it has not run today."""
    while True:
        try:
            s = settings_store.load()
            now = datetime.now()
            hhmm = f"{now:%H:%M}"
            if s["enabled"] and s["last_run_date"] != str(now.date()) and hhmm >= s["run_time"]:
                if run_pipeline():
                    settings_store.save({"last_run_date": str(now.date())})
                    log("Scheduled daily run triggered")
            if s["linkedin_enabled"] and s["linkedin_last_run_date"] != str(now.date()) and hhmm >= s["linkedin_run_time"]:
                if run_linkedin():
                    settings_store.save({"linkedin_last_run_date": str(now.date())})
                    li_log("Scheduled daily LinkedIn run triggered")
            if s["watch_enabled"]:
                watch_tick(s, now)
        except Exception as e:
            log(f"scheduler error: {e}")
        time.sleep(30)


@app.get("/api/state")
def api_state():
    results = []
    if os.path.exists(pipeline.RESULTS):
        with open(pipeline.RESULTS, encoding="utf-8") as f:
            results = [json.loads(l) for l in f if l.strip()][-200:][::-1]
    s = settings_store.load()
    start, end = pipeline.compute_window(s)
    return jsonify(settings=s, running=status["running"], waiting=status["waiting"], log=status["log"][-80:], results=results,
                   window=f"{start:%d %b %H:%M} -> {end:%d %b %H:%M}",
                   linkedin={"running": linkedin.is_running(), "log": li_status["log"][-80:], "results": linkedin.recent(80)})


@app.post("/api/settings")
def api_settings():
    d = request.get_json()
    for key in ("channels", "linkedin_roles"):
        if isinstance(d.get(key), str):
            d[key] = [c.strip() for c in d[key].split(",") if c.strip()]
    return jsonify(settings_store.save(d))


@app.post("/api/run")
def api_run():
    return jsonify(started=run_pipeline(bool((request.get_json(silent=True) or {}).get("reprocess"))))


@app.post("/api/apply")
def api_apply():
    d = request.get_json(silent=True) or {}
    text, link = (d.get("text") or "").strip(), (d.get("link") or "").strip()
    if not (text or link):
        return jsonify(started=False, error="Paste the job post or an apply link"), 400
    apply_now(text, link, bool(d.get("force", True)))
    return jsonify(started=True)


@app.post("/api/linkedin/run")
def api_linkedin_run():
    return jsonify(started=run_linkedin())


@app.post("/api/linkedin/stop")
def api_linkedin_stop():
    linkedin.stop()
    return jsonify(stopped=True)


@app.get("/pdf/<path:name>")
def pdf(name):
    return send_from_directory(os.path.abspath("telegram_apply/output"), name)  # safe_join blocks ../ escapes


@app.get("/")
def index():
    return PAGE


PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Job Pipeline</title><style>
:root{--bg:#f6f7f9;--card:#fff;--tx:#1b1f24;--mu:#6a737d;--bd:#e1e4e8;--ac:#2563eb;--ok:#15803d;--wa:#b45309;--er:#b91c1c}
@media(prefers-color-scheme:dark){:root{--bg:#0e1116;--card:#161b22;--tx:#e6edf3;--mu:#8b949e;--bd:#30363d;--ac:#4c8dff;--ok:#3fb950;--wa:#d29922;--er:#f85149}}
*{box-sizing:border-box}body{margin:0;font:14px/1.5 system-ui,sans-serif;background:var(--bg);color:var(--tx)}
main{max-width:1100px;margin:0 auto;padding:16px}h1{font-size:20px;margin:8px 0 16px}
.grid{display:grid;gap:16px;grid-template-columns:1fr 1fr}@media(max-width:800px){.grid{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:16px}
h2{font-size:15px;margin:0 0 12px}label{display:block;font-size:12px;color:var(--mu);margin:10px 0 3px}
input[type=text],input[type=time],input[type=number],input[type=date]{width:100%;padding:7px 9px;border:1px solid var(--bd);border-radius:6px;background:var(--bg);color:var(--tx)}
.row{display:flex;gap:10px}.row>*{flex:1}.chk{display:flex;gap:8px;align-items:center;margin-top:12px;font-size:14px;color:var(--tx)}
button{padding:8px 14px;border:0;border-radius:6px;background:var(--ac);color:#fff;font-weight:600;cursor:pointer}
button.sec{background:transparent;color:var(--tx);border:1px solid var(--bd)}button:disabled{opacity:.5}
pre{margin:0;max-height:210px;overflow:auto;font-size:12px;background:var(--bg);padding:10px;border-radius:6px;white-space:pre-wrap}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:7px 6px;border-bottom:1px solid var(--bd);vertical-align:top}
th{color:var(--mu);font-weight:600}.ok{color:var(--ok)}.wa{color:var(--wa)}.er{color:var(--er)}.mu{color:var(--mu)}
.pill{display:inline-block;padding:2px 8px;border-radius:99px;font-size:12px;border:1px solid var(--bd)}a{color:var(--ac)}
.wrap{overflow-x:auto}.tabs{display:flex;gap:8px;margin-bottom:16px}.tabs button{background:transparent;color:var(--tx);border:1px solid var(--bd)}
.tabs button.on{background:var(--ac);color:#fff;border-color:var(--ac)}.hide{display:none}
</style></head><body><main>
<h1>Job pipeline <span id=live class=pill>idle</span></h1>
<div class=tabs><button id=tab_tg class=on>Telegram channels</button><button id=tab_li>LinkedIn (last 24 hours)</button></div>

<div class=card style="margin-bottom:16px"><h2>Apply to a job now</h2>
<div class=mu>Paste the job post / description, its apply link (company careers page, Google Form) or both. It is applied to right away with a resume tailored to it - no restart needed.</div>
<label>Job post or description</label><textarea id=one_text rows=5 style="width:100%;padding:7px 9px;border:1px solid var(--bd);border-radius:6px;background:var(--bg);color:var(--tx);font:inherit"></textarea>
<label>Apply link or recruiter email (optional if it is in the text)</label><input type=text id=one_link placeholder="https://careers.company.com/job/123">
<div class=chk><input type=checkbox id=one_force checked><span>I picked this job: ignore the batch, fit score and daily limit filters</span></div>
<div style="margin-top:12px" class=row><button id=one_go>Apply now</button><span class=mu id=one_msg style="align-self:center"></span></div>
</div>

<section id=sec_tg>
<div class=grid>
<div class=card><h2>Daily schedule</h2>
<div class=chk><input type=checkbox id=watch_enabled><span><b>Watch the channels</b>: apply to new posts automatically, all day</span></div>
<div class=row><div><label>Check every (minutes, min 5)</label><input type=number id=watch_every_min></div>
<div><label>Last checked</label><input type=text id=watch_seen disabled></div></div>
<div class=chk><input type=checkbox id=enabled><span>Also run once every day for the time window below</span></div>
<label>Run time (daily)</label><input type=time id=run_time>
<div class=row><div><label>From date (blank = auto)</label><input type=date id=window_start_date></div>
<div><label>To date (blank = today)</label><input type=date id=window_end_date></div></div>
<div class=row><div><label>Check posts from (time)</label><input type=time id=window_start></div>
<div><label>until</label><input type=time id=window_end></div></div>
<div class=mu style="margin-top:6px">Next window: <b id=win></b></div>
<label>Telegram channels (comma separated)</label><input type=text id=channels>
<div class=row><div><label>Only jobs for batch</label><input type=text id=required_batch placeholder='2027'></div>
<div><label>Min job fit (0-100)</label><input type=number id=min_match_score></div>
<div><label>Min resume ATS % </label><input type=number id=min_ats_score></div>
<div><label>Max applications/day</label><input type=number id=max_per_day></div></div>
<div class=chk><input type=checkbox id=add_missing_keywords><span>Add job keywords I'm missing to the Skills section (be ready to discuss them)</span></div>
<div class=chk><input type=checkbox id=dry_run><span><b>Dry run</b> - prepare resumes but don't send emails or submit forms (also applies to LinkedIn)</span></div>
<div style="margin-top:14px" class=row><button id=save>Save settings</button><button class=sec id=run>Run now</button></div>
<div class=chk><input type=checkbox id=reprocess><span>Re-process posts already seen (otherwise they are skipped)</span></div>
</div>
<div class=card><h2>Live log</h2><pre id=log>-</pre></div>
</div>
<div class=card style="margin-top:16px"><h2>Results</h2><div class=wrap><table><thead><tr>
<th>Time</th><th>Job</th><th>Batch</th><th>Fit</th><th>ATS</th><th>Outcome</th><th>Resume used</th></tr></thead><tbody id=rows></tbody></table></div></div>
</section>

<section id=sec_li class=hide>
<div class=grid>
<div class=card><h2>LinkedIn: jobs posted in the last 24 hours</h2>
<div class=mu>Searches your roles, keeps only jobs from the last 24 hours that match them, and applies with a resume tailored to each job
(Easy Apply, and company sites for the rest). Sign in to LinkedIn once: <code>python -m telegram_apply.google_login linkedin</code></div>
<div class=chk><input type=checkbox id=linkedin_enabled><span>Run automatically every day</span></div>
<label>Daily run time</label><input type=time id=linkedin_run_time>
<label>Roles to search (comma separated)</label><input type=text id=linkedin_roles>
<div class=row><div><label>Location</label><input type=text id=linkedin_location></div>
<div><label>Max jobs per role per run</label><input type=number id=linkedin_per_search></div></div>
<div class=chk><input type=checkbox id=linkedin_external><span>Also apply on company sites when a job is not Easy Apply</span></div>
<div class=mu style="margin-top:8px">Dry run (on the Telegram tab) is shared: while it is on, applications are filled but not submitted.</div>
<div style="margin-top:14px" class=row><button id=save2>Save settings</button><button class=sec id=li_run>Run LinkedIn now</button><button class=sec id=li_stop>Stop</button></div>
</div>
<div class=card><h2>LinkedIn log</h2><pre id=li_log>-</pre></div>
</div>
<div class=card style="margin-top:16px"><h2>LinkedIn jobs</h2><div class=wrap><table><thead><tr>
<th>When</th><th>Job</th><th>Company</th><th>Outcome</th><th>Resume used</th><th>Link</th></tr></thead><tbody id=li_rows></tbody></table></div></div>
</section>
</main><script>
const $=id=>document.getElementById(id);
const F=['window_start_date','window_end_date','required_batch','run_time','window_start','window_end','channels','min_match_score','min_ats_score','max_per_day',
 'linkedin_run_time','linkedin_roles','linkedin_location','linkedin_per_search','watch_every_min'];
const NUM=['min_match_score','min_ats_score','max_per_day','linkedin_per_search','watch_every_min'];
const CHK=['enabled','dry_run','add_missing_keywords','linkedin_enabled','linkedin_external','watch_enabled'];
let loaded=false;
const esc=s=>String(s??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
function tab(t){$('sec_tg').classList.toggle('hide',t!=='tg');$('sec_li').classList.toggle('hide',t!=='li');$('tab_tg').classList.toggle('on',t==='tg');$('tab_li').classList.toggle('on',t==='li')}
$('tab_tg').onclick=()=>tab('tg');$('tab_li').onclick=()=>tab('li');
async function refresh(){
 const d=await (await fetch('/api/state')).json();
 if(!loaded){F.forEach(k=>$(k).value=Array.isArray(d.settings[k])?d.settings[k].join(', '):d.settings[k]);
  CHK.forEach(k=>$(k).checked=!!d.settings[k]);loaded=true}
 $('win').textContent=d.window;$('live').textContent=(d.running||d.linkedin.running)?'running...':d.settings.watch_enabled?'watching':'idle';
 $('watch_seen').value=(d.settings.watch_last_check||'never').replace('T',' ');
 $('one_msg').textContent=d.waiting?'waiting for the current run to finish...':d.running?'working - see the live log':'';
 $('run').disabled=d.running;$('log').textContent=d.log.join('\\n')||'-';
 $('li_run').disabled=d.linkedin.running;$('li_log').textContent=d.linkedin.log.join('\\n')||'-';
 $('rows').innerHTML=d.results.map(r=>{
  const c=/^(emailed|form: submitted)/.test(r.status)?'ok':/^dry-run/.test(r.status)?'wa':/error/.test(r.status)?'er':/manual|queued/.test(r.status)?'wa':'mu';
  const links=(r.manual_links||[]).map(l=>`<div><a href="${esc(l)}" target=_blank>open link</a></div>`).join('');
  const rel=r.pdf?r.pdf.split(String.fromCharCode(92)).join('/').split('output/').pop():'';const pdf=r.pdf?`<a href="/pdf/${rel.split('/').map(encodeURIComponent).join('/')}" target=_blank>${esc(rel.split('/').pop())}</a><div class=mu>made for: ${esc(rel.split('/').slice(0,-1).join(' / '))}</div>`:'<span class=mu>-</span>';
  return `<tr><td class=mu>${esc((r.time||'').replace('T',' ').slice(5,16))}</td><td>${esc(r.job)}</td><td>${esc(r.batch??'')}</td><td>${esc(r.fit??'')}</td><td>${r.ats!=null?esc(r.ats)+'%':''}</td>
  <td class=${c}>${esc(r.status)}${links}${(r.added_keywords||[]).length?`<div class=mu>Skills added (learn these): ${esc(r.added_keywords.join(', '))}</div>`:''}</td><td>${pdf}</td></tr>`}).join('')||'<tr><td colspan=7 class=mu>No results yet</td></tr>';
 $('li_rows').innerHTML=d.linkedin.results.map(r=>{
  const c=/Easy Applied/.test(r.status)?'ok':/skipped|not submitted/.test(r.status)?'mu':'wa';
  return `<tr><td class=mu>${esc(r.time)}</td><td>${esc(r.title)}</td><td>${esc(r.company)}</td><td class=${c}>${esc(r.status)}</td>
  <td>${esc(r.resume)}</td><td>${r.link?`<a href="${esc(r.link)}" target=_blank>open</a>`:''}</td></tr>`}).join('')||'<tr><td colspan=6 class=mu>No LinkedIn jobs yet</td></tr>'}
async function save(btn){const b={};CHK.forEach(k=>b[k]=$(k).checked);
 F.forEach(k=>b[k]=NUM.includes(k)?+$(k).value:$(k).value);
 await fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});btn.textContent='Saved';setTimeout(()=>btn.textContent='Save settings',1200);refresh()}
$('save').onclick=()=>save($('save'));$('save2').onclick=()=>save($('save2'));
$('run').onclick=async()=>{await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reprocess:$('reprocess').checked})});refresh()};
$('li_run').onclick=async()=>{await save($('save2'));await fetch('/api/linkedin/run',{method:'POST'});refresh()};
$('one_go').onclick=async()=>{const b={text:$('one_text').value,link:$('one_link').value,force:$('one_force').checked};
 if(!b.text.trim()&&!b.link.trim()){$('one_msg').textContent='Paste the job post or a link first';return}
 const r=await fetch('/api/apply',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});
 if(r.ok){$('one_text').value='';$('one_link').value='';tab('tg')}refresh()};
$('li_stop').onclick=async()=>{await fetch('/api/linkedin/stop',{method:'POST'});refresh()};
refresh();setInterval(refresh,4000);
</script></body></html>"""


if __name__ == "__main__":
    threading.Thread(target=scheduler, daemon=True).start()
    print("Open http://localhost:5055   login: admin / password in", PASSWORD_FILE)
    dashboard_password()
    app.run(host="127.0.0.1", port=5055, threaded=True)
