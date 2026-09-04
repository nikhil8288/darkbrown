/* My work, the approval screen, and the live note thread.

   The bug in the screenshot was not a missing feature: the queue was read
   fine and came back empty, and the screen reported that as "not read". So
   the checks below are mostly about telling those two apart, in both
   directions. */
const fs = require('fs');
const { JSDOM, VirtualConsole } = require('jsdom');
process.on('unhandledRejection', e =>
  console.log('UNHANDLED', e && e.stack ? e.stack.split('\n').slice(0,3).join(' / ') : e));
const html = fs.readFileSync(__dirname + '/../darkbrown/shell/index.html', 'utf8');

const KEYS = ['buildings','units','cases','jobs','moveouts','tenants','agreements','invoices',
  'cheques','docs','approvals','wall','landlords','billruns','batches','closing','attention',
  'health','kpi','panels','bankAccounts','staff','petty'];

const APPR = [{id:'SD-001',ty:'Deposit release',ref:'TA-0301 · MO-0051',amt:6.5,age:72,
               res:1,st:'Pending',why:'Move-out settled. Deductions raised: QAR 0.'},
              {id:'RUN-001',ty:'Invoice run',ref:'AK-12',amt:180,age:5,res:0,st:'Pending',
               why:'Standard monthly run, no variance against agreements.'}];

const NOTES_OK = {notes:[
  {id:'CMT-001',by:'Khayaz N.',role:'MD',when:'2026-09-03 10:00',ago:'2 hours ago',
   t:'Inspection clear, release in full.',mine:true}], count:1};

function boot(opts) {
  const o = Object.assign({approvals: APPR, failed: [], notes: 'ok', role: 'MD'}, opts);
  const seed = Object.assign(Object.fromEntries(KEYS.map(k => [k, []])), {
    approvals: o.approvals, _failed: o.failed,
    attention: [['A1','high','x','43 vacant units','portfolio/units','Vacant units']],
  });
  if (o.approvals === null) delete seed.approvals;
  const errors = [];
  const b = `<script>window.DB_SEED=${JSON.stringify(seed)};window.DB_ROLE=${
    JSON.stringify(o.role)};window.DB_USER="T";window.DB_CSRF="c";</script>`;
  const dom = new JSDOM(html.replace('<!--DB_BOOT-->', b), {
    runScripts:'dangerously', url:'https://erp.darkbrown.qa/darkbrown',
    beforeParse(w){ w.scrollTo=()=>{}; w.scrollBy=()=>{}; },
    virtualConsole: new VirtualConsole().on('jsdomError',
      e => { if(!/Not implemented/.test(e.message)) errors.push(e.message); }),
  });
  const win = dom.window;
  win.scrollTo = () => {};
  const calls = [];
  win.fetch = (url, opt) => {
    calls.push({url, body: opt && opt.body ? JSON.parse(opt.body) : null});
    if (/notes\.thread|notes\.add/.test(url)) {
      if (o.notes === 'load') return new Promise(() => {});
      if (o.notes === 'err') return Promise.resolve({ok:false, status:403,
        json:()=>Promise.resolve({exception:'PermissionError: not yours'})});
      return Promise.resolve({ok:true, json:()=>Promise.resolve({message:NOTES_OK})});
    }
    return Promise.resolve({ok:true, json:()=>Promise.resolve({message:{}})});
  };
  return {win, errors, calls};
}

const results = [];
const t = (n, fn) => { try { fn(); results.push(['PASS', n]); }
  catch (e) { results.push(['FAIL', n + ' — ' + (e.message || e)]); } };
const has = (h, s, w) => { if (h.indexOf(s) === -1) throw new Error('missing ' + (w||JSON.stringify(s))); };
const hasnt = (h, s, w) => { if (h.indexOf(s) !== -1) throw new Error('should not contain ' + (w||JSON.stringify(s))); };

async function draw(win, hash) {
  win.location.hash = hash; win.router();
  await new Promise(r => setTimeout(r, 0));
  win.router();
  return win.document.querySelector('#view').innerHTML;
}

