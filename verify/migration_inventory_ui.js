// Synthetic DOM/fetch tests for the actual shipped inventory functions.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync('darkbrown/shell/index.html','utf8');
const code=source.split('/* ---------------- Migration inventory (authorized management accounts) ---------------- */')[1].split('/* ---------------- Admin ---------------- */')[0];
let clicks=0, request;
const status={textContent:''}, select={value:'',disabled:true,options:[],
  replaceChildren(option){this.options=[option];this.value='';},add(option){this.options.push(option);}};
const button={disabled:false},download={disabled:true};
const ctx={window:{DB_LIVE:true,DB_INVENTORY_ADMIN:false,DB_CSRF:'synthetic-csrf'},
  document:{getElementById:id=>({'migration-company':select,'migration-download':download,'migration-inventory-status':status}[id]),
    createElement:()=>({click(){clicks++;},remove(){}}),body:{appendChild(){}}},
  Option:function(text,value){this.text=text;this.value=value;},
  dbCall:async()=>({site:'synthetic.invalid',companies:['Synthetic <Company>']}),
  URL:{createObjectURL:()=> 'blob:synthetic',revokeObjectURL(){}},setTimeout:fn=>fn(),
  fetch:async(url,args)=>{request={url,args};return {ok:true,headers:{get:()=> 'attachment;'},
    blob:async()=>({text:async()=>JSON.stringify({schema_version:2,snapshot_checksum:'synthetic',errors:[{error:'review'}]})})};}};
vm.createContext(ctx);vm.runInContext(code,ctx);
(async()=>{
  assert.equal(ctx.migrationInventoryCard(),'');
  ctx.window.DB_INVENTORY_ADMIN=true;
  assert(ctx.migrationInventoryCard().includes('Export migration inventory'));
  await ctx.migrationInventoryCompanies(button);
  assert.equal(select.value,'Synthetic <Company>');assert.equal(download.disabled,false);
  await ctx.migrationInventoryDownload(download);
  assert.equal(clicks,1);assert.equal(request.args.headers['X-Frappe-CSRF-Token'],'synthetic-csrf');
  assert.deepEqual(JSON.parse(request.args.body),{company:'Synthetic <Company>',expected_site:'synthetic.invalid'});
  assert(status.textContent.includes('1 inventory issues'));
  ctx.fetch=async()=>({ok:false,status:403});
  await ctx.migrationInventoryDownload(download);
  assert.equal(clicks,1);assert(status.textContent.includes('HTTP 403'));assert.equal(download.disabled,false);
  ctx.fetch=async()=>({ok:true,headers:{get:()=>null}});
  await ctx.migrationInventoryDownload(download);
  assert.equal(clicks,1);assert(status.textContent.includes('did not return'));
  console.log('Inventory UI checks passed: visibility, company selection, CSRF/site binding, download, errors, login response.');
})().catch(e=>{console.error(e);process.exitCode=1;});
