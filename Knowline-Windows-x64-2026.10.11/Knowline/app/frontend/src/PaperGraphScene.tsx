import {useT} from './i18n';
import {useEffect,useMemo,useRef,useState} from 'react';
import {Minus,Plus,RotateCcw,Pause,Play} from 'lucide-react';
import {nodeNebulaUri,nodeNebulaFringe,nodeNebulaStats,prepareNodeNebula,nodeNebulaLoaded} from './nodeNebula';

export type Paper={id:string;title:string;authors:any[];year:number|null;venue:string;citation_count:number|null;metadata_source:any;abstract?:string;abstract_source?:any;download_sources?:any[];cached_resources?:{resource_id:string;version_id:string;sha256:string}[];full_text_status?:string;full_text_reason?:string;citation_source?:any;citation_alternatives?:{citation_count:number;citation_source:{url:string;retrieved_at:string;provider?:string}}[];citation_unknown_reason?:string;doi?:string};
export type PaperGraph={full_text_summary?:{pdf_saved:number;pdf_missing:number;abstracts:number;total:number};origin_id:string;nodes:Paper[];edges:{source:string;target:string;weight:number;kind:string;evidence:any[]}[]};
export const names=(authors:any[])=>authors.map(a=>typeof a==='string'?a:[a.given,a.family].filter(Boolean).join(' ')).join('; ');
// Citations are external, sourced counts. Graph degree never stands in for impact.
export const citationRadius=(count:number|null,max:number)=>{if(count===null)return 4.5;if(max<=0)return 5.5;const fraction=Math.log1p(Math.max(0,count))/Math.log1p(max);return 5.5+10.5*fraction+6*Math.pow(Math.max(0,(fraction-.45)/.55),2);};
// Actual publication years map from red → yellow → blue → white, using actual publication years.
const yearFraction=(year:number|null,first:number,last:number)=>typeof year==='number'&&Number.isFinite(year)&&year>0?(last===first?.5:Math.max(0,Math.min(1,(year-first)/(last-first)))):null;
const yearColor=(fraction:number|null)=>{
 if(fraction===null)return '#9ba6b5';
 const stops=[{at:0,rgb:[255,142,92]},{at:.32,rgb:[255,212,119]},{at:.68,rgb:[120,194,255]},{at:1,rgb:[244,248,255]}];
 const upper=stops.findIndex(s=>s.at>=fraction),right=stops[Math.max(1,upper)],left=stops[Math.max(0,upper-1)],t=(fraction-left.at)/(right.at-left.at);
 return `rgb(${left.rgb.map((v,i)=>Math.round(v+(right.rgb[i]-v)*t)).join(' ')})`;
};
const luminosity=(fraction:number|null)=>fraction===null?.7:.62+.38*fraction;
const authorLabel=(n:Paper)=>{const a=n.authors[0];return (typeof a==='string'?a.trim().split(/\s+/).at(-1):a?.family)||names(n.authors).split(';')[0]||n.title.slice(0,14);};

