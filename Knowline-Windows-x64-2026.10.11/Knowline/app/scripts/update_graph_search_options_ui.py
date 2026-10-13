"""Apply optional graph-search instructions to the source-less release UI.

The paper relationship bundle and shared source-notice wording are scoped
patches. Repeated runs preserve existing changes and cache revisions.
"""
from __future__ import annotations

import argparse
from pathlib import Path


APP = Path(__file__).resolve().parents[1]
DEFAULT_BUNDLE = APP / "dist/assets/PaperRelations-3-vizhM_.js"
DEFAULT_ENTRY = APP / "dist/assets/index-DDV0cMc3.js"

STATE_OLD = '[m,S]=f.useState(""),[C,X]='
STATE_NEW = '[m,S]=f.useState(""),[kwSearchNotes,kwSetSearchNotes]=f.useState(""),[C,X]='
PAYLOAD_OLD = 'query:m,question:m,from_year:C'
PAYLOAD_NEW = 'query:m,question:m+(kwSearchNotes.trim()?"\\n"+kwSearchNotes.trim():""),search_instructions:kwSearchNotes.trim(),from_year:C'
ANCHOR = 'e.jsxs("label",{children:[n?"Connected Papers 推荐列表（已有图谱链接，可选）":"Connected Papers recommendations (existing graph URL, optional)"'
FIELD = 'e.jsxs("label",{className:"paper-search-instructions",children:[n?"搜索侧重点／要求（可选）":"Search focus / instructions (optional)",e.jsx("textarea",{"aria-label":n?"星图搜索侧重点":"Graph search instructions",value:kwSearchNotes,onChange:a=>kwSetSearchNotes(a.target.value),rows:3,maxLength:2000,placeholder:n?"例如：围绕 KISS-ICP，优先 TRO、RA-L；重点看退化场景与实时性。":"For example: around KISS-ICP, prioritize TRO and RA-L; focus on degeneracy and real-time performance."})]}),'
HELP = 'e.jsx("p",{className:"muted",children:n?"起点论文单独定位；刊会与研究要求用于筛选相关论文。主要公开源本轮未取得 PDF 就结束该篇下载，论文节点和已核验引用关系完整保留。":"The origin is located separately; research and venue preferences guide related-paper selection. PDF acquisition ends after bounded public-source checks; verified papers and citation relationships remain in the graph."}),'
SELECTION_OLD = 'await _(),l(c.rows.filter(V=>!V.resource_id).map(V=>V.candidate_id));const F='
SELECTION_NEW = 'await _(),l([]);const F='
IMPORT_ZH_OLD = '" 篇尚未取得 PDF，可点击“查找选中论文的 PDF”补齐。"'
IMPORT_ZH_NEW = '" 篇本轮已跳过，原因见论文详情；需要时可主动重试。"'
IMPORT_EN_OLD = '" PDFs unavailable."'
IMPORT_EN_INTERMEDIATE = '" PDFs skipped this run."'
IMPORT_EN_NEW = '" skipped this run. See paper details; retry manually if needed."'
INCOMPLETE_OLD = '"来源查询未完成，不代表没有公开全文","Source lookup incomplete; availability remains unknown"'
INCOMPLETE_NEW = '"来源查询未完成，本轮已跳过；不代表没有公开全文","Source lookup incomplete; skipped this run, availability remains unknown"'
NOT_FOUND_OLD = '"已检查来源暂未找到全文","No PDF found in checked sources"'
NOT_FOUND_TYPO = '"主要公開源未定位全文，本轮已跳过","No PDF located in checked sources; skipped this run"'
NOT_FOUND_INTERMEDIATE = '"主要公开源未定位全文，本轮已跳过","No PDF located in checked sources; skipped this run"'
NOT_FOUND_NEW = '"本轮查后未取得 PDF；实际查询来源见覆盖记录","No PDF acquired after this run; see actual source coverage"'
IMPORT_DEFAULT_OLD = 'async function H(a=!1)'
IMPORT_DEFAULT_NEW = 'async function H(a=!0)'
IMPORT_STATUS_OLD = 'Q(n?"已直接导入 "+c.imported+" 篇"+(c.missing?"；"+c.missing+" 篇本轮已跳过，原因见论文详情；需要时可主动重试。":"。"):"Imported "+c.imported+" papers directly; "+c.missing+" skipped this run. See paper details; retry manually if needed.")'
IMPORT_STATUS_NEW = 'Q(kwImportOutcome(c,n))'
CHECKED_STATE_OLD = 'if(node.full_text_candidates?.length)return "candidate_needs_review";'
CHECKED_STATE_NEW = CHECKED_STATE_OLD + '\n if(node.full_text_checked===false)return "not_checked";'
LABEL_RETURN_OLD = 'return labels[kwFullTextState(node)][zh?0:1];'
LABEL_RETURN_NEW = 'const state=kwFullTextState(node);\n if(state==="not_found"&&node.full_text_checked!==true)return zh?"本轮查询状态未记录，不能据此判断公开全文是否可用":"This run has no recorded PDF lookup; public availability remains unknown";\n return labels[state][zh?0:1];'
COVERAGE_ANCHOR = 'e.jsx("p",{children:kwFullTextLabel(node,zh)}),'
COVERAGE_NEW = COVERAGE_ANCHOR + '\n   kwPdfCoverage(node,zh),'
RELATION_NEW = COVERAGE_NEW + '\n   kwRelationCoverage(node,zh),'
RELATION_SUMMARY_OLD = 'children:n?"被引已核实 "+b.nodes.filter(a=>a.citation_count!==null).length+"/"+b.nodes.length+" · 星辰大小表示被引 · 越新越亮 · 仅显示真实引用":"Verified citations "+b.nodes.filter(a=>a.citation_count!==null).length+"/"+b.nodes.length+" · size: citations · newer: brighter · sourced citations only"'
RELATION_SUMMARY_NEW = 'children:kwRelationSummary(b,n)'
SOURCE_NOTICE_ZH_OLD = '自动检索来源：Crossref、Semantic Scholar。Google 学术可在正常网页搜索。'
SOURCE_NOTICE_ZH_NEW = '论文发现／引用核验来源：Crossref、Semantic Scholar。Google 学术可在正常网页核验；PDF 获取来源另见论文详情。'
SOURCE_NOTICE_EN_OLD = 'Automatic sources: Crossref and Semantic Scholar. Google Scholar is available through its normal website.'
SOURCE_NOTICE_EN_NEW = 'Paper discovery / citation verification: Crossref and Semantic Scholar. Google Scholar supports normal webpage checks; PDF acquisition sources are listed separately in paper details.'
DIAGNOSTIC_HELPERS = r'''
function kwImportOutcome(result,zh){
 const imported=Number(result.imported)||0,missing=Number(result.missing)||0;
 const rows=(result.rows||[]).filter(row=>!row.resource_id);
 let checked=0,unchecked=0,unknown=0;
 for(const row of rows){
  if(result.fetched_missing===false||row.full_text_checked===false)unchecked++;
  else if(row.full_text_checked===true)checked++;
  else unknown++;
 }
 unknown+=Math.max(0,missing-rows.length);
 const parts=[zh?`已直接导入 ${imported} 篇`:`Imported ${imported} papers`];
 if(checked)parts.push(zh?`${checked} 篇查后未取得 PDF`:`${checked} checked but no PDF acquired`);
 if(unchecked)parts.push(zh?`${unchecked} 篇本轮未查询 PDF`:`${unchecked} PDFs not checked this run`);
 if(unknown)parts.push(zh?`${unknown} 篇查询状态未记录`:`${unknown} PDF lookup states not recorded`);
 return parts.join(zh?"；":"; ")+(missing?(zh?"。来源覆盖与逐篇原因见论文详情；需要时可主动重试。":". See paper details for source coverage and reasons; retry manually if needed."):(zh?"。":"."));
}
function kwPdfSourceRows(node){
 const raw=node.full_text_sources;
 return Array.isArray(raw)?raw:Object.entries(raw||{}).map(([provider,value])=>typeof value==="string"?{provider,status:value}:{provider,...value});
}
function kwPdfCoverage(node,zh){
 const rows=kwPdfSourceRows(node),groups=[
  ["arxiv","arXiv",/arxiv|locate_public/i],
  ["github","GitHub",/github/i],
  ["author_repository",zh?"作者／高校仓库":"Author / university repositories",/作者|高校|author|university|discover|locate_author/i],
  ["publisher_oa",zh?"正式 OA":"Official open access",/正式.*oa|official.*open|publisher_oa|formal_oa|locate_publisher/i],
  ["openalex","OpenAlex",/openalex/i],
  ["semantic_scholar","Semantic Scholar",/semantic.scholar|locate_index/i],
  ["publisher_account",zh?"出版商账户":"Publisher account",/出版商账户|publisher.session|publisher.account/i]
 ];
 const status={requested:["已请求，未取得 PDF","Requested; no PDF acquired"],located:["已定位链接，未取得 PDF","Link located; no PDF acquired"],acquired:["PDF 已保存","PDF saved"],unavailable:["查询／访问失败，不能判定无 PDF","Lookup / access failed; availability unknown"],not_checked:["未查","Not checked"],not_configured:["未配置，未查","Not configured; not checked"],no_match:["本轮未找到已核验匹配","No verified match this run"],cooldown:["限流冷却，本次未查","Rate-limit cooldown; not checked this attempt"]};
 const lines=groups.map(([id,label,pattern])=>{
  const entries=rows.filter(row=>pattern.test(String(row.provider||row.id||row.source||"")));
  const values=entries.length?entries:[{status:"not_checked"}];
  return e.jsxs("p",{"data-pdf-source":id,children:[label," · ",values.map((row,i)=>e.jsxs("span",{"data-source-status":row.status||"not_checked",children:[(status[row.status]||status.not_checked)[zh?0:1],row.request_sent===false?(zh?" · 本次未发送请求":" · Request not sent"):"",row.reason?" · "+row.reason:"",i<values.length-1?"；":""]},i))]},id);
 });
 lines.push(e.jsx("p",{"data-pdf-source":"sci_hub","data-source-status":"not_configured",children:zh?"Sci-Hub · 未接入，未查":"Sci-Hub · Not integrated; not checked"},"sci_hub"));
 return e.jsxs("details",{className:"paper-pdf-source-coverage",children:[e.jsx("summary",{children:zh?"PDF 来源覆盖（与论文发现／引用核验分开）":"PDF source coverage (separate from discovery / citation verification)"}),...lines,e.jsx("p",{children:zh?"仅记录本轮实际查询；未查、限流或访问失败不代表没有公开 PDF，也不表示已穷尽公开网站。":"Only actual checks in this run are recorded. Unchecked, rate-limited or failed sources do not prove no public PDF exists or that public sites were exhausted."})]});
}
'''
LEGACY_DIAGNOSTIC_HELPERS = DIAGNOSTIC_HELPERS
SCI_HUB_GROUP_OLD = '["publisher_account",zh?"出版商账户":"Publisher account",/出版商账户|publisher.session|publisher.account/i]'
SCI_HUB_GROUP_NEW = SCI_HUB_GROUP_OLD + ',\n  ["sci_hub","Sci-Hub",/sci[\\s_-]?hub/i]'
SCI_HUB_STATIC_OLD = ' lines.push(e.jsx("p",{"data-pdf-source":"sci_hub","data-source-status":"not_configured",children:zh?"Sci-Hub · 未接入，未查":"Sci-Hub · Not integrated; not checked"},"sci_hub"));'
SCI_HUB_DYNAMIC_NEW = r''' const sciHubUrl=node.sci_hub_access?.url;
 if(node.doi&&typeof sciHubUrl==="string"&&/^https?:\/\//i.test(sciHubUrl))lines.push(e.jsx("p",{"data-sci-hub-access":"external-link",children:e.jsx("a",{href:sciHubUrl,target:"_blank",rel:"noreferrer noopener",children:zh?"打开本篇 Sci-Hub 入口":"Open this paper's Sci-Hub page"})},"sci_hub_link"));
 lines.push(e.jsx("p",{className:"muted",children:zh?"Sci-Hub 是第三方全文来源，不代表开放许可 OA，也不用于正式发表核验；验证码和访问限制按实际状态记录，不自动绕过。":"Sci-Hub is a third-party full-text source, not an open-license OA or publication-verification source; verification challenges and access limits retain their actual status without automatic bypass."},"sci_hub_role"));'''
