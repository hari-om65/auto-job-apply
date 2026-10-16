"""Control panel for the daily Telegram pipeline.  Run: python -m telegram_apply.web  ->  http://localhost:5055"""
import json
import os
import threading
import time
from datetime import datetime
from flask import Flask, jsonify, request, send_from_directory
from . import pipeline, settings_store

app = Flask(__name__)
status = {"running": False, "log": []}
_lock = threading.Lock()


def log(msg: str) -> None:
    status["log"] = (status["log"] + [f"{datetime.now():%H:%M:%S}  {msg}"])[-200:]
    print(msg, flush=True)


def run_pipeline(reprocess: bool = False) -> bool:
    if not _lock.acquire(blocking=False):
        return False

    def work():
        status["running"] = True
        try:
            pipeline.run_once(log, reprocess)
        except Exception as e:
            log(f"ERROR: {e}")
        finally:
            status["running"] = False
            _lock.release()

    threading.Thread(target=work, daemon=True).start()
    return True


def scheduler() -> None:
    """Start the daily run once the configured time has passed and it hasn't run today."""
    while True:
        try:
            s = settings_store.load()
            now = datetime.now()
            if s["enabled"] and s["last_run_date"] != str(now.date()) and f"{now:%H:%M}" >= s["run_time"]:
                if run_pipeline():
                    settings_store.save({"last_run_date": str(now.date())})
                    log("Scheduled daily run triggered")
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
    return jsonify(settings=s, running=status["running"], log=status["log"][-80:], results=results,
                   window=f"{start:%d %b %H:%M} -> {end:%d %b %H:%M}")


@app.post("/api/settings")
def api_settings():
    d = request.get_json()
    if isinstance(d.get("channels"), str):
        d["channels"] = [c.strip() for c in d["channels"].split(",") if c.strip()]
    return jsonify(settings_store.save(d))


@app.post("/api/run")
def api_run():
    return jsonify(started=run_pipeline(bool((request.get_json(silent=True) or {}).get("reprocess"))))


@app.get("/pdf/<path:name>")
def pdf(name):
    return send_from_directory(os.path.abspath("telegram_apply/output"), os.path.basename(name))


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
.wrap{overflow-x:auto}
</style></head><body><main>
<h1>Job pipeline <span id=live class=pill>idle</span></h1>
<div class=grid>
<div class=card><h2>Daily schedule</h2>
<div class=chk><input type=checkbox id=enabled><span>Run automatically every day (keep this page's server running)</span></div>
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
<div class=chk><input type=checkbox id=dry_run><span><b>Dry run</b> - prepare resumes but don't send emails or submit forms</span></div>
<div style="margin-top:14px" class=row><button id=save>Save settings</button><button class=sec id=run>Run now</button></div>
<div class=chk><input type=checkbox id=reprocess><span>Re-process posts already seen (otherwise they are skipped)</span></div>
</div>
<div class=card><h2>Live log</h2><pre id=log>-</pre></div>
</div>
<div class=card style="margin-top:16px"><h2>Results</h2><div class=wrap><table><thead><tr>
<th>Time</th><th>Job</th><th>Batch</th><th>Fit</th><th>ATS</th><th>Outcome</th><th>Resume used</th></tr></thead><tbody id=rows></tbody></table></div></div>
</main><script>
const $=id=>document.getElementById(id);const F=['window_start_date','window_end_date','required_batch','run_time','window_start','window_end','channels','min_match_score','min_ats_score','max_per_day'];
let loaded=false;
const esc=s=>String(s??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
async function refresh(){
 const d=await (await fetch('/api/state')).json();
 if(!loaded){F.forEach(k=>$(k).value=Array.isArray(d.settings[k])?d.settings[k].join(', '):d.settings[k]);
  $('enabled').checked=d.settings.enabled;$('dry_run').checked=d.settings.dry_run;loaded=true}
 $('win').textContent=d.window;$('live').textContent=d.running?'running...':'idle';
 $('run').disabled=d.running;$('log').textContent=d.log.join('\\n')||'-';
 $('rows').innerHTML=d.results.map(r=>{
  const c=/^(emailed|form: submitted)/.test(r.status)?'ok':/^dry-run/.test(r.status)?'wa':/error/.test(r.status)?'er':/manual|queued/.test(r.status)?'wa':'mu';
  const links=(r.manual_links||[]).map(l=>`<div><a href="${esc(l)}" target=_blank>open link</a></div>`).join('');
  const pdf=r.pdf?`<a href="/pdf/${encodeURIComponent(r.pdf.split('/').pop())}" target=_blank>${esc(r.pdf.split('/').pop())}</a><div class=mu>new resume, tailored from ${esc(r.base_resume||'base resume')}</div>`:'<span class=mu>-</span>';
  return `<tr><td class=mu>${esc((r.time||'').replace('T',' ').slice(5,16))}</td><td>${esc(r.job)}</td><td>${esc(r.batch??'')}</td><td>${esc(r.fit??'')}</td><td>${r.ats!=null?esc(r.ats)+'%':''}</td>
  <td class=${c}>${esc(r.status)}${links}</td><td>${pdf}</td></tr>`}).join('')||'<tr><td colspan=7 class=mu>No results yet</td></tr>'}
$('save').onclick=async()=>{const b={enabled:$('enabled').checked,dry_run:$('dry_run').checked};
 F.forEach(k=>b[k]=['min_match_score','min_ats_score','max_per_day'].includes(k)?+$(k).value:$(k).value);
 await fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});$('save').textContent='Saved';setTimeout(()=>$('save').textContent='Save settings',1200);refresh()};
$('run').onclick=async()=>{await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reprocess:$('reprocess').checked})});refresh()};
refresh();setInterval(refresh,4000);
</script></body></html>"""


if __name__ == "__main__":
    threading.Thread(target=scheduler, daemon=True).start()
    print("Open http://localhost:5055")
    app.run(host="127.0.0.1", port=5055)
