import {useEffect,useLayoutEffect,useRef,useState} from 'react';
import type {CSSProperties} from 'react';
import {Download,Highlighter,MessageSquare,FileCode2,Folder,ShieldCheck,Loader2,X} from 'lucide-react';
import CodeTree from './CodeTree';
import CodeSource from './CodeSource';
import {api,revision} from './api';
import {useT} from './i18n';
import type {Resource} from './types';
import type {SourceTarget} from './Readers';
import './code-reader.css';

type RangeSpec={line_start:number;line_end:number;column_start:number;column_end:number;quote:string};
type Annotation={id:string;version_id:string;revision:number;data:RangeSpec&{kind:string;file:string;file_sha256:string;encoding:string;color:number[];comment:string}};
const colors=[[1,.78,.24],[.35,.85,.65],[.4,.7,1]];

export default function CodeReader({resource:r,target,onChange,onError,onToast}:{resource:Resource;target?:SourceTarget;onChange:()=>Promise<void>;onError:(e:any)=>void;onToast:(s:string)=>void}){
 const t=useT(),source=useRef<HTMLDivElement>(null);
 const [fontSize,setFontSize]=useState(()=>{try{const size=Number(localStorage.getItem('knowline-code-font-size'));return size>=10&&size<=30?size:14;}catch{return 14;}});
 const zoomAnchor=useRef<{top:number;left:number;y:number;x:number;size:number}|undefined>(undefined);
 function zoom(step:number){setFontSize(size=>Math.max(10,Math.min(30,size+step)));}
 const [files,setFiles]=useState<any[]>([]),[filter,setFilter]=useState(''),[selected,setSelected]=useState(target?.file||''),[content,setContent]=useState<any>(),[encoding,setEncoding]=useState('utf-8-sig'),[loading,setLoading]=useState(true),[error,setError]=useState('');
 const [selection,setSelection]=useState<RangeSpec>(),[annotations,setAnnotations]=useState<Annotation[]>([]),[annotating,setAnnotating]=useState<{kind:string;range:RangeSpec;existing?:Annotation}>(),[comment,setComment]=useState(''),[color,setColor]=useState(colors[0]),[saving,setSaving]=useState(false),[showNotes,setShowNotes]=useState(false),[focused,setFocused]=useState(''),[jump,setJump]=useState<number>();
 const [pendingEdit,setPendingEdit]=useState<Annotation>();
 const version=target?.version||r.version_id,historic=version!==r.version_id;
 useEffect(()=>{try{localStorage.setItem('knowline-code-font-size',String(fontSize));}catch{}},[fontSize]);
 useEffect(()=>{
  const container=source.current;if(!container)return;
  function wheel(event:WheelEvent){if(!event.ctrlKey)return;event.preventDefault();event.stopPropagation();if(!event.deltaY)return;
   const area=container!.querySelector<HTMLElement>('.source-code');if(area){const rect=area.getBoundingClientRect();zoomAnchor.current={top:area.scrollTop,left:area.scrollLeft,y:event.clientY-rect.top,x:event.clientX-rect.left,size:fontSize};}
   zoom(event.deltaY<0?1:-1);
  }
  container.addEventListener('wheel',wheel,{passive:false});return()=>container.removeEventListener('wheel',wheel);
 },[content?.path,fontSize]);
 useLayoutEffect(()=>{const anchor=zoomAnchor.current,area=source.current?.querySelector<HTMLElement>('.source-code');if(anchor&&area){const ratio=fontSize/anchor.size;area.scrollTop=(anchor.top+anchor.y)*ratio-anchor.y;area.scrollLeft=(anchor.left+anchor.x)*ratio-anchor.x;zoomAnchor.current=undefined;}},[fontSize]);
 useEffect(()=>{let active=true;setLoading(true);setError('');setFiles([]);setSelected(target?.file||'');setContent(undefined);
  api('/resources/'+r.id+'/code?version='+encodeURIComponent(version)).then(data=>{if(active){setFiles(data.files);const readme=data.files.find((f:any)=>/readme\.md$/i.test(f.path));if(!target?.file&&readme)setSelected(readme.path);}}).catch(e=>{if(active){setError(t(e.code));onError(e);}}).finally(()=>{if(active)setLoading(false);});return()=>{active=false;};
 },[r.id,version,target?.file]);
 useEffect(()=>{let active=true;setAnnotations([]);api<Annotation[]>('/resources/'+r.id+'/annotations?version='+encodeURIComponent(version)).then(a=>{if(active)setAnnotations(a);}).catch(onError);return()=>{active=false;};},[r.id,version,r.revision]);
 useEffect(()=>{setSelection(undefined);setAnnotating(undefined);if(!selected)return;let active=true;setContent(undefined);setError('');
  api('/resources/'+r.id+'/code/file?file='+encodeURIComponent(selected)+'&version='+encodeURIComponent(version)+'&encoding='+encoding).then(data=>{if(active)setContent(data);}).catch(e=>{if(active){setError(t(e.code));onError(e);}});return()=>{active=false;};
 },[selected,encoding,r.id,version]);
 useEffect(()=>{const line=jump??target?.line;if(content&&line)source.current?.querySelector('[data-line="'+line+'"]')?.scrollIntoView({block:'center'});},[content,target?.line,jump]);
 const visible=annotations.filter(a=>a.data.file===selected&&a.data.file_sha256===content?.sha256&&a.data.encoding===encoding);
 function range(start:number,end:number,left=0,right?:number):RangeSpec|undefined{if(!content)return;const lines=content.text.split('\n');right=right??lines[end-1]?.length;if(right===undefined)return;
  const parts=lines.slice(start-1,end);if(!parts.length)return;parts[parts.length-1]=parts[parts.length-1].slice(0,right);parts[0]=parts[0].slice(left);const quote=parts.join('\n');return quote?{line_start:start,line_end:end,column_start:left,column_end:right,quote}:undefined;
 }
 function selectLine(line:number,extend:boolean){if(!content)return;const anchor=extend&&selection?selection.line_start:line;setSelection(range(Math.min(anchor,line),Math.max(anchor,line)));window.getSelection()?.removeAllRanges();}
 function capture(){const sel=window.getSelection();if(!sel?.rangeCount||sel.isCollapsed){setSelection(undefined);return;}const dom=sel.getRangeAt(0);
  function endpoint(node:Node,offset:number){const el=node.nodeType===Node.ELEMENT_NODE?node as Element:node.parentElement,code=el?.closest('code');if(!code||!source.current?.contains(code))return;const prefix=document.createRange();prefix.selectNodeContents(code);prefix.setEnd(node,offset);const line=Number(code.parentElement?.dataset.line);return {line,column:Math.min(prefix.toString().length,content.text.split('\n')[line-1].length)};}
  const a=endpoint(dom.startContainer,dom.startOffset),b=endpoint(dom.endContainer,dom.endOffset);setSelection(a&&b?range(a.line,b.line,a.column,b.column):undefined);
 }
 function begin(kind:string,existing?:Annotation){const chosen=existing?.data||selection;if(historic||!chosen||!content)return;setAnnotating({kind,range:chosen,existing});setComment(existing?.data.comment||'');setColor(existing?.data.color||colors[0]);}
 useEffect(()=>{if(pendingEdit&&content?.path===pendingEdit.data.file&&content?.sha256===pendingEdit.data.file_sha256&&encoding===pendingEdit.data.encoding){begin(pendingEdit.data.kind,pendingEdit);setPendingEdit(undefined);}},[pendingEdit,content,encoding]);
 async function persist(spec:any,existing?:Annotation){setSaving(true);try{
  await api('/resources/'+r.id+'/annotations',{...revision(r),...(existing?{base_annotation_revision:existing.revision}:{}),annotation:spec});await onChange();
  setAnnotations(await api('/resources/'+r.id+'/annotations?version='+encodeURIComponent(version)));setAnnotating(undefined);setSelection(undefined);window.getSelection()?.removeAllRanges();onToast(t('saved'));
 }catch(e){onError(e);}finally{setSaving(false);}}
 async function save(){if(!annotating||!content)return;const old=annotating.existing;await persist({...annotating.range,kind:annotating.kind,file:selected,file_sha256:content.sha256,encoding,color,comment,...(old?{annotation_id:old.id,action:'update'}:{})},old);setShowNotes(true);}
 function focus(id:string){setFocused(id);setShowNotes(true);}
 useEffect(()=>{function key(e:KeyboardEvent){if(annotating||e.ctrlKey||e.metaKey||e.altKey||(e.target as HTMLElement)?.closest('input,textarea,select,[contenteditable="true"]'))return;if(e.key.toLowerCase()==='h'||e.key.toLowerCase()==='n'){if(selection&&!historic){e.preventDefault();begin(e.key.toLowerCase()==='h'?'highlight':'text');}}}window.addEventListener('keydown',key);return()=>window.removeEventListener('keydown',key);},[selection,historic,annotating,content]);
 async function extract(){try{const data=await api('/resources/'+r.id+'/extract',revision(r));onToast(t('extractDone')+': '+data.path);}catch(e){onError(e);}}
 return <div className="code-reader"><aside className="code-tree"><div className="tree-heading"><Folder size={16}/>{t('fileTree')}<span>{files.filter(f=>!f.directory).length}</span></div><input value={filter} onChange={e=>setFilter(e.target.value)} placeholder={t('fileSearch')}/><CodeTree files={files} filter={filter} selected={selected} onSelect={file=>{setJump(undefined);setSelected(file);}}/><button className="small-button" disabled={!!error||!files.length} onClick={extract}><Download size={14}/>{t('extract')}</button></aside>
  <div className="code-content"><div className="reader-toolbar code-toolbar"><span className="code-filename">{selected||t('selectFile')}</span><span className="badge">{t('readonly')}</span><select aria-label={t('encoding')} value={encoding} onChange={e=>setEncoding(e.target.value)}><option>utf-8-sig</option><option>gb18030</option><option>latin-1</option></select>
   <div className="code-zoom" aria-label={t('codeZoom')}><button className="small-button" aria-label={t('codeZoomOut')} title={t('codeZoomOut')} disabled={fontSize<=10} onClick={()=>zoom(-1)}>−</button><button className="small-button code-zoom-reset" aria-label={t('codeZoomReset')} title={t('codeZoomReset')} onClick={()=>setFontSize(14)}>{Math.round(fontSize/14*100)}%</button><button className="small-button" aria-label={t('codeZoomIn')} title={t('codeZoomIn')} disabled={fontSize>=30} onClick={()=>zoom(1)}>+</button></div>
   <button className="small-button" disabled={!selection||historic||saving} title={t('highlight')+' (H)'} onClick={()=>begin('highlight')}><Highlighter size={15}/>{t('highlight')}</button>
   <button className="small-button" disabled={!selection||historic||saving} title={t('codeComment')+' (N)'} onClick={()=>begin('text')}><MessageSquare size={15}/>{t('codeComment')}</button>
   <button className="small-button" aria-pressed={showNotes} onClick={()=>setShowNotes(v=>!v)}>{t('codeAnnotations')} ({annotations.length})</button>
  </div>{historic&&<div className="notice">{t('oldVersion')}</div>}
  {loading?<div className="empty-state"><Loader2 className="spin"/>{t('checking')}</div>:error?<div className="notice danger">{error}</div>:content?<>
   <div className="code-meta">{content.language} · {content.line_count} {t('lines')} · SHA256 {content.sha256.slice(0,12)}{selection&&<span> · {t('selection')} {selection.line_start}–{selection.line_end} {t('lines')}</span>}</div>
   <div className="code-reading-area"><div className="code-source-container" ref={source} style={{'--kw-code-font-size':fontSize+'px'} as CSSProperties} onMouseUp={e=>{if(!(e.target as Element).closest('button'))capture();}} onKeyUp={e=>{if(e.shiftKey)capture();}}><CodeSource text={content.text} language={content.language} line={jump??target?.line} selection={selection} annotations={visible} onSelectLine={selectLine} onAnnotation={focus}/></div>
    {showNotes&&<aside className="code-annotations" aria-label={t('codeAnnotations')}><header><strong>{t('codeAnnotations')}</strong><button className="icon-button" aria-label={t('close')} onClick={()=>setShowNotes(false)}><X size={15}/></button></header>{annotations.length===0&&<p className="muted">{t('noAnnotations')}</p>}{annotations.map(a=><article key={a.id} className={'code-annotation-card '+(focused===a.id?'active':'')}><button className="code-annotation-location" onClick={()=>{setEncoding(a.data.encoding);setSelected(a.data.file);setJump(a.data.line_start);setFocused(a.id);}}>{a.data.file} · {a.data.line_start}–{a.data.line_end} {t('lines')}</button><pre>{a.data.quote}</pre><p>{a.data.comment||t('highlight')}</p><div className="annotation-actions"><button disabled={historic||saving} onClick={()=>{setEncoding(a.data.encoding);setSelected(a.data.file);setJump(a.data.line_start);setPendingEdit(a);}}>{t('editComment')}</button><button disabled={historic||saving} onClick={()=>void persist({annotation_id:a.id,action:'delete'},a)}>{t('delete')}</button></div></article>)}</aside>}
   </div>
  </>:<div className="empty-state"><FileCode2 size={40}/><h3>{t('selectFile')}</h3></div>}
  <div className="reader-footnote"><ShieldCheck size={13}/>{t('codeSelectionHint')} · H / N</div>
  </div>
  {annotating&&<div className="modal-backdrop"><section role="dialog" aria-modal="true" aria-busy={saving} aria-label={t('annotationComment')} className="modal compact"><h2>{t(annotating.kind==='highlight'?'highlight':'codeComment')} · {annotating.range.line_start}–{annotating.range.line_end} {t('lines')}</h2><blockquote className="code-quote">{annotating.range.quote}</blockquote><label>{t('annotationComment')}<textarea autoFocus value={comment} onChange={e=>setComment(e.target.value)} rows={4}/></label><div className="color-options">{colors.map((c,i)=><button key={i} aria-label={t(['yellow','green','blue'][i])} className={color[0]===c[0]?'active':''} style={{background:`rgb(${c.map(v=>v*255).join(',')})`}} onClick={()=>setColor(c)}/>)}</div><div className="modal-actions"><button className="button" disabled={saving} onClick={()=>setAnnotating(undefined)}>{t('cancel')}</button><button className="button primary" disabled={saving||annotating.kind==='text'&&!comment.trim()} onClick={()=>void save()}>{t(saving?'longRunning':'annotationSave')}</button></div></section></div>}
 </div>;
}

