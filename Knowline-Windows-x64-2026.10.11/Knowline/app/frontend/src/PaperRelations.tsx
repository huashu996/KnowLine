import {useT} from './i18n';
import {useEffect,useRef,useState} from 'react';
import {Network,X,RefreshCw,Download,Maximize2,Minimize2} from 'lucide-react';
import {api} from './api';
import JobHandoff,{AgentConnection,jobStatus} from './JobHandoff';
import type {Job,Group} from './types';
import PaperGraphScene,{names,type Paper,type PaperGraph} from './PaperGraphScene';

export default function PaperRelations({jobs,groups,onChange,onError,locale}:{jobs:Job[];groups:Group[];onChange:()=>Promise<void>;onError:(e:any)=>void;locale:string}){
 const t=useT();
 const zh=locale==='zh',graphJobs=jobs.filter(j=>j.task==='paper_relationships');
 const [jobId,setJobId]=useState(''),[graph,setGraph]=useState<PaperGraph>(),[active,setActive]=useState<Paper>(),[selected,setSelected]=useState<string[]>([]);
 const [origin,setOrigin]=useState(''),[from,setFrom]=useState(new Date().getFullYear()-4),[to,setTo]=useState(new Date().getFullYear()),[quantity,setQuantity]=useState(20);
 const [connectedUrl,setConnectedUrl]=useState('');
 const [destination,setDestination]=useState('library'),[busy,setBusy]=useState(false),[message,setMessage]=useState('');
 const [expanded,setExpanded]=useState(false),[windowOnly,setWindowOnly]=useState(false);
 const [hover,setHover]=useState<{paper:Paper;left:number;top:number}>();
 const [abstractExpanded,setAbstractExpanded]=useState(false);
 useEffect(()=>setAbstractExpanded(false),[active?.id]);
 const workspaceRef=useRef<HTMLDivElement>(null),expandButtonRef=useRef<HTMLButtonElement>(null),nativeFullscreen=useRef(false);
 useEffect(()=>{
  const changed=()=>{if(document.fullscreenElement===workspaceRef.current){nativeFullscreen.current=true;setExpanded(true);}else if(nativeFullscreen.current){nativeFullscreen.current=false;setExpanded(false);expandButtonRef.current?.focus();}};
  document.addEventListener('fullscreenchange',changed);return()=>document.removeEventListener('fullscreenchange',changed);
 },[]);
 useEffect(()=>{if(!expanded)return;const previous=document.body.style.overflow;document.body.style.overflow='hidden';expandButtonRef.current?.focus();
  const escape=(e:KeyboardEvent)=>{if(e.key==='Escape'){if(document.fullscreenElement===workspaceRef.current)void document.exitFullscreen();setExpanded(false);expandButtonRef.current?.focus();}};
  document.addEventListener('keydown',escape);return()=>{document.body.style.overflow=previous;document.removeEventListener('keydown',escape);};
 },[expanded]);
 async function toggleWorkspace(){
  if(expanded){if(document.fullscreenElement===workspaceRef.current)await document.exitFullscreen();setExpanded(false);expandButtonRef.current?.focus();return;}
  setExpanded(true);setWindowOnly(false);
  try{if(!workspaceRef.current?.requestFullscreen)throw new Error('fullscreen unavailable');await workspaceRef.current.requestFullscreen();}
  catch{setWindowOnly(true);}
 }
 const job=graphJobs.find(j=>j.id===jobId);
 const citationJobs=jobs.filter(j=>j.task==='refresh_graph_citations'&&j.context?.citation_refresh?.graph_job_id===jobId);
 const citationRevision=citationJobs.map(j=>j.id+':'+j.revision).join(',');
 useEffect(()=>{if(!jobId&&graphJobs.length)setJobId(graphJobs[0].id);if(jobId&&!graphJobs.some(j=>j.id===jobId)){setJobId('');setGraph(undefined);}},[graphJobs.map(j=>j.id).join(',')]);
 useEffect(()=>{
  setGraph(undefined);setActive(undefined);setSelected([]);setMessage('');
  const oldDomain=job?.context.scope.domain_id;
  setDestination(groups.some(g=>g.id===oldDomain)?oldDomain:'library');
  let live=true;if((job?.status==='completed'||job?.status==='partial'))api<PaperGraph>('/jobs/'+job.id+'/paper-graph').then(g=>{if(live)setGraph(g);}).catch(onError);
  return()=>{live=false;};
 },[jobId,job?.revision]);
 useEffect(()=>{if((job?.status==='completed'||job?.status==='partial')&&citationRevision)void api<PaperGraph>('/jobs/'+job.id+'/paper-graph').then(g=>{setGraph(g);setActive(previous=>previous?g.nodes.find(n=>n.id===previous.id):undefined);}).catch(onError);},[jobId,citationRevision]);
 async function create(){setBusy(true);try{
  const j=await api('/jobs',{task:'paper_relationships',query:origin,question:origin,from_year:from,to_year:to,target_count:quantity,ranking_policy:'relevance_citations_recency',skill:'knowline-paper-relations',...(connectedUrl.trim()?{connected_papers_url:connectedUrl.trim()}:{})});
  await onChange();setJobId(j.id);setMessage(zh?'已保存任务并请求启动 AI。真实执行开始后显示处理中，结果校验通过后回流；连接失败可重试或复制任务指令。':'Task saved and AI dispatch requested. Processing starts with a real execution event; results return after validation. Retry or copy instructions if connection fails.');
 }catch(e){onError(e);}finally{setBusy(false);}}
 async function importSelected(fetchMissing=false){if(!job||!selected.length)return;setBusy(true);try{
  const result=await api('/jobs/'+job.id+'/paper-graph/import-saved',{base_revision:job.revision,candidate_ids:selected,destination:destination==='library'?'library':'domain',...(destination==='library'?{}:{domain:destination}),fetch_missing:fetchMissing});
  await onChange();setSelected(result.rows.filter((r:any)=>!r.resource_id).map((r:any)=>r.candidate_id));
  const updated=await api<PaperGraph>('/jobs/'+job.id+'/paper-graph');setGraph(updated);setActive(previous=>previous?updated.nodes.find(n=>n.id===previous.id):undefined);
  setMessage(zh?'已直接导入 '+result.imported+' 篇'+(result.missing?'；'+result.missing+' 篇尚未取得 PDF，可点击“查找选中论文的 PDF”补齐。':'。'):'Imported '+result.imported+' papers directly; '+result.missing+' PDFs unavailable.');
 }catch(e){onError(e);}finally{setBusy(false);}}
 async function refreshCitations(){if(!job)return;setBusy(true);try{await api('/jobs',{task:'refresh_graph_citations',graph_job_id:job.id,graph_revision:job.revision});await onChange();setMessage(zh?'已创建引用核实任务。请让当前 AI 核对论文身份与公开来源，完成后本图自动显示新数据。':'Citation verification task created for the bound local agent; the graph updates after ingestion.');}catch(e){onError(e);}finally{setBusy(false);}}
 const imports=jobs.filter(j=>j.task==='import_graph_papers'&&j.context.paper_graph_selection?.job_id===jobId);
 function showAbstract(paper:Paper,element:HTMLElement){const rect=element.getBoundingClientRect();setHover({paper,left:Math.max(12,Math.min(window.innerWidth-370,rect.right+12)),top:Math.max(12,Math.min(window.innerHeight-280,rect.top))});}
 return <section className="paper-relations">
  <h2><Network size={22}/>{zh?'论文关系图':'Paper relationships'}</h2>
  <p className="muted">{zh?'节点大小按有来源的总被引次数；星光明暗按发表年份。':'Star size follows sourced citation counts; brightness follows publication year.'}</p>
  <AgentConnection zh={zh}/><div className="paper-graph-form">
   <label>{zh?'起点论文标题':'Origin paper title'}<input value={origin} onChange={e=>setOrigin(e.target.value)}/></label>
   <label>{zh?'起始年份':'From year'}<input type="number" value={from} onChange={e=>setFrom(Number(e.target.value))}/></label>
   <label>{zh?'截至年份':'Through year'}<input type="number" value={to} onChange={e=>setTo(Number(e.target.value))}/></label>
   <label>{zh?'相关论文数量（不含起点）':'Related paper count (excluding origin)'}<input aria-label={zh?'目标论文数量':'Target paper count'} type="number" min={1} max={100} value={quantity} onChange={e=>setQuantity(Number(e.target.value))}/></label>
   <button className="button primary" disabled={busy||!origin.trim()||from>to||from<1500||to>2200||!Number.isInteger(quantity)||quantity<1||quantity>100} onClick={()=>void create()}>{zh?'创建关系图任务':'Create graph task'}</button>
  </div>
  <label>{zh?'Connected Papers 推荐列表（已有图谱链接，可选）':'Connected Papers recommendations (existing graph URL, optional)'}<input aria-label={zh?'Connected Papers 图谱链接':'Connected Papers graph URL'} value={connectedUrl} onChange={e=>setConnectedUrl(e.target.value)} placeholder="https://www.connectedpapers.com/main/…/graph"/></label>
  <p className="muted">{zh?'提供图谱链接后优先复用其公开推荐列表，再核验论文身份及真实引用。':'With a graph URL, reuse its public recommendations first, then verify paper identities and real citations.'}</p>
  {graphJobs.length>0&&<label>{zh?'关系图结果':'Graph result'}<select value={jobId} onChange={e=>setJobId(e.target.value)}>{graphJobs.map(j=><option key={j.id} value={j.id}>{j.context.literature_search?.query} · {jobStatus(j.status,zh)}</option>)}</select></label>}
  {message&&<p className="paper-import-status" role="status">{message}</p>}
  {job&&<JobHandoff job={job} zh={zh} onChange={onChange}/>}
  {graph?<>
   <div ref={workspaceRef} className={'paper-workspace-view'+(expanded?' is-expanded':'')} role={expanded?'dialog':undefined} aria-modal={expanded?true:undefined} aria-label={expanded?(zh?'论文关系图全屏工作区':'Fullscreen paper workspace'):undefined} data-expanded={expanded} onKeyDown={e=>{
    if(!expanded||e.key!=='Tab')return;const items=[...e.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled),input,select,a[href],[tabindex="0"]')].filter(el=>el.getClientRects().length),first=items[0],last=items[items.length-1];
    if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}
   }}>
   <div className="paper-workspace-titlebar"><div><strong>{zh?'论文星云图':'Paper constellation'}</strong>{expanded&&<small>{windowOnly?(zh?'窗口展开 · 此浏览器未开放系统全屏':'Window view · browser fullscreen unavailable'):(zh?'全屏视图 · Esc 返回':'Fullscreen · Esc to return')}</small>}</div><button ref={expandButtonRef} className="small-button paper-workspace-expand" aria-expanded={expanded} onClick={()=>void toggleWorkspace()}>{expanded?<Minimize2 size={15}/>:<Maximize2 size={15}/>} {expanded?(zh?'退出全屏':'Exit fullscreen'):(zh?'全屏查看':'View fullscreen')}</button></div>
   <div className="paper-import-toolbar paper-actions" aria-label={zh?'论文导入操作':'Paper import actions'}>
    <div className="paper-selection-group"><strong aria-live="polite">{zh?'已选择':'Selected'} {selected.length} / {graph.nodes.length}</strong>
    <button className="small-button" onClick={()=>setSelected(selected.length===graph.nodes.length?[]:graph.nodes.map(n=>n.id))}>{selected.length===graph.nodes.length?(zh?'取消全选':'Clear selection'):(zh?'全选':'Select all')}</button></div>
    <div className="paper-import-group"><label className="paper-import-target"><span>{zh?'导入到':'Import into'}</span><select aria-label={zh?'论文导入目标':'Paper import destination'} value={destination} onChange={e=>setDestination(e.target.value)}><option value="library">{zh?'仅资源库':'Resource library only'}</option>{groups.map(g=><option key={g.id} value={g.id}>{zh?'资源库 + ':'Library + '}{g.name}</option>)}</select></label>
    <button className="button primary" disabled={!selected.length||busy} onClick={()=>void importSelected()}><Download size={14}/>{busy?(zh?'正在导入':'Importing'):(zh?'导入选中论文':'Import selected papers')}</button></div>
    {selected.some(id=>!graph.nodes.find(n=>n.id===id)?.cached_resources?.length)&&<button className="small-button" disabled={busy} onClick={()=>void importSelected(true)}>{zh?'查找选中论文的 PDF':'Find selected PDFs'}</button>}
    <button className="small-button paper-refresh-citations" disabled={busy||citationJobs.some(j=>j.status!=='completed')} onClick={()=>void refreshCitations()}><RefreshCw size={14}/>{zh?'刷新引用':'Refresh citations'}</button>
   </div>
   {graph.full_text_summary&&<p className="muted" role="status">{zh?`已保存 PDF ${graph.full_text_summary.pdf_saved} 篇 · 未取得全文 ${graph.full_text_summary.pdf_missing} 篇 · 已有摘要 ${graph.full_text_summary.abstracts} 篇`:`Saved PDFs: ${graph.full_text_summary.pdf_saved} · Unavailable: ${graph.full_text_summary.pdf_missing} · Abstracts: ${graph.full_text_summary.abstracts}`}</p>}
   <div className="paper-graph-workspace">
    <div className="paper-graph-list" onScroll={()=>setHover(undefined)}>{graph.nodes.map(n=><div className={'paper-candidate '+(active?.id===n.id?'active':'')} key={n.id}><input type="checkbox" aria-label={'选择候选论文 '+n.title} checked={selected.includes(n.id)} onChange={()=>{setActive(n);setSelected(prev=>prev.includes(n.id)?prev.filter(id=>id!==n.id):[...prev,n.id]);}}/><button onMouseEnter={e=>showAbstract(n,e.currentTarget)} onMouseLeave={()=>setHover(undefined)} onFocus={e=>showAbstract(n,e.currentTarget)} onBlur={()=>setHover(undefined)} onKeyDown={e=>{if(e.key==='Escape')setHover(undefined);}} aria-describedby={hover?.paper.id===n.id?'paper-abstract-hover':undefined} onClick={()=>{setActive(n);setHover(undefined);}}>{n.id===graph.origin_id&&<small>{zh?'起点论文':'Origin paper'}</small>}<strong>{n.title}</strong><span>{names(n.authors)} · {n.year}</span><span>{n.citation_count===null?t('citationCountUnverified'):t('citationCountValue',{count:n.citation_count})}{n.citation_source?.provider?' · '+n.citation_source.provider:''}</span></button></div>)}</div>
    <div className="paper-graph-canvas"><PaperGraphScene key={jobId} graph={graph} active={active} onSelect={setActive} zh={zh}/>
     {active&&<div className="paper-node-popup" role="dialog" aria-label={t('paperDetails')}><button className="icon-button" aria-label={t('closePaperDetails')} onClick={()=>setActive(undefined)}><X size={16}/></button><strong>{active.title}</strong><p>{names(active.authors)}</p><p>{active.venue||t('venueUnverified')} · {active.year}</p><p>{active.citation_count===null?t('citationCountUnverified')+(active.citation_unknown_reason?' · '+active.citation_unknown_reason:''):t('citationCountValue',{count:active.citation_count})+' · '+(active.citation_source?.provider||t('sourceUnverified'))}{active.citation_source&&' · '+active.citation_source.retrieved_at.slice(0,10)}</p><div className="paper-abstract-detail"><strong>{zh?'摘要':'Abstract'}</strong><p className={abstractExpanded?'':'is-collapsed'}>{active.abstract||(zh?'尚无来源摘要或可提取摘要的本地 PDF。':'The source has not provided an abstract.')}</p>{active.abstract&&active.abstract.length>180&&<button className="small-button" aria-expanded={abstractExpanded} onClick={()=>setAbstractExpanded(v=>!v)}>{abstractExpanded?(zh?'收起摘要':'Collapse abstract'):(zh?'展开摘要':'Expand abstract')}</button>}{active.abstract_source&&<a href={active.abstract_source.pdf_url||active.abstract_source.url} target="_blank" rel="noreferrer">{active.abstract_source.provider==='Local PDF abstract'?(zh?'PDF 摘要 · 第 '+(active.abstract_source.page_index+1)+' 页':'PDF abstract · page '+(active.abstract_source.page_index+1)):(zh?'摘要来源':'Abstract source')}</a>}</div><p className="muted">{active.cached_resources?.length?(zh?'PDF 已保存，导入时直接复用。':'PDF saved and ready to reuse.'):(zh?'尚未取得 PDF，可重试查找公开全文。':'PDF unavailable; retry to check public sources.')}{active.full_text_reason&&' · '+(zh?(/403|429|requires_user/.test(active.full_text_reason)?'来源访问受限':/identity|verification|verified/.test(active.full_text_reason)?'全文身份尚未核验':/timeout/.test(active.full_text_reason)?'来源请求超时':'已检查的合法来源暂未提供可用全文'):active.full_text_reason)}</p>{active.cached_resources?.[0]&&<a href={'/api/v1/resources/'+encodeURIComponent(active.cached_resources[0].resource_id)+'/file?version='+encodeURIComponent(active.cached_resources[0].version_id)} target="_blank" rel="noreferrer">{zh?'打开 PDF':'Open PDF'}</a>}<a href={active.metadata_source.url} target="_blank" rel="noreferrer">{t('paperSources')}</a>{active.citation_source&&<a className="citation-source-link" href={active.citation_source.url} target="_blank" rel="noreferrer">{t('citationSources')}</a>}{active.citation_alternatives?.map((alternative,index)=><a className="citation-source-link" key={index} href={alternative.citation_source.url} target="_blank" rel="noreferrer">{alternative.citation_source.provider||t('otherCitationIndex')} {alternative.citation_count.toLocaleString()} · {alternative.citation_source.retrieved_at.slice(0,10)}</a>)}</div>}
    </div>
   </div>
   {hover&&<div id="paper-abstract-hover" className="paper-abstract-hover" role="tooltip" style={{left:hover.left,top:hover.top}}><strong>{hover.paper.title}</strong><p>{hover.paper.abstract||(zh?'尚无来源摘要或可提取摘要的本地 PDF。选中论文可查看详细信息。':'No source abstract is available. Select the paper to view details.')}</p></div>}
   </div>
   <div className="paper-graph-bottom"><small>{zh?'被引已核实 '+graph.nodes.filter(n=>n.citation_count!==null).length+'/'+graph.nodes.length+' · 星辰大小表示被引 · 越新越亮 · 仅显示真实引用':'Verified citations '+graph.nodes.filter(n=>n.citation_count!==null).length+'/'+graph.nodes.length+' · size: citations · newer: brighter · sourced citations only'}</small></div>
   {imports.length>0&&<div className="paper-import-history"><strong>{zh?'此图的导入记录':'Imports from this graph'}</strong>{imports.map(j=><div key={j.id}><p>{j.context.paper_graph_selection.candidates.length}{t('papersCount')}{j.context.import_destination?.kind==='library'?'资源库':j.context.scope.domain_name} · {['completed','partial'].includes(j.status)?`${(j.result?.imported_papers||[]).filter((r:any)=>r.resource_id).length} 篇已导入，${(j.result?.imported_papers||[]).filter((r:any)=>!r.resource_id).length} 篇全文未取得`:jobStatus(j.status,zh)+' · 直接核验与获取全文'}</p>{j.result?.imported_papers?.filter((r:any)=>!r.resource_id).map((r:any)=><small key={r.candidate_id}>{r.title} · {r.unavailable_reason}<br/></small>)}</div>)}</div>}
  </>:<div className="paper-graph-empty">{job?jobStatus(job.status,zh)+(zh?' · 只有校验通过才显示关系图。':' · The graph appears after validation.'):(zh?'输入起点论文、年份和目标数量，创建并启动 AI 关系图任务。':'Enter an origin paper, years and quantity to create and start a graph task.')}</div>}
 </section>;
}
