// Run the release's real reader with a small hook scheduler and PDF loader.
// Assert that saves update the notes, while document/version navigation reloads.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const assets=path.join(__dirname,'../dist/assets');
const main=fs.readFileSync(path.join(__dirname,'../dist/index.html'),'utf8').match(/<script\b[^>]*type="module"[^>]*src="\/assets\/([^"?]+\.js)/)[1];
const reader=fs.readFileSync(path.join(assets,main),'utf8').match(/import\("\.\/(Readers-[^"?]+\.js)(?:\?[^\"]*)?"\)/)[1];
const source=fs.readFileSync(path.join(assets,reader),'utf8');
const component=source.slice(source.indexOf('function Mt('),source.indexOf('export{'));
const hitTest=source.slice(source.indexOf('/* knowline-highlight-hit-test */'),source.indexOf('/* end-knowline-highlight-hit-test */'));
const slots=[],effects=[],loadUrls=[];let cursor=0,dirty=false,props,tree,loads=0,destroys=0,notes=[],saveCount=0;
const saveBodies=[];
const same=(a,b)=>a&&b&&a.length===b.length&&a.every((v,n)=>Object.is(v,b[n]));
const hooks={
 useState(initial){const n=cursor++;if(!(n in slots))slots[n]={value:typeof initial==='function'?initial():initial};return [slots[n].value,value=>{const next=typeof value==='function'?value(slots[n].value):value;if(!Object.is(next,slots[n].value)){slots[n].value=next;dirty=true}}]},
 useRef(value){const n=cursor++;if(!(n in slots))slots[n]={current:value};return slots[n]},
 useEffect(fn,deps){const n=cursor++;const old=slots[n];if(!old||!same(old.deps,deps)){slots[n]={deps,cleanup:old?.cleanup};effects.push(()=>{slots[n].cleanup?.();slots[n].cleanup=fn()})}},
 useLayoutEffect(fn,deps){this.useEffect(fn,deps)},
 useCallback(fn,deps){const n=cursor++;if(!slots[n]||!same(slots[n].deps,deps))slots[n]={deps,fn};return slots[n].fn},
};
const jsx=(type,props,key)=>({type,props,key});
const context={i:hooks,e:{jsx,jsxs:jsx,Fragment:'fragment'},Be:()=>key=>key,
 ct:r=>({base_revision:r.revision,version_id:r.version_id,base_sha256:r.sha256}),
 ut:options=>{loads++;loadUrls.push(options.url);return{promise:Promise.resolve({numPages:3,getPage:async()=>({getViewport:()=>({width:595,height:842})})}),destroy:async()=>{destroys++}}},
 pe:async(url,body)=>{if(body){saveBodies.push(body);saveCount++;const resource={...props.resource,revision:props.resource.revision+1,version_id:'saved-'+saveCount};notes=body.annotation.action==='delete'?[]:[{id:'a_'+saveCount,data:body.annotation}];return{resource}}return notes},
 window:{addEventListener(){},removeEventListener(){},setTimeout(fn){fn()},getSelection:()=>null},
 clearTimeout(){},setTimeout(){},ResizeObserver:class{observe(){}disconnect(){}},document:{},
};
// Imported icons/components are inert; only the reader's actual hooks execute.
for(const name of ['it','at','ot','rt','st','Oe','lt','dt','pt','gt','mt','yt','xt','Fe','ht','ft'])context[name]=name;
vm.createContext(context);vm.runInContext(hitTest+component,context);
async function flush(){for(let n=0;n<30;n++){if(dirty||!tree){dirty=false;cursor=0;tree=context.Mt(props);while(effects.length)effects.shift()()}await new Promise(setImmediate);if(!dirty&&!effects.length)return}throw Error('Hook scheduler did not settle')}
function nodes(type){const out=[];function walk(value){if(!value||typeof value!=='object')return;if(value.type===type)out.push(value);for(const child of Object.values(value))if(Array.isArray(child))child.forEach(walk);else if(child&&typeof child==='object')walk(child)}walk(tree);return out}
async function run(){
 const rectangle={id:'rectangle',data:{kind:'highlight',page_index:1,quads:[[[0,0],[10,0],[0,10],[10,10]],[[20,0],[30,0],[20,10],[30,10]]]}};
 const rotated={id:'rotated',data:{kind:'highlight',page_index:1,vertices:[[10,0],[20,10],[0,10],[10,20]]}};
 assert.equal(context.kwPdfHighlightAt([rectangle],1,[5,5]),rectangle);
 assert.equal(context.kwPdfHighlightAt([rectangle],1,[15,5]),undefined,'Do not select the gap between highlight spans');
 assert.equal(context.kwPdfHighlightAt([rotated],1,[10,10]),rotated);
 assert.equal(context.kwPdfHighlightAt([rotated],1,[1,1]),undefined,'Test the quadrilateral, not its bounding box');
 assert.equal(context.kwPdfHighlightAt([rectangle,rotated],1,[5,5]),rotated,'Select the last drawn overlapping highlight');
 assert.equal(context.kwPdfHighlightAt([rectangle],0,[5,5]),undefined);
 assert.equal(context.kwPdfHighlightAt([{data:{kind:'text',page_index:1,quads:rectangle.data.quads}},{data:{kind:'highlight',page_index:1,vertices:[[0,0],[0,0],[0,0],[0,0]]}},{data:{kind:'highlight',page_index:1,vertices:[[0,0],[NaN,0],[0,10],[10,10]]}}],1,[0,0]),undefined);
 props={resource:{id:'r_test',revision:1,version_id:'initial',title:'Fixture'},target:{page:1},onError:e=>{throw e},onSaved:(resource,notes)=>{props={...props,resource,annotationUpdate:{resource,notes}};dirty=true}};
 await flush();assert.equal(loads,1);const pageKeys=nodes('yt').map(n=>n.key);assert.equal(pageKeys.length,3);
 // Locate the actual save closure by exposing it once in the test evaluator.
 const instrumented=component.replace('async function Ce(t){','async function Ce(t){').replace('function le(t){','kwSave=Ce;function le(t){');
 vm.runInContext(instrumented,context);dirty=true;await flush();
 for(const kind of ['highlight','text']){await context.kwSave({kind,page_index:1,quote:'fixture'});await flush();assert.equal(loads,1,JSON.stringify(loadUrls));assert.equal(destroys,0);assert.deepEqual(nodes('yt').map(n=>n.key),pageKeys);assert.equal(nodes('yt')[0].props.notes[0].data.kind,kind);assert.equal(nodes('yt')[0].props.historic,false)}
 await context.kwSave({action:'delete',annotation_id:'a_2',page_index:1});await flush();assert.equal(loads,1);assert.equal(nodes('yt')[0].props.notes.length,0);
 // Real reader click handler converts viewport coordinates, opens the existing
 // highlight, and sends its ID/geometry to the normal persisted delete path.
 await context.kwSave({kind:'highlight',page_index:1,page_geometry_hash:'geometry',quads:[[[150,10],[190,10],[150,30],[190,30]]],quote:'restore original text'});await flush();
 const highlight=notes[0],pageInfo={readonly:false,geometry:{hash:'geometry',pdf_to_mupdf:[0,1,-1,0,200,0]}};
 nodes('yt')[1].props.onReady(1,{info:pageInfo,viewport:{convertToPdfPoint:(x,y)=>[x,y]},layer:{getBoundingClientRect:()=>({left:100,top:200,right:500,bottom:800})}});await flush();
 const click=(x,y,control=false)=>({clientX:x,clientY:y,target:{closest:selector=>selector==='[data-page-index]'?{dataset:{pageIndex:'1'}}:control?{}:null},preventDefault(){}});
 const scroll=()=>nodes('div').find(n=>n.props.className?.startsWith('pdf-scroll'));
 const popup=()=>nodes('div').find(n=>n.props.className==='pdf-note-popup');
 scroll().props.onClick(click(120,230));await flush();assert(popup(),'Clicking the existing highlight opens its remove action');
 assert.equal(saveCount,4,'Selecting a highlight must not create another annotation');
 context.window.getSelection=()=>({isCollapsed:false});scroll().props.onClick(click(120,270));await flush();assert(popup(),'Text selection must not be intercepted');context.window.getSelection=()=>null;
 scroll().props.onClick(click(120,270,true));await flush();assert(popup(),'Note handles/buttons keep their own click behavior');
 scroll().props.onClick(click(120,270));await flush();assert.equal(popup(),undefined,'Blank-page click closes the popup');
 pageInfo.readonly=true;scroll().props.onClick(click(120,230));await flush();assert.equal(popup(),undefined);pageInfo.readonly=false;
 scroll().props.onClick(click(120,230));await flush();
 const remove=nodes('button').find(n=>n.props.children==='deleteHighlight');assert(remove);await remove.props.onClick();await flush();
 assert.equal(saveBodies.at(-1).annotation.action,'delete');assert.equal(saveBodies.at(-1).annotation.annotation_id,highlight.id);assert.equal(saveBodies.at(-1).annotation.page_geometry_hash,'geometry');
 assert.equal(notes.length,0);assert.equal(popup(),undefined);assert.equal(nodes('yt')[1].props.notes.length,0);assert.equal(loads,1);assert.equal(destroys,0);assert.deepEqual(nodes('yt').map(n=>n.key),pageKeys);
 // A side-panel annotation update also changes only the overlay.
 const external={...props.resource,revision:props.resource.revision+1,version_id:'panel-save'};
 notes=[{id:'panel',data:{kind:'text',page_index:1}}];props={...props,resource:external,annotationUpdate:{resource:external,notes}};dirty=true;await flush();assert.equal(loads,1);assert.equal(nodes('yt')[0].props.notes[0].id,'panel');
 // Replacing document contents and navigating to history must still reload.
 props={...props,annotationUpdate:undefined,resource:{...props.resource,revision:99,version_id:'replaced'}};dirty=true;await flush();assert.equal(loads,2);
 props={...props,target:{page:1,version:'initial'}};dirty=true;await flush();assert.equal(loads,3);assert.equal(nodes('yt')[0].props.historic,true);
 props={...props,target:{page:1}};dirty=true;await flush();assert.equal(loads,4);
 props={...props,resource:{id:'r_other',revision:1,version_id:'other'}};dirty=true;await flush();assert(loads>4);assert.equal(loadUrls.at(-1),'/api/v1/resources/r_other/file?version=other');
 console.log('PDF reader regression passed: click/remove existing highlights, rotated and separated spans, text selection, controls and readonly pages; annotation saves retain PDF/pages, navigation still reloads.');
}
run().catch(e=>{console.error(e);process.exitCode=1});
