import {useCallback,useRef, type Dispatch,type SetStateAction} from 'react';
import {api} from './api';
import type {Resource} from './types';
export const collectionScopes=['resources','knowledge-bases','groups','jobs','relations'];
export type CollectionSetters=Record<string,Dispatch<SetStateAction<any>>>;
/** Preserve per-collection epochs and revision guards for SSE and write refreshes. */
export function useCollectionRefresh(setters:CollectionSetters){
 const refreshEpoch=useRef<Record<string,number>>({}),owners=useRef(setters);owners.current=setters;
 const refresh=useCallback(async(scopes=collectionScopes,ids:string[]=[])=>{
  await Promise.all([...new Set(scopes)].map(async scope=>{
   const epoch=refreshEpoch.current[scope]=(refreshEpoch.current[scope]||0)+1,setValue=owners.current[scope];
   if(scope==='resources'&&ids.length&&ids.length<=30){
    const values=await Promise.all([...new Set(ids)].map(id=>api<Resource>('/resources/'+id).catch(error=>{if(error.code==='resource_not_found')return {id,state:'deleted'} as Resource;throw error;})));
    if(refreshEpoch.current[scope]!==epoch)return;
    setValue((previous:Resource[])=>{const updated=new Map(previous.map(resource=>[resource.id,resource]));values.forEach(resource=>{if(resource.state==='deleted')updated.delete(resource.id);else if(!updated.has(resource.id)||updated.get(resource.id)!.revision<=resource.revision)updated.set(resource.id,resource);});return [...updated.values()];});
   }else{
    const value=await api('/'+scope+(scope==='resources'?'?summary=true':''));
    if(refreshEpoch.current[scope]!==epoch)return;
    if(scope==='resources')setValue((previous:Resource[])=>{const current=new Map(previous.map(resource=>[resource.id,resource]));return value.map((resource:Resource)=>{const old=current.get(resource.id);return old&&old.revision>resource.revision?old:resource;});});
    else setValue(value);
   }
  }));
 },[]);
 return {refresh,refreshEpoch};
}
