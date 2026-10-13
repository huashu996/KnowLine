const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const assets=path.join(__dirname,'../dist/assets');
const source=fs.readFileSync(path.join(assets,'ProposalWorkbench-B_uiGL6A.js'),'utf8');
const jsx=(type,props,key)=>({type,props,key});
const idea={id:'idea',revision:2,title:'Saved idea',description:'Research concept',resource_ids:[],knowledge_base_ids:['kb']};
const job=(id,task)=>({id,task,revision:1,created_at:'2026-10-12',status:'completed',context:{proposal:{idea_id:'idea',target_path:id+'.docx',iteration:1}},result:{artifacts:[{path:id+'.docx'}]}});
function nodes(tree,out=[]){if(!tree||typeof tree!=='object')return out;if(tree.type)out.push(tree);Object.values(tree).forEach(x=>Array.isArray(x)?x.forEach(y=>nodes(y,out)):nodes(x,out));return out;}
async function run(locale){
  const calls=[],values=[[idea],'idea',idea,false,false,'Change font only','ppt',''];let slot=0;
  const ctx={Q:()=>k=>k,n:{useState:()=>[values[slot++],()=>{}],useEffect:()=>{}},s:{jsx,jsxs:jsx},R:{},G:'Icon',K:'Icon',J:'Icon',A:'Icon',Y:'Icon',D:x=>({base_revision:x.revision}),p:async(url,body)=>{calls.push({url,body});return {};}};
  vm.createContext(ctx);vm.runInContext(source.slice(source.indexOf('function se(')).replace('export{se as default};',''),ctx);
  const tree=ctx.se({resources:[],kbs:[{id:'kb',name:'KB',resource_ids:[]}],jobs:[job('ppt','proposal_ppt'),job('word','proposal_word')],locale,onChange:async()=>{},onError:e=>{throw e},onNotice:()=>{}});
  const all=nodes(tree),buttons=all.filter(n=>n.type==='button');
  assert(!buttons.some(n=>JSON.stringify(n.props.children).includes('PPT')),'PPT generation removed');
  const options=all.filter(n=>n.type==='option');assert.deepEqual(options.map(n=>n.props.value),['word'],'PPT cannot be selected as an update baseline');
  const create=buttons.find(n=>JSON.stringify(n.props.children).includes(locale==='zh'?'生成 Word':'Create Word'));
  assert(create&&!create.props.disabled,'Word still enabled');await create.props.onClick();
  assert.equal(calls[0].body.task,'proposal_word');
  const refine=buttons.find(n=>n.props.children===(locale==='zh'?'基于上一轮更新方案':'Refine previous proposal'));refine.props.onClick();await new Promise(resolve=>setImmediate(resolve));
  assert.equal(calls[1].body.task,'proposal_word');assert.equal(calls[1].body.previous_job_id,'word');
  assert(all.some(n=>n.type==='a'&&n.props.href.includes('/jobs/ppt/')),'Historical files remain readable');
}
(async()=>{await run('zh');await run('en');console.log('Word-only proposal UI: generation, refinement, and historical download checks passed.');})().catch(e=>{console.error(e);process.exitCode=1;});
