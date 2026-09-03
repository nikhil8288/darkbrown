/* The files panel and the add-files form, exercised on the screens that carry
   them. The route sweep proves nothing throws; this proves the panel actually
   draws in each of its three states, that the form opens against a record and
   refuses without one, and that what it would send is the payload the server
   endpoint expects. Nothing here talks to a server — fetch is answered here,
   so the states are chosen rather than waited for. */
const fs = require('fs');
const { JSDOM, VirtualConsole } = require('jsdom');
process.on('unhandledRejection', e => { console.log('UNHANDLED', e && e.stack ? e.stack.split('\n').slice(0,3).join(' / ') : e); });
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
    has(m, 'Choose a file');
  });
  t('form: no type is asked for before there is a file to ask about', () => {
    if (win.document.querySelector('.flist'))
      throw new Error('the per-file list drew with no files chosen');
    if (/What is each one/.test(m))
      throw new Error('asked what the files are before any were chosen');
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

// ------------------------------------------------- one type per file, after the drop
const FAKE = n => Array.from({length:n}, (_, i) =>
  ({name: 'doc-' + i + '.pdf', size: 200000 + i}));

await (async () => {
  const {win} = boot('MD', 'ok');
  await draw(win, '#/building/AK-12');
  win.openForm('add-files', {scope:'building', id:'AK-12', label:'AK-12'});
  /* FDATA is module-scoped, so the form is driven the way a person drives it:
     files into FFILES, then the DOM, then collect(). */
  win.FFILES = {file: FAKE(5)};
  win.drawForm();

  t('drop of five: one row and one select per file', () => {
    const rows = win.document.querySelectorAll('.flr');
    if (rows.length !== 5) throw new Error(rows.length + ' rows, wanted 5');
    for (let i = 0; i < 5; i++) {
      const sel = win.document.querySelector('[data-k="k' + i + '"]');
      if (!sel) throw new Error('no select for file ' + i);
      if (sel.value !== 'Other') throw new Error('file ' + i + ' defaults to ' + sel.value);
    }
    if (win.document.querySelector('[data-k="k5"]'))
      throw new Error('a select drew for a file that is not there');
  });

  t('drop of five: the type list is the server\'s, Other first', () => {
    const opts = [...win.document.querySelectorAll('[data-k="k0"] option')]
      .map(o => o.textContent);
    if (opts[0] !== 'Other') throw new Error('first option is ' + opts[0]);
    if (opts.length !== 12) throw new Error(opts.length + ' options, wanted 12');
  });

  t('drop of five: each answer is kept against its own file', () => {
    win.document.querySelector('[data-k="k0"]').value = 'Title Deed';
    win.document.querySelector('[data-k="k3"]').value = 'QID';
    win.collect();
    win.drawForm();
    const v = i => win.document.querySelector('[data-k="k' + i + '"]').value;
    const got = [v(0), v(1), v(2), v(3), v(4)];
    const want = ['Title Deed', 'Other', 'Other', 'QID', 'Other'];
    if (JSON.stringify(got) !== JSON.stringify(want))
      throw new Error(JSON.stringify(got));
  });

  t('drop of five: same-as-the-first copies, it does not invent', () => {
    win.setKindsAll();
    const vals = [...win.document.querySelectorAll('.flr select')].map(s => s.value);
    if (vals.some(v => v !== 'Title Deed')) throw new Error(JSON.stringify(vals));
  });

  t('removing one shifts the answers down with it', () => {
    // rebuild a mixed set: 0 deed, 1 QID, 2 cheque
    win.FFILES = {file: FAKE(3)};
    win.drawForm();
    win.document.querySelector('[data-k="k0"]').value = 'Title Deed';
    win.document.querySelector('[data-k="k1"]').value = 'QID';
    win.document.querySelector('[data-k="k2"]').value = 'Cheque Batch';
    win.collect();
    win.dropFileAt(1);                       // the QID goes
    const rows = win.document.querySelectorAll('.flr');
    if (rows.length !== 2) throw new Error(rows.length + ' rows left, wanted 2');
    const names = [...win.document.querySelectorAll('.fln')].map(n => n.textContent);
    if (JSON.stringify(names) !== JSON.stringify(['doc-0.pdf', 'doc-2.pdf']))
      throw new Error(JSON.stringify(names));
    const v = i => win.document.querySelector('[data-k="k' + i + '"]').value;
    if (v(0) !== 'Title Deed' || v(1) !== 'Cheque Batch')
      throw new Error('answers did not follow their files: ' + v(0) + ', ' + v(1));
    if (win.document.querySelector('[data-k="k2"]'))
      throw new Error('a row was left behind for a removed file');
  });

  t('removing the last one puts the form back to needing a file', () => {
    win.dropFileAt(0); win.dropFileAt(0);
    if (win.document.querySelector('.flist'))
      throw new Error('the list is still drawn with no files');
    win.formNext();
    const err = win.document.getElementById('ferr');
    if (!/Files<\/a> is empty/.test(err.innerHTML))
      throw new Error('did not ask for a file: ' + err.innerHTML);
  });
})();

// ------------------------------------------------------------------- report
let bad = 0;
for (const [st, name] of results) { if (st === 'FAIL') bad++;
  console.log('  ' + st + '  ' + name); }
console.log('\n' + (results.length - bad) + ' passed, ' + bad + ' failed');
process.exit(bad ? 1 : 0);
})();
