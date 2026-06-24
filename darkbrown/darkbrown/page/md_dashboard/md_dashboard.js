// Managing Director Dashboard — Frappe page controller
// Ports design_handoff_md_dashboard pixel-for-pixel and wires to
// darkbrown.md_dashboard.md_dashboard.* whitelisted methods.

frappe.pages['md-dashboard'].on_page_load = function (wrapper) {
  const page = frappe.ui.make_app_page({
    parent: wrapper, title: 'Managing Director', single_column: true,
  });
  new MDDashboard(page, wrapper);
};

// Whitelisted-method path = <app>.<module-folder>.page.<page>.<file>
// For app "darkbrown", module "DarkBrown" => folder "darkbrown":
const M_API = 'darkbrown.darkbrown.page.md_dashboard.md_dashboard';

// ---- design tokens ----
const C = {
  appBg:'#15181d', panel:'#191d23', card:'#1b2027', rowHover:'#20262d',
  border:'#262c35', border2:'#2c333d', borderHover:'#39424d',
  text:'#e6ebf0', sec:'#9aa6b4', sec2:'#8a95a3', muted:'#7d8896',
  muted2:'#6f7a89', faint:'#5f6a78',
  blue:'#2490ef', blueHover:'#1f82d6', link:'#5aa9f0',
  green:'#43c478', teal:'#37c4cf', purple:'#a584ff',
  orange:'#f0a93f', red:'#f0616d', orange2:'#f0884f',
  avBg:'#3a4654', avTx:'#cdd6e0',
};
const TINT = {
  blue:[C.link,'rgba(36,144,239,.14)'], green:[C.green,'rgba(67,196,120,.13)'],
  purple:[C.purple,'rgba(140,108,255,.15)'], orange:[C.orange,'rgba(240,160,60,.14)'],
  teal:[C.teal,'rgba(55,196,207,.14)'], red:[C.red,'rgba(240,97,109,.14)'],
};
const IC = {
  home:'M3 9.5L12 3l9 6.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z',
  grid:'M3 3h7v7H3zM14 3h7v7h-7zM14 14h7v7h-7zM3 14h7v7H3z',
  tag:'M20.6 13.4l-7.2 7.2a2 2 0 0 1-2.8 0L2 12V2h10l8.6 8.6a2 2 0 0 1 0 2.8zM7 7h.01',
  users:'M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z',
  dollar:'M12 1v22M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6',
  cart:'M9 22a1 1 0 1 0 0-2 1 1 0 0 0 0 2zM20 22a1 1 0 1 0 0-2 1 1 0 0 0 0 2zM1 1h4l2.7 13.4a2 2 0 0 0 2 1.6h9.7a2 2 0 0 0 2-1.6L23 6H6',
  box:'M21 16V8a2 2 0 0 0-1-1.7l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.7l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16zM3.3 7l8.7 5 8.7-5M12 22V12',
  clipboard:'M9 2h6a1 1 0 0 1 1 1v1h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2V3a1 1 0 0 1 1-1z',
  layers:'M12 2l9 5-9 5-9-5 9-5zM3 12l9 5 9-5M3 17l9 5 9-5',
  headset:'M3 18v-5a9 9 0 0 1 18 0v5M21 19a2 2 0 0 1-2 2h-1a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2h3zM3 19a2 2 0 0 0 2 2h1a2 2 0 0 0 2-2v-3a2 2 0 0 0-2-2H3z',
  gear:'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-2.7 1.1V21a2 2 0 0 1-4 0v-.1A1.6 1.6 0 0 0 9 19.4a1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0-1.1-2.7H3a2 2 0 0 1 0-4h.1A1.6 1.6 0 0 0 4.6 9a1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H9a1.6 1.6 0 0 0 1-1.5V3a2 2 0 0 1 4 0v.1a1.6 1.6 0 0 0 2.7 1.1l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V9a1.6 1.6 0 0 0 1.5 1H21a2 2 0 0 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1z',
  trendUp:'M23 6l-9.5 9.5-5-5L1 18M17 6h6v6',
  invoice:'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M9 13h6M9 17h4',
  building:'M6 22V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v18M6 22h12M10 6h.01M14 6h.01M10 10h.01M14 10h.01M10 14h.01M14 14h.01M10 22v-4h4v4',
  file:'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6',
  arrowUp:'M12 19V5M5 12l7-7 7 7',
  arrowDown:'M12 5v14M5 12l7 7 7-7',
};
const svg = (path, w=17, sw=1.9) =>
  `<svg width="${w}" height="${w}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${sw}" stroke-linecap="round" stroke-linejoin="round"><path d="${path}"></path></svg>`;