// Weighted communities use existing citation and semantic edges; no new relationships are created.
export function paperTopologyLayout(graph:PaperGraph){
 const ids=new Map(graph.nodes.map((n,i)=>[n.id,i])),adj=graph.nodes.map(()=>graph.nodes.map(()=>0)),degree=graph.nodes.map(()=>0);
 let total=0;
 for(const e of graph.edges){const a=ids.get(e.source),b=ids.get(e.target);if(a===undefined||b===undefined||a===b)continue;const w=e.weight*(e.kind==='semantic_similarity'?.65:1);adj[a][b]+=w;adj[b][a]+=w;degree[a]+=w;degree[b]+=w;total+=w;}
 const groups=graph.nodes.map((_,i)=>[i]);
 if(total>0)while(groups.length>1){let best=0,pair:number[]=[];
  for(let a=0;a<groups.length;a++)for(let b=a+1;b<groups.length;b++){
   const cross=groups[a].reduce((sum,i)=>sum+groups[b].reduce((v,j)=>v+adj[i][j],0),0),da=groups[a].reduce((v,i)=>v+degree[i],0),db=groups[b].reduce((v,i)=>v+degree[i],0),gain=cross-da*db/(2*total);
   if(gain>best+1e-8){best=gain;pair=[a,b];}
  }
  if(!pair.length)break;groups[pair[0]].push(...groups[pair[1]]);groups.splice(pair[1],1);
 }
 const origin=ids.get(graph.origin_id);groups.sort((a,b)=>a.includes(origin??-1)?-1:b.includes(origin??-1)?1:Math.min(...a)-Math.min(...b));
 const peers=graph.nodes.map(()=>new Set<number>());
 for(const e of graph.edges){const a=ids.get(e.source),b=ids.get(e.target);if(a===undefined||b===undefined||a===b||a===origin||b===origin||e.kind==='semantic_similarity')continue;peers[a].add(b);peers[b].add(a);}
 const degreeValues=[...new Set(graph.nodes.filter(n=>n.id!==graph.origin_id).map(n=>peers[ids.get(n.id)!].size))].sort((a,b)=>b-a),levels=Math.min(4,degreeValues.length),radii=levels===1?[150]:Array.from({length:levels},(_,i)=>65+i*135/(levels-1));
 const nodes=graph.nodes.map((n,i)=>{const community=groups.findIndex(g=>g.includes(i)),peerDegree=peers[i].size,ring=n.id===graph.origin_id?-1:Math.min(levels-1,Math.floor(degreeValues.indexOf(peerDegree)*levels/degreeValues.length));return {...n,community,peerDegree,ring,angle:community*2.39996+i*.3,x:400,y:265};});
 const rings=radii.map((_,level)=>nodes.filter(n=>n.ring===level).sort((a,b)=>a.community-b.community||a.id.localeCompare(b.id)));
 // Only angular order changes during refinement; degree strata never drift out.
 for(let pass=0;pass<6;pass++)for(let level=0;level<rings.length;level++){
  const ring=rings[level];if(pass)ring.sort((a,b)=>{
   const bearing=(n:typeof a)=>{const i=ids.get(n.id)!,weights=nodes.filter(p=>p.id!==graph.origin_id&&p.id!==n.id).map(p=>({angle:p.angle,w:adj[i][ids.get(p.id)!]})),x=weights.reduce((s,p)=>s+Math.cos(p.angle)*p.w,0),y=weights.reduce((s,p)=>s+Math.sin(p.angle)*p.w,0);return x||y?Math.atan2(y,x):n.angle;};
   return bearing(a)-bearing(b)||a.id.localeCompare(b.id);
  });
  ring.forEach((n,i)=>{n.angle=-Math.PI/2+2*Math.PI*(i+.23*level)/ring.length;n.x=400+Math.cos(n.angle)*radii[level];n.y=265+Math.sin(n.angle)*radii[level];});
 }
 return nodes;
}


const particleSeed=(key:number)=>{let v=Math.imul(key+101,2246822507);v=Math.imul(v^(v>>>13),3266489909);return ((v^(v>>>16))>>>0)/4294967296;};

