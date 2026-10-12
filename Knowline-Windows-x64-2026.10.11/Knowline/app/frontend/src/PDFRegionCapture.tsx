import {useEffect,useRef,useState} from 'react';
import {Camera,Shapes} from 'lucide-react';
import {api} from './api';
import {useT} from './i18n';

export default function PDFRegionCapture({container,resource,version,historic,target,geometry,onChange,onError,onActivityChange}:{onActivityChange?:(active:boolean)=>void;container:React.RefObject<HTMLDivElement|null>;resource:string;version:string;historic:boolean;target:string;geometry:(index:number)=>string|undefined;onChange:()=>void;onError:(e:any)=>void}){
 const t=useT();
 const [mode,setMode]=useState<'office'|'figure'>(),[preview,setPreview]=useState<any>(),[busy,setBusy]=useState(false),[status,setStatus]=useState('');
 const [pageSize,setPageSize]=useState('wide'),[formulaMode,setFormulaMode]=useState('office'),[objectRatio,setObjectRatio]=useState('faithful');
 useEffect(()=>{onActivityChange?.(!!mode||!!preview||busy);},[mode,preview,busy,onActivityChange]);
 const geo=useRef(geometry);geo.current=geometry;
 useEffect(()=>{setMode(undefined);setPreview(undefined);setStatus('');},[resource,version]);
 useEffect(()=>{
  const host=container.current;if(!mode||!host)return;
  host.classList.add('capturing-region');window.getSelection()?.removeAllRanges();
  let drag:any,overlay:HTMLDivElement|undefined;
  const cleanup=()=>{overlay?.remove();overlay=undefined;drag=undefined;};
  function down(e:PointerEvent){
   if(e.button!==0)return;const slot=(e.target as HTMLElement).closest<HTMLElement>('[data-page-index]'),canvas=slot?.querySelector('canvas');
   if(!slot||!canvas)return;const index=Number(slot.dataset.pageIndex),hash=geo.current(index);if(!hash){setStatus(t('regionRendering'));return;}
   const bounds=canvas.getBoundingClientRect();if(e.clientX<bounds.left||e.clientX>bounds.right||e.clientY<bounds.top||e.clientY>bounds.bottom)return;
   e.preventDefault();e.stopPropagation();cleanup();
   drag={index,hash,bounds,canvas,slot,id:e.pointerId,x:e.clientX,y:e.clientY,endX:e.clientX,endY:e.clientY};host!.setPointerCapture(e.pointerId);
   overlay=document.createElement('div');overlay.className='pdf-region-box';slot.appendChild(overlay);
  }
  function move(e:PointerEvent){if(!drag||e.pointerId!==drag.id)return;e.preventDefault();const b=drag.bounds;drag.endX=Math.max(b.left,Math.min(b.right,e.clientX));drag.endY=Math.max(b.top,Math.min(b.bottom,e.clientY));const slotBounds=drag.slot.getBoundingClientRect();Object.assign(overlay!.style,{left:Math.min(drag.x,drag.endX)-slotBounds.left+'px',top:Math.min(drag.y,drag.endY)-slotBounds.top+'px',width:Math.abs(drag.endX-drag.x)+'px',height:Math.abs(drag.endY-drag.y)+'px'});}
  function up(e:PointerEvent){
   if(!drag||e.pointerId!==drag.id)return;move(e);e.preventDefault();e.stopPropagation();const d=drag,b=d.bounds;
   if(host!.hasPointerCapture(d.id))host!.releasePointerCapture(d.id);
   const region=[(Math.min(d.x,d.endX)-b.left)/b.width,(Math.min(d.y,d.endY)-b.top)/b.height,(Math.max(d.x,d.endX)-b.left)/b.width,(Math.max(d.y,d.endY)-b.top)/b.height];
   if(Math.abs(d.endX-d.x)>=8&&Math.abs(d.endY-d.y)>=8){const c=d.canvas as HTMLCanvasElement,out=document.createElement('canvas');out.width=Math.ceil((region[2]-region[0])*c.width);out.height=Math.ceil((region[3]-region[1])*c.height);out.getContext('2d')!.drawImage(c,region[0]*c.width,region[1]*c.height,out.width,out.height,0,0,out.width,out.height);setPreview({region,page_index:d.index,page_geometry_hash:d.hash,preview:out.toDataURL(),pixelWidth:out.width,pixelHeight:out.height,mode});setMode(undefined);}
   cleanup();
  }
  function key(e:KeyboardEvent){if(e.key==='Escape'){cleanup();setMode(undefined);}}
  const cancel=()=>cleanup();
  host.addEventListener('pointerdown',down,true);host.addEventListener('pointermove',move,true);host.addEventListener('pointerup',up,true);host.addEventListener('pointercancel',cancel);host.addEventListener('scroll',cancel);window.addEventListener('keydown',key);
  return()=>{if(drag&&host.hasPointerCapture(drag.id))host.releasePointerCapture(drag.id);cleanup();host.classList.remove('capturing-region');host.removeEventListener('pointerdown',down,true);host.removeEventListener('pointermove',move,true);host.removeEventListener('pointerup',up,true);host.removeEventListener('pointercancel',cancel);host.removeEventListener('scroll',cancel);window.removeEventListener('keydown',key);};
 },[mode,container]);
 async function submit(){setBusy(true);try{const {preview:image,mode:captureMode,...region}=preview;
  if(captureMode==='figure'){
   await api('/jobs',{task:'replicate_paper_figure',skill:'knowline-replicate-figure',resource_ids:[resource],figure_selection:{...region,version_id:version,page_size:pageSize,formula_mode:formulaMode,object_ratio:objectRatio},question:'依据冻结论文截图，使用 paper-agent figure_only/figure_ppt 与 Paper-framework-skill 忠实复刻为逐对象可编辑单页 PPTX；输出预览和真实审查记录，附同页可复现原文证据。'});
   setStatus('科研图已冻结为复刻任务；当前绑定的本地智能体执行后，成果会回到智能体任务列表。');
  }else{
   await api('/jobs',{task:'copy_office_selection',skill:'knowline-copy-office',resource_ids:[resource],office_selection:{...region,version_id:version,selection_mode:'image_region',target},question:'以冻结截图为依据识别正文与公式，按顺序转换成目标 Office 原生可编辑内容；无法辨认处标注待核对。'});
   setStatus(t('regionOfficeQueued'));
  }
  setPreview(undefined);onChange();
 }catch(e){onError(e);}finally{setBusy(false);}}
 return <><button className="small-button" disabled={historic||busy} onClick={()=>{setMode(mode==='office'?undefined:'office');setStatus('');}}><Camera size={15}/>{mode==='office'?t('cancelCapture'):t('captureTextEquations')}</button><button className="small-button" disabled={historic||busy} onClick={()=>{setMode(mode==='figure'?undefined:'figure');setStatus('');}}><Shapes size={15}/>{mode==='figure'?t('cancelRegion'):t('replicateFigure')}</button>{mode&&<span role="status">{t('regionDragHint')}</span>}{status&&<span role="status">{status}</span>}{preview&&<div className="modal-backdrop"><section className="modal compact region-preview" role="dialog" aria-label={preview.mode==='figure'?t('confirmFigureRegion'):t('confirmEquationRegion')} aria-modal="true" aria-busy={busy}><h2>{preview.mode==='figure'?t('replicateFigure'):t('recognizeScreenshot')} · {t('page')} {preview.page_index+1}</h2><img src={preview.preview} alt={preview.mode==='figure'?t('selectedFigure'):t('selectedTextEquations')}/>{preview.mode==='figure'?<div className="figure-options"><label>{t('figurePageSize')}<select value={pageSize} onChange={e=>setPageSize(e.target.value)}><option value="wide">{t('figureWide')}</option><option value="standard">{t('figureStandard')}</option><option value="a4_landscape">{t('figureA4')}</option></select></label><label>{t('figureObjectRatio')}<select value={objectRatio} onChange={e=>setObjectRatio(e.target.value)}><option value="faithful">{t('figureFaithfulSize')}</option><option value="uniform">{t('figureUniformScale')}</option></select></label><label>{t('figureFormulaMode')}<select value={formulaMode} onChange={e=>setFormulaMode(e.target.value)}><option value="office">{t('figureNativeEquations')}</option><option value="mathtype">MathType</option><option value="both">{t('figureBothEquations')}</option></select></label><p>{t('figureAspectHint',{width:preview.pixelWidth,height:preview.pixelHeight})}{objectRatio==='uniform'?t('figureUniformFactor'):t('figurePhysicalSize')}</p><p>{t('figureEditableHint')}</p><p>{t('figureFontHint')}</p></div>:<p>{t('officeRegionConversion',{target:target==='word'?'Word':'PowerPoint'})}</p>}<div className="modal-actions"><button className="button" disabled={busy} onClick={()=>{setMode(preview.mode);setPreview(undefined);}}>{t('captureAgain')}</button><button className="button" disabled={busy} onClick={()=>setPreview(undefined)}>{t('cancel')}</button><button className="button primary" disabled={busy} onClick={()=>void submit()}>{preview.mode==='figure'?t('createFigureTask'):t('createRecognitionTask')}</button></div></section></div>}</>;
}