const SPAN_DEFS = {
  overview:  { salesTrend:8, expiries:4, approvals:5, bookings:7, projects:12 },
  portfolio: { projects:8, expiries:4, collections:12 },
  tenants:   { funnel:4, bookings:8, approvals:12 },
  finance:   { collections:6, receivables:6, approvals:12 },
};

class MDDashboard {
  constructor(page, wrapper) {
    this.page = page;
    this.$body = $(wrapper).find('.layout-main-section');
    this.state = { tab: 'overview', period: 'month' };
    this.data = {};
    this.injectStyles();
    this.render();          // paint shell immediately
    this.loadAll();         // then fetch real data
  }

  injectStyles() {
    if (document.getElementById('mdd-styles')) return;
    const s = document.createElement('style');
    s.id = 'mdd-styles';
    s.textContent = `
      .mdd *{box-sizing:border-box}
      .mdd{font-family:'Inter',-apple-system,sans-serif;color:${C.text};font-size:13px}
      @keyframes mddDraw{to{stroke-dashoffset:0}}
      .mdd .kpi:hover{border-color:${C.borderHover}!important;transform:translateY(-2px)}
      .mdd .row:hover{background:${C.rowHover}}
      .mdd .sc:hover{background:#222831;border-color:#3a4350}
      .mdd .seg:hover{color:${C.text}}
      .mdd .tab{transition:color .15s,border-color .15s}
    `;
    document.head.appendChild(s);
  }

  async loadAll() {
    const P = this.state.period;
    const call = (m, args={}) =>
      frappe.call({ method: `${M_API}.${m}`, args }).then(r => r.message).catch(() => null);
    const [kpis, activity, expiries, occ, coll, aging, incVsCost, approvals] =
      await Promise.all([
        call('get_kpis', { period: P }),
        call('get_recent_activity', { limit: 5 }),
        call('get_expiries', { days: 90 }),
        call('get_building_occupancy'),
        call('get_collections_vs_billed', { months: 6 }),
        call('get_arrears_aging'),
        call('get_income_vs_cost', { months: 12 }),
        call('get_pending_approvals'),
      ]);
    this.data = { kpis, activity, expiries, occ, coll, aging, incVsCost, approvals };
    this.render();
  }

  setTab(t)    { this.state.tab = t; this.render(); }
  setPeriod(p) { this.state.period = p; this.loadAll(); }

  // ---------- render ----------
  render() {
    const d = this.data;
    const sp = SPAN_DEFS[this.state.tab] || SPAN_DEFS.overview;
    const span = k => `grid-column:span ${sp[k] || 12};`;
    const show = k => k in sp;

    const html = `
      <div class="mdd" style="background:${C.appBg};min-height:100%;padding:24px 28px 60px;margin:-15px -15px 0">
        <div style="max-width:1320px;margin:0 auto">
          ${this.pageHeader()}
          ${this.tabsRow()}
          ${this.shortcutsRow()}
          ${this.kpiGrid(d.kpis)}
          <div style="display:grid;grid-template-columns:repeat(12,1fr);gap:16px;align-items:start">
            ${show('salesTrend')  ? `<div style="${span('salesTrend')}">${this.incomeChart(d.incVsCost)}</div>` : ''}
            ${show('collections') ? `<div style="${span('collections')}">${this.collectionsChart(d.coll)}</div>` : ''}
            ${show('approvals')   ? `<div style="${span('approvals')}">${this.approvalsList(d.approvals)}</div>` : ''}
            ${show('bookings')    ? `<div style="${span('bookings')}">${this.activityTable(d.activity)}</div>` : ''}
            ${show('funnel')      ? `<div style="${span('funnel')}">${this.funnelCard()}</div>` : ''}
            ${show('receivables') ? `<div style="${span('receivables')}">${this.agingCard(d.aging)}</div>` : ''}
            ${show('expiries')    ? `<div style="${span('expiries')}">${this.expiriesList(d.expiries)}</div>` : ''}
            ${show('projects')    ? `<div style="${span('projects')}">${this.occupancyCard(d.occ)}</div>` : ''}
          </div>
        </div>
      </div>`;
    this.$body.html(html);
    this.bind();
  }

