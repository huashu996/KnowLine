import {useT} from './i18n';
import KnowledgeBuildTiming from './KnowledgeBuildTiming';
import {useEffect,useState} from 'react';
import {api} from './api';
import type {Job} from './types';
import './job-handoff.css';
export function jobStatus(status:string,zh:boolean){
 const labels:Record<string,string>=zh?{waiting_user:'待处理',queued:'排队中',running:'处理中',completed:'已完成',partial:'部分完成',failed:'未完成',interrupted:'已中断'}:{waiting_user:'Pending',queued:'Queued',running:'Processing',completed:'Completed',partial:'Partially completed',failed:'Incomplete',interrupted:'Interrupted'};
 return labels[status]||status;
}
export function AgentConnection({zh}:{zh:boolean}){
 const [state,setState]=useState<any>();
 useEffect(()=>{let live=true;const refresh=()=>void api('/agent/status').then(s=>{if(live)setState(s)}).catch(()=>{if(live)setState({state:'disconnected',message:'无法读取本地智能体连接状态。'})});refresh();const timer=setInterval(refresh,5000);return()=>{live=false;clearInterval(timer)}},[]);
 return <p className="codex-connection" role="status" data-agent-state={state?.state}>{state?(zh?state.message:state.available?'Local agent connected and executable. Results return after validation.':state.bound?'Bound local agent is offline; waiting for automatic recovery.':'No local agent connected. Ask your local AI project to connect to Knowline.'):(zh?'正在检查智能体连接…':'Checking agent connection…')}</p>;
}

