/* Synthetic selected-period and signed-chart regression; no private figures. */
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync('darkbrown/shell/index.html','utf8');
function between(a,b){return html.slice(html.indexOf(a),html.indexOf(b,html.indexOf(a)));}
const box={};
const ctx={window:{DB_LIVE:true},DB_SEED:{panels:{waterfall:{},financialPeriods:{jul:{waterfall:{gross:100,expense:135,spread:-35,groups:[{label:'Expenses',total:135}],frm:'2030-01-01',to:'2030-01-31'},buildings:{A:{rev:100,cost:120}}},jun:{waterfall:{gross:90,expense:70,spread:20,groups:[],frm:'2029-12-01',to:'2029-12-31'},buildings:{A:{rev:90,cost:60}}}}}}, $:()=>box,esc:String,money:n=>n.toFixed(2),kf:String,liveEmpty:String};
ctx.window.DB_SEED=ctx.DB_SEED;vm.createContext(ctx);
vm.runInContext(between("let dashPeriod='jul';",'function liveEmpty'),ctx);
vm.runInContext(between('function renderWaterfall(){','/* ---------- billed'),ctx);
vm.runInContext("renderWaterfall()",ctx);
assert(box.innerHTML.includes('Net result -35.00'));
const rects=[...box.innerHTML.matchAll(/<rect x="[^"]+" y="([^"]+)" width="[^"]+" height="([^"]+)"/g)];
assert.equal(rects.length,3);rects.forEach(r=>assert(+r[1]>=0&&+r[2]>=0));
vm.runInContext("dashPeriod='jun';renderWaterfall()",ctx);
assert(box.innerHTML.includes('Net result 20.00')&&box.innerHTML.includes('2029-12-01'));
vm.runInContext("let BD=[{n:'A',arr:12,occ:80}],BD_view=[],PF_view=[],hmKey='',pfKey='',hmDir=1,pfDir=1;"+between('function syncViews(){','window.syncViews'),ctx);
assert.equal(vm.runInContext('syncViews();PF_view[0].m',ctx),30);
assert.equal(vm.runInContext("dashPeriod='jul';syncViews();PF_view[0].m",ctx),-20);
assert.equal(vm.runInContext('PF_view[0].arr',ctx),12);
console.log('PASS selected-period bridge, loss geometry, portfolio refresh and current arrears');
