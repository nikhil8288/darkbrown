// Execute the real route with a synthetic register larger than the old cutoff.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync('darkbrown/shell/index.html','utf8');
const source=html.slice(html.indexOf('ROUTES.invoices=()=>{'),html.indexOf('window.openI='));
let filter={},shown=[];
const INV=Array.from({length:2313},(_,n)=>({id:'INV-'+n,tn:'Tenant '+n,bn:'A',u:'U'+n,st:'Unpaid',balance:1}));
INV.push({id:'DRAFT',st:'Draft',balance:900},{id:'CANCELLED',st:'Cancelled',balance:700});
const ctx={ROUTES:{},INV,AMEND:[],qs:()=>filter,page:(...v)=>v.join(''),stat:v=>JSON.stringify(v),n0:v=>v,invBal:i=>i.balance,escA:v=>v,esc:v=>v,tbl:(cols,rows)=>{shown=rows;return '';}};
vm.createContext(ctx);vm.runInContext(source,ctx);
let out=ctx.ROUTES.invoices();assert(out.includes('["Outstanding",2313'));assert.equal(shown.length,100);assert(out.includes('Page 1 of 24'));
filter={q:'INV-2312'};out=ctx.ROUTES.invoices();assert.equal(shown.length,1);assert.equal(shown[0].id,'INV-2312');
filter={p:'24'};out=ctx.ROUTES.invoices();assert.equal(shown.length,15);assert(out.includes('Page 24 of 24'));
filter={q:'does-not-exist',p:'24'};out=ctx.ROUTES.invoices();assert.equal(shown.length,0);assert(out.includes('Page 1 of 1'));
console.log('PASS: complete totals, draft/cancel exclusion, search beyond 1000, last/empty pages');