  pageHeader() {
    const P = this.state.period;
    const segs = [['month','This Month'],['quarter','This Quarter'],['year','This Year']]
      .map(([k,l]) => {
        const on = P===k;
        return `<button class="seg" data-period="${k}" style="border:none;border-radius:6px;padding:6px 14px;font-size:12px;font-weight:550;font-family:inherit;cursor:pointer;transition:all .15s;${on?`background:${C.border2};color:#fff;box-shadow:0 1px 2px rgba(0,0,0,.3)`:`background:transparent;color:${C.sec2}`}">${l}</button>`;
      }).join('');
    const today = frappe.datetime.str_to_user(frappe.datetime.now_date());
    return `
      <div style="display:flex;align-items:flex-end;justify-content:space-between;gap:20px;flex-wrap:wrap;margin-bottom:18px">
        <div>
          <div style="display:flex;align-items:center;gap:10px">
            <h1 style="font-size:23px;font-weight:700;letter-spacing:-.3px;margin:0">Managing Director</h1>
            <span style="font-size:11px;font-weight:600;color:${C.green};background:rgba(67,196,120,.12);border:1px solid rgba(67,196,120,.25);padding:2px 9px;border-radius:20px">Live</span>
          </div>
          <p style="color:${C.muted};font-size:12.5px;margin-top:5px">${today} · Daily health check across leasing, occupancy &amp; collections</p>
        </div>
        <div style="display:flex;align-items:center;background:${C.card};border:1px solid ${C.border2};border-radius:8px;padding:3px">${segs}</div>
      </div>`;
  }

  tabsRow() {
    const T = this.state.tab;
    const tabs = [['overview','Overview'],['portfolio','Portfolio'],['tenants','Tenants & Leasing'],['finance','Finance']]
      .map(([k,l]) => {
        const on = T===k;
        return `<button class="tab" data-tab="${k}" style="background:none;border:none;border-bottom:2px solid transparent;padding:10px 16px;font-size:13px;font-weight:600;font-family:inherit;cursor:pointer;margin-bottom:-1px;${on?`color:${C.link};border-bottom-color:${C.blue}`:`color:${C.muted}`}">${l}</button>`;
      }).join('');
    return `<div style="display:flex;gap:2px;border-bottom:1px solid ${C.border};margin-bottom:22px">${tabs}</div>`;
  }

  shortcutsRow() {
    const defs = [['New Enquiry','users','blue'],['New Sublease','tag','green'],
      ['Rent Receipt','dollar','teal'],['Add Building','building','purple'],
      ['Units','box','orange'],['Reports','file','blue']];
    const pills = defs.map(([label,icon,t]) => {
      const [tc,tb] = TINT[t];
      return `<button class="sc" style="display:flex;align-items:center;gap:9px;height:38px;padding:0 14px 0 11px;background:${C.card};border:1px solid ${C.border2};border-radius:8px;color:#d3dae2;font-weight:550;font-size:12.5px;font-family:inherit;cursor:pointer;transition:border-color .15s,background .15s">
        <span style="width:24px;height:24px;border-radius:6px;display:flex;align-items:center;justify-content:center;color:${tc};background:${tb}">${svg(IC[icon],14,2)}</span>${label}</button>`;
    }).join('');
    return `<div style="margin-bottom:22px">
      <div style="font-size:11px;font-weight:600;letter-spacing:.5px;text-transform:uppercase;color:${C.faint};margin-bottom:10px">Your Shortcuts</div>
      <div style="display:flex;gap:10px;flex-wrap:wrap">${pills}</div></div>`;
  }

