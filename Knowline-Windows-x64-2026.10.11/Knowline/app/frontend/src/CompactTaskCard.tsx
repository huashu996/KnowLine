import {useId,useState} from 'react';
import type {ReactNode} from 'react';
import {Check,ChevronDown,ChevronRight,Copy,Loader2,MoreHorizontal,Play,Square,Terminal,Trash2,X} from 'lucide-react';
import {api} from './api';
import type {Job} from './types';
import JobHandoff,{failureSummary,jobStatus} from './JobHandoff';
import {TaskScope,TaskDrafts,downloadableDrafts} from './TaskPresentation';
import './compact-tasks.css';

function executionTime(job:Job,zh:boolean){
 const execution=(job as any).execution||{},timing=job.result?.knowledge_build_report?.timing||{};
 let seconds=execution.elapsed_seconds;
 if(typeof seconds!=='number'||!Number.isFinite(seconds)||seconds<0){
  const start=execution.started_at||timing.started_at,finish=execution.finished_at||timing.published_at;
  seconds=start&&finish?(Date.parse(finish)-Date.parse(start))/1000:NaN;
 }
 if(!Number.isFinite(seconds)||seconds<0)return zh?'用时未记录':'Duration unavailable';
 if(seconds>0&&seconds<1)return zh?'用时 <1 秒':'Time <1 s';
 const total=Math.round(seconds),h=Math.floor(total/3600),m=Math.floor(total%3600/60),s=total%60;
 const value=[h?(zh?h+' 小时':h+' h'):'',m?(zh?m+' 分':m+' m'):'',s||!h&&!m?(zh?s+' 秒':s+' s'):''].filter(Boolean).join(' ');
 return (zh?'用时 ':'Time ')+value;
}

function taskTimestamp(job:Job,zh:boolean){
 const execution=(job as any).execution||{},timing=job.result?.knowledge_build_report?.timing||{};
 for(const [value,started] of [[execution.started_at,true],[timing.started_at,true],[job.created_at,false]] as const){
  if(typeof value!=='string'||!value.trim())continue;
  const date=new Date(value);if(!Number.isFinite(date.getTime()))continue;
  const pad=(n:number)=>String(n).padStart(2,'0');
  return {dateTime:date.toISOString(),text:date.getFullYear()+'.'+pad(date.getMonth()+1)+'.'+pad(date.getDate())+'——'+date.getHours()+':'+pad(date.getMinutes()),label:started?(zh?'运行时间（电脑本地时间）':'Run time (computer local time)'):(zh?'创建时间（尚未记录运行时间）':'Created time (run time unavailable)')};
 }
 return undefined;
}

