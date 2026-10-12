import {useEffect,useLayoutEffect,useMemo,type MutableRefObject} from 'react';
import {ReferenceScene,targets} from './reference-neural/Scene';
import {referenceModules} from './reference-neural/theme';
import type {Category,KnowledgeData} from './nebulaData';
import './reference-neural/scene.css';
type Props={data:KnowledgeData;live:MutableRefObject<any>;paused:boolean;reduced:boolean;category:Category|null;selected:string|null;zoom:number;onCategory:(c:Category)=>void;onSelect:(id:string)=>void;onHoverCategory:(c:Category|null)=>void};
export default function NeuralReferenceVisual(p:Props){
 const MODULES=useMemo(()=>referenceModules(p.data.clusters),[p.data.clusters]);
 const items=useMemo(()=>[],[]),graph=useMemo(()=>({...p.data,nodes:p.data.nodes.map(n=>({...n,kind:n.category}))}),[p.data]);
 if(!p.live.current){const now=performance.now(),state={t0:now,time:0,stage:'hub',mod:null,modules:MODULES,items:[],size:{w:innerWidth,h:innerWidth<700?900:innerHeight},reduced:p.reduced,paused:p.paused||p.reduced,hover:null,itemState:[],fanStart:now,orb:{x:innerWidth/2,y:innerHeight*.53,s:440},springs:{}} as any,pose:any=targets(state,0),sp=(x:number)=>({x,v:0});state.springs={dust:sp(.3),orb:{x:sp(pose.orb.x),y:sp(pose.orb.y),s:sp(p.reduced?pose.orb.s:120),o:sp(p.reduced?1:0)},jelly:Object.fromEntries(MODULES.map((m:any)=>{const j=pose.jelly[m.id];return [m.id,{x:sp(p.reduced?j.x:pose.orb.x),y:sp(p.reduced?j.y:pose.orb.y),s:sp(p.reduced?j.s:20),o:sp(p.reduced?1:0),lo:sp(p.reduced?1:0)}];}))};p.live.current=state;}
 useLayoutEffect(()=>{const l=p.live.current;l.modules=MODULES;l.zoom=p.zoom;l.reduced=p.reduced;l.paused=p.paused||p.reduced;const candidate=p.category||p.data.nodes.find(n=>n.id===p.selected)?.category;l.mod=MODULES.some((m:any)=>m.id===candidate)?candidate:null;l.stage=l.mod?'module':'hub';l.syncVideo?.();l.requestRender?.();},[p.paused,p.reduced,p.category,p.selected,p.data,p.live,p.zoom,MODULES]);
 useEffect(()=>{const host=document.querySelector('.neural-reference-stage') as HTMLElement;if(!host)return;const l=p.live.current,resize=()=>{l.size={w:host.clientWidth,h:host.clientHeight};l.snapLayout=true;l.requestRender?.();},observer=new ResizeObserver(resize);observer.observe(host);resize();const sync=()=>{host.querySelectorAll('video').forEach(v=>{v.dataset.static=String(p.reduced);if(l.paused||l.reduced||document.hidden)v.pause();else v.play().catch(()=>{});});};l.syncVideo=sync;sync();host.querySelectorAll('video').forEach(v=>v.addEventListener('loadeddata',sync));document.addEventListener('visibilitychange',sync);return()=>{observer.disconnect();host.querySelectorAll('video').forEach(v=>{v.pause();v.removeEventListener('loadeddata',sync);});document.removeEventListener('visibilitychange',sync);};},[p.live,p.reduced]);
 return <div className={'neural-reference-stage'+(p.paused||p.reduced?' is-paused':'')} data-source-project="luoluo-121/neural-creator-dashboard"><ReferenceScene graph={graph} items={items} live={p.live} sel={p.selected} onModule={p.onCategory} onItem={p.onSelect} onHoverCategory={p.onHoverCategory}/></div>;
}