  kpiGrid(kpis) {
    if (!kpis) return this.skeleton(6, 92);
    const cards = kpis.map(k => {
      const [tc,tb] = TINT[k.tint] || TINT.blue;
      const goodCol = k.good ? C.green : C.red;
      const goodBg = k.good ? 'rgba(67,196,120,.13)' : 'rgba(240,97,109,.14)';
      const arrow = k.dir==='up' ? IC.arrowUp : IC.arrowDown;
      return `<div class="kpi" style="background:${C.card};border:1px solid ${C.border};border-radius:11px;padding:16px 16px 15px;transition:border-color .15s,transform .15s">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px">
          <span style="width:32px;height:32px;border-radius:8px;display:flex;align-items:center;justify-content:center;color:${tc};background:${tb}">${svg(IC[k.icon],17)}</span>
          <span style="display:flex;align-items:center;gap:3px;font-size:11.5px;font-weight:600;color:${goodCol};background:${goodBg};padding:2px 7px;border-radius:6px">${svg(arrow,11,2.6)}${k.delta}</span>
        </div>
        <div style="font-size:24px;font-weight:700;letter-spacing:-.4px;line-height:1">${k.value}</div>
        <div style="font-size:12px;color:${C.sec};margin-top:6px;font-weight:500">${k.label}</div>
        <div style="font-size:11px;color:${C.muted2};margin-top:2px">${k.sub}</div></div>`;
    }).join('');
    return `<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(196px,1fr));gap:14px;margin-bottom:22px">${cards}</div>`;
  }

  cardShell(inner, pad='18px') {
    return `<div style="background:${C.card};border:1px solid ${C.border};border-radius:12px;padding:${pad}">${inner}</div>`;
  }
  cardTitle(t, sub) {
    return `<div style="font-size:14px;font-weight:600">${t}</div>${sub?`<div style="font-size:11.5px;color:${C.muted};margin-top:2px">${sub}</div>`:''}`;
  }

  // ----- income vs cost area chart (data-driven) -----
  incomeChart(rows) {
    if (!rows) return this.cardShell(this.cardTitle('Rental Income vs Lease Cost','QAR · last 12 months')+this.skelBlock(170));
    const W=600, H=210, x0=30, x1=569, yTop=58, yBot=170;
    const maxV = Math.max(1, ...rows.map(r => Math.max(r.income, r.cost)));
    const X = i => x0 + (x1-x0) * (i/(rows.length-1||1));
    const Y = v => yTop + (yBot-yTop) * (1 - v/maxV);
    const incPts = rows.map((r,i)=>`${X(i).toFixed(0)},${Y(r.income).toFixed(0)}`);
    const costPts = rows.map((r,i)=>`${X(i).toFixed(0)},${Y(r.cost).toFixed(0)}`);
    const incLine = 'M'+incPts.join(' L');
    const costLine = 'M'+costPts.join(' L');
    const area = incLine + ` L${x1},180 L${x0},180 Z`;
    const labels = rows.map(r=>`<span>${r.month}</span>`).join('');
    const last = rows[rows.length-1];
    const inner = `
      <div style="display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:18px">
        <div>${this.cardTitle('Rental Income vs Lease Cost','QAR · last 12 months · gap = net margin')}</div>
        <div style="display:flex;align-items:center;gap:14px;font-size:11.5px;color:${C.sec}">
          <span style="display:flex;align-items:center;gap:6px"><span style="width:9px;height:9px;border-radius:2px;background:${C.blue}"></span>Sublease income</span>
          <span style="display:flex;align-items:center;gap:6px"><span style="width:14px;height:0;border-top:2px solid ${C.muted}"></span>Head-lease cost</span>
        </div>
      </div>
      <svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto;display:block">
        <defs><linearGradient id="bvGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="${C.blue}" stop-opacity="0.32"></stop>
          <stop offset="100%" stop-color="${C.blue}" stop-opacity="0"></stop></linearGradient></defs>
        <line x1="20" y1="40" x2="585" y2="40" stroke="${C.border}"></line>
        <line x1="20" y1="90" x2="585" y2="90" stroke="${C.border}"></line>
        <line x1="20" y1="140" x2="585" y2="140" stroke="${C.border}"></line>
        <path d="${costLine}" fill="none" stroke="${C.muted}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="stroke-dasharray:1200;stroke-dashoffset:1200;animation:mddDraw 1.5s ease forwards .35s"></path>
        <path d="${area}" fill="url(#bvGrad)"></path>
        <path d="${incLine}" fill="none" stroke="${C.blue}" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" style="stroke-dasharray:1200;stroke-dashoffset:1200;animation:mddDraw 1.5s ease forwards .2s"></path>
        <circle cx="${X(rows.length-1).toFixed(0)}" cy="${Y(last.income).toFixed(0)}" r="4.5" fill="${C.blue}" stroke="${C.card}" stroke-width="2.5"></circle>
      </svg>
      <div style="display:flex;justify-content:space-between;margin-top:6px;padding:0 6px;font-size:10.5px;color:${C.muted2}">${labels}</div>`;
    return this.cardShell(inner, '18px 18px 14px');
  }

