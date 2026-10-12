import {useContext,useEffect,useState} from 'react';
import {FileText,RefreshCw} from 'lucide-react';
import {api,ApiError} from './api';
import {LocaleContext} from './i18n';

export default function WordPanel(){
 const {locale}=useContext(LocaleContext),en=locale==='en';
 const [sessions,setSessions]=useState<any[]>([]),[selected,setSelected]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState(''),[result,setResult]=useState('');
 const [style,setStyle]=useState('IEEE_SUPERSCRIPT'),[font,setFont]=useState('Times New Roman'),[size,setSize]=useState(10.5);
 const active=sessions.find(s=>s.session===selected&&s.online);
 async function refresh(){try{const data=await api<any[]>('/word/sessions');setSessions(data);setSelected(value=>data.some(s=>s.session===value&&s.online)?value:data.find(s=>s.online)?.session||'');}catch(e){setError((e as Error).message);}}
 useEffect(()=>{void refresh();const id=setInterval(()=>void refresh(),3000);return()=>clearInterval(id);},[]);
 const errors:Record<string,string>={word_session_offline:en?'The Word session is closed.':'Word 会话已关闭，请通过 AI 重新打开工作副本。',word_track_changes_pending:en?'Resolve tracked changes before updating citations.':'请先处理修订，引用工具不会擅自接受或拒绝修订。',word_other_citation_system:en?'This document uses another citation manager.':'此文档使用 EndNote 等其他引用系统，暂不混用。',word_style_invalid:en?'Unsupported citation style.':'当前引用样式不可用。'};
 async function act(action:string,params:any={}){setBusy(true);setError('');setResult('');try{await api('/word/'+selected+'/actions',{action,...params});setResult(en?'Word document updated.':'Word 工作副本已更新。');await refresh();}catch(e){setError(e instanceof ApiError?errors[e.code]||e.code:(e as Error).message);}finally{setBusy(false);}}
 return <section className="settings-section word-panel"><h3><FileText size={19}/>{en?'Word citations':'Word 引用联动'}</h3>
  <p>{en?'Ask AI to open a project Word document and cite verified papers from a named domain. An independent Word working copy keeps dynamic citations and refreshes their order while connected.':'在 AI 中指定项目里的 Word 文档和领域，按段落含义选择已核验的论文。工具打开独立工作副本；连接期间，删除或移动引用会自动重排。'}</p>
  <div className="word-controls"><label>{en?'Connected document':'连接的文档'}<select aria-label={en?'Connected Word document':'连接的 Word 文档'} value={selected} onChange={e=>setSelected(e.target.value)}><option value="">{en?'No connected document':'尚未连接文档'}</option>{sessions.filter(s=>s.online).map(s=><option key={s.session} value={s.session}>{s.document.split(/[\\/]/).pop()} · {s.session.slice(0,6)}</option>)}</select></label><button className="button secondary" onClick={()=>void refresh()} aria-label={en?'Refresh Word connections':'刷新 Word 连接'}><RefreshCw size={16}/></button></div>
  {active&&<p className="word-status">Word {active.word_version} · {active.style} · {en?'Automatic refresh':'自动刷新'} {active.refresh_count}{active.warning&&' · '+(errors[active.warning]||active.warning)}</p>}
  <div className="word-controls"><label>{en?'Citation style':'引用样式'}<select aria-label={en?'Word citation style':'Word 引用样式'} value={style} onChange={e=>setStyle(e.target.value)}><option value="IEEE_SUPERSCRIPT">{en?'Numeric superscript (numbered)':'数字上标（顺序编号）'}</option><option value="IEEE">{en?'IEEE (numbered)':'IEEE（顺序编号）'}</option><option value="APA">{en?'APA (author–year)':'APA（作者—年份）'}</option><option value="GB7714">{en?'GB7714 (Word built-in)':'GB7714（Word 内置）'}</option></select></label><button className="button secondary" disabled={!active||busy} onClick={()=>void act('style',{name:style})}>{en?'Apply style':'统一切换样式'}</button></div>
  <div className="word-controls"><label>{en?'Bibliography font':'参考文献字体'}<input value={font} onChange={e=>setFont(e.target.value)}/></label><label>{en?'Size (pt)':'字号（磅）'}<input type="number" min="6" max="72" step="0.5" value={size} onChange={e=>setSize(Number(e.target.value))}/></label><button className="button secondary" disabled={!active||busy} onClick={()=>void act('format',{formatting:{font,size}})}>{en?'Apply format':'统一字体字号'}</button></div>
  <div className="word-controls">{(['bibliography','refresh','save'] as const).map((action,i)=><button key={action} className="button secondary" disabled={!active||busy} onClick={()=>void act(action)}>{(en?['Insert bibliography','Update citations','Save working copy']:['插入参考文献表','更新引用','保存工作副本'])[i]}</button>)}</div>
  {error&&<p role="alert" className="danger">{error}</p>}{result&&<p role="status">{result}</p>}
  <small>{en?'Styles use this computer’s Word definitions. This is a project collaboration tool; an installed Word ribbon add-in is not included.':'样式使用本机 Word 的定义；具体期刊规范仍需核对。当前为项目协作工具，尚未安装 Word 功能区插件。'}</small>
 </section>;
}
