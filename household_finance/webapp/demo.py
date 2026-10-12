"""체험판(데모) 페이지 생성 - 서버 없이 브라우저만으로 웹앱 화면을 둘러보게 한다.

실제 웹앱(static/app.js·app.css)을 그대로 쓰고, 화면이 서버에 묻는 조회 요청(GET /api/...)의 답을
샘플 데이터로 미리 계산해 한 HTML 파일에 넣는다. 저장 요청은 "체험판에서는 저장되지 않습니다"로 거절한다.
실행: python -m household_finance demo --out 체험판.html
"""

from __future__ import annotations

import json
import tempfile
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from household_finance.engine import shift_month
from household_finance.webapp.app import STATIC, create_app

SHIM = r"""
(() => {
  // 체험판: fetch('/api/...')를 미리 계산한 답으로 바꾼다. 저장 요청은 거절한다.
  const DATA = JSON.parse(document.getElementById('hh-demo-data').textContent);
  window.HH_DEMO = true;
  const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
  const READONLY = '체험판에서는 저장되지 않습니다. 실제 앱은 내 컴퓨터에서 실행하세요 (README의 "2단계: 웹앱").';
  const realFetch = window.fetch.bind(window);
  window.fetch = async (input, init = {}) => {
    const url = new URL(typeof input === 'string' ? input : input.url, location.href);
    if (!url.pathname.startsWith('/api/')) return realFetch(input, init);
    const method = (init.method || 'GET').toUpperCase();
    const p = url.pathname, q = url.searchParams;
    if (method !== 'GET') {
      if (p === '/api/login' || p === '/api/logout') return json({ ok: true });
      return json({ detail: READONLY }, 403);
    }
    if (p === '/api/status') return json({ setup_needed: false, has_data: true });
    if (p === '/api/me') return json(DATA.me);
    if (p === '/api/meta') return json(DATA.meta);
    if (p === '/api/dashboard') {
      const key = `${q.get('view') || '전체'}|${q.get('month') || DATA.meta.base_month}`;
      return DATA.dashboard[key] ? json(DATA.dashboard[key]) : json({ detail: '체험판에는 이 달의 데이터가 없습니다.' }, 404);
    }
    if (p === '/api/transactions') {
      const month = q.get('month'), cat = q.get('category'), member = q.get('member'), text = (q.get('q') || '').toLowerCase();
      return json(DATA.transactions.filter((t) => (!month || t.day.startsWith(month)) && (!cat || t.category === cat)
        && (!member || t.member === member) && (!text || t.desc.toLowerCase().includes(text))));
    }
    const ent = p.match(/^\/api\/entities\/(\w+)$/);
    if (ent && DATA.entities[ent[1]]) return json(DATA.entities[ent[1]]);
    const snap = p.match(/^\/api\/snapshots\/(\d{4}-\d{2})$/);
    if (snap && DATA.snapshots[snap[1]]) return json(DATA.snapshots[snap[1]]);
    return json({ detail: '체험판에서 지원하지 않는 화면입니다.' }, 404);
  };
  // 엑셀 내려받기 같은 링크도 막는다 (체험판에는 서버가 없음)
  document.addEventListener('click', (e) => {
    const a = e.target.closest && e.target.closest('a[href^="/api/"]');
    if (!a) return;
    e.preventDefault();
    const t = document.getElementById('toast'); t.textContent = READONLY; t.hidden = false; setTimeout(() => { t.hidden = true; }, 3500);
  }, true);
})();
"""

BANNER_CSS = """
.demo-banner { background: var(--soft); color: var(--muted); font-size: 12px; text-align: center; padding: 6px 16px;
  border-bottom: 1px solid var(--line); }
.demo-banner b { color: var(--fg); font-weight: 600; }
.bar { top: 0; }
"""


def collect(today: date | None = None) -> dict:
    """샘플 데이터로 웹앱을 띄우고 화면이 쓰는 조회 응답을 모은다."""
    with tempfile.TemporaryDirectory() as tmp:
        client = TestClient(create_app(Path(tmp) / "demo.db", today=today))
        client.post("/api/setup", json={"users": [{"username": "체험", "password": "demo-password", "member": "본인"}],
                                        "start": "sample"})
        meta = client.get("/api/meta").json()
        out = {"me": client.get("/api/me").json(), "meta": meta, "dashboard": {}, "entities": {}, "snapshots": {}}
        for view in meta["views"]:
            for month in meta["months"]:
                out["dashboard"][f"{view}|{month}"] = client.get("/api/dashboard", params={"view": view, "month": month}).json()
        out["transactions"] = client.get("/api/transactions").json()
        for kind in ["accounts", "holdings", "debts", "goals", "insurances", "events"]:
            out["entities"][kind] = client.get(f"/api/entities/{kind}").json()
        for month in meta["months"] + [shift_month(meta["base_month"], 1)]:
            out["snapshots"][month] = client.get(f"/api/snapshots/{month}").json()
        return out


def build_demo(out_path: str | Path, today: date | None = None) -> Path:
    data = json.dumps(collect(today), ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    page = f"""<title>우리집 주식회사 체험판</title>
<style>
{css}
{BANNER_CSS}
</style>
<div class="demo-banner"><b>체험판</b> · 가상의 3인 가구 샘플 데이터입니다. 모든 메뉴를 눌러 볼 수 있고, 저장은 되지 않습니다.</div>
<div id="app" aria-live="polite"></div>
<div id="toast" role="status" hidden></div>
<script type="application/json" id="hh-demo-data">{data}</script>
<script>{SHIM}</script>
<script>{js}</script>
"""
    out_path = Path(out_path)
    out_path.write_text(page, encoding="utf-8")
    return out_path
