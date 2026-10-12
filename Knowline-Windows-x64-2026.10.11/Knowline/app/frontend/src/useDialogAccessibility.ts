import {useEffect} from 'react';

const focusable='button:not([disabled]),input:not([disabled]):not([type=hidden]),select:not([disabled]),textarea:not([disabled]),a[href],[tabindex]:not([tabindex="-1"])';
const visible=(element:HTMLElement)=>!!element.getClientRects().length&&!element.closest('[inert]');
/** Also covers existing task, reader and native-picker result dialogs. */
export function useDialogAccessibility(){
 useEffect(()=>{
  let current:HTMLElement|null=null,restore:HTMLElement|null=null,previousFocus=document.activeElement instanceof HTMLElement?document.activeElement:null,isolated:HTMLElement[]=[];
  const restoreBackground=()=>{isolated.forEach(element=>element.inert=false);isolated=[];};
  const controls=()=>current?Array.from(current.querySelectorAll<HTMLElement>(focusable)).filter(visible):[];
  const focusFirst=()=>{if(!current)return;const values=controls(),initial=current.querySelector<HTMLElement>('[autofocus]')||values.find(element=>!element.matches('.modal-close,[data-dialog-close]'))||values[0]||current;initial.focus({preventScroll:true});};
  const sync=()=>{
   const dialogs=Array.from(document.querySelectorAll<HTMLElement>('[role="dialog"][aria-modal="true"]')).filter(element=>!!element.getClientRects().length);
   const next=dialogs.at(-1)||null;if(next===current)return;
   restoreBackground();
   if(!next){current=null;if(restore?.isConnected&&!restore.closest('[inert]'))restore.focus({preventScroll:true});restore=null;return;}
   if(!current)restore=previousFocus;
   current=next;current.tabIndex=-1;
   for(let child:HTMLElement=next;child.parentElement;child=child.parentElement){for(const sibling of Array.from(child.parentElement.children)){if(sibling!==child&&sibling instanceof HTMLElement&&!sibling.inert&&!sibling.matches('script,style,link')){sibling.inert=true;isolated.push(sibling);}}}
   if(!next.contains(document.activeElement))focusFirst();
  };
  const key=(event:KeyboardEvent)=>{
   if(!current)return;
   if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='k'){event.preventDefault();event.stopImmediatePropagation();const search=current.querySelector<HTMLInputElement>('input[type=search]');search?.focus();return;}
   if(event.key==='Escape'){
    event.preventDefault();event.stopImmediatePropagation();
    const close=current.querySelector<HTMLButtonElement>('[data-dialog-close],.modal-close')||Array.from(current.querySelectorAll<HTMLButtonElement>('.modal-actions button')).find(button=>/^(取消|关闭|Cancel|Close)$/i.test(button.textContent?.trim()||''));
    if(current.getAttribute('aria-busy')!=='true'&&close&&!close.disabled)close.click();return;
   }
   if(event.key!=='Tab')return;
   const values=controls(),first=values[0],last=values.at(-1);
   if(!first){event.preventDefault();current.focus();return;}
   if(event.shiftKey&&(document.activeElement===first||!current.contains(document.activeElement))){event.preventDefault();last!.focus();}
   else if(!event.shiftKey&&(document.activeElement===last||!current.contains(document.activeElement))){event.preventDefault();first.focus();}
  };
  const focus=(event:FocusEvent)=>{if(current&&event.target instanceof Node&&!current.contains(event.target))focusFirst();else if(!current&&event.target instanceof HTMLElement&&!event.target.closest('[role="dialog"][aria-modal="true"]'))previousFocus=event.target;};
  const observer=new MutationObserver(sync);observer.observe(document.body,{childList:true,subtree:true});sync();
  window.addEventListener('keydown',key,true);document.addEventListener('focusin',focus,true);
  return()=>{observer.disconnect();window.removeEventListener('keydown',key,true);document.removeEventListener('focusin',focus,true);restoreBackground();};
 },[]);
}