  // ----- collected vs billed bars -----
  collectionsChart(rows) {
    if (!rows) return this.cardShell(this.cardTitle('Rent Collected vs Billed','QAR M per month')+this.skelBlock(160));
    const maxV = Math.max(1, ...rows.map(r=>r.billed));
    const baseY=150, topY=30, n=rows.length, slot=88, x0=34;
    const bars = rows.map((r,i)=>{
      const bx = x0 + i*slot;
      const bh = (r.billed/maxV)*(baseY-topY);
      const ch = (r.collected/maxV)*(baseY-topY);
      const ratio = r.billed ? r.collected/r.billed : 0;
      const col = ratio>=1 ? C.green : ratio<0.9 ? C.orange : C.blue;
      return `<rect x="${bx}" y="${(baseY-bh).toFixed(0)}" width="46" height="${bh.toFixed(0)}" rx="4" fill="${C.border2}"></rect>
              <rect x="${bx}" y="${(baseY-ch).toFixed(0)}" width="46" height="${ch.toFixed(0)}" rx="4" fill="${col}"></rect>`;
    }).join('');
    const labels = rows.map(r=>`<span>${r.month}</span>`).join('');
    const inner = `${this.cardTitle('Rent Collected vs Billed','QAR M per month · grey = billed')}
      <div style="margin-top:14px"></div>
      <svg viewBox="0 0 560 200" style="width:100%;height:auto;display:block">${bars}
        <line x1="20" y1="150" x2="545" y2="150" stroke="#363d47" stroke-width="1.2"></line></svg>
      <div style="display:flex;justify-content:space-between;margin-top:6px;padding:0 14px;font-size:10.5px;color:${C.muted2}">${labels}</div>`;
    return this.cardShell(inner, '18px 18px 14px');
  }

  approvalsList(rows) {
    rows = rows || [];
    const items = rows.length ? rows.map(a => {
      const [tc,tb] = TINT[a.tint] || TINT.blue;
      return `<div class="row" style="display:flex;align-items:center;gap:12px;padding:11px 4px;border-bottom:1px solid #23292f;cursor:pointer;border-radius:6px;transition:background .12s">
        <span style="width:32px;height:32px;border-radius:8px;flex-shrink:0;display:flex;align-items:center;justify-content:center;color:${tc};background:${tb}">${svg(IC[a.icon]||IC.file,15)}</span>
        <div style="flex:1;min-width:0">
          <div style="display:flex;align-items:center;gap:7px">
            <span style="font-size:12.5px;font-weight:600;white-space:nowrap">${a.type}</span>
            <span style="font-size:10.5px;color:${C.muted2};white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${a.ref}</span></div>
          <div style="font-size:11px;color:${C.sec2};margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${a.detail}</div></div>
        <div style="text-align:right;flex-shrink:0">
          <div style="font-size:12.5px;font-weight:650;color:${C.text}">${a.amount}</div>
          <div style="font-size:10px;color:${C.muted2};margin-top:2px">${a.age}</div></div></div>`;
    }).join('') : this.emptyRow('Nothing pending approval');
    const inner = `<div style="display:flex;align-items:center;justify-content:space-between;padding-right:14px;margin-bottom:14px">
        <div style="display:flex;align-items:center;gap:9px"><div style="font-size:14px;font-weight:600">Pending Your Approval</div>
          <span style="font-size:10.5px;font-weight:700;color:${C.orange};background:rgba(240,160,60,.14);border-radius:20px;padding:1px 8px">${rows.length}</span></div>
        <a href="#" style="font-size:11.5px;color:${C.link};text-decoration:none;font-weight:550">View all</a></div>
      <div style="display:flex;flex-direction:column;max-height:312px;overflow-y:auto;padding-right:8px">${items}</div>`;
    return this.cardShell(inner, '18px 4px 8px 18px');
  }

