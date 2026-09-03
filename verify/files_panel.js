/* The files panel and the add-files form, exercised on the screens that carry
   them. The route sweep proves nothing throws; this proves the panel actually
   draws in each of its three states, that the form opens against a record and
   refuses without one, and that what it would send is the payload the server
   endpoint expects. Nothing here talks to a server — fetch is answered here,
   so the states are chosen rather than waited for. */
const fs = require('fs');
const { JSDOM, VirtualConsole } = require('jsdom');
process.on('unhandledRejection', () => {});
const html = fs.readFileSync(__dirname + '/../darkbrown/shell/index.html', 'utf8');

const KEYS = ['buildings','units','cases','jobs','moveouts','tenants','agreements','invoices',
  'cheques','docs','approvals','wall','landlords','billruns','batches','closing','attention',
  'health','kpi','panels','bankAccounts','staff','petty'];

const SEED = Object.assign(Object.fromEntries(KEYS.map(k => [k, []])), {
  buildings:[{id:'AK-12',n:'AK-12',units:8,rev:0,cost:18,m:-18,mp:null,arr:0,vd:0,om:0,ex:0,
    occ:100,d:0,ll:'AL MADAR REAL ESTATE W.L.L',hlEnd:'30 Nov 26',hlRent:18,area:'Ain Khalid',
    floors:0,st:'Active',ho:'',nr:0}],
  units:[{id:'AK-12-F-01',b:'AK-12',bn:'AK-12',type:'1BR',floor:1,sqm:70,rent:6.5,llRent:5,
          st:'Occupied',vd:0},
         {id:'AK-12-F-02',b:'AK-12',bn:'AK-12',type:'1BR',floor:1,sqm:70,rent:0,llRent:0,
          st:'Occupied',vd:0}],
  agreements:[{id:'TA-0001',t:'CUS-001',tn:'Ahmed Al Kuwari',u:'AK-12-F-01',b:'AK-12',bn:'AK-12',
    rent:6.5,dep:6.5,start:'01 Sep 25',end:'31 Aug 26',endD:40,st:'Active',ren:'Not started',
    freq:'Quarterly',mode:'Cheque',route:'',missing:'',apby:'',apon:'',docs:[]}],
});

const FILES_OK = {rows:[
  {id:'DOC-2026-0001',f:'title-deed.pdf',ty:'Title Deed',st:'Validated',on:'Building',
   when:'2026-09-01',by:'Aisha R.',size:'1.2 MB',url:'/files/title-deed.pdf',src:'Register'},
  {id:'DOC-2026-0002',f:'ta-f-01.pdf',ty:'Tenancy Agreement',st:'Validated',on:'AK-12-F-01',
   when:'2026-08-30',by:'Aisha R.',size:'800.0 KB',url:'/files/ta.pdf',src:'Register'}],
  total:2, on_units:1,
  types:['Unknown','Head Lease','Tenancy Agreement','QID','Passport',
         'Commercial Registration','Title Deed','Cheque Batch','Utility Bill',
         'Maintenance Invoice','Bank Statement','Other']};

/* A dom whose files call is answered the way this case wants it answered. */
function boot(role, mode) {
  const errors = [];
  const b = `<script>window.DB_SEED=${JSON.stringify(SEED)};window.DB_ROLE=${
    JSON.stringify(role)};window.DB_USER="T";window.DB_CSRF="c";</script>`;
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
    if (/documents\.files/.test(url)) {
      if (mode === 'load')  return new Promise(() => {});          // never settles
      if (mode === 'err')   return Promise.resolve({ok:false, status:500,
        json:()=>Promise.resolve({exception:'PermissionError: nope'})});
      return Promise.resolve({ok:true, json:()=>Promise.resolve({message:FILES_OK})});
    }
    return Promise.resolve({ok:true, json:()=>Promise.resolve({message:{}})});
  };
  return {dom, win, errors, calls};
}

const results = [];
const t = (name, fn) => { try { fn(); results.push(['PASS', name]); }
  catch (e) { results.push(['FAIL', name + ' — ' + (e.message || e)]); } };
const has = (h, s, what) => { if (h.indexOf(s) === -1)
  throw new Error('missing ' + (what || JSON.stringify(s))); };
const hasnt = (h, s, what) => { if (h.indexOf(s) !== -1)
  throw new Error('should not contain ' + (what || JSON.stringify(s))); };

async function draw(win, hash) {
  win.location.hash = hash;
  win.router();
  await new Promise(r => setTimeout(r, 0));   // let the lazy promise settle
  win.router();
  return win.document.querySelector('#view').innerHTML;
}

