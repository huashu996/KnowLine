"""Apply the scoped graph status UI update to this source-less release bundle."""
from pathlib import Path

APP=Path(__file__).resolve().parents[1]
path=APP/'dist/assets/PaperRelations-3-vizhM_.js'
text=path.read_text('utf-8')
if 'function kwFullTextState(' not in text:
    old='children:n?`已保存 PDF ${b.full_text_summary.pdf_saved} 篇 · 未取得全文 ${b.full_text_summary.pdf_missing} 篇 · 已有摘要 ${b.full_text_summary.abstracts} 篇`:`Saved PDFs: ${b.full_text_summary.pdf_saved} · Unavailable: ${b.full_text_summary.pdf_missing} · Abstracts: ${b.full_text_summary.abstracts}`'
    new='children:kwFullTextSummary(b,n)'
    assert text.count(old)==1
    text=text.replace(old,new)
    start='e.jsxs("p",{className:"muted",children:[h.cached_resources?.length?'
    end='h.cached_resources?.[0]&&e.jsx("a",'
    a=text.index(start);b=text.index(end,a)
    text=text[:a]+'kwFullTextDetail(h,n),'+text[b:]
    text+='''
function kwFullTextState(node){
 if(node.cached_resources?.length)return "acquired";
 if(node.full_text_candidates?.length)return "candidate_needs_review";
 const reason=node.full_text_reason||"";
 if(/candidate_needs_review|identity_mismatch|identity_conflict|verification_required|unverified|ambiguous/.test(reason))return "candidate_needs_review";
 if(/index_unavailable|locator_unavailable|source_unavailable|timeout|budget|http_5|http_429|rate_limit|refresh|saved_pdf_missing/.test(reason))return "search_incomplete";
 if(/requires_user|login|subscription|confirmation|redirect|http_40|not_connected/.test(reason))return "access_restricted";
 return reason?"not_found":"not_checked";
}
function kwFullTextLabel(node,zh){
 const labels={acquired:["PDF 已保存，导入时直接复用。","PDF saved and ready to reuse."],candidate_needs_review:["全文身份或版本关联待核验","Full-text identity or version link needs review"],search_incomplete:["来源查询未完成，不代表没有公开全文","Source lookup incomplete; availability remains unknown"],access_restricted:["出版商访问待处理；可继续查找公开副本","Publisher access needs attention; public copies may be available"],not_found:["已检查来源暂未找到全文","No PDF found in checked sources"],not_checked:["尚未检查全文","Full text not checked"]};
 return labels[kwFullTextState(node)][zh?0:1];
}
function kwFullTextSummary(graph,zh){
 const saved=graph.full_text_summary.pdf_saved,missing=graph.full_text_summary.pdf_missing,abstracts=graph.full_text_summary.abstracts;
 const counts={};for(const node of graph.nodes||[]){const state=kwFullTextState(node);counts[state]=(counts[state]||0)+1;}
 const parts=zh?[`已保存 PDF ${saved} 篇`,`待获取 ${missing} 篇`,`已有摘要 ${abstracts} 篇`]:[`Saved PDFs: ${saved}`,`Pending: ${missing}`,`Abstracts: ${abstracts}`];
 if(counts.search_incomplete)parts.push(zh?`查询未完成 ${counts.search_incomplete} 篇`:`Lookup incomplete: ${counts.search_incomplete}`);
 if(counts.candidate_needs_review)parts.push(zh?`待核验 ${counts.candidate_needs_review} 篇`:`Needs review: ${counts.candidate_needs_review}`);
 if(counts.access_restricted)parts.push(zh?`访问待处理 ${counts.access_restricted} 篇`:`Access needs attention: ${counts.access_restricted}`);
 return parts.join(" · ");
}
function kwFullTextDetail(node,zh){
 const publisher=node.publisher_attempt,attempts=node.full_text_attempts||[],candidates=node.full_text_candidates||[];
 const reason=publisher?.reason||"";
 const publisherText=/challenge|requires_user/.test(reason)?(zh?"出版商会话遇到网站验证，请在机构访问窗口完成验证后重试。":"Publisher session requires website verification; complete it in the account window and retry."):/subscription_denied/.test(reason)?(zh?"已登录，但本篇正式 PDF 权限未通过。":"Signed in, but access to this article was denied."):/login|not_connected|site_required/.test(reason)?(zh?"本篇出版商会话尚不可用。":"Publisher session is not ready for this article."):reason;
 const scholar=node.google_scholar_verification?.url||"https://scholar.google.com/scholar?hl=en&q="+encodeURIComponent('"'+node.title+'"');
 return e.jsxs("div",{className:"muted",children:[
   e.jsx("p",{children:kwFullTextLabel(node,zh)}),
   publisherText&&e.jsxs("p",{children:[zh?"正式版获取：":"Publisher PDF: ",publisherText]}),
   (attempts.length>0||node.full_text_reason)&&e.jsxs("details",{children:[e.jsx("summary",{children:zh?"查看获取过程与失败原因":"Acquisition attempts and reasons"}),attempts.length?attempts.map((a,i)=>e.jsxs("p",{children:[a.provider," · ",a.reason,a.http_status?" · HTTP "+a.http_status:"",a.retry_after_seconds?" · "+a.retry_after_seconds+"s":""]},i)):e.jsx("p",{children:node.full_text_reason})]}),
   candidates.filter(c=>/^https:\\/\\//.test(c.url||"")).map(c=>e.jsxs("p",{children:[e.jsx("a",{href:c.url,target:"_blank",rel:"noreferrer",children:c.title||c.url})," · ",zh?"候选版本，尚未导入":"Candidate version; not imported"]},c.url)),
   e.jsx("p",{children:e.jsx("a",{href:scholar,target:"_blank",rel:"noreferrer",children:zh?"用 Google 学术核验论文信息":"Cross-check bibliographic details in Google Scholar"})})
 ]});
}
'''
    path.write_text(text,'utf-8')
    print('Updated graph status, publisher diagnostics, candidate links and Google Scholar entry.')
