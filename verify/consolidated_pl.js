/* Actual shell routes with synthetic endpoint responses. No ERP writes. */
const fs=require('fs'),assert=require('assert'),{JSDOM,VirtualConsole}=require('jsdom');
const source=fs.readFileSync('darkbrown/shell/index.html','utf8');
const cols=[['income','Revenue'],['head_lease','Head Lease Rent'],['cos','Cost of Sales'],['gross','Gross Profit'],['staff','Staff Cost'],['operating','Operating Expenses'],['depreciation','Depreciation & Amortisation'],['bank','Bank Charges'],['other','Other Expenses'],['net','Net Profit / Loss']].map(([key,label])=>({key,label}));
const values={income:100,head_lease:80,cos:30,gross:-10,staff:10,operating:2,depreciation:0,bank:1,other:0,net:-23};
const report={company:'Synthetic',currency:'QAR',frm:'2026-08-01',to:'2026-09-30',columns:cols,reconciled:true,notes:['Provisional source costs'],
 months:['2026-08','2026-09'].map(month=>({month,rows:[{building:'SYN-B',label:'SYN-B',...values},{building:'__company__',label:'Company / unassigned costs',...Object.fromEntries(cols.map(c=>[c.key,0]))}],total:values})),
 total:Object.fromEntries(cols.map(c=>[c.key,2*values[c.key]]))};
const calls=[],errors=[];
function boot(role='ACC'){
 return new JSDOM(source.replace('<!--DB_BOOT-->',`<script>window.DB_SEED={buildings:[],units:[],_failed:[]};window.DB_ROLE='${role}';window.DB_USER='Synthetic';window.DB_CSRF='c';</script>`),{
  url:'https://erp.darkbrown.qa/darkbrown#/consolidated?start=2026-08&end=2026-09',runScripts:'dangerously',
  virtualConsole:new VirtualConsole().on('jsdomError',e=>{if(!/Not implemented/.test(e.message))errors.push(e.message)}),
  beforeParse(w){w.scrollTo=()=>{};w.scrollBy=()=>{};w.fetch=async(url,opts)=>{
   const args=JSON.parse(opts.body||'{}');calls.push({url,args});
   let data={};
   if(url.includes('consolidated_pl.report'))data=report;
   if(url.includes('consolidated_pl.cell'))data={...args,frm:'2026-08-01',to:'2026-08-31',building_label:'SYN-B',label:'Net Profit / Loss',total:-23,entries:450,has_more:args.page<4,notes:report.notes,
    accounts:[{account:'H',label:'Head Lease Rent',amount:-80},{account:'I',label:'Rent Income',amount:100}],
    rows:[{account:'I',posting_date:'2026-08-15',voucher_type:'Journal Entry',voucher_no:'SYN-EXACT',debit:0,credit:100}]};
   if(url.includes('accounting.voucher'))data={id:'SYN-EXACT',d:'2026-08-15',desc:'Exact selected source',vt:'Journal Entry',lines:[['A','Asset',1,0],['E','Equity',0,1]]};
   if(url.includes('statements.profit_and_loss'))data={...values,expense:123,margin:-23,frm:'2026-08-01',to:'2026-09-30',notes:[],revenue:{rows:[],total:100},groups:[],sections:[]};
   if(url.includes('accounting.books'))data={coa:[],jrn:[],groups:{}};
   return {ok:true,json:async()=>({message:data})};
  };}
 });
}
const tick=()=>new Promise(r=>setTimeout(r,25));
(async()=>{
 const dom=boot(),w=dom.window,view=()=>w.document.querySelector('#view');
 await tick();w.router();await tick();
 assert.equal(view().querySelectorAll('input[type="month"]').length,2);
 assert(view().textContent.includes('Apply filters'));
 assert(!view().querySelector('.ptoggle'));
 assert(view().textContent.includes('Provisional source costs'));
 assert.equal(view().querySelectorAll('.cpl-month').length,2);
 assert.equal(view().querySelectorAll('.cpl-total').length,2);
 assert(view().querySelector('.cpl-range-total').textContent.includes('-46.00'));
 const link=view().querySelector('a[href*="bucket=net"]');
 assert(link.getAttribute('href').includes('month=2026-08&building=SYN-B&bucket=net&start=2026-08&end=2026-09'));
 assert(link.classList.contains('cpl-loss'));
 view().querySelector('#cpl-table-scroll').scrollLeft=330;w.cplRememberX(330);
 const matrix=w.location.hash;
 link.click();await tick();w.router();await tick();
 assert.equal(calls.find(c=>c.url.includes('consolidated_pl.cell')).args.building,'SYN-B');
 assert(view().textContent.includes('-80.00')&&view().textContent.includes('450'));
 view().querySelector('.ah-open').click();await tick();w.router();await tick();
 assert(view().textContent.includes('Exact selected source'));
 const voucher=calls.find(c=>c.url.includes('accounting.voucher')).args;
 assert(Object.values(voucher).includes('SYN-EXACT')&&Object.values(voucher).includes('Journal Entry'));
 w.appBack();await tick();w.router();await tick();
 assert(w.location.hash.startsWith('#/plcell?'));
 [...view().querySelectorAll('button')].find(b=>b.textContent==='Next page').click();await tick();w.router();await tick();
 assert(calls.some(c=>c.url.includes('consolidated_pl.cell')&&c.args.page===1));
 w.appBack();await tick();w.appBack();await tick();w.router();await tick();
 assert.equal(w.location.hash,matrix);
 assert.equal(view().querySelector('#cpl-table-scroll').scrollLeft,330);
 view().querySelector('a[aria-current="page"]').previousElementSibling.click();await tick();w.router();await tick();
 assert(w.location.hash.startsWith('#/pl?start=2026-08&end=2026-09'));
 assert.equal(view().querySelectorAll('input[type="month"]').length,2);
 assert(!view().querySelector('.ptoggle'));
 assert.equal(errors.length,0,errors.join('\n'));
 dom.window.close();
 for(const role of ['DOC','MNT']){
  const denied=boot(role);await tick();assert(!denied.window.document.querySelector('.cpl-table'));denied.window.close();
 }
 console.log('PASS desktop matrix, range controls, losses, exact source selection, pagination, role denial and Back with horizontal scroll');
})().catch(e=>{console.error(e);process.exitCode=1});