export default function PaperGraphScene({graph,active,onSelect,zh}:{graph:PaperGraph;active?:Paper;onSelect:(n:Paper)=>void;zh:boolean}){
 const t=useT();
 const [paused,setPaused]=useState(false),[reduced,setReduced]=useState(()=>matchMedia('(prefers-reduced-motion: reduce)').matches),[hidden,setHidden]=useState(document.hidden);
 useEffect(()=>{const mq=matchMedia('(prefers-reduced-motion: reduce)'),motion=()=>setReduced(mq.matches),visibility=()=>setHidden(document.hidden);mq.addEventListener('change',motion);document.addEventListener('visibilitychange',visibility);return()=>{mq.removeEventListener('change',motion);document.removeEventListener('visibilitychange',visibility);};},[]);
 const [nebulaRevision,setNebulaRevision]=useState(()=>nodeNebulaLoaded()?1:0);useEffect(()=>{let live=true;prepareNodeNebula().then(ok=>{if(live&&ok)setNebulaRevision(1);});return()=>{live=false;};},[]);const [zoom,setZoom]=useState(1),[pan,setPan]=useState({x:0,y:0}),[dragging,setDragging]=useState(false),[positions,setPositions]=useState<Record<string,{x:number;y:number}>>({});
 const drag=useRef({x:0,y:0,startX:0,startY:0,moved:false,pointer:-1,nodeId:''});
 const visibleEdges=useMemo(()=>graph.edges.filter(e=>e.kind==='citation'),[graph]);
 const coordinates=useMemo(()=>paperTopologyLayout({...graph,edges:visibleEdges}),[graph,visibleEdges]);
 const maxCitations=Math.max(0,...graph.nodes.map(n=>n.citation_count??0));
 const points=coordinates.map(n=>({...n,...positions[n.id]})),byId=new Map(points.map(n=>[n.id,n]));
 const years=graph.nodes.map(n=>n.year).filter((y):y is number=>typeof y==='number'&&Number.isFinite(y)&&y>0),first=years.length?Math.min(...years):0,last=years.length?Math.max(...years):0;
 const linked=new Set(active?[active.id,...visibleEdges.filter(e=>e.source===active.id||e.target===active.id).flatMap(e=>[e.source,e.target])]:[]);
 const nebulae=useMemo(()=>graph.nodes.map((n,i)=>nodeNebulaUri(yearColor(yearFraction(n.year,first,last)),i,citationRadius(n.citation_count,maxCitations)<9,n.citation_count===null,Math.min(1,citationRadius(n.citation_count,maxCitations)/22))),[graph,first,last,maxCitations,nebulaRevision]);
 const labels=new Map<string,{x:number;y:number;w:number;h:number;text:string}>(),placed:{x:number;y:number;w:number;h:number}[]=[];
 for(const n of [...points].sort((a,b)=>a.id===graph.origin_id?-1:b.id===graph.origin_id?1:a.y-b.y)){
  const full=authorLabel(n)+', '+(n.year??'年份未知'),text=full.length>19?full.slice(0,18)+'…':full;
  const w=Math.min(132,Math.max(54,text.length*5.8+12)),h=18,r=Math.max(18,citationRadius(n.citation_count,maxCitations)*2.1);
  const options=[{x:n.x-w/2,y:n.y-r-23},{x:n.x-w/2,y:n.y+r+8},{x:n.x+r+11,y:n.y-h/2},{x:n.x-r-w-11,y:n.y-h/2}];
  const clamp=(v:number,min:number,max:number)=>Math.max(min,Math.min(max,v));
  const overlap=(a:{x:number;y:number;w:number;h:number},b:{x:number;y:number;w:number;h:number})=>Math.max(0,Math.min(a.x+a.w,b.x+b.w)-Math.max(a.x,b.x))*Math.max(0,Math.min(a.y+a.h,b.y+b.h)-Math.max(a.y,b.y));
  const candidate=options.map((o,i)=>{const box={x:clamp(o.x,5,795-w),y:clamp(o.y,5,495-h),w,h};return {box,score:i*3+placed.reduce((sum,p)=>sum+overlap(box,p)*2,0)+points.filter(p=>p.id!==n.id).reduce((sum,p)=>sum+overlap(box,{x:p.x-citationRadius(p.citation_count,maxCitations)-3,y:p.y-citationRadius(p.citation_count,maxCitations)-3,w:2*citationRadius(p.citation_count,maxCitations)+6,h:2*citationRadius(p.citation_count,maxCitations)+6})*.7,0)};}).sort((a,b)=>a.score-b.score)[0].box;
  labels.set(n.id,{...candidate,text});placed.push(candidate);
 }
 function reset(){setZoom(1);setPan({x:0,y:0});setPositions({});}
 return <div className={'paper-network '+(dragging?'dragging':'')} data-alpha-profile="round-continuous-fade-v5" data-node-motion={paused||reduced||hidden||dragging?'paused':'running'} data-node-texture-source={nebulaRevision?"user-round-nebula-v4-20261006":"loading"} data-node-texture-generations={nodeNebulaStats.generations} data-node-texture-ms={nodeNebulaStats.durationMs}>
  <div className="paper-network-heading" aria-hidden="true"><span className="paper-network-beacon"/><div><strong>{zh?'论文星图':'RESEARCH CONSTELLATION'}</strong><small>{graph.nodes.length} {zh?'篇论文':'papers'} · {visibleEdges.length} {zh?'条引用':'citations'}</small></div></div>
  <svg viewBox="0 0 800 520" aria-label={zh?'二维论文关系网络':'2D paper relationship network'} role="img"
   onPointerDown={e=>{if(e.button!==0)return;const matrix=e.currentTarget.getScreenCTM();if(!matrix)return;const p=new DOMPoint(e.clientX,e.clientY).matrixTransform(matrix.inverse()),nodeId=(e.target as Element).closest('[data-node-id]')?.getAttribute('data-node-id')||'',node=byId.get(nodeId);
    drag.current={x:p.x,y:p.y,startX:node?.x??pan.x,startY:node?.y??pan.y,moved:false,pointer:e.pointerId,nodeId};e.currentTarget.setPointerCapture(e.pointerId);setDragging(true);}}
   onPointerMove={e=>{const d=drag.current;if(d.pointer!==e.pointerId)return;const matrix=e.currentTarget.getScreenCTM();if(!matrix)return;const p=new DOMPoint(e.clientX,e.clientY).matrixTransform(matrix.inverse()),dx=p.x-d.x,dy=p.y-d.y;
    if(Math.hypot(dx,dy)>4)d.moved=true;if(!d.moved)return;if(d.nodeId)setPositions(prev=>({...prev,[d.nodeId]:{x:d.startX+dx/zoom,y:d.startY+dy/zoom}}));else setPan({x:d.startX+dx,y:d.startY+dy});}}
   onPointerUp={e=>{const d=drag.current;if(d.pointer!==e.pointerId)return;if(!d.moved&&d.nodeId){const n=byId.get(d.nodeId);if(n)onSelect(n);}d.pointer=-1;setDragging(false);if(e.currentTarget.hasPointerCapture(e.pointerId))e.currentTarget.releasePointerCapture(e.pointerId);}}
   onPointerCancel={()=>{drag.current.pointer=-1;drag.current.moved=true;setDragging(false);}}
   onLostPointerCapture={()=>{drag.current.pointer=-1;setDragging(false);}}>
   <defs>{points.map((n,index)=>{const c=yearColor(yearFraction(n.year,first,last));return <radialGradient id={'paper-star-'+index} key={n.id}><stop offset="0%" stopColor={c} stopOpacity=".82"/><stop offset="24%" stopColor={c} stopOpacity=".55"/><stop offset="58%" stopColor={c} stopOpacity=".18"/><stop offset="100%" stopColor={c} stopOpacity="0"/></radialGradient>;})}</defs>
   <rect data-paper-background="pure-black" width="800" height="520" fill="#000000" pointerEvents="none"/>
   <g transform={`translate(${pan.x+400} ${pan.y+240}) scale(${zoom}) translate(-400 -240)`}>
    <g className="paper-topology-rings" pointerEvents="none" aria-hidden="true">{[...new Set(coordinates.filter(n=>n.ring>=0).map(n=>Math.round(Math.hypot(n.x-400,n.y-265))))].map(r=><circle key={r} cx={400} cy={265} r={r}/>)}</g>
    {visibleEdges.map((e,i)=>{const a=byId.get(e.source),b=byId.get(e.target);if(!a||!b)return null;const highlighted=!!active&&(e.source===active.id||e.target===active.id),center=e.source===graph.origin_id||e.target===graph.origin_id,color=center?'#e8bc73':'#8eefff',width=Math.min(1.35,.75+e.weight*.2);return <g key={i} data-source={e.source} data-target={e.target} data-kind={e.kind} data-center-edge={center} className={'paper-edge '+(active&&!highlighted?'is-muted':'')} pointerEvents="none"><line className="paper-edge-glow" x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={color} strokeWidth={width+1} opacity={highlighted?.07:.025}/><line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={color} strokeWidth={width} opacity={highlighted?.95:active?.3:.7}/><title>{zh?'来源支持的直接引用':'Sourced direct citation'}</title></g>;})}
    {points.map((n,index)=>{const r=citationRadius(n.citation_count,maxCitations),fraction=yearFraction(n.year,first,last),f=luminosity(fraction),color=yearColor(fraction),origin=n.id===graph.origin_id,selected=active?.id===n.id,label=labels.get(n.id)!,known=n.citation_count!==null;return <g key={n.id} className={'paper-graph-node'+(origin?' is-origin':'')+(selected?' is-selected':'')+(known?' is-known':' is-unknown')} role="button" tabIndex={0} aria-label={n.title} data-node-id={n.id} data-year-color={color} data-citations={known?n.citation_count:'unknown'} data-luminosity={f} data-community={n.community} data-peer-degree={n.peerDegree} data-topology-ring={n.ring} data-year-state={fraction===null?'unknown':'known'} onClick={e=>{if(e.detail===0)onSelect(n);}} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();onSelect(n);}}}>
     <circle className="paper-node-hit" cx={n.x} cy={n.y} r={Math.max(12,r+5)} fill="transparent"/><circle className="paper-node-core" cx={n.x} cy={n.y} r={r} fill="none" data-nebula-radius={r} stroke={known?'none':color} strokeWidth={known?0:.8} strokeDasharray={known?undefined:'1.5 2.5'}/>
     <image style={{animationDuration:(90+index%5*6)+'s',animationDelay:(-index*8.7)+'s'}} className="paper-node-nebula" href={nebulae[index]} x={n.x-Math.max(18,r*1.75)} y={n.y-Math.max(18,r*1.75)} width={Math.max(36,r*3.5)} height={Math.max(36,r*3.5)} opacity={1} pointerEvents="none"/>
     <g className="paper-nebula-fringe" style={{transformOrigin:`${n.x}px ${n.y}px`,animationDuration:(108+index%4*4)+'s',animationDelay:(-index*7.3)+'s'}} pointerEvents="none" aria-hidden="true">{nodeNebulaFringe(index,r<9).map((p,k)=>{const size=Math.max(36,r*3.5);return <circle key={k} className="paper-fringe-particle" style={{animationDelay:-p.phase+'s',animationDuration:4+particleSeed(index*91+k*7)*4+'s'}} cx={n.x+p.x*size} cy={n.y+p.y*size} r={p.r*size} fill={color} opacity={p.opacity}/>;})}</g>
     <g className="paper-node-label" pointerEvents="none"><line className="paper-label-leader" x1={n.x} y1={n.y} x2={Math.max(label.x,Math.min(label.x+label.w,n.x))} y2={Math.max(label.y,Math.min(label.y+label.h,n.y))} stroke={selected?'#ffaad1':'#c9d2dc'} strokeWidth={.45} opacity={.42}/><text style={{fill:selected?'#ffaad1':'#f8fafc'}} data-label-state={selected?'selected':'ordinary'} x={label.x+label.w/2} y={label.y+13} textAnchor="middle">{label.text}</text></g><title>{n.title+' · '+(n.citation_count===null?(zh?'引用次数未知': 'Citation count unknown'):n.citation_count+(zh?' 次引用':' citations'))}</title>
    </g>;})}
   </g>
  </svg>
  <span className="paper-network-hint">{zh?'拖动空白处平移 · 拖动节点调整 · 点击查看来源':'Drag background to pan · Drag nodes to arrange · Click for sources'}</span>
  <div className="paper-relation-legend" aria-label={zh?'关系线说明':'Relationship legend'}><span><i className="center-edge-swatch"/>{zh?'目标论文引用':'Target citations'}</span><span><i className="peer-edge-swatch"/>{zh?'其他论文引用':'Peer citations'}</span></div>
  <div className="paper-year-legend" aria-label={zh?'论文年份明暗：越新越亮':'Paper luminosity: newer is brighter'}>
   <span>{zh?'发表时间 · 越新越亮':'Publication year · newer is brighter'}</span>
   <div className="paper-year-gradient" style={{background:last===first?yearColor(years.length?.5:null):`linear-gradient(to right, ${yearColor(0)} 0%, ${yearColor(.32)} 32%, ${yearColor(.68)} 68%, ${yearColor(1)} 100%)`}}/>
   <div className="paper-year-ticks"><span>{years.length?first+' · 较早':'年份未知'}</span><span>{years.length?last+' · 较新':''}</span></div>{years.length<graph.nodes.length&&<small>{t('unknownYearLegend')}</small>}
  </div>
  <div className="paper-citation-legend" aria-label={zh?'星辰大小表示有来源的总被引次数':'Star size shows sourced total citations'}>{zh?'星辰大小 · 总被引次数':'Star size · indexed citations'}<span>● 0 · ● {maxCitations.toLocaleString()} · ◌ {zh?'未知':'unknown'}</span></div>
  <div className="paper-graph-zoom"><button aria-label={zh?(paused?'播放节点自转':'暂停节点自转'):(paused?'Play node rotation':'Pause node rotation')} disabled={reduced} onClick={()=>setPaused(p=>!p)} title={reduced?(zh?'系统减少动态效果':'Reduced motion'):undefined}>{paused||reduced?<Play size={16}/>:<Pause size={16}/>}</button><button aria-label={zh?'缩小关系图':'Zoom out'} onClick={()=>setZoom(z=>Math.max(.55,z-.15))}><Minus size={16}/></button><button aria-label={zh?'放大关系图':'Zoom in'} onClick={()=>setZoom(z=>Math.min(1.7,z+.15))}><Plus size={16}/></button><button aria-label={zh?'重置关系图视角':'Reset graph view'} onClick={reset}><RotateCcw size={16}/></button></div>
 </div>;
}