  activityTable(rows) {
    rows = rows || [];
    const body = rows.length ? rows.map(b => {
      const [sc,sb] = TINT[b.sc] || TINT.blue;
      return `<div class="row" style="display:grid;grid-template-columns:1.6fr 1fr auto auto;gap:14px;align-items:center;padding:11px 4px;border-bottom:1px solid #23292f;cursor:pointer;transition:background .12s">
        <div style="min-width:0"><div style="font-size:12.5px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${b.project}</div>
          <div style="font-size:11px;color:${C.sec2};margin-top:1px">${b.unit}</div></div>
        <div style="font-size:12.5px;font-weight:650">${b.value}</div>
        <span style="justify-self:center;font-size:11px;font-weight:600;padding:2px 10px;border-radius:20px;color:${sc};background:${sb};white-space:nowrap">${b.status}</span>
        <span style="width:28px;height:28px;border-radius:50%;background:${C.avBg};display:flex;align-items:center;justify-content:center;font-size:10.5px;font-weight:600;color:${C.avTx}">${b.who}</span></div>`;
    }).join('') : this.emptyRow('No recent lease activity');
    const inner = `<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px">
        <div style="font-size:14px;font-weight:600">Recent Lease Activity</div>
        <a href="#" style="font-size:11.5px;color:${C.link};text-decoration:none;font-weight:550">Open Leasing</a></div>
      <div style="display:grid;grid-template-columns:1.6fr 1fr auto auto;gap:14px;padding:0 4px 9px;font-size:10.5px;font-weight:600;letter-spacing:.4px;text-transform:uppercase;color:${C.faint};border-bottom:1px solid ${C.border}">
        <span>Tenant / Unit</span><span>Rent</span><span style="text-align:center">Status</span><span>Agent</span></div>${body}`;
    return this.cardShell(inner, '18px 18px 8px');
  }

  funnelCard() {
    const funnel = [
      {stage:'Enquiries',count:'248',w:'100%',col:C.link},
      {stage:'Viewings',count:'132',w:'53%',col:C.teal},
      {stage:'Offers',count:'64',w:'26%',col:C.purple},
      {stage:'Negotiation',count:'38',w:'15%',col:C.orange},
      {stage:'Signed',count:'31',w:'12%',col:C.green},
    ];
    const rows = funnel.map(f => `<div>
      <div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:5px"><span style="color:${C.avTx};font-weight:500">${f.stage}</span><span style="font-weight:650">${f.count}</span></div>
      <div style="height:8px;background:${C.rowHover};border-radius:5px;overflow:hidden"><div style="height:100%;width:${f.w};background:${f.col};border-radius:5px;transition:width .6s ease"></div></div></div>`).join('');
    const inner = `${this.cardTitle('Enquiry Pipeline','Tenant conversion this quarter')}
      <div style="margin-top:18px;display:flex;flex-direction:column;gap:13px">${rows}</div>`;
    return this.cardShell(inner);
  }

  agingCard(rows) {
    rows = rows || [];
    const cols = [C.green,C.orange,C.orange2,C.red];
    const maxV = Math.max(1, ...rows.map(r=>r.amount));
    const body = rows.map((r,i)=>{
      const w = Math.round((r.amount/maxV)*100);
      return `<div><div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:5px">
        <span style="color:${C.avTx};font-weight:500">${r.bucket}</span><span style="font-weight:650">QAR ${(r.amount/1e6).toFixed(2)}M</span></div>
        <div style="height:8px;background:${C.rowHover};border-radius:5px;overflow:hidden"><div style="height:100%;width:${w}%;background:${cols[i]||C.green};border-radius:5px;transition:width .6s ease"></div></div></div>`;
    }).join('');
    const inner = `${this.cardTitle('Rent Arrears Aging','Tenant outstanding by bucket')}
      <div style="margin-top:18px;display:flex;flex-direction:column;gap:14px">${body}</div>`;
    return this.cardShell(inner);
  }