(async () => {

// ------------------------------------------------- empty is not the same as unread
await (async () => {
  const {win, errors} = boot({approvals: []});
  const h = await draw(win, '#/mywork');
  t('My work: an empty queue reads as nothing waiting, not as NOT WIRED', () => {
    if (errors.length) throw new Error(errors[0]);
    has(h, 'Nothing is waiting on you');
    hasnt(h, 'NOT WIRED');
    hasnt(h, 'queue not read');
    has(h, '>0<', 'a zero count on the tile rather than a dash');
  });
})();

await (async () => {
  const {win} = boot({approvals: null, failed: ['approvals']});
  const h = await draw(win, '#/mywork');
  t('My work: a queue that genuinely failed still says NOT WIRED', () => {
    has(h, 'NOT WIRED');
    has(h, 'queue not read');
  });
})();

await (async () => {
  const {win} = boot({approvals: [], failed: ['approvals']});
  const h = await draw(win, '#/mywork');
  t('My work: a key present but named in _failed is not trusted', () => {
    has(h, 'NOT WIRED');
  });
})();

await (async () => {
  const {win} = boot({});
  const h = await draw(win, '#/mywork');
  t('My work: a populated queue lists its rows', () => {
    has(h, 'SD-001'); has(h, 'Deposit release');
    hasnt(h, 'NOT WIRED');
    has(h, 'over 48h');
  });
})();

// ------------------------------------------------------------- the note thread
await (async () => {
  const {win, calls} = boot({});
  const h = await draw(win, '#/approval/SD-001');
  t('approval: the thread is fetched against the record, not the category', () => {
    const c = calls.find(x => /notes\.thread/.test(x.url));
    if (!c) throw new Error('notes.thread was never called');
    if (JSON.stringify(c.body) !== JSON.stringify({doctype:'Security Deposit', name:'SD-001'}))
      throw new Error('sent ' + JSON.stringify(c.body));
  });
  t('approval: notes render with author, role and age', () => {
    has(h, 'Inspection clear, release in full.');
    has(h, 'Khayaz N.'); has(h, '2 hours ago');
  });
  t('approval: the composer has no role picker when live', () => {
    if (win.document.getElementById('ntrole'))
      throw new Error('the role dropdown is still offered on a live site');
    has(h, 'Signed as');
    has(h, 'kept on the record');
  });
  t('approval: nothing is invented about supporting records', () => {
    hasnt(h, '3 validated');
    hasnt(h, 'Prior approvals');
    hasnt(h, 'workflow 2E');
    has(h, 'Security Deposit · SD-001');
  });
  t('approval: a reserved category says so', () => has(h, 'cannot be delegated'));
})();

await (async () => {
  const {win} = boot({notes: 'load'});
  const h = await draw(win, '#/approval/SD-001');
  t('approval: a thread still loading does not claim there are no notes', () => {
    has(h, 'Reading the trail');
    hasnt(h, 'No notes yet');
  });
})();

await (async () => {
  const {win} = boot({notes: 'err'});
  const h = await draw(win, '#/approval/SD-001');
  t('approval: a refused thread reads as an error, not as an empty trail', () => {
    has(h, 'SERVER ERROR');
    hasnt(h, 'No notes yet');
    hasnt(h, 'Add note', 'a composer over a thread that could not be read');
  });
})();

// ------------------------------------------------------------------ posting
await (async () => {
  const {win, calls} = boot({});
  await draw(win, '#/approval/SD-001');
  t('posting: an empty note is not sent', () => {
    win.document.getElementById('ntbox').value = '   ';
    win.postNote('Security Deposit', 'SD-001', 'notes:Security Deposit:SD-001');
    if (calls.some(c => /notes\.add/.test(c.url)))
      throw new Error('an empty note went to the server');
  });
  t('posting: a real note is sent with its record, and the button locks', () => {
    win.document.getElementById('ntbox').value = 'Approved on condition.';
    win.postNote('Security Deposit', 'SD-001', 'notes:Security Deposit:SD-001');
    const c = calls.find(x => /notes\.add/.test(x.url));
    if (!c) throw new Error('notes.add was never called');
    if (c.body.text !== 'Approved on condition.') throw new Error(JSON.stringify(c.body));
    if (c.body.doctype !== 'Security Deposit' || c.body.name !== 'SD-001')
      throw new Error(JSON.stringify(c.body));
    if (!win.document.getElementById('ntsave').disabled)
      throw new Error('the save button stayed live, so a double click files twice');
  });
})();

// --------------------------------------------------- a screen with no record
await (async () => {
  const {win, calls} = boot({});
  const h = await draw(win, '#/mywork');
  t('a thread is never fetched for a screen that has no doctype behind it', () => {
    // the ledger journal route calls noteThread with no doctype
    win.location.hash = '#/journal/JV-1500'; win.router();
    const bad = calls.filter(c => /notes\.thread/.test(c.url))
      .some(c => !c.body || !c.body.doctype);
    if (bad) throw new Error('a thread was fetched with no doctype');
  });
})();

let bad = 0;
for (const [st, n] of results) { if (st === 'FAIL') bad++; console.log('  ' + st + '  ' + n); }
console.log('\n' + (results.length - bad) + ' passed, ' + bad + ' failed');
process.exit(bad ? 1 : 0);
})();
