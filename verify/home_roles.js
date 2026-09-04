/* Home, five readings of it, and the navigation policy around it.

   Two things are being proved. That each role's home is built from payload it
   actually got - an array the server never sent must read as unread, not as
   zero. And that the policy is consistent: a route hidden from the sidebar is
   a route that is also refused, and nobody can be left on a screen they cannot
   open. */
const fs = require('fs');
const { JSDOM, VirtualConsole } = require('jsdom');
process.on('unhandledRejection', e =>
  console.log('UNHANDLED', e && e.stack ? e.stack.split('\n').slice(0,3).join(' / ') : e));
const html = fs.readFileSync(__dirname + '/../darkbrown/shell/index.html', 'utf8');

const KEYS = ['buildings','units','cases','jobs','moveouts','tenants','agreements','invoices',
  'cheques','docs','approvals','wall','landlords','billruns','batches','closing','attention',
  'health','kpi','panels','bankAccounts','staff','petty'];

const FULL = {
  buildings:[{id:'AK-12',n:'AK-12',units:8,rev:40,cost:18,m:22,occ:88,arr:0,vd:0,om:0,ex:0,
              d:0,ll:'AL MADAR',hlEnd:'30 Nov 26',hlRent:18,area:'Ain Khalid',floors:0,
              st:'Active',ho:'',nr:0}],
  units:[{id:'AK-12-F-01',b:'AK-12',bn:'AK-12',type:'1BR',floor:1,sqm:70,rent:6.5,llRent:5,
          st:'Occupied',vd:0},
         {id:'AK-12-F-02',b:'AK-12',bn:'AK-12',type:'1BR',floor:1,sqm:70,rent:0,llRent:4.2,
          st:'Vacant',vd:41},
         {id:'AK-12-G-01',b:'AK-12',bn:'AK-12',type:'2BR',floor:0,sqm:95,rent:0,llRent:6,
          st:'Not Ready',vd:12}],
  agreements:[{id:'TA-0001',t:'C1',tn:'Ahmed Al Kuwari',u:'AK-12-F-01',b:'AK-12',bn:'AK-12',
               rent:6.5,dep:6.5,start:'01 Sep 25',end:'30 Sep 26',endD:26,st:'Active',
               ren:'Not started',freq:'Quarterly',mode:'Cheque',missing:'',docs:[]},
              {id:'TA-0002',t:'C2',tn:'Noora Al-Kaabi',u:'AK-12-G-01',b:'AK-12',bn:'AK-12',
               rent:7,dep:7,start:'01 Oct 25',end:'30 Sep 27',endD:390,st:'Pending',
               ren:'\u2014',freq:'Monthly',mode:'Cash',missing:'QID not captured',docs:[]}],
  approvals:[{id:'SD-001',ty:'Deposit release',ref:'TA-0301',amt:6.5,age:72,res:1,st:'Pending',why:'x'},
             {id:'RUN-001',ty:'Invoice run',ref:'AK-12',amt:180,age:5,res:0,st:'Pending',why:'y'}],
  cases:[{id:'CASE-1',tn:'Ahmed',amt:18,stage:'Promise broken',age:44,owner:'Anoop M.',b:'AK-12'},
         {id:'CASE-2',tn:'Sara',amt:4,stage:'Reminder sent',age:9,owner:'Anoop M.',b:'AK-12'}],
  jobs:[{id:'MR-1',b:'AK-12',bn:'AK-12',u:'AK-12-F-01',t:'Chiller down',cat:'HVAC',pr:'Emergency',
         age:21,st:'Open',cost:3.2,ceil:1},
        {id:'MR-2',b:'AK-12',bn:'AK-12',u:'',t:'Lift service',cat:'Lift',pr:'Medium',
         age:3,st:'Assigned',cost:0.4,ceil:0},
        {id:'MR-3',b:'AK-12',bn:'AK-12',u:'',t:'Done',cat:'Other',pr:'Low',age:30,st:'Closed',cost:0,ceil:0}],
  cheques:[{id:'CHQ-1',no:'64632',tn:'AL MADAR',bank:'QNB',amt:50,mat:'01 Sep 26',matD:2,st:'Received'},
           {id:'CHQ-2',no:'64633',tn:'Ahmed',bank:'Doha',amt:6.5,mat:'20 Aug 26',matD:-9,
            st:'Returned',reason:'Insufficient Funds'},
           {id:'CHQ-3',no:'64634',tn:'Sara',bank:'QNB',amt:7,mat:'30 Nov 26',matD:80,st:'Received'}],
  invoices:[{id:'INV-1',tn:'Ahmed',amt:6.5,paid:0,due:'01 Aug 26',dueD:-34,st:'Overdue',b:'AK-12'},
            {id:'INV-2',tn:'Sara',amt:7,paid:7,due:'01 Sep 26',dueD:2,st:'Paid',b:'AK-12'}],
  docs:[{id:'DOC-1',f:'qid.jpg',ty:'QID',st:'Needs review',conf:72,by:'Aisha R.',when:'Today',link:'TN-1'},
        {id:'DOC-2',f:'ta.pdf',ty:'Tenant Agreement',st:'Validated',conf:97,by:'Aisha R.',when:'23 Jul',link:'TA-0001'}],
  moveouts:[{id:'MO-1',tn:'Ahmed',u:'AK-12-F-01',step:'Inspection',status:'Inspection',out:'30 Sep 26'}],
  attention:[['A1','high','x','43 vacant units','portfolio/units','Vacant units']],
};

