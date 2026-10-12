import type {Job} from './types';
import {useContext} from 'react';
import {LocaleContext,useT} from './i18n';
export function TaskScope({job,zh}:{job:Job;zh:boolean}){
 const t=useT();
 const context:any=job.context,s=context?.literature_search,scope=context?.scope;
 return <details className="job-scope-details"><summary>{zh?'任务范围':'Task scope'}</summary><p>{context?.domain?.name||context?.scope?.domain_name||job.question}</p>{s&&<p>{s.from_year??s.start_year??s.year_start??t('taskUnbounded')}—{s.to_year??s.end_year??s.year_end??t('taskUnbounded')} {t('taskYears')}{typeof (s.target_count??s.count)==='number'?t('taskTarget',{count:s.target_count??s.count}):''}</p>}<p>{context?.resources?.length?t('taskSelected',{count:context.resources.length}):t('taskSearchScope')}{scope?.kb_id?t('taskOnlyKnowledge'):''}</p><details className="task-technical"><summary>{zh?'技术详情':'Technical details'}</summary><pre>{[job.context_path,context?.output_dir].filter(Boolean).join('\n')}</pre></details></details>;
}
function artifactLabel(path:string,index:number,zh:boolean){
 const ext=path.split('.').pop()?.toLowerCase();
 if(!zh)return ext==='md'?'Read task report':ext==='pdf'?'View PDF document':ext==='docx'?'Download Word document':ext==='pptx'?'Download editable presentation':ext==='csv'?'Download paper list (CSV)':ext==='xlsx'?'Download results spreadsheet':'Download output '+(index+1);
 return ext==='md'?'阅读任务报告':ext==='pdf'?'查看 PDF 文档':ext==='docx'?'下载 Word 文档':ext==='pptx'?'下载可编辑演示文稿':ext==='csv'?'下载论文清单（表格）':ext==='xlsx'?'下载结果表格':'下载成果 '+(index+1);
}
export function TaskArtifacts({job}:{job:Job}){
 const zh=useContext(LocaleContext).locale!=='en';
 const values=job.result?.artifacts||[],human=values.filter((a:any)=>/\.(md|pdf|docx|pptx|csv|xlsx)$/i.test(a.path)),technical=values.filter((a:any)=>!human.includes(a));
 const links=(list:any[],friendly:boolean)=>list.map((a:any,i:number)=><a className="artifact-link" key={a.path} href={'/api/v1/jobs/'+job.id+'/artifact?path='+encodeURIComponent(a.path)} download>{friendly?artifactLabel(a.path,i,zh):a.path.split('/').pop()}</a>);
 return <>{human.length?links(human,true):<p className="muted">{zh?'处理结果已保存，可在对应资料或图谱中查看。':'Results are saved in the corresponding resources or graph.'}</p>}{technical.length>0&&<details className="task-technical"><summary>{zh?'技术文件':'Technical files'} · {technical.length}</summary><div className="technical-artifacts">{links(technical,false)}</div></details>}</>;
}

export function TaskDrafts({job,zh}:{job:Job;zh:boolean}){
 const drafts=downloadableDrafts(job);
 if(!drafts.length)return null;
 return <section className="task-draft-files" aria-label={zh?'已保存的 PPT':'Saved PPT'}>
  <p className="notice">{zh?'PPT 已保留。验收未通过，可先下载查看；这不表示任务已完成。':'The PPT is saved. It has not passed validation; download it to review. The task is still incomplete.'}</p>
  {drafts.map(a=><a className="artifact-link" key={a.path} href={'/api/v1/jobs/'+job.id+'/artifact?draft=true&path='+encodeURIComponent(a.path)+'&sha256='+encodeURIComponent(a.sha256)} download>{zh?'下载 PPT（未通过验收）':'Download PPT (validation not passed)'}</a>)}
 </section>;
}

export function downloadableDrafts(job:Job){
 // A partial task may already contain an accepted final PPT. Offer that
 // artifact instead of labelling its working copy as a failed presentation.
 if(job.status==='partial'&&job.result?.artifacts?.some((a:any)=>/\.pptx$/i.test(a.path)))return [];
 return job.draft_artifacts||[];
}
