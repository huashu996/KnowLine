import {useContext,useEffect,useState} from 'react';import type {KB,Job} from './types';
import {LocaleContext,useT} from './i18n';
export default function KnowledgeBuildTiming({job,kb,initialBuild=false}:{job?:Job;kb?:KB;initialBuild?:boolean}){
 const t=useT(),locale=useContext(LocaleContext).locale==='zh'?'zh-CN':'en-US';
 const [now,setNow]=useState(Date.now());useEffect(()=>{const timer=setInterval(()=>setNow(Date.now()),1000);return()=>clearInterval(timer);},[]);
 if(!job)return null;const execution=(job as any).execution||{},timing=job.result?.knowledge_build_report?.timing||{},start=timing.started_at||(initialBuild&&(kb as any)?.created_at?(kb as any).created_at:job.created_at||execution.started_at),finish=timing.published_at||execution.finished_at;
 const seconds=Math.max(0,Math.floor(((finish?Date.parse(finish):now)-Date.parse(start))/1000));if(!Number.isFinite(seconds))return null;
 const duration=(seconds>=3600?Math.floor(seconds/3600)+t('hoursShort')+' ': '')+Math.floor(seconds/60)%60+t('minutesShort')+' '+seconds%60+t('secondsShort'),complete=kb?kb.knowledge_state==='organized':job.status==='completed';
 return <span className="knowledge-build-timing" data-build-start={start} data-build-finish={finish||''} data-build-elapsed={seconds} role="status"><strong>{t(complete&&finish?'buildCompletedTime':finish?'buildFinishedTime':'buildElapsedTime')} {duration}</strong><small>{t('startedAt')} {new Date(start).toLocaleString(locale)}{finish?' · '+t('finishedAt')+' '+new Date(finish).toLocaleString(locale):''}</small></span>;
}