export function scholarSearchUrl(job:any){
 const s=job.context?.literature_search,q=s?.search_plan?.scholar_query||s?.query;
 if(!q)return 'https://scholar.google.com/';
 const params=new URLSearchParams({q,hl:'en'});
 if(s.from_year)params.set('as_ylo',String(s.from_year));
 if(s.to_year)params.set('as_yhi',String(s.to_year));
 return 'https://scholar.google.com/scholar?'+params.toString();
}
export function failureSummary(job:any,zh=true){
 const source=job.execution?.error_code;
 if(job.task==='replicate_paper_figure'&&/quote_not_found/.test(String(source||'')+' '+String(job.error||'')+' '+String(job.execution?.failure_detail||'')))return zh?'引用的图题与冻结论文页原文不一致，成果未能回流。请修正图题证据后重新核验；已生成的 PPT 保留。':'The quoted figure caption does not match the frozen paper page, so the result could not be accepted. Correct the caption evidence and validate again; the generated PPT is retained.';
 if(source==='scholar_browser_only')return zh?'Google 学术请使用正常网页搜索。可选择公开引文接口继续自动检索，已有资料保留。':'Use Google Scholar in its normal website. Permit the public citation APIs to continue automatic discovery; saved data is retained.';
 if(source?.startsWith('connected_papers_'))return zh?'提供的 Connected Papers 图谱暂时无法读取或要求人工处理。本轮已暂停，未代登录或重复生成图谱；已有成果保留。':'The supplied Connected Papers graph could not be read or needs human access. This run paused; existing results are retained.';
 const stats=job.result?.literature_summary;
 if(job.task==='discover_papers'&&stats&&stats.imported_count===0){const target=job.context?.literature_search?.target_count??job.result?.summary?.requested_papers;return zh?`本轮已定位 ${stats.candidate_count??0} 条候选，未取得并导入可用全文${target?'，尚未达到 '+target+' 篇目标':''}。${stats.citation_record_count?'已核实的引用记录已保留。':''}具体获取原因见下方全文缺项与结果提醒。`:`Located ${stats.candidate_count??0} candidates, but no usable full-text PDFs were imported${target?'; the target is '+target+' papers':''}. See the acquisition reasons and result notes below.`;}
 const scholar:Record<string,[string,string]>={scholar_rate_limited:['Google 学术暂时限制访问，查询已停止。论文未被判为不存在，机构权限也未被判为失效；已有资料和图谱保留，请稍后重试。','Google Scholar temporarily limited access. The search stopped; this does not mean the paper is missing or institution access failed. Saved results are retained.'],scholar_access_challenge:['Google 学术要求人工验证，查询已停止。请在正常网页中处理验证后再试；已有结果保留。','Google Scholar requested human verification. The search stopped; use the normal website and retry later. Existing results are retained.'],scholar_no_results:['Google 学术在本轮限定查询中未返回候选，检索已结束。','Google Scholar returned no candidates for this bounded query. The search has ended.'],scholar_source_unavailable:['暂时无法读取 Google 学术，查询已停止；这不能证明论文不存在。请检查网络后再试，已有结果保留。','Google Scholar is unavailable. The search stopped; this does not establish that the paper is missing. Existing results are retained.'],scholar_source_format_unrecognized:['Google 学术返回的页面无法识别，查询已停止；尚未确认有无对应论文，已有结果保留。','The Google Scholar response could not be read. The search stopped without deciding that the paper is missing.']};
 if(scholar[source])return scholar[source][zh?0:1];
 if(source?.startsWith('public_citation_'))return zh?'公开引文接口本轮未取得可用候选。各来源状态已记录，已有资料与图谱保留。':'The public citation APIs did not return usable candidates. Source statuses and saved results are retained.';
 if(/agent_execution_timeout|codex_timeout/.test(String(source||'')+' '+String(job.error||'')))return zh?'上次执行达到总时限而中断，已保存成果保留。当前所有智能体任务均无总时限，可重试继续，或随时手动取消。':'The previous run reached its overall time limit. Saved results are retained. All agent tasks now run without an overall time limit; retry to continue or cancel at any time.';
 if(/office_visual_review_required/.test(String(job.error||'')))return zh?'文档已保存，但缺少最终页面预览或视觉审查记录。补齐检查后才能确认完成。':'The document was saved, but final page previews or the visual review record are missing. Complete the review before confirming success.';
 if(!zh)return 'This task did not finish. Expand technical details for the diagnostic record.';
 const raw=String(job.error||'')+' '+String(job.execution?.failure_detail||'');
 if(/invalid_result|结果校验|完成记录/.test(raw))return '任务的完成记录未通过检查，暂时无法确认全部完成。已经保存的资料会保留，可查看结果或重试。';
 if(/trusted_skill_missing|No module named|ModuleNotFoundError/.test(raw))return '运行所需的组件缺失，任务没有正常完成。请修复运行环境后重试。';
 if(/timeout|timed.out|超时/i.test(raw))return '处理超过了本次允许的时间。已经保存的资料会保留，可以缩小范围后重试。';
 if(/login|unauthorized|not.authenticated|未登录/i.test(raw))return 'AI 的登录状态不可用。请重新登录后重试。';
 if(/connection|ECONN|网络连接|connecterror/i.test(raw))return '处理时连接中断。请检查网络和本地服务后重试。';
 if(/429|rate.limit|限流/i.test(raw))return '论文来源暂时限制了下载请求。已下载的资料会保留，请稍后重试。';
 if(job.status==='interrupted')return '处理过程被中断，任务没有完成。已保存的资料会保留，可以重新开始。';
 return job.error?String(job.error):'任务没有正常完成，已保存的资料会保留。具体原因尚未确认，可以重试或展开技术详情查看记录。';
}
function duration(s:any,zh:boolean){return typeof s==='number'?s<60?Math.round(s)+(zh?' 秒':' s'):Math.round(s/60)+(zh?' 分钟':' min'):'';}
export function warningSummary(warnings:string[],task?:string){
 if(task==='replicate_paper_figure')return warnings;
 const all=warnings.join(' '),items:string[]=[];
 if(/needs_review|元数据|metadata|待核/i.test(all))items.push('部分论文的作者、年份或出版信息还需要核对，引用前请确认。');
 if(/crossref|citation.count|引用次数/i.test(all))items.push('引用次数来自检索来源，可能与其他平台的统计不同。');
 if(/truncat|截断|candidate.pool|候选|bounded|有限|incomplete|不完整/i.test(all))items.push('本次只展示已核实的部分内容，结果不代表全部相关论文或关系。');
 if(/403|429|IEEE|限制|限流|unavailable|全文|download|下载/i.test(all))items.push('部分来源未能取得全文，可稍后重试或手动下载后导入。');
 if(!items.length)items.push('结果中还有需要确认的事项，可展开查看完整说明。');
 return items;
}
export default function JobHandoff({job,zh,onChange}:{job:Job;zh:boolean;onChange:()=>Promise<void>}){
 const t=useT();
 const [busy,setBusy]=useState(false),[message,setMessage]=useState(''),[text,setText]=useState('');
 const j:any=job,active=['queued','running'].includes(job.status),finished=['completed','partial'].includes(job.status),failed=['failed','interrupted'].includes(job.status);
 const direct=job.task==='import_graph_papers';
 async function run(publicFallback=false,normalizeQuery=false){setBusy(true);setMessage('');try{await api('/jobs/'+job.id+'/run',{base_revision:job.revision,...(publicFallback?{allow_public_citation_fallback:true}:{}),...(normalizeQuery?{normalize_discovery_query:true}:{})});await onChange();}catch{setMessage(zh?'暂时无法开始，请检查连接或稍后重试。':'Could not start. Check the connection or try again later.');}finally{setBusy(false);}}
 async function cancel(){setBusy(true);setMessage('');try{await api('/jobs/'+job.id+'/cancel',{base_revision:job.revision});await onChange();setMessage(zh?'任务已停止，已保存的资料与结果保留。':'Task stopped. Saved data and results are retained.');}catch{setMessage(zh?'暂时无法停止，请刷新任务状态后重试。':'Could not stop. Refresh the task state and retry.');}finally{setBusy(false);}}
 async function copy(){setMessage('');try{const data=await api<{text:string}>('/jobs/'+job.id+'/instructions');setText(data.text);try{await navigator.clipboard.writeText(data.text);setMessage(zh?'已复制，可粘贴到 AI 继续处理。':'Copied. Paste into AI to continue.');}catch{setMessage(zh?'请从展开的文本框复制。':'Copy from the expanded text box.');}}catch{setMessage(zh?'暂时无法读取任务指令，请检查本地服务。':'Could not load instructions.');}}
 const summary=j.result?.literature_summary;
 return <section className="job-handoff" aria-label={zh?'任务进度与结果':'Task progress and outcome'}>
  {failed&&<div className="notice danger task-failure" role="alert"><strong>{zh?'这次任务未完成':'Task incomplete'}</strong><p>{failureSummary(j,zh)}</p><details className="task-technical"><summary>{zh?'技术详情':'Technical details'}</summary><pre>{[j.error,j.execution?.failure_detail].filter(Boolean).join('\n\n')}</pre></details></div>}
  {!finished&&!failed&&<p className="muted">{job.status==='queued'?(zh?'正在准备任务并启动独立智能体，多个任务可以同时执行。':'Preparing an independent agent for this task. Multiple tasks can run simultaneously.'):zh?(active?'正在处理，完成后会在这里显示结果。':'任务已准备好，点击下方按钮开始。'):(active?'Processing. Results will appear here.':'Ready. Start the task below.')}</p>}
  {job.context?.literature_search?.search_plan?.normalized&&<p className="muted">{zh?'实际检索词：':'Search terms: '}{job.context.literature_search.search_plan.scholar_query} · {zh?'目标 ':'Target '}{job.context.literature_search.target_count}{zh?' 篇；按原请求核对主题、年份和刊会。':' papers; verify relevance, years and venues against the original request.'}</p>}
  {!finished&&<p className="muted">{zh?'本次执行无总时限，可随时取消。':'No overall execution limit. You can cancel at any time.'}</p>}
  {(j.execution?.discovery?.provider==='Public citation APIs'||j.execution?.discovery?.expanded_search)&&<p className="muted" role="status">{zh?'自动检索来源：Crossref、Semantic Scholar。Google 学术可在正常网页搜索。':'Automatic sources: Crossref and Semantic Scholar. Google Scholar is available through its normal website.'}</p>}
  {j.execution?.discovery?.provider==='Connected Papers'&&<p className="notice" role="status">{zh?'已复用 Connected Papers 公开推荐列表。推荐基于相似性，真实引用关系仍需独立核验。':'Reused public Connected Papers recommendations. They are similarity-based; real citation relationships require independent verification.'}</p>}
  <div className="job-handoff-actions">{!finished&&<button className="button primary" disabled={busy||active} onClick={()=>void run()}>{direct?(zh?(active?'正在直接导入':'继续直接导入'):(active?'Importing directly':'Continue direct import')):active?jobStatus(job.status,zh):zh?(failed?'重试任务':'开始处理'):'Run task'}</button>}{active&&<button className="button" disabled={busy} onClick={()=>void cancel()}>{zh?'取消任务':'Cancel task'}</button>}{failed&&job.task==='paper_relationships'&&['scholar_rate_limited','scholar_browser_only'].includes(j.execution?.error_code)&&!job.context?.literature_search?.source_policy?.public_citation_fallback&&<button className="button" disabled={busy} onClick={()=>void run(true)}>{zh?'使用公开引文接口继续':'Continue with public citation APIs'}</button>}{!direct&&<button className="button" onClick={()=>void copy()}>{zh?'复制指令':'Copy instructions'}</button>}{!direct&&job.context?.literature_search?.query&&<a className="button" href={scholarSearchUrl(job)} target="_blank" rel="noreferrer">{zh?'打开 Google 学术':'Open Google Scholar'}</a>}</div>
  {failed&&job.task==='discover_papers'&&!job.context?.literature_search?.search_plan&&/篇|为主|重点|TRO|RA-?L/i.test(job.context?.literature_search?.query||'')&&<button className="button" disabled={busy} onClick={()=>void run(false,true)}>{zh?'按主题与刊会重新检索':'Search again by topic and venue'}</button>}
  {direct&&<p className="muted">{zh?'直接复用选中论文的书目、已有 PDF 和获取来源，逐篇登记结果。':'Selected citations, cached PDFs and located sources are reused directly.'}</p>}
  {['build_knowledge','update_knowledge'].includes(job.task)&&<KnowledgeBuildTiming job={job}/>}
  {summary&&<p className="notice" role="status">{active?(zh?'上次结果：':'Previous result: '):''}{t('savedFullText',{count:summary.imported_count??'—'})}{typeof summary.unavailable_count==='number'?' · '+t('missingFullText',{count:summary.unavailable_count}):''}{summary.registration_report_missing?' · '+t('fullTextRegistrationMissing'):''}</p>}
  {failed&&job.task==='discover_papers'&&j.result?.imported_papers?.some((r:any)=>!r.resource_id)&&<details className="task-warnings"><summary>{zh?'全文缺项与获取原因':'Missing full text and acquisition reasons'}</summary><div className="task-scroll">{j.result.imported_papers.filter((r:any)=>!r.resource_id).map((r:any)=><p key={r.candidate_id}><strong>{r.title}</strong><br/>{r.unavailable_reason}</p>)}</div></details>}
  {j.metadata_summary&&<details><summary>{t('publicationCheckSummary',{verified:j.metadata_summary.verified_count??'—',unresolved:j.metadata_summary.unresolved_count??'—'})}</summary><div className="task-scroll">{j.metadata_summary.rows?.map((row:any)=><p key={row.resource_id}>{row.title} · {t(row.status==='verified'?'publicationConfirmed':'publicationPending')}</p>)}</div></details>}
  {job.result?.warnings?.length>0&&<details className="task-warnings"><summary>{zh?'结果提醒':'Result notes'} · {job.result.warnings.length}</summary>{(zh?warningSummary(job.result.warnings,job.task):['Some results need review. See the original notes for details.']).map((s,i)=><p key={i}>{s}</p>)}<details className="task-technical"><summary>{zh?'完整说明（技术详情）':'Original technical notes'}</summary><div className="task-scroll">{job.result.warnings.map((s:string,i:number)=><p key={i}>{s}</p>)}</div></details></details>}
  {j.execution&&<details className="task-record"><summary>{zh?'执行记录':'Execution record'}{duration(j.execution.elapsed_seconds,zh)?' · '+duration(j.execution.elapsed_seconds,zh):''}</summary><p>{jobStatus(job.status,zh)}{j.execution.started_at?' · '+t('startedAt')+' '+new Date(j.execution.started_at).toLocaleString(zh?'zh-CN':'en-US'):''}{j.execution.finished_at?' · '+t('finishedAt')+' '+new Date(j.execution.finished_at).toLocaleString(zh?'zh-CN':'en-US'):''}</p><p>{job.status==='partial'?(zh?'成果文件已保存，仍有未完成项；请查看结果提醒。':'Output files are saved, but some requested work remains incomplete. See result notes.'):t(active?'taskValidationPending':finished?'taskValidationPassed':failed?'taskIncompleteRetained':'taskWaiting')}</p><details className="task-technical"><summary>{zh?'技术详情':'Technical details'}</summary><pre>{[j.execution.message,j.execution.thread_id,job.context_path?.replace('context.json','codex-events.jsonl')].filter(Boolean).join('\n')}</pre></details></details>}
  {j.execution?.stages&&<details className="task-record"><summary>{zh?'分段用时':'Stage timing'}</summary>{Object.entries(j.execution.stages).map(([key,value])=><p key={key}>{({memory_seconds:t('stageMemory'),citation_seconds:t('stageCitations'),metadata_seconds:t('stageMetadata'),discovery_seconds:t('stageDiscovery'),model_seconds:t('stageAnalysis'),ingest_seconds:t('stageRegistration'),direct_import_seconds:t('stageDirectImport')} as Record<string,string>)[key]||key} · {Number(value).toFixed(2)} {zh?'秒':'seconds'}</p>)}{j.execution.queue_seconds!==undefined&&<p>{zh?'启动用时':'Startup'} · {Number(j.execution.queue_seconds).toFixed(2)} {zh?'秒':'seconds'}</p>}</details>}
  {message&&<p role="status">{message}</p>}
  {text&&<details open className="task-technical"><summary>{zh?'任务指令（供 AI 使用）':'Instructions for AI'}</summary><textarea aria-label={zh?'任务指令文本':'Task instruction text'} readOnly value={text} onFocus={e=>e.target.select()}/><button className="small-button" onClick={()=>setText('')}>{zh?'关闭指令':'Close instructions'}</button></details>}
 </section>;
}

