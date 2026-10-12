import {useRef,useState} from 'react';
import {upload} from './api';
import {useT} from './i18n';
import {codeAccept,projectArchive} from './codeImport';
import type {Group} from './types';
export default function ImportPicker({groups,domain,initialKind='paper',onDone,onError}:{groups:Group[];domain?:string;initialKind?:'paper'|'code';onDone:()=>Promise<void>;onError:(e:any)=>void}){
 const t=useT();
 const [target,setTarget]=useState(domain||''),[kind,setKind]=useState(initialKind),[busy,setBusy]=useState(false),[results,setResults]=useState<string[]>([]),folder=useRef<HTMLInputElement>(null);
 async function choose(list:FileList|null,directory=false){
  if(!list?.length)return;
  const files=Array.from(list),messages:string[]=[];setBusy(true);setResults([]);
  try{
   if(kind==='code'&&directory){
    const packed=await projectArchive(files),data=await upload(packed.file,'code-project',target);
    messages.push(packed.file.name.slice(0,-4)+'：'+(t(data.duplicate?(target?'importDuplicateDomain':'importDuplicate'):'importDone'))+t('importFileCount',{count:data.file_count}));
    const skipped=packed.skipped+(data.skipped_count||0);if(skipped)messages.push(t('importSkipped',{count:skipped}));
   }else{
    for(const file of files){
     if(kind==='paper'&&!file.name.toLowerCase().endsWith('.pdf'))continue;
     try{const data=await upload(file,kind,target);messages.push(file.name+'：'+(t(data.duplicate?(target?'importDuplicateDomain':'importDuplicate'):'importDone')));}
     catch(e){messages.push(file.name+'：'+t('importFailed'));onError(e);}
     setResults([...messages]);
    }
    if(!messages.length)messages.push(t('importNoPDF'));
   }
  }catch(e){messages.push(t('importProjectFailed'));onError(e);}
  finally{setResults(messages);try{await onDone();}finally{setBusy(false);}}
 }
 return <section className="import-picker">
  <label>{t('importKind')}<select aria-label={t('importKindInput')} value={kind} disabled={busy} onChange={e=>{setKind(e.target.value as 'paper'|'code');setResults([]);}}><option value="paper">{t('importPaper')}</option><option value="code">{t('importCode')}</option></select></label>
  <label>{t('importDomainOptional')}<select value={target} disabled={busy} onChange={e=>setTarget(e.target.value)}><option value="">{t('importLibraryOnly')}</option>{groups.map(g=><option key={g.id} value={g.id}>{g.name}</option>)}</select></label>
  <p>{t(kind==='paper'?'importPaperHint':'importCodeHint')} {' '}{t('importOriginalHint')}</p>
  <label className="file-picker-label">{t(kind==='paper'?'pickPDFs':'pickCodes')}<input key={kind} aria-label={t(kind==='paper'?'pickPDF':'pickCode')} type="file" accept={kind==='paper'?'.pdf,application/pdf':codeAccept} multiple disabled={busy} onChange={e=>{void choose(e.target.files);e.target.value='';}}/></label>
  <button className="button" disabled={busy} onClick={()=>folder.current?.click()}>{t(kind==='paper'?'pickPDFFolder':'pickCodeFolder')}</button>
  <input key={kind+'-folder'} aria-label={t(kind==='paper'?'pickPDFFolder':'pickCodeFolder')} hidden ref={folder} type="file" multiple disabled={busy} {...({webkitdirectory:''} as any)} onChange={e=>{void choose(e.target.files,true);e.target.value='';}}/>
  {busy&&<p role="status">{t('importWait')}</p>}<ul className="import-results">{results.map((result,i)=><li key={i}>{result}</li>)}</ul>
  <small>{t(kind==='paper'?'importPaperMetadataHint':'importCodeSafetyHint')}</small>
 </section>;
}
