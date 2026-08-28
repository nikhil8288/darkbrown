const fs = require('fs');
const { JSDOM } = require('jsdom');
process.on('unhandledRejection', () => {});   // jsdom teardown noise
const html = fs.readFileSync(__dirname + '/../darkbrown/shell/index.html', 'utf8');

// the real route table
const ROUTES = [...new Set([...html.matchAll(/ROUTES\.([a-zA-Z0-9_]+)\s*=/g)].map(m => m[1]))].sort();

const KEYS = ['buildings','units','cases','jobs','moveouts','tenants','agreements','invoices',
  'cheques','docs','approvals','wall','landlords','billruns','batches','closing','attention',
  'health','kpi','panels','bankAccounts','staff','petty'];

const STATES = {
  // NEW behaviour: every panel present and genuinely empty
  'new  empty-book  {k:[] for all}': Object.fromEntries(KEYS.map(k => [k, []])),
  // OLD behaviour on an empty database: seed() returned {}
  'old  empty-book  {}': {},
  // populated, using the exact key shape api.app emits
  'populated (real row shape)': Object.assign(Object.fromEntries(KEYS.map(k => [k, []])), {
      buildings:[{id:'Al Sadd',n:'Al Sadd',units:12,rev:180,cost:140,m:40,mp:22,arr:0,
                  vd:0,om:0,ex:0,occ:92,d:0,ll:'SUP-001',hlEnd:'2027-06-30',hlRent:140,
                  area:'Al Sadd',floors:4,st:'Active',ho:'2024-01-01',nr:0}],
      units:[{id:'Al Sadd-101',b:'Al Sadd',bn:'Al Sadd',type:'2BR',floor:1,sqm:90,
              rent:6.5,llRent:5,st:'Occupied',vd:0}],
  }),
  // OLD behaviour, keys omitted entirely for empty panels
  'old  keys-omitted  {buildings only}': {
      buildings:[{id:'Al Sadd',n:'Al Sadd',units:12,rev:180,cost:140,m:40,mp:22,arr:0,
                  vd:0,om:0,ex:0,occ:92,d:0,ll:'SUP-001',hlEnd:'2027-06-30',hlRent:140,
                  area:'Al Sadd',floors:4,st:'Active',ho:'2024-01-01',nr:0}]},
  // NEW behaviour with a failure recorded
  'new  with _failed': Object.assign(Object.fromEntries(KEYS.map(k => [k, []])),
      {_failed:['cheques','kpi'], _errors:{cheques:'OperationalError: x', kpi:'KeyError: y'}}),
};

const results = [];
for (const role of ['MD','GM','ACC','DOC','MNT']) {
  for (const [state, seed] of Object.entries(STATES)) {
    const boot = `<script>window.DB_SEED=${JSON.stringify(seed)};window.DB_ROLE=${JSON.stringify(role)};window.DB_USER="T";window.DB_CSRF="c";</script>`;
    const errors = [];
    const dom = new JSDOM(html.replace('<!--DB_BOOT-->', boot), {
      runScripts: 'dangerously', url: 'https://erp.darkbrown.qa/darkbrown',
      beforeParse(w) { w.scrollTo = () => {}; w.scrollBy = () => {};
                       w.fetch = () => Promise.resolve({ok:true, json:()=>Promise.resolve({})}); },
      virtualConsole: new (require('jsdom').VirtualConsole)()
        .on('jsdomError', e => { if (!/Not implemented/.test(e.message))
                                   errors.push('BOOT ' + e.message); }),
    });
    const win = dom.window;
    win.scrollTo = () => {};
    win.fetch = () => Promise.resolve({ ok: true, json: () => Promise.resolve({}) });

    const bootOk = typeof win.router === 'function';
    const live = win.DB_LIVE;
    let broken = [];
    if (bootOk) {
      for (const r of ROUTES) {
        win.location.hash = '#/' + r;
        try {
          win.router();
          const v = win.document.querySelector('#view');
          if (v && /uw-tag">ERROR|could not be drawn/.test(v.innerHTML)) broken.push(r);
        } catch (e) { broken.push(r + '(threw:' + e.message + ')'); }
      }
    }
    results.push({ role, state, bootOk, live, broken, errors });
    dom.window.close();
  }
}

console.log(`routes: ${ROUTES.length}   role x state combinations: ${results.length}`);
console.log(`total route renders: ${ROUTES.length * results.length}\n`);
let bad = 0;
for (const r of results) {
  const ok = r.bootOk && r.live === true && r.broken.length === 0 && r.errors.length === 0;
  if (!ok) bad++;
  console.log(`  ${ok ? 'PASS' : 'FAIL'}  [${r.role}] ${r.state}`
    + `  boot=${r.bootOk} DB_LIVE=${r.live} brokenRoutes=${r.broken.length}`);
  if (r.errors.length) console.log(`          ${r.errors[0].slice(0, 140)}`);
  if (r.broken.length) console.log(`          ${r.broken.slice(0, 8).join(', ')}`);
}
console.log(`\n${results.length - bad} passed, ${bad} failed`);
