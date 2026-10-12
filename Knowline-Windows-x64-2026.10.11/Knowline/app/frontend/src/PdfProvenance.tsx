import {useContext,useEffect,useState} from 'react';
import {api} from './api';
import {LocaleContext} from './i18n';
export default function PdfProvenance({resource}:{resource:any}){
 const {locale}=useContext(LocaleContext),en=locale==='en',m=resource.metadata;
 const [citation,setCitation]=useState<any>(m.publication_record);
 useEffect(()=>{let active=true;setCitation(m.publication_record);if(m.publication_record_id)void api('/paper-records/'+m.publication_record_id).then(value=>{if(active)setCitation(value);}).catch(()=>{});return()=>{active=false;};},[resource.id,resource.revision]);
 const labels:Record<string,string>={published:en?'Version of record':'正式出版版',accepted_manuscript:en?'Accepted manuscript':'作者接受稿',preprint:en?'Preprint':'预印本',unknown:en?'Unknown':'未知'};
 return <div className="pdf-provenance">{citation&&<div className="citation-provenance"><strong>{en?"Citation record":"引用记录"}</strong><p>{citation.title}</p><p>{citation.venue} · {citation.year} · {citation.doi||citation.url}</p><small>{citation.publication_status==="published"?(en?"Published metadata; independent of this PDF version":"正式出版元数据，与此 PDF 版本独立"):(en?"Latest verified preprint; publication unverified":"已核实的最新预印本；正式出版未核实")}</small></div>}<p>{en?'PDF version: ':'PDF 版本：'}{labels[m.pdf_version]||labels.unknown}</p>{m.publisher_url&&<a href={m.publisher_url} target="_blank" rel="noreferrer">{en?'Publisher source':'出版方来源'}</a>}{m.access_method&&<p>{en?'Access: ':'获取方式：'}{m.access_method}</p>}{m.acquired_at&&<p>{en?'Acquired: ':'获取时间：'}{new Date(m.acquired_at).toLocaleString(en?'en-US':'zh-CN')}</p>}{m.fallback_reason&&<p>{en?'Fallback reason: ':'回退原因：'}{m.fallback_reason}</p>}{m.pdf_version_basis&&<details><summary>{en?'Version evidence':'版本依据'}</summary><p>{m.pdf_version_basis.statement||String(m.pdf_version_basis)}</p><small>{en?'Version asserted by user; PDF identity checked separately.':'版本由用户依据来源确认；PDF 身份另行核验。'}</small></details>}</div>;
}
