import {createPortal} from 'react-dom';
import {useState} from 'react';
import {api} from './api';
import Modal from './Modal';
import {useT} from './i18n';

export default function KnowledgeImport({onImported}:{onImported:(id:string)=>Promise<void>}){
 const t=useT();
 const [busy,setBusy]=useState(false),[picking,setPicking]=useState(false),[message,setMessage]=useState(''),[progress,setProgress]=useState('');
 const errors:Record<string,string>={knowledge_folder_required:'请选择知识库文件夹。',knowledge_folder_not_found:'所选文件夹已不可用，请重新选择。',knowledge_format_unsupported:'这个文件夹不是支持的知识库，请选择包含 .rag.manifest.json 的知识库文件夹。',knowledge_source_changed:'原库内容发生变化，请重新选择后导入。',knowledge_import_limit:'知识库超过本次导入限额，请拆分后再试。',knowledge_source_invalid:'原库内容或关系不完整，请先修复原库。',unsafe_link:'文件夹含有链接或快捷目录，请选择实际文件夹。',knowledge_folder_picker_busy:'文件夹选择窗口已经打开，请先完成选择。',knowledge_folder_picker_unavailable:'当前系统无法打开文件夹选择窗口，请在 Windows 知序中导入。',knowledge_folder_picker_failed:'文件夹选择窗口未能打开，请重试。'};
 async function chooseAndImport(){
  setBusy(true);setPicking(true);setMessage('');setProgress('');
  try{
   const selected=await api('/knowledge-bases/select-folder',{});
   setPicking(false);
   if(selected.cancelled)return;
   setProgress(t('readKnowledgeBusy'));
   const preview=await api('/knowledge-bases/import-preview',{folder:selected.folder});
   setProgress(t('importKnowledgeName',{name:preview.name}));
   const result=await api('/knowledge-bases/import-folder',{folder:selected.folder,name:preview.name,source_sha256:preview.source_sha256});
   await onImported(result.knowledge_base.id);
  }catch(e:any){setMessage(errors[e.code]?t(e.code):t('importIncomplete'));}
  finally{setBusy(false);setPicking(false);setProgress('');}
 }
 return <><button className="button" disabled={busy} onClick={()=>void chooseAndImport()}>{t(picking?'chooseFolderBusy':busy?'importBusy':'importExistingKnowledge')}</button>{!picking&&(message||progress)&&createPortal(<Modal title={t('importExistingKnowledge')} busy={busy} onClose={()=>setMessage('')}><p role="status">{message||progress}</p>{message&&<button className="button primary" onClick={()=>void chooseAndImport()}>{t('chooseFolderAgain')}</button>}</Modal>,document.body)}</>;
}