SCI_HUB_COOLDOWN_OLD = '(status[row.status]||status.not_checked)[zh?0:1]'
SCI_HUB_COOLDOWN_NEW = '(row.status==="cooldown"&&row.request_sent===true?(zh?"已请求后限流，本轮已结束":"Requested then rate-limited; ended this run"):(status[row.status]||status.not_checked)[zh?0:1])'
DIAGNOSTIC_HELPERS = DIAGNOSTIC_HELPERS.replace(SCI_HUB_GROUP_OLD, SCI_HUB_GROUP_NEW).replace(SCI_HUB_STATIC_OLD, SCI_HUB_DYNAMIC_NEW).replace(SCI_HUB_COOLDOWN_OLD, SCI_HUB_COOLDOWN_NEW)
RELATION_HELPERS = r'''
function kwRelationSummary(graph,zh){
 const nodes=graph.nodes||[],count=nodes.filter(node=>node.citation_count!=null).length;
 const checked=nodes.filter(node=>node.references_checked===true).length,edges=(graph.edges||[]).filter(edge=>edge.kind==="citation").length;
 return zh?`被引数量已核实 ${count}/${nodes.length} · 参考列表已核查 ${checked}/${nodes.length} · 已核验引用边 ${edges} 条`:`Verified citation counts ${count}/${nodes.length} · Reference lists checked ${checked}/${nodes.length} · ${edges} verified citation edges`;
}
function kwRelationCoverage(node,zh){
 const statuses={checked:["已核查参考列表","Reference list checked"],not_checked:["未查","Not checked"],identity_unverified:["候选身份未核实，未采纳","Candidate identity unverified; not accepted"],query_incomplete:["查询未完成","Lookup incomplete"],unavailable:["查询失败","Lookup failed"]};
 const sources=Array.isArray(node.reference_sources)?node.reference_sources:[];
 return e.jsxs("details",{className:"paper-reference-coverage",children:[e.jsx("summary",{children:zh?"引用关系核查覆盖":"Citation relationship coverage"}),
  e.jsx("p",{children:node.references_checked===true?(zh?"已逐篇检查已取得的参考列表，匹配图内论文与已核验版本别名。":"Available references were checked against graph papers and verified version aliases."):(zh?"参考列表尚未核查，不能据此判定没有引用关系。":"Reference lists have not been checked; absence of an edge does not prove absence of a citation.")}),
  ...sources.map((row,i)=>e.jsxs("p",{"data-reference-source":row.provider,children:[row.provider," · ",(statuses[row.status]||statuses.query_incomplete)[zh?0:1],row.url?e.jsx("a",{href:row.url,target:"_blank",rel:"noreferrer",children:zh?" · 来源":" · Source"}):""]},i)),
  e.jsx("p",{children:zh?`缺 DOI 的参考条目 ${Number(node.references_without_doi)||0} 条；尚未解析身份 ${Number(node.references_unresolved_count)||0} 条。尚未解析的条目不等于遗漏的图内引用边。`:`References without DOI: ${Number(node.references_without_doi)||0}; unresolved identities: ${Number(node.references_unresolved_count)||0}. Unresolved entries are not a count of missing graph edges.`}),
  e.jsx("p",{children:zh?"总被引次数按来源分别记录，不与图内引用边数混用；来源未覆盖的关系仍可能遗漏。":"Total citation counts remain source-specific and separate from graph edge counts; uncovered sources may contain additional relationships."})]});
}
'''