  expiriesList(rows) {
    rows = rows || [];
    const body = rows.length ? rows.map(e => {
      const [sc,sb] = TINT[e.sc] || TINT.blue;
      const kindCol = e.kind==='Head Lease' ? C.purple : C.teal;
      return `<div class="row" style="display:flex;align-items:center;gap:12px;padding:11px 4px;border-bottom:1px solid #23292f;cursor:pointer;border-radius:6px;transition:background .12s">
        <div style="flex:1;min-width:0"><div style="font-size:12.5px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${e.name}</div>
          <div style="display:flex;align-items:center;gap:7px;margin-top:2px"><span style="font-size:10.5px;font-weight:600;color:${kindCol}">${e.kind}</span><span style="font-size:10.5px;color:${C.muted2}">· ${e.date}</span></div></div>
        <div style="text-align:right;flex-shrink:0"><span style="font-size:11px;font-weight:600;padding:2px 9px;border-radius:20px;color:${sc};background:${sb};white-space:nowrap">${e.status}</span>
          <div style="font-size:10px;color:${C.muted2};margin-top:3px">${e.days}</div></div></div>`;
    }).join('') : this.emptyRow('No expiries in the next 90 days');
    const inner = `<div style="display:flex;align-items:center;justify-content:space-between;padding-right:14px;margin-bottom:14px">
        <div style="font-size:14px;font-weight:600">Upcoming Lease Expiries</div>
        <span style="font-size:10.5px;font-weight:700;color:${C.orange};background:rgba(240,160,60,.14);border-radius:20px;padding:1px 8px">Next 90d</span></div>
      <div style="display:flex;flex-direction:column;max-height:312px;overflow-y:auto;padding-right:8px">${body}</div>`;
    return this.cardShell(inner, '18px 4px 8px 18px');
  }

  occupancyCard(rows) {
    rows = rows || [];
    const body = rows.length ? rows.map(p => {
      const [sc,sb] = TINT[p.sc] || TINT.green;
      return `<div style="display:flex;align-items:center;gap:16px;padding:13px 4px;border-bottom:1px solid #23292f">
        <div style="width:190px;flex-shrink:0;min-width:0"><div style="font-size:12.5px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${p.name}</div>
          <div style="font-size:11px;color:${C.sec2};margin-top:1px">${p.loc}</div></div>
        <div style="flex:1;height:9px;background:${C.rowHover};border-radius:5px;overflow:hidden"><div style="height:100%;width:${p.pct}%;background:${sc};border-radius:5px;transition:width .7s ease"></div></div>
        <div style="width:42px;text-align:right;font-size:12.5px;font-weight:650;flex-shrink:0">${p.pct}%</div>
        <span style="width:78px;text-align:center;flex-shrink:0;font-size:11px;font-weight:600;padding:3px 0;border-radius:20px;color:${sc};background:${sb}">${p.status}</span></div>`;
    }).join('') : this.emptyRow('No buildings with units yet');
    const inner = `<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px">
        <div style="font-size:14px;font-weight:600">Portfolio Occupancy by Building</div>
        <a href="#" style="font-size:11.5px;color:${C.link};text-decoration:none;font-weight:550">Open Properties</a></div>${body}`;
    return this.cardShell(inner, '18px 18px 6px');
  }

  // ---- helpers ----
  emptyRow(msg) {
    return `<div style="padding:24px 4px;text-align:center;font-size:12px;color:${C.muted2}">${msg}</div>`;
  }
  skeleton(n, h) {
    const cards = Array(n).fill(0).map(()=>`<div style="background:${C.card};border:1px solid ${C.border};border-radius:11px;height:${h}px;opacity:.5"></div>`).join('');
    return `<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(196px,1fr));gap:14px;margin-bottom:22px">${cards}</div>`;
  }
  skelBlock(h){ return `<div style="height:${h}px;opacity:.4;margin-top:14px;background:${C.rowHover};border-radius:8px"></div>`; }

  bind() {
    this.$body.find('.seg').on('click', e => this.setPeriod($(e.currentTarget).data('period')));
    this.$body.find('.tab').on('click', e => this.setTab($(e.currentTarget).data('tab')));
  }
}