export default function CompactTaskCard({job,title,zh,selected,onSelect,onChange,onDelete,children}:{job:Job;title:string;zh:boolean;selected:boolean;onSelect:()=>void;onChange:()=>Promise<void>;onDelete:()=>void;children?:ReactNode}){
 const [open,setOpen]=useState(false),[busy,setBusy]=useState(false),[copied,setCopied]=useState(false),[notice,setNotice]=useState(''),[instructions,setInstructions]=useState('');
 const resultId=useId(),active=['queued','running'].includes(job.status),finished=['completed','partial','failed','interrupted'].includes(job.status),failed=['failed','interrupted'].includes(job.status);
 const drafts=downloadableDrafts(job),hasResult=!!job.result||failed||!!drafts.length,artifacts=[...(job.result?.artifacts||[]),...drafts];
 const timestamp=taskTimestamp(job,zh);
 async function copy(){
  setNotice('');setCopied(false);
  try{
   const {text}=await api<{text:string}>('/jobs/'+job.id+'/instructions');
   try{await navigator.clipboard.writeText(text);setCopied(true);setInstructions('');}
   catch{setInstructions(text);setNotice(zh?'请选择下方指令并复制。':'Select and copy the instructions below.');}
  }catch{setNotice(zh?'无法读取任务指令，请稍后重试。':'Could not load task instructions.');}
 }
 async function transition(action:'run'|'cancel'){
  setBusy(true);setNotice('');
  try{await api('/jobs/'+job.id+'/'+action,{base_revision:job.revision});await onChange();}
  catch{setNotice(zh?'操作未成功，请刷新状态后重试。':'Refresh the task state and try again.');}
  finally{setBusy(false);}
 }
 return <article className={'task-strip'+(selected?' is-selected':'')} data-task-status={job.status}>
  <div className="task-strip-header">
   <div className="task-strip-identity">
    <input type="checkbox" aria-label={(zh?'选择任务 ':'Select task ')+title} checked={selected} onChange={onSelect}/>
    <span className="task-strip-icon"><Terminal size={17}/></span>
    <div className="task-strip-name"><h3 title={title}>{title}</h3>{timestamp?<time className="task-strip-date" dateTime={timestamp.dateTime} title={timestamp.label} aria-label={timestamp.label+' '+timestamp.text}>{timestamp.text}</time>:<span className="task-strip-date">{zh?'时间未记录':'Time unavailable'}</span>}</div>
   </div>
   <span className={'badge task-strip-status status-'+job.status} role="status">{jobStatus(job.status,zh)}</span>
   <span className="task-strip-duration" title={finished?executionTime(job,zh):undefined}>{finished?executionTime(job,zh):''}</span>
   <div className="task-strip-actions">
    <button className="task-strip-button" onClick={()=>void copy()} aria-label={zh?'复制任务指令':'Copy task instructions'} title={zh?'复制任务指令':'Copy task instructions'}>{copied?<Check size={15}/>:<Copy size={15}/>}<span>{copied?(zh?'已复制':'Copied'):(zh?'复制指令':'Copy instructions')}</span></button>
    <button className="task-strip-button task-strip-result-toggle" disabled={!hasResult} aria-expanded={open} aria-controls={resultId} onClick={()=>setOpen(!open)}>{open?<ChevronDown size={15}/>:<ChevronRight size={15}/>}<span>{zh?'任务结果':'Results'}</span><small className={artifacts.length?'':'is-empty'} aria-hidden={!artifacts.length}>{artifacts.length||''}</small></button>
    <details className="task-strip-more"><summary aria-label={zh?'更多任务操作':'More task actions'} title={zh?'更多任务操作':'More task actions'}><MoreHorizontal size={19}/></summary><div className="task-strip-menu">
     {!finished&&!active&&<button disabled={busy} onClick={()=>void transition('run')}>{busy?<Loader2 size={14} className="spin"/>:<Play size={14}/>} {zh?'开始处理':'Start task'}</button>}
     {failed&&<button disabled={busy} onClick={()=>void transition('run')}><Play size={14}/> {zh?'重试任务':'Retry task'}</button>}
     {active&&<button disabled={busy} onClick={()=>void transition('cancel')}><Square size={14}/> {zh?'取消任务':'Cancel task'}</button>}
     <button disabled={busy} onClick={onDelete}><Trash2 size={14}/> {zh?'删除任务':'Delete task'}</button>
    </div></details>
   </div>
  </div>
  {notice&&<p className="task-strip-notice" role="status">{notice}</p>}
  {instructions&&<div className="task-strip-instructions"><div><strong>{zh?'任务指令':'Task instructions'}</strong><button className="icon-button" aria-label={zh?'关闭任务指令':'Close task instructions'} onClick={()=>setInstructions('')}><X size={16}/></button></div><textarea aria-label={zh?'任务指令文本':'Task instruction text'} readOnly value={instructions} onFocus={event=>event.target.select()}/></div>}
  <section className="task-strip-result" id={resultId} hidden={!open} aria-label={zh?'任务结果内容':'Task result content'}>{open&&<>
   {failed&&<p className="notice danger">{failureSummary(job,zh)}</p>}
   {job.status==='partial'&&job.task==='replicate_paper_figure'&&<p className="notice" role="status">{zh?'复刻尚未全部完成：':'Figure reconstruction is incomplete: '}{job.result?.warnings?.[0]||(zh?'仍有对象未完成，请查看结果提醒。':'Some objects remain incomplete. See the result notes.')}</p>}
   <TaskDrafts job={job} zh={zh}/>
   {children||(!failed&&<p className="muted">{zh?'暂无可查看的结果。':'No result is available.'}</p>)}
   <details className="task-strip-record"><summary>{zh?'执行详情与任务范围':'Execution details and scope'}</summary><TaskScope job={job} zh={zh}/><JobHandoff job={job} zh={zh} onChange={onChange}/></details>
  </>}</section>
 </article>;
}
