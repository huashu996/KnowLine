import {useId, type ReactNode} from 'react';
import {X} from 'lucide-react';
import {useT} from './i18n';

export default function Modal({title,description,onClose,children,wide=false,busy=false}:{title:string;description?:string;onClose:()=>void;children:ReactNode;wide?:boolean;busy?:boolean}){
 const t=useT(),titleId=useId(),descriptionId=useId();
 return <div className="modal-backdrop" onMouseDown={event=>{if(event.target===event.currentTarget&&!busy)onClose();}}>
  <section role="dialog" aria-modal="true" aria-labelledby={titleId} aria-describedby={description?descriptionId:undefined} aria-busy={busy} className={'modal '+(wide?'wide':'')} tabIndex={-1}>
   <button data-dialog-close className="modal-close icon-button" aria-label={t('close')} disabled={busy} onClick={onClose}><X size={20}/></button>
   <h2 id={titleId}>{title}</h2>{description&&<p id={descriptionId} className="muted modal-description">{description}</p>}{children}
  </section>
 </div>;
}