else:
    print('Graph acquisition UI is already updated.')

text=path.read_text('utf-8')
if 'function kwFullTextAttempt(' not in text:
    text=text.replace('a.provider," · ",a.reason','kwFullTextAttempt(a,zh)')
    text=text.replace('saved_pdf_missing/.test(reason)','saved_pdf_missing|download_busy|search_unavailable|page_unavailable/.test(reason)')
    text=text.replace(':reason;\n const scholar',':/download_busy|queue_timeout/.test(reason)?(zh?"下载通道被占用或排队超时，本篇正式 PDF 未取得。":"Publisher download queue was busy or timed out."):reason;\n const scholar')
    text+='''
function kwFullTextAttempt(a,zh){
 const providers={"Publisher session":"出版商账户",discover:"已知作者主页",locate_publisher:"出版社公开页面",locate_public:"arXiv",locate_github:"GitHub",locate_openalex:"OpenAlex",locate_index:"Semantic Scholar","PDF download":"PDF 下载"};
 const reasons={public_repository_no_identity_match:"未找到满足身份核验条件的匹配",official_source_not_located:"未提供已知作者主页，继续其他来源",public_index_unavailable:"索引未完成查询",github_search_unavailable:"GitHub 查询未完成",github_no_verified_pdf:"本轮结果未定位可核验 PDF",institution_download_busy:"下载通道被占用",institution_queue_timeout:"下载排队超时",publisher_page_no_public_pdf:"页面未定位公开 PDF 链接",publisher_page_identity_unverified:"出版页面身份待核验"};
 const status=a.status==="located"?(zh?"已定位全文链接":"Full-text link located"):a.status==="acquired"?(zh?"PDF 已保存":"PDF saved"):(zh?(reasons[a.reason]||a.reason):a.reason);
 return (zh?(providers[a.provider]||a.provider):a.provider)+" · "+status+(a.request_sent===false?(zh?" · 本次未发送请求":" · Request not sent"):"");
}
'''
    path.write_text(text,'utf-8')
    print('Updated named source attempts and honest queue/cooldown outcomes.')

# Login-first routing is a deliberate skip, not a failed publisher download.
if 'kwPublisherSkipped' not in text:
    text=text.replace('const publisherText=/challenge|requires_user/.test(reason)?',
        'const kwPublisherSkipped=publisher?.status==="skipped";\n const publisherText=kwPublisherSkipped?(zh?"账户未认证或会话暂不可用，已跳过订阅出版社，直接查公开源。":"Account not authenticated or session unavailable; subscription publisher skipped, public sources used directly."):/challenge|requires_user/.test(reason)?')
    text=text.replace('"Publisher session":"出版商账户",','"DOI publisher route":"出版商路径","Publisher session":"出版商账户",')
    text=text.replace('const status=a.status==="located"?',
        'const status=a.status==="skipped"?(zh?"未认证或会话不可用，直接查公开源":"Publisher skipped; public sources used directly"):a.status==="located"?')
    path.write_text(text,'utf-8')
    print('Updated intentional publisher skip status for direct public downloads.')