from update_graph_relationship_layers_ui import SUMMARY_OLD, SUMMARY_NEW
LEGACY_RELATION_HELPERS = RELATION_HELPERS
RELATION_HELPERS = RELATION_HELPERS.replace(SUMMARY_OLD, SUMMARY_NEW)


def replace_once(source: str, old: str, new: str, name: str) -> str:
    if new in source:
        if source.count(new) != 1:
            raise ValueError(f"{name}: patched expression is duplicated")
        return source
    if source.count(old) != 1:
        raise ValueError(f"{name}: expected exactly one release-bundle anchor")
    return source.replace(old, new, 1)


def patch(source: str) -> str:
    source = replace_once(source, STATE_OLD, STATE_NEW, "search-instruction state")
    source = replace_once(source, PAYLOAD_OLD, PAYLOAD_NEW, "separate query and instructions")
    source = replace_once(source, ANCHOR, FIELD + HELP + ANCHOR, "search-instruction textarea")
    source = replace_once(source, SELECTION_OLD, SELECTION_NEW, "clear processed import selection")
    if IMPORT_STATUS_NEW not in source:
        source = replace_once(source, IMPORT_ZH_OLD, IMPORT_ZH_NEW, "bounded import status in Chinese")
        source = replace_once(source, IMPORT_EN_INTERMEDIATE if IMPORT_EN_INTERMEDIATE in source else IMPORT_EN_OLD,
            IMPORT_EN_NEW, "bounded import status in English")
    source = replace_once(source, IMPORT_DEFAULT_OLD, IMPORT_DEFAULT_NEW, "import also acquires missing PDFs")
    source = replace_once(source, IMPORT_STATUS_OLD, IMPORT_STATUS_NEW, "reported lookup versus no lookup")
    source = replace_once(source, INCOMPLETE_OLD, INCOMPLETE_NEW, "incomplete source lookup remains unknown")
    if NOT_FOUND_TYPO in source:
        source = replace_once(source, NOT_FOUND_TYPO, NOT_FOUND_NEW, "correct open-source skip label")
    elif NOT_FOUND_INTERMEDIATE in source:
        source = replace_once(source, NOT_FOUND_INTERMEDIATE, NOT_FOUND_NEW, "actual lookup coverage instead of presumed exhaustion")
    else:
        source = replace_once(source, NOT_FOUND_OLD, NOT_FOUND_NEW, "bounded not-found status")
    source = replace_once(source, CHECKED_STATE_OLD, CHECKED_STATE_NEW, "unqueried is not a failed search")
    source = replace_once(source, LABEL_RETURN_OLD, LABEL_RETURN_NEW, "legacy lookup state remains unknown")
    source = replace_once(source, COVERAGE_ANCHOR, COVERAGE_NEW, "per-source PDF coverage")
    if 'function kwImportOutcome(' not in source:
        source += DIAGNOSTIC_HELPERS
    elif LEGACY_DIAGNOSTIC_HELPERS in source:
        source = source.replace(LEGACY_DIAGNOSTIC_HELPERS, DIAGNOSTIC_HELPERS, 1)
    elif source.count('function kwImportOutcome(') != 1 or DIAGNOSTIC_HELPERS not in source:
        raise ValueError("PDF diagnostics: unknown or duplicated helper version")
    source = replace_once(source, COVERAGE_NEW, RELATION_NEW, "reference-list coverage")
    source = replace_once(source, RELATION_SUMMARY_OLD, RELATION_SUMMARY_NEW, "reference lists versus citation counts")
    if 'function kwRelationSummary(' not in source:
        source += RELATION_HELPERS
    elif LEGACY_RELATION_HELPERS in source:
        source = source.replace(LEGACY_RELATION_HELPERS, RELATION_HELPERS, 1)
    elif source.count('function kwRelationSummary(') != 1 or RELATION_HELPERS not in source:
        raise ValueError("Reference coverage: unknown or duplicated helper version")
    if source.count('className:"paper-search-instructions"') != 1:
        raise ValueError("search-instruction textarea must occur exactly once")
    if source.count('search_instructions:kwSearchNotes.trim()') != 1:
        raise ValueError("search instructions must be transmitted exactly once")
    return source


def patch_discovery_source_notice(source: str) -> str:
    source = replace_once(source, SOURCE_NOTICE_ZH_OLD, SOURCE_NOTICE_ZH_NEW, "Chinese discovery / citation title")
    return replace_once(source, SOURCE_NOTICE_EN_OLD, SOURCE_NOTICE_EN_NEW, "English discovery / citation title")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--entry", type=Path, default=DEFAULT_ENTRY,
        help="Shared JobCard bundle; only discovery / citation notice wording is patched")
    args = parser.parse_args()
    source = args.bundle.read_text(encoding="utf-8")
    updated = patch(source)
    entry_source = args.entry.read_text(encoding="utf-8")
    updated_entry = patch_discovery_source_notice(entry_source)
    # Validate both patches before writing either release asset.
    if updated == source and updated_entry == entry_source:
        print("Graph search instructions and bounded-skip UI are already applied; bundle unchanged.")
    else:
        if updated != source:
            args.bundle.write_text(updated, encoding="utf-8", newline="")
        if updated_entry != entry_source:
            args.entry.write_text(updated_entry, encoding="utf-8", newline="")
        print("Updated graph search, PDF acquisition coverage and discovery / citation notices.")


if __name__ == "__main__":
    main()
