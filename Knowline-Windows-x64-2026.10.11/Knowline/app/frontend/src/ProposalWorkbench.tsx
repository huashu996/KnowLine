import {useT} from './i18n';
import {useEffect,useState} from 'react';
import {BookOpen,FileText,Lightbulb,Plus,Presentation,Save} from 'lucide-react';
import {api,revision} from './api';
import type {Job,KB,Resource} from './types';
import './proposal.css';

type Idea={id:string;title:string;description:string;resource_ids:string[];knowledge_base_ids:string[];revision:number;updated_at:string};
type Props={resources:Resource[];kbs:KB[];jobs:Job[];locale:string;onChange:()=>Promise<void>;onError:(error:any)=>void;onNotice:(message:string)=>void};
const empty={title:'',description:'',resource_ids:[] as string[],knowledge_base_ids:[] as string[]};

export default function ProposalWorkbench({resources,kbs,jobs,locale,onChange,onError,onNotice}:Props){
 const t=useT();
 const zh=locale==='zh';
 const [ideas,setIdeas]=useState<Idea[]>([]),[active,setActive]=useState<string>(''),[draft,setDraft]=useState({...empty}),[busy,setBusy]=useState(false),[dirty,setDirty]=useState(false);
 const current=ideas.find(idea=>idea.id===active);
 const [updateRequest,setUpdateRequest]=useState(''),[previousId,setPreviousId]=useState('');
 useEffect(()=>{setUpdateRequest('');setPreviousId('');},[active]);
 const [resourceQuery,setResourceQuery]=useState('');
 const available=resources.filter(r=>r.state==='ready'&&(r.type==='paper'||r.type==='code'));
 const matches=resourceQuery.trim()?available.filter(r=>r.title.toLocaleLowerCase().includes(resourceQuery.trim().toLocaleLowerCase())):[];
 useEffect(()=>{let live=true;const refresh=()=>{void api<Idea[]>('/ideas').then(v=>{if(live)setIdeas(v);}).catch(e=>{if(live)onError(e);});};refresh();window.addEventListener('knowline:ideas',refresh);return()=>{live=false;window.removeEventListener('knowline:ideas',refresh);};},[]);
 useEffect(()=>{if(current&&!dirty)setDraft({title:current.title,description:current.description,resource_ids:current.resource_ids,knowledge_base_ids:current.knowledge_base_ids});},[active,ideas,dirty]);
 const pick=(ids:string[],id:string)=>ids.includes(id)?ids.filter(item=>item!==id):[...ids,id];
 const edit=(patch:Partial<typeof empty>)=>{setDraft(value=>({...value,...patch}));setDirty(true);};
 async function save(){
  if(!draft.title.trim()||!draft.description.trim()){onNotice(zh?'请填写想法名称和研究构思':'Enter a title and research concept.');return;}
  setBusy(true);
  try{
   const idea=await api<Idea>(current?'/ideas/'+current.id:'/ideas',{...draft,...(current?revision(current):{})},current?'PATCH':'POST');
   setIdeas(await api<Idea[]>('/ideas'));setActive(idea.id);setDirty(false);await onChange();onNotice(zh?'研究想法已保存':'Research idea saved.');
  }catch(error){onError(error);}finally{setBusy(false);}
 }
 async function generate(format:'word'|'ppt'){
  if(!current||dirty){onNotice(zh?'请先保存当前想法':'Save this idea first.');return;}
  if(!current.resource_ids.length&&!current.knowledge_base_ids.length){onNotice(zh?'请先选择知识库或资料':'Select a knowledge base or resource first.');return;}
  setBusy(true);
  try{
   await api('/jobs',{task:format==='word'?'proposal_word':'proposal_ppt',idea_id:current.id,idea_revision:current.revision,question:current.description});
   await onChange();onNotice(zh?'已创建任务，等待当前绑定的本地智能体处理；完成后结果会出现在这里。':'Task created for the bound local agent. Results will appear here.');
  }catch(error){onError(error);}finally{setBusy(false);}
 }
 async function removeIdea(){if(!current||!window.confirm(zh?'删除此想法？原资料和历史任务成果保留。':'Delete this idea? Source resources and historical results are preserved.'))return;setBusy(true);try{await api('/ideas/'+current.id,revision(current),'DELETE');setIdeas(await api<Idea[]>('/ideas'));setActive('');setDraft({...empty});setDirty(false);await onChange();}catch(e){onError(e);}finally{setBusy(false);}}
 const related=jobs.filter(job=>job.context?.proposal?.idea_id===active).sort((a,b)=>b.created_at.localeCompare(a.created_at));
 const completed=related.filter(job=>['completed','partial'].includes(job.status)&&job.result?.artifacts?.some((a:any)=>a.path===job.context.proposal.target_path));
 const previous=completed.find(job=>job.id===previousId)||completed[0];
 async function updateProposal(){
  if(!current||dirty||!previous||!updateRequest.trim())return;
  setBusy(true);try{
   await api('/jobs',{task:previous.task,idea_id:current.id,idea_revision:current.revision,previous_job_id:previous.id,previous_job_revision:previous.revision,update_request:updateRequest,question:updateRequest});
   setUpdateRequest('');await onChange();onNotice(zh?'已提交更新，将基于所选成果和历史上下文迭代；旧成果保留。':'Update submitted with the selected result and its history. Previous results are retained.');
  }catch(error){onError(error);}finally{setBusy(false);}
 }
 return <main className="page-content proposal-page"><div className="page-heading"><div><h1>{zh?'方案工作台':'Proposal Workbench'}</h1><p>{zh?'按研究想法组织已有知识库、论文与代码，再生成有来源依据的研究陈述或讲解演示。':'Organize existing knowledge, papers and code by idea, then draft a grounded statement or presentation.'}</p></div></div>
  <div className="proposal-layout"><aside className="proposal-list"><div className="proposal-list-heading"><strong>{zh?'研究想法':'Research ideas'}</strong><button className="icon-button" aria-label={zh?'新建想法':'New idea'} onClick={()=>{setActive('');setDraft({...empty});setDirty(false);}}><Plus size={18}/></button></div>{ideas.map(idea=><button key={idea.id} className={'proposal-list-item '+(active===idea.id?'active':'')} onClick={()=>{if(dirty&&!window.confirm(zh?'放弃未保存修改？':'Discard unsaved edits?'))return;setDirty(false);setActive(idea.id);setDraft({title:idea.title,description:idea.description,resource_ids:idea.resource_ids,knowledge_base_ids:idea.knowledge_base_ids});}}><Lightbulb size={17}/><span><strong>{idea.title}</strong><small>{idea.resource_ids.length} {zh?'份资料':'resources'} · {idea.knowledge_base_ids.length} {zh?'个知识库':'knowledge bases'}</small></span></button>)}{!ideas.length&&<p className="muted">{zh?'还没有研究想法':'No ideas yet.'}</p>}</aside>
  <section className="proposal-editor"><div className="proposal-editor-head"><h2>{current?(zh?'编辑研究想法':'Edit research idea'):(zh?'新建研究想法':'New research idea')}</h2><span>{current?`${zh?'版本':'Revision'} ${current.revision}`:''}</span></div><label>{zh?'名称':'Title'}<input value={draft.title} maxLength={200} onChange={event=>edit({title:event.target.value})} placeholder={zh?'例如：连续时间世界模型与交互记忆':'e.g. Continuous-time world model with interaction memory'}/></label><label>{zh?'研究构思':'Research concept'}<textarea rows={5} value={draft.description} onChange={event=>edit({description:event.target.value})} placeholder={zh?'写下研究问题、动机、已有方法的不足和初步方案。':'Describe the question, motivation, research gap and proposed method.'}/></label>
  <p className="muted">{zh?'知识库与论文或代码任选其一，也可组合。仅选择知识库即可，无需补充论文或代码。':'Choose knowledge bases, papers or code, or combine them. A knowledge base alone is sufficient; additional resources are optional.'}</p>
  <div className="proposal-picker"><h3><BookOpen size={17}/>{zh?'选择已有知识库':'Knowledge bases'}</h3>{kbs.map(kb=><label key={kb.id} className="proposal-option"><input type="checkbox" checked={draft.knowledge_base_ids.includes(kb.id)} onChange={()=>edit({knowledge_base_ids:pick(draft.knowledge_base_ids,kb.id)})}/><span>{kb.name}<small>{(kb as any).source_count??kb.resource_ids.length} {zh?'份资料':'resources'} · {kb.index_state==='ready'?(zh?'可用':'ready'):(zh?'尚未就绪':'not ready')}</small></span></label>)}{!kbs.length&&<p className="muted">{zh?'暂无知识库':'No knowledge bases.'}</p>}</div>
  <div className="proposal-picker"><h3><FileText size={17}/>{zh?'补充选定论文与代码':'Additional papers and code'}</h3><input type="search" aria-label={zh?'搜索已有论文与代码':'Search existing papers and code'} placeholder={zh?'输入标题搜索':'Search by title'} value={resourceQuery} onChange={e=>setResourceQuery(e.target.value)}/>{resourceQuery&&<button className="text-button" onClick={()=>setResourceQuery('')}>{zh?'清空搜索':'Clear search'}</button>}<div className="proposal-selected" aria-label={zh?'已选补充资料':'Selected resources'}>{draft.resource_ids.map(id=>{const r=resources.find(r=>r.id===id);return <div key={id} className="proposal-option"><span>{r?.title||id}</span><button className="small-button" aria-label={(zh?'取消选择 ':'Remove ')+(r?.title||id)} onClick={()=>edit({resource_ids:draft.resource_ids.filter(value=>value!==id)})}>{zh?'取消':'Remove'}</button></div>;})}</div><div className="proposal-resource-list">{matches.slice(0,30).map(resource=><label key={resource.id} className="proposal-option"><input type="checkbox" checked={draft.resource_ids.includes(resource.id)} onChange={()=>edit({resource_ids:pick(draft.resource_ids,resource.id)})}/><span>{resource.title}<small>{resource.type==='paper'?(zh?'论文':'Paper'):(zh?'代码':'Code')} · {resource.version_id}</small></span></label>)}</div><p className="muted" role="status">{!resourceQuery.trim()?(zh?'搜索平台已有资料，可选择多篇论文或代码。':'Search existing resources to select papers or code.'):matches.length?(zh?`找到 ${matches.length} 项${matches.length>30?'，请细化搜索':''}`:`${matches.length} matches`):(zh?'没有匹配资料':'No matching resources')}</p></div>
  <div className="proposal-actions">{current&&<button className="button" disabled={busy} onClick={()=>void removeIdea()}>{t('deleteIdea')}</button>}<button className="button primary" disabled={busy} onClick={save}><Save size={16}/>{zh?'保存想法':'Save idea'}</button><button className="button" disabled={busy||!current||dirty} onClick={()=>generate('word')}><FileText size={16}/>{zh?'生成 Word 研究陈述':'Create Word statement'}</button><button className="button" disabled={busy||!current||dirty} onClick={()=>generate('ppt')}><Presentation size={16}/>{zh?'生成讲解 PPT':'Create explainer PPT'}</button></div><p className="muted proposal-codex-note">{zh?'生成与更新通过当前绑定的本地智能体执行，处理进度在任务中显示；已有成果作为只读上下文保留。':'Generation and refinement use the bound local agent. Tasks show progress and retain previous results as read-only context.'}</p>
  {current&&<section className="proposal-update"><h3>{zh?'更新想法 / 优化方案':'Update idea / refine proposal'}</h3><p className="muted">{zh?'在已有成果上继续修改，保留上一轮内容与上下文。每轮生成新版本，历史成果保持原样。':'Continue from a previous result and its context. Each iteration creates a new version and preserves the history.'}</p>{completed.length?<><label>{zh?'基于哪个成果更新':'Previous result'}<select aria-label={zh?'选择上一轮方案':'Select previous proposal'} disabled={busy} value={previous?.id||''} onChange={e=>setPreviousId(e.target.value)}>{completed.map(job=><option key={job.id} value={job.id}>{job.task==='proposal_word'?'Word':'PPT'} · {zh?'第':'Round '}{job.context.proposal.iteration||1}{zh?'轮':''} · {new Date(job.created_at).toLocaleString(zh?'zh-CN':'en-US')}</option>)}</select></label><label>{zh?'更新想法或优化要求':'Update or refinement request'}<textarea aria-label={zh?'更新想法或优化要求':'Update or refinement request'} rows={4} maxLength={10000} value={updateRequest} disabled={busy} onChange={e=>setUpdateRequest(e.target.value)} placeholder={zh?'例如：保留上一版方法框架，加强创新点，并根据新增资料调整实验设计。':'For example: keep the previous method, strengthen the novelty and revise experiments using the new sources.'}/></label><button className="button primary" disabled={busy||dirty||!updateRequest.trim()} onClick={()=>void updateProposal()}>{zh?'基于上一轮更新方案':'Refine previous proposal'}</button>{dirty&&<p className="muted">{zh?'先保存上方想法与来源的修改，再更新方案。':'Save the idea and source changes above before refining.'}</p>}</>:<p className="muted">{zh?'第一轮成果完成后，即可在这里补充要求、继续更新。':'Once the first result is ready, add your requirements here to refine it.'}</p>}</section>}
  {current&&<div className="proposal-results"><h3>{zh?'关联成果':'Related results'} <span>{related.length}</span></h3>{related.length?related.map(job=><article key={job.id} className="proposal-result"><span>{job.task==='proposal_word'?'Word':'PPT'} · {zh?'第':'Round '}{job.context.proposal.iteration||1}{zh?'轮':''} · {job.context.proposal.mode==='update'?(zh?'更新':'Refinement'):(zh?'首次生成':'Initial generation')} · {job.status==='completed'?(zh?'已完成':'Completed'):(zh?'待 AI 处理':'Awaiting AI')}</span><small>{job.created_at.slice(0,10)}</small>{job.result?.artifacts?.map((artifact:{path:string})=><a key={artifact.path} href={'/api/v1/jobs/'+job.id+'/artifact?path='+encodeURIComponent(artifact.path)} download>{artifact.path.split('/').pop()}</a>)}</article>):<p className="muted">{zh?'尚无生成记录':'No generated work yet.'}</p>}</div>}</section></div></main>;
}
