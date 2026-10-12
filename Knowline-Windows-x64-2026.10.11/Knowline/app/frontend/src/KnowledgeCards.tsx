import {useEffect,useState} from 'react';
import {api} from './api';
import {useT} from './i18n';
import type {KB} from './types';
import Markdown from 'react-markdown';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import 'katex/dist/katex.min.css';

export default function KnowledgeCards({kb,locale,onEvidence,onError}:{kb:KB;locale:string;onEvidence:(e:any)=>void;onError:(e:any)=>void}){
 const t=useT();
 const [cards,setCards]=useState<any[]>([]),[layer,setLayer]=useState('all'),[limit,setLimit]=useState(30);
 useEffect(()=>{let active=true;setCards([]);setLimit(30);api('/knowledge-bases/'+kb.id+'/cards').then(data=>{if(active)setCards(data.cards);}).catch(onError);return()=>{active=false;};},[kb.id,kb.revision,kb.build_id,kb.index_state]);
 const zh=locale==='zh';
 return <div className="knowledge-cards"><div className="knowledge-layer-tabs"><button className={layer==='all'?'active':''} onClick={()=>setLayer('all')}>{zh?'全部知识':'All cards'}</button>{kb.layers?.map(l=><button key={l.id} title={l.focus} className={layer===l.id?'active':''} onClick={()=>setLayer(l.id)}>{l.name}</button>)}</div>{kb.layers?.filter(l=>layer==='all'||layer===l.id).map(l=><div className="layer-focus" key={l.id}><strong>{l.name}</strong><p>{l.focus}</p></div>)}{!cards.length?<div className="notice">{zh?'原文索引不等于知识整理。AI 构建任务将按上述主题与侧重点生成知识内容、来源和关联，通过验收后在这里显示。可以在智能体任务中查看实际状态。':'Source indexing is separate from knowledge organization. Ask AI in this project to analyze these layers; evidence-backed cards will appear here.'}</div>:cards.filter(c=>layer==='all'||c.layer_id===layer).slice(0,limit).map(c=><article className="knowledge-card" id={'knowledge-card-'+c.id} key={c.id}><small>{kb.layers?.find(l=>l.id===c.layer_id)?.name} · {c.origin==='imported'?t('importedKnowledgeStatus'):zh?'AI 整理 · 待审核':'AI · Needs review'}</small><h3>{c.title}</h3>{c.figure&&<img loading="lazy" alt={c.title} src={'/api/v1/knowledge-bases/'+kb.id+'/cards/'+encodeURIComponent(c.id)+'/figure'}/>}<div className="knowledge-markdown"><Markdown remarkPlugins={[remarkMath]} rehypePlugins={[[rehypeKatex,{trust:false,strict:false}]]}>{c.content}</Markdown></div><div className="card-evidence">{c.imported_sources?.map((s:any,i:number)=><a className="small-button" key={i} href={'/api/v1/knowledge-bases/'+s.kb_id+'/imported-source/'+encodeURIComponent(s.document_id)} target="_blank" rel="noreferrer">{t('importedKnowledgeSource')} · {s.title}</a>)}{c.evidence.map((e:any,i:number)=><button className="small-button" key={i} onClick={()=>onEvidence(e)}>{zh?'查看原文':'Open source'} · {e.page_index!=null?(zh?'第 '+(e.page_index+1)+' 页':'Page '+(e.page_index+1)):e.file?e.file+':'+e.line_start:(zh?'本地网站链接':'Local website link')}</button>)}</div>{c.links?.map((id:string)=><button className="small-button" key={id} onClick={()=>{setLayer('all');setTimeout(()=>document.getElementById('knowledge-card-'+id)?.scrollIntoView({block:'center'}),0);}}>{zh?'关联知识':'Related card'}: {cards.find(v=>v.id===id)?.title}</button>)}</article>)}{cards.filter(c=>layer==='all'||c.layer_id===layer).length>limit&&<button className="button" onClick={()=>setLimit(n=>n+30)}>{t('moreKnowledge')}</button>}</div>;
}