function boot(role, seedOverride) {
  const seed = Object.assign(Object.fromEntries(KEYS.map(k => [k, []])), FULL,
                             seedOverride || {});
  for (const k of Object.keys(seedOverride || {}))
    if (seedOverride[k] === undefined) delete seed[k];
  const errors = [];
  const b = `<script>window.DB_SEED=${JSON.stringify(seed)};window.DB_ROLE=${
    JSON.stringify(role)};window.DB_USER="T";window.DB_CSRF="c";</script>`;
  const dom = new JSDOM(html.replace('<!--DB_BOOT-->', b), {
    runScripts:'dangerously', url:'https://erp.darkbrown.qa/darkbrown',
    beforeParse(w){ w.scrollTo=()=>{}; w.scrollBy=()=>{};
                    w.fetch=()=>Promise.resolve({ok:true,json:()=>Promise.resolve({message:{}})}); },
    virtualConsole: new VirtualConsole().on('jsdomError',
      e => { if(!/Not implemented/.test(e.message)) errors.push(e.message); }),
  });
  const win = dom.window;
  win.scrollTo = () => {};
  win.fetch = () => Promise.resolve({ok:true, json:()=>Promise.resolve({message:{rows:[]}})});
  return {win, errors};
}

const results = [];
const t = (n, fn) => { try { fn(); results.push(['PASS', n]); }
  catch (e) { results.push(['FAIL', n + ' — ' + (e.message || e)]); } };
const has = (h,s,w) => { if (h.indexOf(s)===-1) throw new Error('missing '+(w||JSON.stringify(s))); };
const hasnt = (h,s,w) => { if (h.indexOf(s)!==-1) throw new Error('should not contain '+(w||JSON.stringify(s))); };

function draw(win, hash) {
  if (hash !== null) win.location.hash = hash;
  win.router();
  return win.document.querySelector('#view').innerHTML;
}

// ------------------------------------------------------------------ landing
for (const [role, want] of [['MD','MD Command Centre'],['GM','General Manager · home'],
                            ['ACC','Accounts · home'],['DOC','Documentation · home'],
                            ['MNT','Maintenance · home']]) {
  const {win, errors} = boot(role);
  t(role + ': lands on its own home with no hash', () => {
    if (errors.length) throw new Error(errors[0]);
    win.location.hash = '';
    win.router();
    if (win.document.getElementById('ptop').textContent !== want)
      throw new Error('landed on ' + win.document.getElementById('ptop').textContent);
  });
}

// ------------------------------------------------------------ what each sees
(() => {
  const {win} = boot('GM');
  const h = draw(win, '#/home');
  t('GM home: approvals split, reserved counted but not offered', () => {
    has(h, 'RUN-001', 'the GM-decidable approval');
    has(h, 'reserved to the');
    has(h, 'Waiting on me');
  });
  t('GM home: occupancy, expiry and escalation are all present', () => {
    has(h, 'AK-12-F-02', 'the vacant unit');
    has(h, 'bleed');
    has(h, 'TA-0001', 'the tenancy expiring inside 90 days');
    has(h, 'TA-0002', 'the tenancy pending activation');
    has(h, 'QID not captured');
    has(h, 'CASE-1', 'the broken promise');
    hasnt(h, 'CASE-2', 'a case that is not escalating');
  });
})();