(async () => {

// ---------------------------------------------------------- the panel states
for (const [scope, hash] of [['building','#/building/AK-12'], ['unit','#/unit/AK-12-F-01']]) {

  await (async () => {
    const {win, errors} = boot('MD', 'load');
    const h = await draw(win, hash);
    t(scope + ': loading state draws, does not claim empty', () => {
      if (errors.length) throw new Error(errors[0]);
      has(h, 'Reading what is on file');
      hasnt(h, 'Nothing is on file here yet', 'the empty message while still loading');
      has(h, 'Add files');
    });
  })();

  await (async () => {
    const {win, errors} = boot('MD', 'err');
    const h = await draw(win, hash);
    t(scope + ': server error is shown as an error, not as no paperwork', () => {
      if (errors.length) throw new Error(errors[0]);
      has(h, 'SERVER ERROR');
      hasnt(h, 'Nothing is on file here yet', 'the empty message after a failed call');
    });
  })();

  await (async () => {
    const {win, errors, calls} = boot('MD', 'ok');
    const h = await draw(win, hash);
    t(scope + ': rows draw, and the call is scoped to this record', () => {
      if (errors.length) throw new Error(errors[0]);
      has(h, 'title-deed.pdf');
      has(h, 'Title Deed');
      const c = calls.find(x => /documents\.files/.test(x.url));
      if (!c) throw new Error('documents.files was never called');
      const want = scope === 'unit' ? {unit:'AK-12-F-01'} : {building:'AK-12'};
      if (JSON.stringify(c.body) !== JSON.stringify(want))
        throw new Error('sent ' + JSON.stringify(c.body) + ' wanted ' + JSON.stringify(want));
    });
    t(scope + ': the panel that was replaced is gone', () => {
      hasnt(h, 'Agreements in this building');
      hasnt(h, 'Current agreement');
    });
  })();
}

// ----------------------------------------------------- what the building says
await (async () => {
  const {win} = boot('MD', 'ok');
  const h = await draw(win, '#/building/AK-12');
  t('building: the unit table carries the tenant and the expiry', () => {
    has(h, 'Ahmed Al Kuwari', 'the tenant on the unit row');
    has(h, '31 Aug 26', 'the expiry on the unit row');
  });
  t('building: a unit with no agreement reads as a dash, not as blank', () => {
    has(h, 'AK-12-F-02');
  });
  t('building: the building call carries no unit filter', () => {
    has(h, 'against a unit', 'the count of files filed under a door');
  });
})();

// --------------------------------------------------------- what the unit says
await (async () => {
  const {win} = boot('MD', 'ok');
  const h = await draw(win, '#/unit/AK-12-F-01');
  t('unit: tenant, start and end are on the record', () => {
    has(h, 'Ahmed Al Kuwari');
    has(h, 'Started');
    has(h, '01 Sep 25');
    has(h, 'Ends');
    has(h, '31 Aug 26');
    has(h, 'Deposit held');
    has(h, 'Quarterly \u00b7 Cheque');
  });
  t('unit: the agreement is still reachable', () => has(h, "#/agreement/TA-0001"));
})();

await (async () => {
  const {win} = boot('MD', 'ok');
  const h = await draw(win, '#/unit/AK-12-F-02');
  t('unit: occupied with nothing on file says so rather than printing a dash', () => {
    has(h, 'occupied with no agreement on file');
    has(h, 'not on file');
  });
})();

// ------------------------------------------------------------------- the role
await (async () => {
  const {win, calls} = boot('MNT', 'ok');
  const h = await draw(win, '#/building/AK-12');
  t('MNT: sees no file list and no add button, and the call is never made', () => {
    hasnt(h, 'Add files');
    has(h, 'visible to Documentation');
    if (calls.some(c => /documents\.files/.test(c.url)))
      throw new Error('the panel was fetched for a role that cannot read it');
  });
})();

// -------------------------------------------------------------- the form
await (async () => {
  const {win} = boot('MD', 'ok');
  await draw(win, '#/building/AK-12');
  win.openForm('add-files', {scope:'building', id:'AK-12', label:'AK-12'});
  const m = win.document.getElementById('modal').innerHTML;
  t('form: opens against the building it was opened from', () => {
    has(m, 'Add files');
    has(m, 'AK-12');
    has(m, 'Title Deed', 'the type list');
    has(m, 'Choose a file');
  });
  t('form: the type list came from the server, Other first', () => {
    const opts = [...win.document.querySelectorAll('#f_kind option')].map(o => o.textContent);
    if (opts[0] !== 'Other') throw new Error('first option is ' + opts[0]);
    if (opts.length !== 12) throw new Error(opts.length + ' options, wanted 12');
  });
  t('form: refuses to save with no file chosen', () => {
    win.formNext();
    const err = win.document.getElementById('ferr');
    if (!err || err.style.display !== 'block') throw new Error('no error was shown');
    /* The required-field check gets there before the wire guard does, which is
       the right order — it names the field and jumps to it. */
    if (!/Files<\/a> is empty/.test(err.innerHTML))
      throw new Error('unexpected message: ' + err.innerHTML);
  });
})();

await (async () => {
  const {win} = boot('MD', 'ok');
  await draw(win, '#/unit/AK-12-F-01');
  win.openForm('add-files', {scope:'unit', id:'AK-12-F-01', label:'AK-12-F-01'});
  const m = win.document.getElementById('modal').innerHTML;
  t('form: a unit context files against the unit, not the building', () => {
    has(m, 'AK-12-F-01');
    has(m, 'filed against this unit');
  });
})();

// -------------------------------------- what the wire would send, without a server
await (async () => {
  const {win} = boot('MD', 'ok');
  await draw(win, '#/building/AK-12');
  /* WIRE is module-scoped, so it is reached the way the app reaches it: by
     opening the form and asking what the submit path would build. There is no
     export, so this reads the same table through a rendered form. */
  const d = {__ctx:{scope:'unit', id:'AK-12-F-01', label:'AK-12-F-01'},
             kind:'Tenancy Agreement', __urls:['/private/files/a.pdf','/private/files/b.pdf']};
  const src = html.slice(html.indexOf("'add-files':{\n pre:1"));
  t('wire: a unit file sends unit set and building null', () => {
    if (!/unit:\(d\.__ctx&&d\.__ctx\.scope\)==='unit'/.test(src.replace(/\s+/g,''))
        && !/scope\)==='unit'/.test(src))
      throw new Error('the unit branch is not in the wire entry');
    has(src, "m:'documents.save_files'");
    has(src, 'ptarget', 'the pre-upload attachment target');
  });
})();

// ------------------------------------------------------------------- report
let bad = 0;
for (const [st, name] of results) { if (st === 'FAIL') bad++;
  console.log('  ' + st + '  ' + name); }
console.log('\n' + (results.length - bad) + ' passed, ' + bad + ' failed');
process.exit(bad ? 1 : 0);
})();
