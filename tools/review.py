# -*- coding: utf-8 -*-
"""
review.py - صفحه‌ی بازبینی زنده‌ی ترجمه‌ها (EN ↔ FA)

یک سرور کوچک محلی بالا می‌آورد که:
  * پیشرفت کلی را به تفکیک دسته نشان می‌دهد
  * ترجمه‌ها را کنار متن انگلیسی فهرست می‌کند (راست‌چین، با جست‌وجو و فیلتر)
  * رشته‌های ترجمه‌نشده را هم نشان می‌دهد تا بشود کار را ادامه داد

استفاده:
    python3 tools/review.py --port 8000
    # مرورگر: http://localhost:8000
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fslib  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, "work")
BATCH_DIR = os.path.join(ROOT, "translations", "batches")

DATA = {"rows": [], "cats": {}, "index": {}}


def reload_data():
    index = fslib.load_index([os.path.join(WORK, "index_common.tsv"),
                              os.path.join(WORK, "index_pc.tsv")])
    cats = {}
    counts = {}
    for key, name in (("common", "index_common.tsv"), ("pc", "index_pc.tsv")):
        path = os.path.join(WORK, name)
        if not os.path.exists(path):
            continue
        for line in open(path, encoding="utf-8", newline=""):
            parts = line.rstrip("\r\n").split("\t")
            if len(parts) >= 4:
                cats[parts[0]] = parts[2]
                counts[parts[0]] = int(parts[3]) if parts[3].isdigit() else 1
    tm, done, problems = fslib.load_tm(BATCH_DIR, index, verbose=False)
    rows = []
    for sid, en in index.items():
        rows.append({
            "id": sid,
            "cat": cats.get(sid, "?"),
            "n": counts.get(sid, 1),
            "en": en,
            "fa": tm.get(en, ""),
        })
    rows.sort(key=lambda r: (-r["n"], r["id"]))
    DATA["rows"] = rows
    DATA["cats"] = cats
    DATA["index"] = index
    DATA["problems"] = problems
    return rows


PAGE = """<!doctype html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>بازبینی فارسی‌سازی Mafia III</title>
<style>
 :root {{ --bg:#12141a; --card:#1b1f29; --line:#2a3040; --fg:#e8eaf0; --mut:#98a2b8; --acc:#f2b544; }}
 * {{ box-sizing:border-box; }}
 body {{ margin:0; background:var(--bg); color:var(--fg);
        font:15px/1.9 "Vazirmatn","Segoe UI",Tahoma,sans-serif; }}
 header {{ padding:18px 22px; border-bottom:1px solid var(--line); background:var(--card);
          position:sticky; top:0; z-index:5; }}
 h1 {{ margin:0 0 6px; font-size:19px; }}
 .mut {{ color:var(--mut); font-size:13px; }}
 .stats {{ display:flex; flex-wrap:wrap; gap:8px; margin-top:10px; }}
 .pill {{ background:#222838; border:1px solid var(--line); border-radius:999px;
         padding:4px 12px; font-size:13px; }}
 .pill b {{ color:var(--acc); }}
 .bar {{ height:8px; background:#222838; border-radius:999px; overflow:hidden; margin-top:10px; }}
 .bar i {{ display:block; height:100%; background:linear-gradient(90deg,#f2b544,#e2703a); }}
 .tools {{ display:flex; gap:8px; flex-wrap:wrap; margin-top:12px; }}
 input,select {{ background:#0f1219; color:var(--fg); border:1px solid var(--line);
                border-radius:8px; padding:8px 10px; font:inherit; }}
 input {{ flex:1; min-width:220px; }}
 main {{ padding:14px 22px 60px; }}
 .row {{ display:grid; grid-template-columns:110px 1fr 1fr; gap:12px; padding:10px 12px;
        border-bottom:1px solid var(--line); }}
 .row:hover {{ background:#181c26; }}
 .id {{ color:var(--mut); font-size:12px; direction:ltr; text-align:left; }}
 .en {{ color:#b9c2d6; direction:ltr; text-align:left; white-space:pre-wrap;
       font-family:"Segoe UI",Arial,sans-serif; font-size:13.5px; }}
 .fa {{ white-space:pre-wrap; }}
 .empty {{ color:#5d667d; font-style:italic; }}
 .tag {{ display:inline-block; background:#26304a; border-radius:6px; padding:0 6px;
        font-size:11px; color:#a9b6d8; margin-inline-start:6px; }}
 .more {{ text-align:center; padding:16px; }}
 button {{ background:var(--acc); color:#20180a; border:0; border-radius:8px;
          padding:9px 18px; font:inherit; font-weight:700; cursor:pointer; }}
 code {{ background:#0f1219; padding:1px 5px; border-radius:4px; direction:ltr; }}
</style>
</head>
<body>
<header>
  <h1>بازبینی فارسی‌سازی Mafia III</h1>
  <div class="mut">منبع: <code>stringtable_en_common_group.xml</code> و <code>stringtable_en_pc_group.xml</code></div>
  <div class="stats" id="stats"></div>
  <div class="bar"><i id="bar" style="width:0%"></i></div>
  <div class="tools">
    <input id="q" placeholder="جست‌وجو در متن انگلیسی یا فارسی…" oninput="render(0)">
    <select id="cat" onchange="render(0)">
      <option value="">همه‌ی دسته‌ها</option>
      <option value="ui">ui — منو و رابط</option>
      <option value="bark">bark — فریادهای کوتاه</option>
      <option value="story">story — دیالوگ و داستان</option>
      <option value="cue">cue — آواها</option>
      <option value="legal">legal — حقوقی و تیتراژ</option>
    </select>
    <select id="st" onchange="render(0)">
      <option value="done">فقط ترجمه‌شده‌ها</option>
      <option value="todo">فقط ترجمه‌نشده‌ها</option>
      <option value="all">همه</option>
    </select>
  </div>
</header>
<main id="list"></main>
<div class="more"><button onclick="render(page+1)">نمایش بیشتر</button></div>
<script>
let DATA = {data};
let page = 0;
const PER = 120;
function filtered() {{
  const q = document.getElementById('q').value.trim().toLowerCase();
  const c = document.getElementById('cat').value;
  const s = document.getElementById('st').value;
  return DATA.filter(r =>
     (!c || r.cat === c) &&
     (s === 'all' || (s === 'done' ? r.fa : !r.fa)) &&
     (!q || r.en.toLowerCase().includes(q) || r.fa.includes(q) || r.id.toLowerCase().includes(q)));
}}
function stats() {{
  const cats = {{}};
  let done = 0;
  DATA.forEach(r => {{
    const c = cats[r.cat] = cats[r.cat] || [0,0,0,0];
    c[0]++; c[2] += r.n;
    if (r.fa) {{ c[1]++; c[3] += r.n; done++; }}
  }});
  const el = document.getElementById('stats');
  el.innerHTML = `<span class="pill">کل رشته‌های یکتا: <b>${{DATA.length.toLocaleString('fa-IR')}}</b></span>` +
    `<span class="pill">ترجمه‌شده: <b>${{done.toLocaleString('fa-IR')}}</b> (${{(100*done/DATA.length).toFixed(1)}}٪)</span>` +
    Object.entries(cats).sort((a,b)=>b[1][0]-a[1][0]).map(([k,v]) =>
      `<span class="pill">${{k}}: <b>${{v[1].toLocaleString('fa-IR')}}</b>/${{v[0].toLocaleString('fa-IR')}}</span>`).join('');
  document.getElementById('bar').style.width = (100*done/DATA.length) + '%';
}}
function render(p) {{
  if (p === 0) {{ page = 0; document.getElementById('list').innerHTML = ''; }}
  else page = p;
  const rows = filtered().slice(0, (page+1)*PER);
  document.getElementById('list').innerHTML = rows.map(r => `
    <div class="row">
      <div class="id">${{r.id}}<span class="tag">${{r.cat}}</span><span class="tag">×${{r.n}}</span></div>
      <div class="en">${{esc(r.en)}}</div>
      <div class="fa ${{r.fa?'':'empty'}}">${{r.fa ? esc(r.fa) : '— ترجمه نشده —'}}</div>
    </div>`).join('');
}}
function esc(s) {{ return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }}
stats(); render(0);
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            rows = DATA["rows"] or reload_data()
            payload = json.dumps(rows, ensure_ascii=False)
            body = PAGE.format(data=payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif u.path == "/api/rows":
            body = json.dumps(DATA["rows"] or reload_data(), ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="0.0.0.0")
    args = ap.parse_args()
    reload_data()
    print("بازبینی آماده است: http://%s:%d  (%d رشته)" % (args.host, args.port, len(DATA["rows"])))
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
