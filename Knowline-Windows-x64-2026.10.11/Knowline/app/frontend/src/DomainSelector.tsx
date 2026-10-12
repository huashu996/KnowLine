import {useEffect,useRef,useState} from 'react';
import {ChevronDown,ChevronRight} from 'lucide-react';
import type {Resource,Group} from './types';

function DomainCheck({ids,selected,onChange,label}:{ids:string[];selected:string[];onChange:()=>void;label:string}){
 const ref=useRef<HTMLInputElement>(null),count=ids.filter(id=>selected.includes(id)).length;
 useEffect(()=>{if(ref.current)ref.current.indeterminate=count>0&&count<ids.length;},[count,ids.length]);
 return <input ref={ref} type="checkbox" aria-label={label} checked={!!ids.length&&count===ids.length} disabled={!ids.length} onChange={onChange}/>;
}
export default function DomainSelector({resources,groups,selected,onChange,query='',locale}:{resources:Resource[];groups:Group[];selected:string[];onChange:(ids:string[])=>void;query?:string;locale:string}){
 const [expanded,setExpanded]=useState<string[]>([]),zh=locale==='zh';
 const ready=resources.filter(r=>r.state==='ready');
 const domains=[...groups,{id:'ungrouped',name:zh?'未归入领域':'Unassigned',resource_ids:ready.filter(r=>!groups.some(g=>g.resource_ids.includes(r.id))).map(r=>r.id)}];
 return <div className="member-selector domain-selector">{domains.map(g=>{const members=ready.filter(r=>g.resource_ids.includes(r.id)),hits=members.filter(r=>(r.title+' '+r.path).toLowerCase().includes(query.toLowerCase())),ids=members.map(r=>r.id),open=expanded.includes(g.id)||!!query;if(!hits.length)return null;return <section key={g.id}><div className="domain-select-heading"><button type="button" aria-label={(open?'折叠 ':'展开 ')+g.name} aria-expanded={open} onClick={()=>setExpanded(open?expanded.filter(id=>id!==g.id):[...expanded,g.id])}>{open?<ChevronDown size={16}/>:<ChevronRight size={16}/>}</button><DomainCheck ids={ids} selected={selected} label={'选择领域 '+g.name} onChange={()=>onChange(ids.every(id=>selected.includes(id))?selected.filter(id=>!ids.includes(id)):[...new Set([...selected,...ids])])}/><strong>{g.name}</strong><small>{ids.length} · {ids.filter(id=>selected.includes(id)).length} {zh?'已选':'selected'}</small></div>{open&&hits.map(r=><label className="member-option domain-select-member" key={r.id}><input type="checkbox" checked={selected.includes(r.id)} onChange={()=>onChange(selected.includes(r.id)?selected.filter(id=>id!==r.id):[...selected,r.id])}/><span><strong>{r.title}</strong><small>{r.type==='paper'?'论文':r.type==='code'?'代码':'网站 / 链接'}</small></span></label>)}</section>;})}</div>;
}
