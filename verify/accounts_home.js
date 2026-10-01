/* Synthetic DOM/route checks; no real financial data and no server writes. */
const fs=require('fs'),assert=require('assert'),{JSDOM,VirtualConsole}=require('jsdom');
let html=fs.readFileSync('darkbrown/shell/index.html','utf8');
const age={gross:100,credits:-20,net:80,as_on:'2026-09-30',buckets:{current:20,b30:30,b60:10,b90:0,b90p:40},rows:[],note:'Dated ledger'};
const data={frm:'2026-08-01',to:'2026-09-30',company:'Synthetic',currency:'QAR',notes:['Provisional source costs'],
 pl:{income:200,expense:260,net:-60,margin:-30,groups:[{label:'Costs',total:260,rows:[]}]},
 monthly:[{month:'2026-08',income:100,expense:140,net:-40},{month:'2026-09',income:100,expense:120,net:-20}],
 buildings:[{building:'SYN-B',income:200,expense:240,net:-40,margin:-20},{building:'Unassigned / company costs',income:0,expense:20,net:-20,margin:null}],
 positions:[{kind:'cash',code:'Bank',label:'Bank',amount:12},{kind:'deposits',code:'Deposit',label:'Deposit liability',amount:5}],
 cash_flow:{opening:10,closing:12,net:2,buckets:[{label:'Operating',total:2}],reconciled:true},
 balance_sheet:{balanced:true},receivables:age,payables:age,
 occupancy:{units:2,occupied:1,pct:50,as_on:'2026-10-01',note:'Latest only'}};
const calls=[],errors=[];
const seed={buildings:[],units:[],_failed:[]};
html=html.replace('<!--DB_BOOT-->',`<script>window.DB_SEED=${JSON.stringify(seed)};window.DB_ROLE='ACC';window.DB_USER='Synthetic';window.DB_CSRF='c';</script>`);
const dom=new JSDOM(html,{url:'https://erp.darkbrown.qa/darkbrown#/home?start=2026-08&end=2026-09',runScripts:'dangerously',
 virtualConsole:new VirtualConsole().on('jsdomError',e=>{if(!/Not implemented/.test(e.message))errors.push(e.message)}),
 beforeParse(w){w.scrollTo=()=>{};w.scrollBy=()=>{};w.fetch=async(url,opts)=>{calls.push([url,opts]);return {ok:true,json:async()=>({message:url.includes('reports.catalogue')?{packs:[{key:'arrears',title:'Synthetic ageing',description:'Synthetic',source:'Synthetic'}],buildings:[],default_from:'2026-10-01',default_to:'2026-10-01'}:url.includes('reports.run')?{title:'Synthetic ageing',columns:[],rows:[],count:0,from:JSON.parse(opts.body).frm,to:JSON.parse(opts.body).to}:url.includes('accounts_home.overview')?data:url.includes('statements.profit_and_loss')?{...data.pl,frm:data.frm,to:data.to,revenue:{rows:[],total:200},sections:[{rows:[],total:200},{rows:[],total:260}]}:url.includes('accounting.voucher')?{id:'SYN-EXACT',d:'2026-08-01',desc:'Requested source',vt:'Journal Entry',lines:[['A','Asset',1,0],['E','Equity',0,1]]}:url.includes('accounting.books')?{coa:[],jrn:[],groups:{}}:{}})}};}});
const w=dom.window,tick=()=>new Promise(r=>setTimeout(r,15));
(async()=>{
 await tick();w.router();
 const view=()=>w.document.querySelector('#view');
 assert(view().textContent.includes('Financial overview'));
 assert(view().textContent.includes('Provisional source costs'));
 assert(view().textContent.includes('-60.00'));
 const rects=[...view().querySelectorAll('svg rect')];assert.equal(rects.length,6);
 rects.forEach(x=>assert(+x.getAttribute('height')>=0));
 assert(view().textContent.includes('Cash & bank'));
 assert(!view().textContent.includes('undefined'));
 const href=view().querySelector('a[href*="accounts-report/building?"]').getAttribute('href');
 assert(href.includes('building=SYN-B')&&href.includes('start=2026-08')&&!href.includes('?building=SYN-B?'));
 w.go('#/accounts-report/buildings');w.qsSet('building','SYN-B');
 const previous=w.location.hash;
 w.go('#/pl');await tick();
 assert(w.location.hash.includes('start=2026-08')&&w.location.hash.includes('end=2026-09'));
 w.appBack();await tick();assert.equal(w.location.hash,previous);
 assert.equal(w.qs().building,'SYN-B');
 assert.equal(w.document.querySelector('[aria-label="Building breakdown"]').value,'SYN-B');
 w.go('#/journal/SYN-EXACT');await tick();w.router();await tick();
 assert(view().textContent.includes('Requested source'));
 assert(calls.some(([u])=>u.includes('accounting.voucher')));
 w.go('#/unit/Synthetic unit');assert.equal(w.history.state.dbNav.hash,w.location.hash);
 w.go('#/home?start=2026-08&end=2026-09');await tick();
 w.go('#/reports');await tick();w.rptRun('arrears');await tick();
 const originalPack=w.location.hash;
 w.rptSet('from','2026-07-01');await tick();assert.equal(w.RPT.from,'2026-07-01');
 w.appBack();await tick();assert.equal(w.location.hash,originalPack);assert.equal(w.RPT.from,'2026-10-01');
 assert(w.document.querySelector('#view').textContent.includes('Synthetic ageing'));
 w.go('#/home?start=2026-08&end=2026-09');await tick();
 w.acctPreset('m1');assert(!w.location.hash.includes('start='));
 w.go('#/home?start=2026-10&end=2026-10');assert.equal(w.acctPeriod().to,new Date().toISOString().slice(0,10));
 await tick();
 assert.equal(errors.length,0,errors.join('\n'));
 dom.window.close();console.log('PASS live-data summaries, losses, URL month filters, nested Back, source-voucher fetch and preset reset');
})().catch(e=>{dom.window.close();console.error(e);process.exitCode=1});
