/* 우리집 주식회사 - 단일 페이지 앱. 외부 라이브러리 없이 동작한다 (인터넷 없이도 사용 가능).
   화면: #/dashboard #/transactions #/import #/close #/budget #/settings */
(() => {
  'use strict';

  // ---------------------------------------------------------------- 도우미
  const $app = document.getElementById('app');
  const nf = new Intl.NumberFormat('ko-KR');
  const won = (x) => nf.format(Math.round(x));
  const short = (x) => {
    const a = Math.abs(x), s = x < 0 ? '-' : '';
    if (a >= 1e8) return s + (a / 1e8).toFixed(2).replace(/\.?0+$/, '') + '억';
    if (a >= 1e4) return s + nf.format(Math.round(a / 1e4)) + '만';
    return s + nf.format(Math.round(a));
  };
  const pct = (x, d = 1) => (x == null ? '—' : (x * 100).toFixed(d) + '%');
  const tone = (s) => !s ? 'none'
    : /🔴|❌|초과|부족|공백/.test(s) ? 'bad'
    : /⚠|⚖|미달|지연|주의|리밸런싱|감소/.test(s) ? 'warn'
    : /✅|🎉|달성|양호|순항|정상|증가|적정/.test(s) ? 'ok' : 'none';
  const clean = (s) => String(s ?? '').replace(/^[^0-9A-Za-z가-힣+\-]+/u, '').replace(/^-\s*/, '').trim();
  const monthLabel = (m) => (m.slice(5) === '01' ? m.slice(2, 4) + '년 ' : '') + Number(m.slice(5)) + '월';
  const monthTitle = (m) => `${m.slice(0, 4)}년 ${Number(m.slice(5))}월`;
  const shiftMonth = (m, k) => { const t = Number(m.slice(0, 4)) * 12 + Number(m.slice(5)) - 1 + k; return `${Math.floor(t / 12)}-${String(t % 12 + 1).padStart(2, '0')}`; };

  /** DOM 생성: h('div', {class: 'x', onclick: fn}, '글자', 자식…). 글자는 항상 textContent로 넣는다. */
  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
      else if (k === 'class') el.className = v;
      else if (k === 'style') Object.assign(el.style, v);
      else if (k in el && k !== 'list' && typeof v !== 'string') el[k] = v;
      else el.setAttribute(k, v === true ? '' : v);
    }
    for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid instanceof Node ? kid : String(kid));
    return el;
  }
  const pill = (status) => h('span', { class: 'pill', 'data-tone': tone(status) }, clean(status));

  function toast(msg) {
    const t = document.getElementById('toast');
    t.textContent = msg; t.hidden = false;
    clearTimeout(toast.timer); toast.timer = setTimeout(() => { t.hidden = true; }, 2600);
  }

  async function api(path, opts = {}) {
    const isForm = opts.body instanceof FormData;
    const res = await fetch(path, {
      method: opts.method || (opts.body ? 'POST' : 'GET'), credentials: 'same-origin',
      headers: opts.body && !isForm ? { 'Content-Type': 'application/json' } : {},
      body: opts.body ? (isForm ? opts.body : JSON.stringify(opts.body)) : undefined,
    });
    const data = (res.headers.get('content-type') || '').includes('json') ? await res.json() : null;
    if (res.status === 401 && !opts.allow401) { state.me = null; renderLogin(); throw new Error('로그인이 필요합니다.'); }
    if (!res.ok) {
      const d = data && data.detail;
      throw new Error(typeof d === 'string' ? d : Array.isArray(d) ? d.map((x) => x.msg).join(', ') : `요청 실패 (${res.status})`);
    }
    return data;
  }

  const state = { me: null, meta: null, view: '전체', month: null, route: 'dashboard' };

  // ---------------------------------------------------------------- 차트 (SVG)
  const SVG = 'http://www.w3.org/2000/svg';
  const s = (tag, attrs = {}) => { const el = document.createElementNS(SVG, tag); for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v); return el; };
  const scale = (d0, d1, r0, r1) => (v) => (d1 === d0 ? (r0 + r1) / 2 : r0 + (v - d0) / (d1 - d0) * (r1 - r0));
  function ticks(min, max, count = 4) {
    const span = (max - min) || Math.abs(max) || 1, raw = span / count, mag = 10 ** Math.floor(Math.log10(raw)), e = raw / mag;
    const step = (e >= 7.5 ? 10 : e >= 3.5 ? 5 : e >= 1.5 ? 2 : 1) * mag;
    const out = []; for (let v = Math.floor(min / step) * step; v <= Math.ceil(max / step) * step + step / 2; v += step) out.push(Math.round(v / step) * step);
    return out;
  }
  function frame(box, label) {
    box.replaceChildren();
    const W = Math.max(280, box.clientWidth || 600), H = 240;
    const svg = s('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': label });
    box.append(svg);
    const measure = (texts) => Math.max(0, ...texts.map((t) => { const n = s('text'); n.textContent = t; svg.append(n); const w = n.getComputedTextLength(); n.remove(); return w; }));
    return { svg, W, H, measure };
  }
  function yAxis(svg, tks, y, x0, x1) {
    for (const t of tks) {
      svg.append(s('line', { x1: x0, x2: x1, y1: y(t), y2: y(t), stroke: 'var(--grid)' }));
      const n = s('text', { x: x0 - 6, y: y(t) + 4, 'text-anchor': 'end' }); n.textContent = short(t); svg.append(n);
    }
  }
  function tipper(box) {
    const t = h('div', { class: 'tip', hidden: true }); box.append(t);
    return {
      show(ev, head, lines) {
        t.replaceChildren(h('div', { class: 'h' }, head), ...lines.map(([c, n, v]) => h('div', { class: 'r' }, h('i', { style: { background: c || 'transparent' } }), h('span', null, n), h('b', null, v))));
        t.hidden = false;
        const r = box.getBoundingClientRect(), x = ev.clientX - r.left, y = ev.clientY - r.top;
        t.style.left = Math.max(0, Math.min(r.width - t.offsetWidth, x + 12)) + 'px';
        t.style.top = Math.max(0, y - t.offsetHeight - 8) + 'px';
      },
      hide() { t.hidden = true; },
    };
  }
  function xLabels(svg, items, xOf, H, minGap) {
    const every = items.length > 1 && (xOf(items[1]) - xOf(items[0])) < minGap ? 2 : 1;
    items.forEach((it, i) => { if ((items.length - 1 - i) % every) return; const n = s('text', { x: xOf(it), y: H - 6, 'text-anchor': 'middle' }); n.textContent = monthLabel(it.month); svg.append(n); });
  }

  function groupedBars(box, rows, series) {
    const { svg, W, H, measure } = frame(box, series.map((x) => x.name).join(', '));
    const mb = 24, mt = 8, max = Math.max(1, ...rows.flatMap((r) => series.map((x) => r[x.key])));
    const tks = ticks(0, max); const y = scale(0, tks[tks.length - 1], H - mb, mt);
    const ml = measure(tks.map(short)) + 8, step = (W - ml) / rows.length, bw = step * 0.78, gw = bw / series.length;
    yAxis(svg, tks, y, ml, W);
    const xc = (r) => ml + rows.indexOf(r) * step + step / 2;
    xLabels(svg, rows, xc, H, 42);
    rows.forEach((r, i) => series.forEach((x, j) => {
      const v = r[x.key]; svg.append(s('rect', { x: ml + i * step + (step - bw) / 2 + j * gw + 1, width: Math.max(1, gw - 2), y: y(v), height: Math.max(0, y(0) - y(v)), rx: 2, fill: x.color }));
    }));
    svg.append(s('line', { x1: ml, x2: W, y1: y(0), y2: y(0), stroke: 'var(--axis)' }));
    const tip = tipper(box);
    rows.forEach((r, i) => {
      const hit = s('rect', { x: ml + i * step, width: step, y: mt, height: H - mb - mt, fill: 'transparent' });
      hit.addEventListener('mousemove', (ev) => tip.show(ev, r.month, [...series.map((x) => [x.color, x.name, short(r[x.key]) + '원']),
        ...(r.saving_rate != null ? [[null, '저축률', pct(r.saving_rate)]] : [])]));
      hit.addEventListener('mouseleave', () => tip.hide());
      svg.append(hit);
    });
  }

  function lineChart(box, rows, series) {
    const { svg, W, H, measure } = frame(box, series.map((x) => x.name).join(', '));
    const mb = 24, mt = 14, vals = rows.flatMap((r) => series.map((x) => r[x.key]));
    const tks = ticks(Math.min(0, ...vals), Math.max(1, ...vals)); const y = scale(tks[0], tks[tks.length - 1], H - mb, mt);
    const ml = measure(tks.map(short)) + 8, last = rows[rows.length - 1];
    const ends = series.map((x) => ({ ...x, text: `${x.name} ${short(last[x.key])}`, y: y(last[x.key]) })).sort((a, b) => a.y - b.y);
    for (let i = 1; i < ends.length; i++) if (ends[i].y - ends[i - 1].y < 14) ends[i].y = ends[i - 1].y + 14;
    const mr = measure(ends.map((e) => e.text)) + 14;
    const x = scale(0, rows.length - 1, ml, W - mr);
    yAxis(svg, tks, y, ml, W - mr);
    xLabels(svg, rows, (r) => x(rows.indexOf(r)), H, 42);
    for (const sr of series) {
      svg.append(s('path', { d: rows.map((r, i) => `${i ? 'L' : 'M'}${x(i)},${y(r[sr.key])}`).join(''), fill: 'none', stroke: sr.color, 'stroke-width': 2, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }));
      svg.append(s('circle', { cx: x(rows.length - 1), cy: y(last[sr.key]), r: 3.5, fill: sr.color }));
    }
    for (const e of ends) { const n = s('text', { x: W - mr + 8, y: e.y + 4, style: `fill:${e.color};font-weight:500` }); n.textContent = e.text; svg.append(n); }
    const tip = tipper(box), rule = s('line', { y1: mt, y2: H - mb, stroke: 'var(--axis)', visibility: 'hidden' }); svg.append(rule);
    const hit = s('rect', { x: ml, y: mt, width: W - mr - ml, height: H - mb - mt, fill: 'transparent' });
    hit.addEventListener('mousemove', (ev) => {
      const r = svg.getBoundingClientRect(), px = (ev.clientX - r.left) * W / r.width;
      const i = Math.max(0, Math.min(rows.length - 1, Math.round((px - ml) / ((W - mr - ml) / Math.max(1, rows.length - 1)))));
      rule.setAttribute('x1', x(i)); rule.setAttribute('x2', x(i)); rule.setAttribute('visibility', 'visible');
      tip.show(ev, rows[i].month, [...series.map((sr) => [sr.color, sr.name, short(rows[i][sr.key]) + '원']), [null, '총부채', short(rows[i].debt) + '원']]);
    });
    hit.addEventListener('mouseleave', () => { tip.hide(); rule.setAttribute('visibility', 'hidden'); });
    svg.append(hit);
  }

  function cashChart(box, rows, minCash) {
    const { svg, W, H, measure } = frame(box, '향후 6개월 예상 잔고');
    const mb = 24, mt = 18, vals = rows.map((r) => r.balance);
    const tks = ticks(Math.min(0, ...vals), Math.max(minCash, ...vals)); const y = scale(tks[0], tks[tks.length - 1], H - mb, mt);
    const ml = measure(tks.map(short)) + 8, step = (W - ml) / rows.length, bw = Math.min(32, step * 0.6);
    yAxis(svg, tks, y, ml, W);
    const xc = (r) => ml + rows.indexOf(r) * step + step / 2;
    xLabels(svg, rows, xc, H, 0);
    const tip = tipper(box);
    rows.forEach((r) => {
      const top = Math.min(y(r.balance), y(0));
      svg.append(s('rect', { x: xc(r) - bw / 2, width: bw, y: top, height: Math.abs(y(0) - y(r.balance)), rx: 4, fill: r.balance < minCash ? 'var(--bad)' : 'var(--s1)' }));
      const n = s('text', { x: xc(r), y: y(Math.max(0, r.balance)) - 5, 'text-anchor': 'middle', style: 'fill:var(--fg)' }); n.textContent = short(r.balance); svg.append(n);
      const hit = s('rect', { x: xc(r) - step / 2, width: step, y: mt, height: H - mb - mt, fill: 'transparent' });
      hit.addEventListener('mousemove', (ev) => tip.show(ev, r.month, [[null, '예상 잔고', won(r.balance) + '원'], [null, '순현금흐름', (r.net >= 0 ? '+' : '') + won(r.net) + '원'], [null, '일정 유입/유출', `${short(r.event_in)} / ${short(r.event_out)}`]]));
      hit.addEventListener('mouseleave', () => tip.hide());
      svg.append(hit);
    });
    svg.append(s('line', { x1: ml, x2: W, y1: y(minCash), y2: y(minCash), stroke: 'var(--axis)', 'stroke-dasharray': '4 3' }));
    svg.append(s('line', { x1: ml, x2: W, y1: y(0), y2: y(0), stroke: 'var(--axis)' }));
  }

  function hbar(label, ratioV, markAt, color, valueNodes, band) {
    const scaleMax = Math.max(1, ratioV, markAt);
    const track = h('div', { class: 'track' });
    if (band) track.append(h('div', { class: 'band', style: { left: band[0] / scaleMax * 100 + '%', width: (band[1] - band[0]) / scaleMax * 100 + '%' } }));
    track.append(h('div', { class: 'fill', style: { width: Math.min(ratioV, scaleMax) / scaleMax * 100 + '%', background: color } }),
      h('div', { class: 'mark', style: { left: `calc(${markAt / scaleMax * 100}% - 1px)` } }));
    return h('div', { class: 'brow' }, h('span', { title: label }, label), track, h('span', { class: 'bval' }, ...valueNodes));
  }

  // ---------------------------------------------------------------- 공통 화면 틀
  const ROUTES = [['dashboard', '대시보드'], ['transactions', '거래내역'], ['import', '내역 가져오기'], ['close', '월말 결산'], ['plan', '자산·계획'], ['budget', '예산'], ['report', '결산 리포트'], ['settings', '설정']];

  function shell(content) {
    const nav = h('nav', { class: 'nav', 'aria-label': '메뉴' }, ROUTES.map(([id, name]) => h('a', { href: `#/${id}`, 'aria-current': state.route === id ? 'page' : null }, name)));
    const who = h('div', { class: 'who' }, `${state.me.username} (${state.me.member})`,
      h('button', { class: 'btn small', onclick: async () => { await api('/api/logout', { method: 'POST' }); state.me = null; renderLogin(); } }, '로그아웃'));
    $app.replaceChildren(h('header', { class: 'bar' }, h('span', { class: 'brand' }, '우리집 주식회사'), nav, who), h('main', null, content));
  }

  function viewSwitch(onChange) {
    return h('div', { class: 'seg', role: 'group', 'aria-label': '구성원 보기' }, state.meta.views.map((v) =>
      h('button', { type: 'button', 'aria-pressed': String(state.view === v), onclick: () => { state.view = v; onChange(); } }, v)));
  }
  function monthSelect(onChange) {
    return h('select', { 'aria-label': '기준월', onchange: (e) => { state.month = e.target.value; onChange(); } },
      [...state.meta.months].reverse().map((m) => h('option', { value: m, selected: m === state.month }, monthTitle(m))));
  }
  function categorySelect(value, onchange, { includeBlank = false } = {}) {
    const groups = {};
    for (const c of state.meta.categories) (groups[c.group] ||= []).push(c.name);
    return h('select', { onchange, 'aria-label': '카테고리' },
      includeBlank ? h('option', { value: '' }, '전체 카테고리') : null,
      h('option', { value: '미분류', selected: value === '미분류' }, '미분류'),
      Object.entries(groups).map(([g, names]) => h('optgroup', { label: g }, names.map((n) => h('option', { value: n, selected: n === value }, n)))));
  }
  const memberSelect = (value, onchange, withAll = false) => h('select', { onchange, 'aria-label': '구성원' },
    withAll ? h('option', { value: '' }, '모든 구성원') : null, state.meta.owners.map((m) => h('option', { value: m, selected: m === value }, m)));

  // ---------------------------------------------------------------- 대시보드
  const KPI_TAGS = { net: '재무 건전성', saving: '지출 통제', budget: '지출 통제', invest_paid: '투자 확대', invest_assets: '투자 확대', emergency: '지출 통제', debt_ratio: '재무 건전성', dsr: '재무 건전성', goals: '목표', fi: '투자 확대' };
  const KPI_ORDER = ['net', 'saving', 'budget', 'invest_paid', 'invest_assets', 'emergency', 'debt_ratio', 'dsr', 'goals', 'fi'];

  async function renderDashboard() {
    const body = h('div', { class: 'section' }, h('p', { class: 'muted' }, '불러오는 중…'));
    const head = h('div', { class: 'head' }, h('div', null, h('p', { class: 'eyebrow' }, `${monthTitle(state.month)} 월간 결산`), h('h1', null, '우리집 주식회사'), h('p', { class: 'take', id: 'take' }, ' ')),
      h('div', { class: 'row' }, monthSelect(renderDashboard), viewSwitch(renderDashboard)));
    shell([head, body]);
    let d;
    try { d = await api(`/api/dashboard?view=${encodeURIComponent(state.view)}&month=${state.month}`); }
    catch (e) { body.replaceChildren(h('div', { class: 'fail' }, e.message)); return; }

    const alerts = d.alerts;
    const urgent = alerts.filter((a) => tone(a) === 'bad').length;
    document.getElementById('take').textContent = alerts.length
      ? `${state.view} 기준 알림 ${alerts.length}건${urgent ? `, 그중 ${urgent}건은 즉시 조치` : ''}. 가장 먼저 볼 것: ${clean(alerts[0])}.`
      : `${state.view} 기준 이번 달 알림이 없습니다.`;

    const cards = Object.fromEntries(d.cards.map((c) => [c.kpi, c]));
    const kpis = h('div', { class: 'kpis' }, KPI_ORDER.map((k) => {
      const c = cards[k];
      const v = c.value == null ? '—' : c.format === 'won' ? short(c.value) : c.format === 'months' ? c.value.toFixed(1) + '개월' : pct(c.value);
      return h('article', { class: 'kpi' }, h('span', { class: 'tag' }, KPI_TAGS[k]), h('span', { class: 'label' }, c.label.replace(' (이번 달)', '').replace(' (가중)', '')),
        h('span', { class: 'value' }, v), h('span', { class: 'note' }, c.note), pill(c.status));
    }));

    const alertCard = h('article', { class: 'card' }, h('h3', null, '이번 달 알림'), h('p', { class: 'sub' }, '예산·저축·투자·비상자금·일정·목표·보험 자동 점검'),
      h('ul', { class: 'alerts' }, (alerts.length ? alerts : ['✅ 이상 없음, 이번 달도 잘 운영되었습니다']).map((a) => h('li', { 'data-tone': tone(a) }, clean(a)))));
    const members = d.balance.members;
    const memberCard = h('article', { class: 'card' }, h('h3', null, '구성원별 순자산'), h('p', { class: 'sub' }, `${monthTitle(d.base_month)} 말 잔액 · 보기 선택과 관계없이 모두 표시`),
      h('div', { class: 'table-wrap' }, h('table', null, h('thead', null, h('tr', null, h('th', null, '구성원'), h('th', { class: 'num' }, '자산'), h('th', { class: 'num' }, '부채'), h('th', { class: 'num' }, '순자산'), h('th', { class: 'num narrow-hide' }, '투자+연금'))),
        h('tbody', null, members.map((m) => h('tr', null, h('td', null, m.member), h('td', { class: 'num' }, short(m.assets)), h('td', { class: 'num' }, m.debt ? short(m.debt) : '-'), h('td', { class: 'num' }, short(m.net)), h('td', { class: 'num narrow-hide' }, short(m.invest))))))));

    // 지출 통제
    const pnlRows = d.pnl.months.map((m, i) => ({ month: m, income: d.pnl.rows.income[i], consumption: d.pnl.rows.consumption[i], invest: d.pnl.rows.invest[i], saving_rate: state.view === '공동' ? null : d.pnl.rows.saving_rate[i] }));
    const series = [{ key: 'income', name: '소득', color: 'var(--s1)' }, { key: 'consumption', name: '소비지출', color: 'var(--s2)' }, { key: 'invest', name: '투자 납입', color: 'var(--s3)' }];
    const monthlyBox = h('div', { class: 'chart' });
    const monthlyCard = h('article', { class: 'card' }, h('h3', null, '월별 소득 · 소비 · 투자 납입'), h('p', { class: 'sub' }, '최근 12개월 · 저축·투자·원금상환은 소비에서 제외'),
      h('div', { class: 'legend' }, series.map((x) => h('span', null, h('i', { style: { background: x.color } }), x.name))), monthlyBox);
    const budgetBox = h('div', { class: 'bars' });
    for (const [basis, title] of [['월', '월 예산 (고정비·변동비)'], ['연', `연 예산 누계 (비정기비, ${Number(d.base_month.slice(5))}/12 경과분)`]]) {
      const rows = d.budget.rows.filter((r) => r.basis === basis && r.period_budget > 0).sort((a, b) => b.actual / b.period_budget - a.actual / a.period_budget);
      if (!rows.length) continue;
      budgetBox.append(h('h4', null, title));
      for (const r of rows) {
        const ratioV = r.actual / r.period_budget, t = tone(r.status);
        budgetBox.append(hbar(r.category, ratioV, 1, t === 'bad' ? 'var(--bad)' : t === 'warn' ? 'var(--warn)' : 'var(--s1)',
          [h('b', null, pct(ratioV, 0)), ` · ${short(r.actual)} / ${short(r.period_budget)}`]));
      }
    }
    const budgetCard = h('article', { class: 'card' }, h('h3', null, '예산 대비 실적'),
      h('p', { class: 'sub' }, state.view === '전체' ? '집행률이 높은 순 · 검은 선이 예산' : `가계 예산 대비 ${state.view} 사용분`),
      budgetBox.childNodes.length ? budgetBox : h('p', { class: 'empty' }, '예산이 없습니다. 예산 메뉴에서 정하세요.'));

    // 투자 확대
    const trendBox = h('div', { class: 'chart' });
    const trendCard = h('article', { class: 'card' }, h('h3', null, '순자산과 투자+연금 자산'), h('p', { class: 'sub' }, '월말 잔액 기준 · 최근 12개월'), trendBox);
    const band = d.invest.allocation.length ? state.meta.settings.band : 0.05;
    const top = Math.max(0.6, ...d.invest.allocation.map((a) => Math.max(a.current, a.target + band))) * 1.1;
    const allocBox = h('div', { class: 'bars' }, d.invest.total_value ? d.invest.allocation.map((a) => {
      const gap = a.current - a.target;
      return hbar(a.asset_class, a.current / top, a.target / top, tone(a.status) === 'warn' && state.view === '전체' ? 'var(--warn)' : 'var(--s3)',
        [h('b', null, pct(a.current)), ` · 목표 ${pct(a.target, 0)} (${gap >= 0 ? '+' : ''}${(gap * 100).toFixed(1)}%p)`], [(a.target - band) / top, (a.target + band) / top]);
    }) : h('p', { class: 'empty' }, '보유 종목이 없습니다.'));
    const c = d.invest.contribution;
    const allocCard = h('article', { class: 'card' }, h('h3', null, '자산배분: 목표 vs 현재'),
      h('p', { class: 'sub' }, `막대가 현재 비중, 검은 선이 목표, 회색 띠가 허용 범위(±${Math.round(band * 100)}%p) · 이번 달 납입 ${short(c.month)} / 목표 ${short(c.target)}`), allocBox);

    // 목표·현금흐름
    const goalCard = h('article', { class: 'card' }, h('h3', null, '재무 목표 진척'), h('p', { class: 'sub' }, '막대가 진척률, 검은 선이 오늘 기준 계획 진척률'),
      h('div', { class: 'table-wrap' }, h('table', { class: 'nowrap' }, h('thead', null, h('tr', null, h('th', null, '목표'), h('th', { class: 'narrow-hide' }, '담당'), h('th', null, '진척률'), h('th', null, '상태'), h('th', { class: 'num' }, '필요 월적립'), h('th', { class: 'narrow-hide' }, '목표일'))),
        h('tbody', null, d.goals.rows.map((g) => {
          const track = h('div', { class: 'track' }, h('div', { class: 'fill', style: { width: Math.min(100, (g.progress || 0) * 100) + '%', background: tone(g.status) === 'warn' ? 'var(--warn)' : 'var(--s1)' } }),
            h('div', { class: 'mark', style: { left: `calc(${Math.min(100, (g.plan || 0) * 100)}% - 1px)` } }));
          return h('tr', null, h('td', null, g.name), h('td', { class: 'narrow-hide' }, g.owner), h('td', null, h('span', { class: 'prog' }, track, pct(g.progress, 0))), h('td', null, pill(g.status)),
            h('td', { class: 'num' }, g.monthly_needed == null ? '-' : short(g.monthly_needed) + '원'), h('td', { class: 'narrow-hide' }, (g.end || '').slice(0, 7)));
        })))));
    const cashBox = h('div', { class: 'chart' });
    const cashCard = h('article', { class: 'card' }, h('h3', null, '향후 6개월 예상 잔고'), h('p', { class: 'sub' }, `정기 유입·유출 평균 + 일정 반영 · 점선이 최소 유지잔고 ${short(d.cashflow.min_cash)}`), cashBox);

    body.replaceChildren(
      h('section', { class: 'section', id: 'kpi' }, h('h2', null, '핵심 지표'), kpis),
      h('section', { class: 'grid' }, alertCard, memberCard),
      h('section', { class: 'section', id: 'spend' }, h('h2', null, '지출 통제'), h('div', { class: 'grid' }, monthlyCard, budgetCard)),
      h('section', { class: 'section', id: 'invest' }, h('h2', null, '투자 확대'), h('div', { class: 'grid' }, trendCard, allocCard)),
      h('section', { class: 'section', id: 'goals' }, h('h2', null, '목표 · 현금흐름'), h('div', { class: 'grid' }, goalCard, cashCard)));
    const draw = () => {
      groupedBars(monthlyBox, pnlRows, series);
      lineChart(trendBox, d.balance.trend, [{ key: 'net', name: '순자산', color: 'var(--s1)' }, { key: 'invest', name: '투자+연금', color: 'var(--s3)' }]);
      cashChart(cashBox, d.cashflow.rows, d.cashflow.min_cash);
    };
    draw();
    window.onresize = () => { clearTimeout(draw.t); draw.t = setTimeout(() => state.route === 'dashboard' && draw(), 150); };
  }

  // ---------------------------------------------------------------- 거래내역
  const txFilter = { month: null, category: '', member: '', q: '' };

  async function renderTransactions() {
    txFilter.month ??= state.month;
    const list = h('div', { class: 'card' }, h('p', { class: 'muted' }, '불러오는 중…'));
    const filters = h('div', { class: 'row' },
      h('select', { 'aria-label': '월', onchange: (e) => { txFilter.month = e.target.value; load(); } },
        h('option', { value: '' }, '모든 달'), [...state.meta.months].reverse().map((m) => h('option', { value: m, selected: m === txFilter.month }, monthTitle(m)))),
      categorySelect(txFilter.category, (e) => { txFilter.category = e.target.value; load(); }, { includeBlank: true }),
      memberSelect(txFilter.member, (e) => { txFilter.member = e.target.value; load(); }, true),
      h('input', { type: 'text', placeholder: '내용 검색', value: txFilter.q, 'aria-label': '내용 검색', oninput: (e) => { txFilter.q = e.target.value; clearTimeout(load.t); load.t = setTimeout(load, 250); } }),
      h('button', { class: 'btn', onclick: () => { txFilter.category = '미분류'; renderTransactions(); } }, '미분류만 보기'));
    shell([h('div', { class: 'head' }, h('div', null, h('p', { class: 'eyebrow' }, '분개장'), h('h1', null, '거래내역'),
      h('p', { class: 'take' }, '카테고리를 바꾸면 바로 저장됩니다. 같은 가게가 자주 나오면 "규칙 저장"을 눌러 다음부터 자동 분류되게 하세요.'))), addForm(load), filters, list]);

    async function load() {
      const qs = new URLSearchParams(Object.entries(txFilter).filter(([, v]) => v));
      let rows;
      try { rows = await api('/api/transactions?' + qs); } catch (e) { list.replaceChildren(h('div', { class: 'fail' }, e.message)); return; }
      const sum = (g) => rows.filter((r) => g.includes(r.group)).reduce((a, r) => a + r.amount, 0);
      const unc = rows.filter((r) => r.category === '미분류' || r.group === '미분류').length;
      const summary = h('p', { class: 'sub' }, `${nf.format(rows.length)}건 · 소득 ${won(sum(['소득']))}원 · 소비 ${won(sum(['고정비', '변동비', '비정기비']))}원 · 자본이동 ${won(sum(['자본이동']))}원` + (unc ? ` · 미분류 ${unc}건` : ''));
      const tbody = h('tbody', null, rows.slice().reverse().map((t) => txRow(t)));
      list.replaceChildren(summary, rows.length ? h('div', { class: 'table-wrap scroll' }, h('table', null,
        h('thead', null, h('tr', null, h('th', null, '일자'), h('th', null, '내용'), h('th', { class: 'num' }, '금액'), h('th', null, '카테고리'), h('th', null, '구성원'), h('th', { class: 'narrow-hide' }, '결제수단'), h('th', null, ''))), tbody))
        : h('p', { class: 'empty' }, '조건에 맞는 거래가 없습니다.'));
    }

    function txRow(t) {
      const actions = h('td', { class: 'num' });
      const ruleBtn = h('button', { class: 'btn small', hidden: true, onclick: () => {
        const kw = h('input', { type: 'text', value: t.desc, 'aria-label': '규칙 키워드', style: { width: '140px' } });
        actions.replaceChildren(kw, h('button', { class: 'btn small primary', onclick: async () => {
          try { const r = await api('/api/rules', { body: { keyword: kw.value, category: t.category } }); toast(`규칙 저장 · 미분류 ${r.reclassified}건 자동 분류`); load(); } catch (e) { toast(e.message); }
        } }, '저장'));
      } }, '규칙 저장');
      const del = h('button', { class: 'btn small danger', onclick: async () => {
        if (del.dataset.confirm !== '1') { del.dataset.confirm = '1'; del.textContent = '한 번 더 눌러 삭제'; return; }
        try { await api(`/api/transactions/${t.id}`, { method: 'DELETE' }); toast('삭제했습니다'); load(); } catch (e) { toast(e.message); }
      } }, '삭제');
      actions.append(ruleBtn, ' ', del);
      const patch = async (fields) => { try { await api(`/api/transactions/${t.id}`, { method: 'PATCH', body: fields }); Object.assign(t, fields); toast('저장했습니다'); return true; } catch (e) { toast(e.message); return false; } };
      return h('tr', null, h('td', null, t.day), h('td', null, t.desc, t.memo ? h('span', { class: 'muted' }, ` · ${t.memo}`) : null), h('td', { class: 'num' }, won(t.amount)),
        h('td', null, categorySelect(t.category || '미분류', async (e) => { if (await patch({ category: e.target.value })) ruleBtn.hidden = e.target.value === '미분류'; else e.target.value = t.category || '미분류'; })),
        h('td', null, memberSelect(t.member, async (e) => { if (!(await patch({ member: e.target.value }))) e.target.value = t.member; })), h('td', { class: 'narrow-hide muted' }, t.payment), actions);
    }
    load();
  }

  function addForm(after) {
    const f = { day: new Date().toISOString().slice(0, 10), desc: '', amount: '', category: '식비', member: state.me.member, payment: '현금' };
    const set = (k) => (e) => { f[k] = e.target.value; };
    return h('details', { class: 'card' }, h('summary', null, '거래 직접 입력 (현금 지출 등)'),
      h('div', { class: 'form' },
        h('label', { class: 'field' }, '일자', h('input', { type: 'date', value: f.day, onchange: set('day') })),
        h('label', { class: 'field' }, '내용', h('input', { type: 'text', oninput: set('desc') })),
        h('label', { class: 'field' }, '금액(원)', h('input', { type: 'number', min: 1, oninput: set('amount') })),
        h('label', { class: 'field' }, '카테고리', categorySelect(f.category, set('category'))),
        h('label', { class: 'field' }, '구성원', memberSelect(f.member, set('member'))),
        h('label', { class: 'field' }, '결제수단', h('input', { type: 'text', value: f.payment, oninput: set('payment') })),
        h('button', { class: 'btn primary', onclick: async () => {
          try { await api('/api/transactions', { body: { ...f, amount: Number(f.amount) } }); toast('추가했습니다'); after(); } catch (e) { toast(e.message); }
        } }, '추가')));
  }

  // ---------------------------------------------------------------- 내역 가져오기
  function renderImport() {
    const file = h('input', { type: 'file', accept: '.csv,.xlsx', 'aria-label': '내역 파일' });
    const member = memberSelect(state.me.member, null);
    const payment = h('input', { type: 'text', placeholder: '예: 신한카드', 'aria-label': '결제수단' });
    const result = h('div');
    const send = async (dry) => {
      if (!file.files[0]) { toast('파일을 고르세요'); return; }
      const fd = new FormData(); fd.append('file', file.files[0]); fd.append('member', member.value); fd.append('payment', payment.value); fd.append('dry_run', dry ? 'true' : 'false');
      try {
        const r = await api('/api/import/statement', { body: fd });
        result.replaceChildren(h('div', null, h('p', null, `${dry ? '추가 예정' : '추가'} ${r.added.length}건 · 중복 제외 ${r.duplicates}건 · 건너뜀 ${r.skipped.length}건` + (r.uncategorized ? ` · 미분류 ${r.uncategorized}건 (거래내역에서 지정)` : '')),
          r.added.length ? h('div', { class: 'table-wrap scroll' }, h('table', null, h('thead', null, h('tr', null, h('th', null, '일자'), h('th', null, '내용'), h('th', { class: 'num' }, '금액'), h('th', null, '분류'))),
            h('tbody', null, r.added.map((t) => h('tr', null, h('td', null, t.day), h('td', null, t.desc), h('td', { class: 'num' }, won(t.amount)), h('td', null, t.category === '미분류' ? pill('⚠ 미분류') : t.category)))))) : null,
          r.skipped.length ? h('details', null, h('summary', null, '건너뛴 행 보기'), h('ul', null, r.skipped.map((x) => h('li', { class: 'muted' }, x)))) : null));
        if (!dry) { toast('가져왔습니다'); state.meta = await api('/api/meta'); }
      } catch (e) { result.replaceChildren(h('p', { class: 'error' }, e.message)); }
    };
    const wbFile = h('input', { type: 'file', accept: '.xlsx', 'aria-label': '엑셀 파일' });
    const confirm = h('input', { type: 'checkbox', id: 'wb-confirm' });
    const wbResult = h('p', { class: 'sub' });
    shell([h('div', { class: 'head' }, h('div', null, h('p', { class: 'eyebrow' }, '자동화'), h('h1', null, '내역 가져오기'),
      h('p', { class: 'take' }, '카드사·은행에서 받은 내역을 CSV나 엑셀(.xlsx)로 저장해 올리세요. 분류규칙으로 자동 분류하고, 이미 있는 거래는 건너뜁니다.'))),
      h('section', { class: 'card' }, h('h3', null, '카드·은행 내역'),
        h('div', { class: 'form' }, h('label', { class: 'field' }, '파일 (.csv, .xlsx)', file), h('label', { class: 'field' }, '이 내역의 구성원', member), h('label', { class: 'field' }, '결제수단', payment),
          h('div', { class: 'row' }, h('button', { class: 'btn', onclick: () => send(true) }, '미리보기'), h('button', { class: 'btn primary', onclick: () => send(false) }, '가져오기'))),
        h('p', { class: 'sub' }, '국내 금융사 파일(cp949 인코딩, 머리말·합계 행, 입금/출금 분리 열)을 자동으로 처리합니다. 취소·환불(음수 금액)은 건너뜁니다.'), result),
      h('section', { class: 'card' }, h('h3', null, '엑셀 파일과 주고받기'),
        h('p', { class: 'sub' }, '1단계 스프레드시트(우리집_자산관리_*.xlsx)를 올리면 가계 데이터를 그 파일 내용으로 바꿉니다. 로그인 계정은 그대로입니다.'),
        h('div', { class: 'row' }, wbFile, h('label', { for: 'wb-confirm', class: 'row' }, confirm, '지금 데이터를 모두 바꾸는 것을 확인했습니다'),
          h('button', { class: 'btn', onclick: async () => {
            if (!wbFile.files[0]) { toast('엑셀 파일을 고르세요'); return; }
            if (!confirm.checked) { toast('확인란을 체크하세요'); return; }
            const fd = new FormData(); fd.append('file', wbFile.files[0]);
            try { const r = await api('/api/import/workbook', { body: fd }); wbResult.textContent = `가져왔습니다: 거래 ${nf.format(r.transactions)}건, 계좌 ${r.accounts}개, 기준월 ${r.base_month}`; state.meta = await api('/api/meta'); state.month = state.meta.base_month; }
            catch (e) { wbResult.textContent = e.message; }
          } }, '엑셀로 바꾸기')), wbResult,
        h('p', null, h('a', { class: 'btn', href: '/api/export.xlsx' }, '현재 데이터를 엑셀로 내려받기'), h('span', { class: 'sub' }, '  수식이 살아 있는 스프레드시트로 받아 구글 시트나 엑셀에서 계속 볼 수 있습니다.')))]);
  }

  // ---------------------------------------------------------------- 월말 결산
  async function renderClose() {
    const month = h('input', { type: 'month', value: shiftMonth(state.meta.base_month, 1), 'aria-label': '결산할 달' });
    const table = h('div', { class: 'card' }, h('p', { class: 'muted' }, '불러오는 중…'));
    const prices = h('div', { class: 'card' });
    shell([h('div', { class: 'head' }, h('div', null, h('p', { class: 'eyebrow' }, '월간 결산'), h('h1', null, '월말 결산'),
      h('p', { class: 'take' }, '달을 고르면 계좌별로 지난달 잔액이 채워져 있습니다. 바뀐 잔액만 고치고 저장하세요. 현재 기준월: ' + monthTitle(state.meta.base_month)))),
      h('div', { class: 'row' }, h('label', { class: 'field' }, '결산할 달', month), h('button', { class: 'btn', onclick: () => load() }, '불러오기')), table, prices]);

    async function load() {
      const m = month.value;
      let r;
      try { r = await api(`/api/snapshots/${m}`); } catch (e) { table.replaceChildren(h('div', { class: 'fail' }, e.message)); return; }
      const inputs = {};
      const rows = r.rows.map((a) => {
        const inp = h('input', { type: 'number', class: 'amount', value: a.amount ?? a.previous ?? 0, 'aria-label': `${a.name} 잔액` });
        inputs[a.id] = inp;
        return h('tr', null, h('td', null, a.name, h('span', { class: 'muted' }, ` · ${a.institution}`)), h('td', { class: 'narrow-hide' }, a.type), h('td', { class: 'narrow-hide' }, a.owner),
          h('td', { class: 'num muted' }, a.previous == null ? '-' : won(a.previous)), h('td', { class: 'num' }, inp), h('td', { class: 'muted' }, a.amount == null ? '새로 입력' : '저장됨'));
      });
      const values = () => Object.fromEntries(Object.entries(inputs).map(([k, v]) => [k, Math.round(Number(v.value) || 0)]));
      table.replaceChildren(h('h3', null, `${monthTitle(m)} 말 잔액`), h('p', { class: 'sub' }, '부채도 양수로 적습니다. 카드 결제예정액은 다음 달에 빠져나갈 금액입니다.'),
        r.rows.length ? h('div', { class: 'table-wrap' }, h('table', null, h('thead', null, h('tr', null, h('th', null, '계좌'), h('th', { class: 'narrow-hide' }, '유형'), h('th', { class: 'narrow-hide' }, '소유'), h('th', { class: 'num' }, `${monthTitle(r.previous_month)} 말`), h('th', { class: 'num' }, `${monthTitle(m)} 말`), h('th', null, ''))), h('tbody', null, rows)))
          : h('p', { class: 'empty' }, '등록된 계좌가 없습니다. 엑셀 파일의 [계좌] 시트에 등록한 뒤 가져오세요.'),
        h('div', { class: 'row' }, h('button', { class: 'btn', onclick: async () => { try { await api(`/api/snapshots/${m}`, { method: 'PUT', body: { amounts: values() } }); toast('잔액을 저장했습니다'); load(); } catch (e) { toast(e.message); } } }, '잔액만 저장'),
          h('button', { class: 'btn primary', onclick: async () => {
            try { await api(`/api/snapshots/${m}`, { method: 'PUT', body: { amounts: values() } }); await api('/api/close-month', { body: { month: m } }); state.meta = await api('/api/meta'); state.month = m; toast(`${monthTitle(m)} 결산을 마쳤습니다`); location.hash = '#/dashboard'; }
            catch (e) { toast(e.message); }
          } }, '저장하고 이 달을 기준월로')));
      // 보유 종목 현재가
      const d = await api(`/api/dashboard?month=${state.meta.base_month}`);
      const hs = d.invest.holdings;
      prices.replaceChildren(h('h3', null, '보유 종목 현재가'), h('p', { class: 'sub' }, '월말 종가를 넣으면 자산배분과 수익률이 다시 계산됩니다.'),
        hs.length ? h('div', { class: 'table-wrap' }, h('table', null, h('thead', null, h('tr', null, h('th', null, '종목'), h('th', { class: 'narrow-hide' }, '계좌'), h('th', { class: 'num' }, '수량'), h('th', { class: 'num' }, '현재가'), h('th', { class: 'num' }, '평가금액'), h('th', { class: 'num' }, '수익률'))),
          h('tbody', null, hs.map((x) => {
            const inp = h('input', { type: 'number', class: 'amount', value: x.price, 'aria-label': `${x.name} 현재가`, onchange: async (e) => { try { await api(`/api/holdings/${x.id}`, { method: 'PATCH', body: { price: Number(e.target.value) } }); toast('현재가를 저장했습니다'); } catch (err) { toast(err.message); } } });
            return h('tr', null, h('td', null, x.name), h('td', { class: 'narrow-hide muted' }, x.account), h('td', { class: 'num' }, nf.format(x.qty)), h('td', { class: 'num' }, inp), h('td', { class: 'num' }, won(x.value)), h('td', { class: 'num' }, pct(x.return)));
          })))) : h('p', { class: 'empty' }, '보유 종목이 없습니다.'));
    }
    load();
  }

  // ---------------------------------------------------------------- 예산
  async function renderBudget() {
    const box = h('div', { class: 'card' }, h('p', { class: 'muted' }, '불러오는 중…'));
    shell([h('div', { class: 'head' }, h('div', null, h('p', { class: 'eyebrow' }, '예산 통제'), h('h1', null, '예산'),
      h('p', { class: 'take' }, '고정비·변동비는 월 예산, 여행·명절·세금 같은 비정기비는 연 예산으로 정하면 지난 달수만큼 나눠 비교합니다. 부부가 함께 정하세요.'))), box]);
    const d = await api(`/api/dashboard?month=${state.month}`);
    const byCat = Object.fromEntries(d.budget.rows.map((r) => [r.category, r]));
    const cats = state.meta.categories.filter((c) => ['고정비', '변동비', '비정기비'].includes(c.group));
    box.replaceChildren(h('h3', null, `${monthTitle(d.base_month)} 기준`), h('div', { class: 'table-wrap' }, h('table', null,
      h('thead', null, h('tr', null, h('th', null, '카테고리'), h('th', { class: 'narrow-hide' }, '대분류'), h('th', null, '기준'), h('th', { class: 'num' }, '예산'), h('th', { class: 'num' }, '실적'), h('th', null, '상태'), h('th', null, ''))),
      h('tbody', null, cats.map((c) => {
        const r = byCat[c.name];
        const basis = h('select', { 'aria-label': `${c.name} 기준` }, ['월', '연'].map((b) => h('option', { value: b, selected: (r?.basis || (c.group === '비정기비' ? '연' : '월')) === b }, b)));
        const amount = h('input', { type: 'number', class: 'amount', min: 0, value: r?.budget ?? 0, 'aria-label': `${c.name} 예산` });
        return h('tr', null, h('td', null, c.name), h('td', { class: 'narrow-hide muted' }, c.group), h('td', null, basis), h('td', { class: 'num' }, amount),
          h('td', { class: 'num' }, r ? won(r.actual) : '-'), h('td', null, r ? pill(r.status) : ''),
          h('td', null, h('button', { class: 'btn small', onclick: async () => { try { await api(`/api/budgets/${encodeURIComponent(c.name)}`, { method: 'PUT', body: { basis: basis.value, amount: Math.round(Number(amount.value) || 0) } }); toast(`${c.name} 예산 저장`); } catch (e) { toast(e.message); } } }, '저장')));
      })))));
  }

  // ---------------------------------------------------------------- 설정
  async function renderSettings() {
    const st = state.meta.settings;
    const fields = [
      ['t_saving', '목표 저축률 (%)', 100], ['t_emergency', '비상자금 목표 (개월)', 1], ['t_debt', '부채비율 상한 (%)', 100], ['t_dsr', 'DSR 상한 (%)', 100],
      ['band', '리밸런싱 밴드 (%p)', 100], ['min_cash', '최소 유지잔고 (원)', 1], ['alert_days', '일정 알림 (며칠 전)', 1], ['goal_tol', '목표 지연 허용폭 (%p)', 100],
    ];
    const inputs = Object.fromEntries(fields.map(([k, , mul]) => [k, h('input', { type: 'number', step: 'any', value: +(st[k] * mul).toFixed(4) })]));
    const inv = Object.fromEntries(state.meta.owners.map((m) => [m, h('input', { type: 'number', class: 'amount', value: st.invest_targets[m] ?? 0, 'aria-label': `${m} 월 투자 목표` })]));
    const me = await api('/api/me');
    const nu = { username: h('input', { type: 'text', 'aria-label': '아이디' }), password: h('input', { type: 'password', 'aria-label': '비밀번호' }), member: h('select', { 'aria-label': '구성원' }, ['본인', '배우자'].map((m) => h('option', { value: m }, m))) };
    shell([h('div', { class: 'head' }, h('div', null, h('p', { class: 'eyebrow' }, '경영 목표'), h('h1', null, '설정'))),
      h('section', { class: 'card' }, h('h3', null, 'KPI 기준값'), h('div', { class: 'form' }, fields.map(([k, label]) => h('label', { class: 'field' }, label, inputs[k]))),
        h('h3', null, '구성원별 월 투자 납입 목표'), h('div', { class: 'form' }, state.meta.owners.map((m) => h('label', { class: 'field' }, m, inv[m]))),
        h('p', { class: 'sub' }, `가계 합계 ${won(Object.values(st.invest_targets).reduce((a, b) => a + b, 0))}원 · 각 구성원 보기에서 자기 몫과 비교합니다.`),
        h('div', null, h('button', { class: 'btn primary', onclick: async () => {
          const body = Object.fromEntries(fields.map(([k, , mul]) => [k, Number(inputs[k].value) / mul]));
          body.min_cash = Math.round(body.min_cash); body.alert_days = Math.round(body.alert_days);
          body.invest_targets = Object.fromEntries(Object.entries(inv).map(([m, i]) => [m, Math.round(Number(i.value) || 0)]));
          try { await api('/api/settings', { method: 'PUT', body }); state.meta = await api('/api/meta'); toast('설정을 저장했습니다'); renderSettings(); } catch (e) { toast(e.message); }
        } }, '저장'))),
      h('section', { class: 'card' }, h('h3', null, '로그인 계정'), h('ul', null, me.users.map((u) => h('li', null, `${u.username} · ${u.member}`))),
        h('p', { class: 'sub' }, '배우자 계정을 나중에 만들거나 비밀번호를 바꿀 때 씁니다 (같은 아이디면 비밀번호가 바뀝니다).'),
        h('div', { class: 'form' }, h('label', { class: 'field' }, '아이디', nu.username), h('label', { class: 'field' }, '비밀번호 (8자 이상)', nu.password), h('label', { class: 'field' }, '구성원', nu.member),
          h('button', { class: 'btn', onclick: async () => { try { await api('/api/users', { body: { username: nu.username.value, password: nu.password.value, member: nu.member.value } }); toast('계정을 저장했습니다'); renderSettings(); } catch (e) { toast(e.message); } } }, '계정 저장')))]);
  }

  // ---------------------------------------------------------------- 자산·계획 (계좌·보유종목·부채·목표·보험·일정 편집)
  const acctOptions = (types) => state.meta.accounts.filter((a) => !types || types.includes(a.type)).map((a) => [a.id, `${a.id} · ${a.name}`]);
  const ENTITY = {
    accounts: {
      title: '계좌', note: '가족의 모든 계좌·자산·부채. 월말 결산과 재무상태표가 이 목록을 씁니다. 계좌ID는 나중에 바꿀 수 없습니다.',
      key: 'id', label: (r) => r.name,
      fields: [
        { k: 'id', label: '계좌ID', type: 'text', lock: true, placeholder: '예: A07' },
        { k: 'name', label: '계좌명', type: 'text' },
        { k: 'institution', label: '기관', type: 'text' },
        { k: 'type', label: '유형', type: 'select', options: () => state.meta.account_types },
        { k: 'owner', label: '소유자', type: 'select', options: () => state.meta.owners },
        { k: 'liquidity', label: '유동성', type: 'select', options: () => state.meta.liquidity, hint: '즉시 = 오늘 꺼낼 수 있음' },
        { k: 'memo', label: '메모', type: 'text' },
      ],
    },
    holdings: {
      title: '보유종목', note: '수량·평균단가·현재가로 자산배분과 수익률을 계산합니다. 국내 상장 종목은 시세코드(KRX:005930)를 넣으면 자동 갱신됩니다.',
      key: 'id', label: (r) => r.name,
      fields: [
        { k: 'account_id', label: '계좌', type: 'select', options: () => acctOptions(['투자', '연금']) },
        { k: 'name', label: '종목명', type: 'text' },
        { k: 'code', label: '시세코드', type: 'text', placeholder: 'KRX:005930' },
        { k: 'asset_class', label: '자산군', type: 'select', options: () => state.meta.asset_classes },
        { k: 'qty', label: '수량', type: 'number' },
        { k: 'avg_price', label: '평균단가', type: 'money' },
        { k: 'price', label: '현재가', type: 'money' },
      ],
    },
    debts: {
      title: '부채', note: '잔액은 월말 결산의 잔액을 씁니다. 여기에는 금리·만기·월 원리금을 적습니다 (DSR·금리 상승 시뮬레이션에 사용).',
      key: 'id', label: (r) => r.name,
      fields: [
        { k: 'name', label: '대출명', type: 'text' },
        { k: 'account_id', label: '부채 계좌', type: 'select', options: () => acctOptions(['부채']) },
        { k: 'rate', label: '금리 (연 %)', type: 'pct' },
        { k: 'maturity', label: '만기일', type: 'date', optional: true },
        { k: 'method', label: '상환방식', type: 'text', placeholder: '원리금균등' },
        { k: 'payment', label: '월 원리금', type: 'money' },
      ],
    },
    goals: {
      title: '목표', note: '연결계좌의 잔액 합으로 진척률을 계산합니다. 목표금액을 비워 두면 비상자금처럼 "목표 개월수 × 필수지출"로 자동 계산합니다.',
      key: 'id', label: (r) => r.name,
      fields: [
        { k: 'name', label: '목표명', type: 'text' },
        { k: 'owner', label: '담당', type: 'select', options: () => state.meta.members },
        { k: 'target', label: '목표금액 (비우면 자동)', type: 'money', optional: true },
        { k: 'start', label: '시작일', type: 'date' },
        { k: 'end', label: '목표일', type: 'date' },
        { k: 'accounts', label: '연결계좌 (최대 3개)', type: 'accounts' },
      ],
    },
    insurances: {
      title: '보험', note: '보장금액을 넣으면 대시보드가 구성원별 보장 공백을 찾아냅니다. 0 또는 빈칸은 보장 없음입니다.',
      key: 'id', label: (r) => `${r.insured} · ${r.product}`,
      fields: [
        { k: 'insured', label: '피보험자', type: 'select', options: () => state.meta.members },
        { k: 'insurer', label: '보험사', type: 'text' },
        { k: 'product', label: '상품명', type: 'text' },
        { k: 'coverages', label: '보장금액', type: 'coverages' },
        { k: 'premium', label: '월보험료', type: 'money' },
        { k: 'maturity', label: '만기일', type: 'date', optional: true },
        { k: 'renewable', label: '갱신형', type: 'select', options: () => [['N', '아니오'], ['Y', '예']] },
      ],
    },
    events: {
      title: '일정', note: '만기·세금·명절·성과급 같은 큰 돈의 흐름. 유입·유출은 6개월 현금흐름 예측에, 가까운 일정은 대시보드 알림에 들어갑니다.',
      key: 'id', label: (r) => r.desc,
      fields: [
        { k: 'day', label: '일자', type: 'date' },
        { k: 'desc', label: '내용', type: 'text' },
        { k: 'kind', label: '구분', type: 'select', options: () => state.meta.event_kinds },
        { k: 'amount', label: '금액', type: 'money', optional: true },
        { k: 'member', label: '구성원', type: 'select', options: () => state.meta.owners },
      ],
    },
  };
  const ENTITY_ORDER = ['accounts', 'holdings', 'debts', 'goals', 'insurances', 'events'];

  function showValue(f, v) {
    if (f.type === 'money') return v == null ? (f.optional ? '자동' : '-') : won(v);
    if (f.type === 'pct') return v == null ? '-' : (v * 100).toFixed(2) + '%';
    if (f.type === 'accounts') return (v || []).join(', ') || '-';
    if (f.type === 'coverages') return Object.entries(v || {}).filter(([, x]) => x > 0).map(([k, x]) => `${k} ${short(x)}`).join(' · ') || '없음';
    if (f.type === 'select') { const o = f.options().find((x) => (Array.isArray(x) ? x[0] : x) === v); return Array.isArray(o) ? o[1] : (v ?? '-'); }
    return v == null || v === '' ? '-' : String(v);
  }

  function entityForm(kind, row, done) {
    const spec = ENTITY[kind], inputs = {};
    const opt = (o, v) => { const [val, text] = Array.isArray(o) ? o : [o, o]; return h('option', { value: val, selected: val === v }, text); };
    const cells = spec.fields.map((f) => {
      const v = row ? row[f.k] : undefined;
      let input;
      if (f.type === 'select') input = h('select', null, f.options().map((o) => opt(o, v)));
      else if (f.type === 'accounts') {
        const picks = [0, 1, 2].map((i) => h('select', { 'aria-label': `${f.label} ${i + 1}` }, h('option', { value: '' }, '-'), acctOptions().map((o) => opt(o, (v || [])[i]))));
        inputs[f.k] = { get: () => picks.map((p) => p.value).filter(Boolean) };
        return h('label', { class: 'field', style: { gridColumn: '1 / -1' } }, f.label, h('div', { class: 'row' }, picks));
      } else if (f.type === 'coverages') {
        const each = Object.fromEntries(state.meta.coverages.map((c) => [c, h('input', { type: 'number', min: 0, class: 'amount', value: (v || {})[c] || '', placeholder: '0', 'aria-label': `${c} 보장금액` })]));
        inputs[f.k] = { get: () => Object.fromEntries(Object.entries(each).map(([c, i]) => [c, Math.round(Number(i.value) || 0)])) };
        return h('div', { class: 'field', style: { gridColumn: '1 / -1' } }, f.label, h('div', { class: 'form' }, Object.entries(each).map(([c, i]) => h('label', { class: 'field' }, c, i))));
      } else {
        const type = f.type === 'date' ? 'date' : ['money', 'number', 'pct'].includes(f.type) ? 'number' : 'text';
        const shown = v == null ? '' : f.type === 'pct' ? +(v * 100).toFixed(4) : v;
        input = h('input', { type, value: shown, step: 'any', min: type === 'number' ? 0 : null, placeholder: f.placeholder || null, disabled: Boolean(row && f.lock) });
      }
      inputs[f.k] = inputs[f.k] || { get: () => {
        const raw = input.value.trim();
        if (['money', 'number', 'pct'].includes(f.type)) {
          if (raw === '') return f.optional ? null : 0;
          const n = Number(raw);
          return f.type === 'pct' ? n / 100 : f.type === 'money' ? Math.round(n) : n;
        }
        if (f.type === 'date') return raw || null;
        return raw;
      } };
      return h('label', { class: 'field' }, f.label, input, f.hint ? h('span', { class: 'muted' }, f.hint) : null);
    });
    const err = h('p', { class: 'error' });
    const save = async () => {
      const body = Object.fromEntries(Object.entries(inputs).map(([k, i]) => [k, i.get()]));
      if (kind === 'events' && body.amount == null) body.amount = 0;
      try {
        if (row) await api(`/api/entities/${kind}/${encodeURIComponent(row[spec.key])}`, { method: 'PUT', body });
        else await api(`/api/entities/${kind}`, { body });
        state.meta = await api('/api/meta');
        toast(row ? '수정했습니다' : '추가했습니다');
        done();
      } catch (e) { err.textContent = e.message; }
    };
    return h('div', { class: 'card' }, h('h3', null, row ? `${spec.title} 수정: ${spec.label(row)}` : `${spec.title} 추가`),
      h('div', { class: 'form' }, cells), err,
      h('div', { class: 'row' }, h('button', { class: 'btn primary', onclick: save }, row ? '저장' : '추가'), h('button', { class: 'btn', onclick: done }, '취소')));
  }

  async function renderPlan() {
    state.planTab ||= 'accounts';
    const kind = state.planTab, spec = ENTITY[kind];
    const tabs = h('div', { class: 'seg', role: 'group', 'aria-label': '편집할 항목' }, ENTITY_ORDER.map((k) =>
      h('button', { type: 'button', 'aria-pressed': String(k === kind), onclick: () => { state.planTab = k; renderPlan(); } }, ENTITY[k].title)));
    const formSlot = h('div');
    const listCard = h('div', { class: 'card' }, h('p', { class: 'muted' }, '불러오는 중…'));
    const extra = h('div', { class: 'section' });
    shell([h('div', { class: 'head' }, h('div', null, h('p', { class: 'eyebrow' }, '계정과목·사업계획'), h('h1', null, '자산·계획'),
      h('p', { class: 'take' }, spec.note)), tabs), formSlot, listCard, extra]);
    const rows = await api(`/api/entities/${kind}`);
    const shownFields = spec.fields.filter((f) => f.type !== 'coverages' || kind === 'insurances');
    const reload = () => renderPlan();
    const openForm = (row) => { formSlot.replaceChildren(entityForm(kind, row, reload)); formSlot.scrollIntoView({ block: 'nearest' }); };
    listCard.replaceChildren(
      h('div', { class: 'row', style: { justifyContent: 'space-between' } }, h('h3', null, `${spec.title} ${rows.length}건`), h('button', { class: 'btn primary', onclick: () => openForm(null) }, `${spec.title} 추가`)),
      rows.length ? h('div', { class: 'table-wrap scroll' }, h('table', { class: 'nowrap' },
        h('thead', null, h('tr', null, shownFields.map((f) => h('th', { class: ['money', 'number', 'pct'].includes(f.type) ? 'num' : null }, f.label)), h('th', null, ''))),
        h('tbody', null, rows.map((r) => {
          const del = h('button', { class: 'btn small danger', onclick: async () => {
            if (del.dataset.confirm !== '1') { del.dataset.confirm = '1'; del.textContent = '한 번 더 눌러 삭제'; return; }
            try { await api(`/api/entities/${kind}/${encodeURIComponent(r[spec.key])}`, { method: 'DELETE' }); state.meta = await api('/api/meta'); toast('삭제했습니다'); reload(); }
            catch (e) { toast(e.message); del.dataset.confirm = ''; del.textContent = '삭제'; }
          } }, '삭제');
          return h('tr', null, shownFields.map((f) => h('td', { class: ['money', 'number', 'pct'].includes(f.type) ? 'num' : null }, showValue(f, r[f.k]))),
            h('td', { class: 'num' }, h('button', { class: 'btn small', onclick: () => openForm(r) }, '수정'), ' ', del));
        })))) : h('p', { class: 'empty' }, `아직 ${spec.title}이(가) 없습니다. 위의 추가 버튼으로 시작하세요.`));
    if (kind === 'holdings') extra.append(priceCard(reload), allocationCard());
  }

  function priceCard(after) {
    const out = h('div');
    const show = (r) => out.replaceChildren(h('p', null, `${r.dry_run ? '갱신 예정' : '갱신'} ${r.updated.length}종목 · 건너뜀 ${r.skipped.length} · 실패 ${r.failed.length}`),
      r.updated.length ? h('div', { class: 'table-wrap' }, h('table', null, h('thead', null, h('tr', null, h('th', null, '종목'), h('th', { class: 'num' }, '이전'), h('th', { class: 'num' }, '새 현재가'))),
        h('tbody', null, r.updated.map((x) => h('tr', null, h('td', null, x.name), h('td', { class: 'num muted' }, x.old == null ? '-' : won(x.old)), h('td', { class: 'num' }, won(x.new))))))) : null,
      r.failed.length ? h('p', { class: 'error' }, '실패: ' + r.failed.map((x) => `${x.name}(${x.reason})`).join(', ') + ' · 기존 가격을 유지했습니다. 시세 CSV를 올리거나 직접 입력하세요.') : null,
      r.skipped.length ? h('p', { class: 'sub' }, '건너뜀: ' + r.skipped.map((x) => `${x.name}(${x.reason})`).join(', ')) : null);
    const file = h('input', { type: 'file', accept: '.csv', 'aria-label': '시세 CSV' });
    return h('section', { class: 'card' }, h('h3', null, '현재가 갱신'),
      h('p', { class: 'sub' }, '자동 갱신은 네이버 금융 시세를 읽습니다(공식 API가 아니라 막히면 실패로 표시). 대신 "시세코드,현재가" 또는 "종목명,현재가" 두 열 CSV를 올려도 됩니다.'),
      h('div', { class: 'row' },
        h('button', { class: 'btn primary', onclick: async () => { try { const r = await api('/api/prices/refresh', { body: { dry_run: false } }); show(r); if (r.updated.length) toast('현재가를 갱신했습니다'); } catch (e) { toast(e.message); } } }, '시세 자동 갱신'),
        file, h('button', { class: 'btn', onclick: async () => {
          if (!file.files[0]) { toast('CSV 파일을 고르세요'); return; }
          const fd = new FormData(); fd.append('file', file.files[0]); fd.append('dry_run', 'false');
          try { show(await api('/api/prices/upload', { body: fd })); toast('현재가를 반영했습니다'); } catch (e) { toast(e.message); }
        } }, '시세 CSV 반영'),
        h('button', { class: 'btn', onclick: after }, '목록 새로고침')), out);
  }

  function allocationCard() {
    const t = state.meta.allocation;
    const inputs = Object.fromEntries(state.meta.asset_classes.map((c) => [c, h('input', { type: 'number', min: 0, max: 100, step: 'any', class: 'amount', value: +((t[c] || 0) * 100).toFixed(2), 'aria-label': `${c} 목표 비중` })]));
    const sum = h('p', { class: 'sub' });
    const upd = () => { const s = Object.values(inputs).reduce((a, i) => a + (Number(i.value) || 0), 0); sum.textContent = `합계 ${s.toFixed(1)}%` + (Math.abs(s - 100) > 0.05 ? ' · 100%가 되어야 저장됩니다' : ''); };
    Object.values(inputs).forEach((i) => i.addEventListener('input', upd)); upd();
    return h('section', { class: 'card' }, h('h3', null, '목표 자산배분'), h('p', { class: 'sub' }, '분기마다 부부가 함께 점검하세요. 현재 비중이 목표에서 리밸런싱 밴드 이상 벗어나면 대시보드에 알림이 뜹니다.'),
      h('div', { class: 'form' }, Object.entries(inputs).map(([c, i]) => h('label', { class: 'field' }, `${c} (%)`, i))), sum,
      h('div', null, h('button', { class: 'btn primary', onclick: async () => {
        const targets = Object.fromEntries(Object.entries(inputs).map(([c, i]) => [c, (Number(i.value) || 0) / 100]));
        try { await api('/api/allocation', { method: 'PUT', body: { targets } }); state.meta = await api('/api/meta'); toast('목표 비중을 저장했습니다'); } catch (e) { toast(e.message); }
      } }, '저장')));
  }

  // ---------------------------------------------------------------- 월간 결산 리포트 (인쇄용)
  async function renderReport() {
    const body = h('div', { class: 'section' }, h('p', { class: 'muted' }, '불러오는 중…'));
    shell([h('div', { class: 'head no-print' }, h('div', null, h('p', { class: 'eyebrow' }, '가족회의 자료'), h('h1', null, '결산 리포트'),
      h('p', { class: 'take' }, '월간 결산 때 부부가 함께 보는 한 장 요약입니다. 인쇄하거나 PDF로 저장해 보관하세요.')),
      h('div', { class: 'row' }, monthSelect(renderReport), window.HH_DEMO ? h('span', { class: 'sub' }, '인쇄·PDF 저장은 실제 앱에서 됩니다') : h('button', { class: 'btn primary', onclick: () => window.print() }, '인쇄 / PDF 저장'),
        state.meta.mail_enabled && !window.HH_DEMO ? h('button', { class: 'btn', onclick: async () => {
          try { const r = await api('/api/report/send', { body: { month: state.month } }); toast(`메일을 보냈습니다: ${r.sent_to.join(', ')}`); } catch (e) { toast(e.message); }
        } }, '메일로 보내기') : null)), body]);
    const d = await api(`/api/dashboard?view=전체&month=${state.month}`);
    const rows = d.pnl.rows, i = rows.income.length - 1, avg = (k) => d.pnl.agg[k].O;
    const card = Object.fromEntries(d.cards.map((c) => [c.kpi, c]));
    const fmtCard = (c) => c.value == null ? '—' : c.format === 'won' ? won(c.value) + '원' : c.format === 'months' ? c.value.toFixed(1) + '개월' : pct(c.value);
    const tbl = (head, trs) => h('div', { class: 'table-wrap' }, h('table', null, h('thead', null, h('tr', null, head.map((x, j) => h('th', { class: j ? 'num' : null }, x)))), h('tbody', null, trs)));
    const tr = (cells) => h('tr', null, cells.map((c, j) => h('td', { class: j ? 'num' : null }, c)));
    const cur = d.balance.current, prev = d.balance.previous;
    const pnlLine = (label, k, isPct) => tr([label, isPct ? pct(rows[k][i]) : won(rows[k][i]), isPct ? pct(rows[k][i - 1]) : won(rows[k][i - 1]),
      isPct ? pct(d.pnl.agg.saving_rate.N) : won(avg(k))]);
    const over = d.budget.rows.filter((r) => /초과/.test(r.status));
    const upcoming = d.events.filter((e) => e.dday >= 0 && e.dday <= 62);
    body.replaceChildren(h('article', { class: 'card report' },
      h('p', { class: 'eyebrow' }, `작성 ${d.today} · 기준 ${monthTitle(d.base_month)} 말`),
      h('h2', { style: { fontSize: '22px' } }, `우리집 주식회사 ${monthTitle(d.base_month)} 월간 결산`),
      h('p', null, `순자산 ${won(cur.net)}원(전월 대비 ${cur.net - prev.net >= 0 ? '+' : ''}${won(cur.net - prev.net)}원), 저축률 ${pct(rows.saving_rate[i])}, 투자 납입 ${won(rows.invest[i])}원. 점검 알림 ${d.alerts.length}건.`),
      h('h3', null, '1. 핵심 지표'),
      tbl(['지표', '값', '참고', '상태'], KPI_ORDER.map((k) => h('tr', null, h('td', null, card[k].label), h('td', { class: 'num' }, fmtCard(card[k])), h('td', { class: 'num muted' }, card[k].note), h('td', { class: 'num' }, pill(card[k].status))))),
      h('h3', null, '2. 손익 (이번 달 · 전월 · 12개월 평균)'),
      tbl(['항목', monthTitle(d.base_month), monthTitle(d.pnl.months[i - 1]), '12개월 평균'], [
        pnlLine('소득', 'income'), pnlLine('고정비', 'fixed'), pnlLine('변동비', 'variable'), pnlLine('비정기비', 'irregular'),
        pnlLine('소비지출 합계', 'consumption'), pnlLine('잉여 (소득-소비)', 'surplus'), pnlLine('저축률', 'saving_rate', true), pnlLine('투자 납입', 'invest')]),
      h('h3', null, '3. 재무상태 (월말 잔액)'),
      tbl(['항목', '이번 달', '전월', '증감'], [['총자산', 'assets'], ['총부채', 'liabilities'], ['순자산', 'net'], ['투자+연금', 'invest'], ['비상자금(즉시 현금)', 'emergency']]
        .map(([l, k]) => tr([l, won(cur[k]), won(prev[k]), (cur[k] - prev[k] >= 0 ? '+' : '') + won(cur[k] - prev[k])]))),
      tbl(['구성원', '자산', '부채', '순자산'], d.balance.members.map((m) => tr([m.member, won(m.assets), won(m.debt), won(m.net)]))),
      h('h3', null, '4. 예산 통제'),
      over.length ? tbl(['초과 카테고리', '예산', '실적', '집행률'], over.map((r) => tr([r.category, won(r.period_budget), won(r.actual), pct(r.rate, 0)]))) : h('p', null, '예산을 넘은 카테고리가 없습니다.'),
      h('h3', null, '5. 목표 진척'),
      tbl(['목표', '현재 / 목표', '진척률', '필요 월적립', '상태'], d.goals.rows.map((g) => h('tr', null, h('td', null, g.name), h('td', { class: 'num' }, `${short(g.current)} / ${short(g.target)}`),
        h('td', { class: 'num' }, `${pct(g.progress, 0)} (계획 ${pct(g.plan, 0)})`), h('td', { class: 'num' }, g.monthly_needed == null ? '-' : won(g.monthly_needed) + '원'), h('td', { class: 'num' }, pill(g.status))))),
      h('h3', null, '6. 다음 달 할 일'),
      h('ul', { class: 'checklist' }, [...d.alerts.filter((a) => !a.startsWith('🗓')).map(clean), ...upcoming.map((e) => `${e.day} ${e.desc}${e.amount ? ` (${e.kind} ${won(e.amount)}원)` : ''}`)].map((x) => h('li', null, x))),
      h('h3', null, '7. 이번 달 결정 사항'),
      h('div', { class: 'memo' }, [1, 2, 3].map(() => h('div', { class: 'line' })))));
  }

  // ---------------------------------------------------------------- 로그인·처음 설정
  function renderLogin() {
    const u = h('input', { type: 'text', autocomplete: 'username', id: 'login-user' });
    const p = h('input', { type: 'password', autocomplete: 'current-password', id: 'login-pass' });
    const err = h('p', { class: 'error' });
    const go = async () => { try { await api('/api/login', { body: { username: u.value, password: p.value }, allow401: true }); start(); } catch (e) { err.textContent = e.message; } };
    p.addEventListener('keydown', (e) => { if (e.key === 'Enter') go(); });
    $app.replaceChildren(h('div', { class: 'auth' }, h('div', { class: 'card' }, h('h1', null, '우리집 주식회사'), h('p', { class: 'sub' }, '가정 자산관리 대시보드'),
      h('label', { class: 'field' }, '아이디', u), h('label', { class: 'field' }, '비밀번호', p), err, h('button', { class: 'btn primary', onclick: go }, '로그인'))));
    u.focus();
  }

  function renderSetup(st = {}) {
    const mk = (member) => ({ member, username: h('input', { type: 'text', autocomplete: 'off', 'aria-label': `${member} 아이디` }), password: h('input', { type: 'password', autocomplete: 'new-password', 'aria-label': `${member} 비밀번호` }) });
    const a = mk('본인'), b = mk('배우자');
    const startSel = h('select', null, h('option', { value: 'blank' }, '빈 가계로 시작'), h('option', { value: 'sample' }, '샘플 데이터로 둘러보기'));
    const err = h('p', { class: 'error' });
    const code = h('input', { type: 'text', autocomplete: 'off', id: 'setup-code', placeholder: '예: 7F3K9Q' });
    $app.replaceChildren(h('div', { class: 'auth' }, h('div', { class: 'card' }, h('h1', null, '처음 설정'),
      st.setup_code_required ? h('label', { class: 'field' }, '설치 코드 (서버를 켤 때 화면에 표시된 코드)', code) : null, h('p', { class: 'sub' }, '부부가 각자 쓸 계정을 만듭니다. 배우자 계정은 나중에 설정 메뉴에서 만들어도 됩니다.'),
      ...[a, b].map((x) => h('div', { class: 'form' }, h('label', { class: 'field' }, `${x.member} 아이디`, x.username), h('label', { class: 'field' }, '비밀번호 (8자 이상)', x.password))),
      h('label', { class: 'field' }, '시작 방법', startSel),
      h('p', { class: 'sub' }, '1단계 엑셀 파일이 있다면 빈 가계로 시작한 뒤 [내역 가져오기 → 엑셀 파일과 주고받기]에서 올리세요.'), err,
      h('button', { class: 'btn primary', onclick: async () => {
        const users = [a, b].filter((x) => x.username.value).map((x) => ({ username: x.username.value, password: x.password.value, member: x.member }));
        try { await api('/api/setup', { body: { users, start: startSel.value, code: code.value } }); start(); } catch (e) { err.textContent = e.message; }
      } }, '시작하기'))));
  }

  // ---------------------------------------------------------------- 시작·라우팅
  const RENDER = { dashboard: renderDashboard, transactions: renderTransactions, import: renderImport, close: renderClose, plan: renderPlan, budget: renderBudget, report: renderReport, settings: renderSettings };

  function route() {
    if (!state.me) return;
    const r = location.hash.replace(/^#\//, '') || 'dashboard';
    state.route = RENDER[r] ? r : 'dashboard';
    window.onresize = null;
    Promise.resolve().then(() => RENDER[state.route]()).catch((e) => toast(e.message));
  }

  async function start() {
    try {
      const st = await api('/api/status');
      if (st.setup_needed) { renderSetup(st); return; }
      state.me = await api('/api/me', { allow401: true });
      state.meta = await api('/api/meta');
      state.month = state.meta.base_month;
      route();
    } catch (e) { if (!state.me) renderLogin(); }
  }
  window.addEventListener('hashchange', route);
  start();
})();
