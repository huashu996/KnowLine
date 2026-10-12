import {useLayoutEffect,useRef,useState,type ReactNode} from 'react';
import './list-performance.css';
/** The full result stays in the owner; only DOM rows are windowed. */
export default function VirtualRows<T>({items,height,render,itemKey}:{items:T[];height:number;render:(item:T,index:number)=>ReactNode;itemKey:(item:T)=>string}){
 const host=useRef<HTMLDivElement>(null),[range,setRange]=useState({start:0,end:30}),[measured,setMeasured]=useState(height),[focused,setFocused]=useState<string>();
 const rowHeight=Math.max(height,measured);
 useLayoutEffect(()=>{
  const element=host.current;if(!element)return;let scroll:HTMLElement|null=element.parentElement;
  while(scroll&&(!/(auto|scroll)/.test(getComputedStyle(scroll).overflowY)||scroll.scrollHeight<=scroll.clientHeight+1))scroll=scroll.parentElement;
  const target=scroll||window;let frame=0;
  const measure=()=>{frame=0;const row=element.querySelector<HTMLElement>('.resource-row');if(row)setMeasured(row.getBoundingClientRect().height);const viewport=scroll?scroll.getBoundingClientRect():{top:0,height:innerHeight},bounds=element.getBoundingClientRect();const start=Math.max(0,Math.min(items.length-1,Math.floor((viewport.top-bounds.top)/rowHeight)-6));const end=Math.min(items.length,start+Math.ceil(viewport.height/rowHeight)+12);setRange(old=>old.start===start&&old.end===end?old:{start,end});};
  const schedule=()=>{if(!frame)frame=requestAnimationFrame(measure);};target.addEventListener('scroll',schedule,{passive:true});window.addEventListener('resize',schedule);const observer=new ResizeObserver(schedule);observer.observe(element);if(scroll)observer.observe(scroll);measure();
  return()=>{cancelAnimationFrame(frame);target.removeEventListener('scroll',schedule);window.removeEventListener('resize',schedule);observer.disconnect();};
 },[items,rowHeight]);
 if(items.length<=120)return <>{items.map(render)}</>;
 const start=Math.min(range.start,Math.max(0,items.length-1)),end=Math.max(start,range.end);
 const indices=Array.from({length:Math.max(0,end-start)},(_,i)=>start+i),focusedIndex=focused?items.findIndex(item=>itemKey(item)===focused):-1;
 if(focusedIndex>=0&&!indices.includes(focusedIndex))indices.push(focusedIndex);
 return <div ref={host} className="virtual-rows" data-total={items.length} style={{height:items.length*rowHeight,position:'relative'}} onFocusCapture={event=>setFocused((event.target as HTMLElement).closest<HTMLElement>('[data-virtual-key]')?.dataset.virtualKey)} onBlurCapture={event=>{if(!event.currentTarget.contains(event.relatedTarget as Node))setFocused(undefined);}}>{indices.sort((a,b)=>a-b).map(index=><div key={itemKey(items[index])} data-virtual-key={itemKey(items[index])} style={{position:'absolute',top:index*rowHeight,left:0,right:0,height:rowHeight}}>{render(items[index],index)}</div>)}</div>;
}