(() => {
  const {win} = boot('ACC');
  const h = draw(win, '#/home');
  t('Accounts home: cheques due, returned, and what is past due', () => {
    has(h, '64632', 'the cheque maturing in two days');
    hasnt(h, '64634', 'a cheque 80 days out');
    has(h, 'Insufficient Funds');
    has(h, 'INV-1', 'the overdue invoice');
    hasnt(h, 'INV-2', 'an invoice already paid');
  });
})();

(() => {
  const {win} = boot('DOC');
  const h = draw(win, '#/home');
  t('Documentation home: the review queue and the short packs', () => {
    has(h, 'qid.jpg');
    has(h, '72%');
    hasnt(h, 'ta.pdf', 'a document already validated');
    has(h, 'TA-0002', 'the agreement missing its pack');
    has(h, 'under 85% confidence');
  });
})();

(() => {
  const {win} = boot('MNT');
  const h = draw(win, '#/home');
  t('Maintenance home: open jobs oldest first, ceiling, not-ready units', () => {
    has(h, 'MR-1'); has(h, 'MR-2');
    hasnt(h, 'MR-3', 'a closed job');
    has(h, 'Chiller down');
    has(h, 'reserved to the Managing Director');
    has(h, 'AK-12-G-01', 'the Not Ready unit');
    has(h, 'Where the work is');
  });
})();

// ------------------------------------- an array never sent is not a zero
(() => {
  const {win} = boot('MNT', {jobs: undefined});
  const h = draw(win, '#/home');
  t('a payload key the server never sent reads as unread, not as none', () => {
    has(h, 'NOT WIRED');
    has(h, 'it is unread');
    hasnt(h, 'No job is open', 'an empty state over data that was never returned');
  });
})();

(() => {
  const {win} = boot('MNT', {_failed: ['jobs']});
  const h = draw(win, '#/home');
  t('a key present but named in _failed is not counted either', () => {
    has(h, 'NOT WIRED');
  });
})();

(() => {
  const {win} = boot('MNT', {jobs: []});
  const h = draw(win, '#/home');
  t('a key that came back genuinely empty says so plainly', () => {
    has(h, 'No job is open');
    hasnt(h, 'NOT WIRED');
    has(h, '>0<', 'a zero on the tile');
  });
})();

// ------------------------------------------------------------------ policy
const DENIED = {GM:['dash'], ACC:['dash','approvals','maint'],
                DOC:['dash','cheques','recon','trial'],
                MNT:['dash','cheques','coa','cases','agreements']};
for (const [role, routes] of Object.entries(DENIED)) {
  const {win} = boot(role);
  for (const r of routes) {
    t(role + ': ' + r + ' is refused and hidden together', () => {
      const h = draw(win, '#/' + r);
      has(h, 'cannot open this area', 'the block screen');
      const nv = [...win.document.querySelectorAll('.nv')].find(n => n.dataset.r === r);
      if (nv && nv.style.display !== 'none')
        throw new Error('still in the sidebar');
    });
  }
}

(() => {
  const {win} = boot('MNT');
  t('nobody is ever shut out of their own home', () => {
    for (const role of ['MD','GM','ACC','DOC','MNT']) {
      win.ROLEV = role;
      if (!win.roleCan('home')) throw new Error(role + ' cannot open home');
    }
  });
  t('the block screen offers a way back that the role can actually open', () => {
    const h = draw(win, '#/coa');
    has(h, 'Back to my home');
    hasnt(h, 'shareholder movement', 'the owner-balance explanation on a books refusal');
  });
})();

(() => {
  const {win} = boot('GM');
  t('an unknown hash lands on the home, not on a refused Command Centre', () => {
    const h = draw(win, '#/nosuchroute');
    hasnt(h, 'cannot open this area');
    has(h, 'Waiting on me');
  });
})();

(() => {
  const {win} = boot('MD');
  t('the old #/mywork hash still resolves', () => {
    const h = draw(win, '#/mywork');
    has(h, 'Awaiting me');
    hasnt(h, 'could not be drawn');
  });
})();

let bad = 0;
for (const [st, n] of results) { if (st === 'FAIL') bad++; console.log('  ' + st + '  ' + n); }
console.log('\n' + (results.length - bad) + ' passed, ' + bad + ' failed');
process.exit(bad ? 1 : 0);
