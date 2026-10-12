import {useRef,useState} from 'react';import {replacePDF} from './api';
import {useT} from './i18n';
export default function PdfReplace({resources,onChange}:{resources:any[];onChange:(message:string)=>Promise<void>}){
 const t=useT();
 const fileInput=useRef<HTMLInputElement>(null),[busy,setBusy]=useState(false),[message,setMessage]=useState('');
 const resource=resources.length===1&&resources[0].type==='paper'?resources[0]:null;
 async function replace(file?:File){if(!file||!resource)return;setBusy(true);setMessage('');try{const data=await replacePDF(resource,file);const notice=t(data.unchanged?'replacePDFSame':'replacePDFDone');await onChange(notice);setMessage(notice);}catch(e:any){const messages:Record<string,string>={file_empty:'所选文件为空，请选择有效 PDF。',upload_too_large:'PDF 超过 128 MB，请先减小文件体积。',pdf_invalid:'所选文件不是可读取的 PDF，请重新选择。',revision_conflict:'这篇论文已经更新，请刷新后重试。',hash_conflict:'当前 PDF 已有变化，请刷新后重试。'};setMessage(messages[e.code]?t(e.code):t('replacePDFFailed'));}finally{setBusy(false);}}
 return <><button type="button" disabled={busy||!resource} title={resource?t('replacePDFTitle',{name:resource.title}):t('replacePDFSelect')} onClick={()=>fileInput.current?.click()}>{t('replacePDF')}</button><input ref={fileInput} hidden type="file" accept=".pdf,application/pdf" aria-label={t('replacePDFInput')} onChange={e=>{const file=e.target.files?.[0];e.target.value='';void replace(file);}}/>{message&&<span role="status">{message}</span>}</>;
}
