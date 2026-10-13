const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../dist/assets/knowline-appearance.js'),'utf8');
function boot(saved,osDark=false,blockedStorage=false,legacy=null){
 const events={},mediaEvents={},root={dataset:{},style:{}},media={matches:osDark,addEventListener:(name,fn)=>mediaEvents[name]=fn};
 const context={window:{matchMedia:()=>media,addEventListener:(name,fn)=>events[name]=fn},document:{documentElement:root},localStorage:{getItem:key=>{if(blockedStorage)throw Error('blocked');return key==='kw-appearance-v2'?saved:legacy;}},HTMLElement:class{},customElements:{define:()=>{}}};
 vm.createContext(context);vm.runInContext(source,context);return {root,media,events,mediaEvents};
}
let ui=boot(null,true);assert.equal(ui.root.dataset.theme,'light','first launch is white even on dark OS');assert.equal(ui.root.dataset.accent,'blue');
ui.media.matches=false;ui.mediaEvents.change();ui.media.matches=true;ui.mediaEvents.change();assert.equal(ui.root.dataset.theme,'light','default never follows OS');
ui=boot(null,true,false,JSON.stringify({mode:'dark',accent:'teal'}));assert.equal(ui.root.dataset.theme,'light','old preview mode resets to requested white');assert.equal(ui.root.dataset.accent,'teal','keep accent choice');
ui=boot(JSON.stringify({mode:'system',accent:'blue'}));ui.media.matches=true;ui.mediaEvents.change();assert.equal(ui.root.dataset.theme,'dark','explicit system appearance updates live');
ui=boot(JSON.stringify({mode:'light',accent:'teal'}),true);assert.equal(ui.root.dataset.theme,'light');assert.equal(ui.root.dataset.accent,'teal');ui.mediaEvents.change();assert.equal(ui.root.dataset.theme,'light','explicit light does not follow OS');
ui=boot(JSON.stringify({mode:'dark',accent:'graphite'}));assert.equal(ui.root.dataset.theme,'dark');assert.equal(ui.root.style.colorScheme,'dark');
ui.events.storage({key:'kw-appearance-v2',newValue:JSON.stringify({mode:'system',accent:'blue'})});assert.equal(ui.root.dataset.theme,'light','other windows sync preferences');
ui.events.storage({key:'unrelated',newValue:JSON.stringify({mode:'dark'})});assert.equal(ui.root.dataset.theme,'light');
for(const saved of ['{broken',JSON.stringify({mode:'unknown',accent:'invalid'})]){ui=boot(saved,true);assert.equal(ui.root.dataset.theme,'light');assert.equal(ui.root.dataset.accent,'blue');}
ui=boot(null,true,true);assert.equal(ui.root.dataset.theme,'light','blocked storage does not break white startup');
ui=boot(JSON.stringify({mode:'dark',accent:'teal'}));ui.events.storage({key:null,newValue:null});assert.equal(ui.root.dataset.theme,'light','cleared storage restores light default');
console.log('Appearance: white startup and migration, explicit system/dark modes, persistence, window sync, invalid/blocked storage passed.');
