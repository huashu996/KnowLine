"""Remove shared-reference lines from the installed paper graph view."""
import hashlib
import json
from pathlib import Path
import re

APP = Path(__file__).resolve().parents[1]
DIST = APP / 'dist'
VERSION = 'citation-cocitation-v2'


def main():
    file = DIST / 'assets/PaperRelations-3-vizhM_.js'
    source = file.read_text('utf-8')
    old = 'M=f.useMemo(()=>s.edges||[],[s])'
    new = 'M=f.useMemo(()=>(s.edges||[]).filter(t=>t.kind!=="bibliographic_coupling"),[s])'
    if old in source:
        if source.count(old) != 1:
            raise ValueError('Ambiguous graph renderer')
        source = source.replace(old, new, 1)
    elif new not in source:
        raise ValueError('Unexpected graph renderer')
    summary = '''function kwRelationSummary(graph,zh){
 const nodes=graph.nodes||[],edges=(graph.edges||[]).filter(edge=>edge.kind!=="bibliographic_coupling"),count=nodes.filter(node=>node.citation_count!=null).length;
 const checked=nodes.filter(node=>node.references_checked===true).length,total=edges.length;
 const citation=edges.filter(edge=>edge.kind==="citation").length,cocitation=edges.filter(edge=>edge.kind==="co_citation").length,semantic=edges.filter(edge=>edge.kind==="semantic_similarity").length;
 return zh?`显示关系线 ${total} 条 · 直接引用 ${citation} · 共同被引 ${cocitation}${semantic?` · 语义推断 ${semantic}`:""} · 被引数量已核实 ${count}/${nodes.length} · 参考列表已核查 ${checked}/${nodes.length}`:`${total} visible relationship lines · Direct citations ${citation} · Co-citations ${cocitation}${semantic?` · Inferred similarity ${semantic}`:""} · Verified citation counts ${count}/${nodes.length} · Reference lists checked ${checked}/${nodes.length}`;
}'''
    source, count = re.subn(r'function kwRelationSummary\(graph,zh\)\{.*?\n\}', lambda _: summary, source, count=1, flags=re.S)
    if count != 1:
        raise ValueError('Missing relation summary')
    source = source.replace('const kinds=new Set(edges.map(edge=>edge.kind)),items=[];',
        'const kinds=new Set(edges.filter(edge=>edge.kind!=="bibliographic_coupling").map(edge=>edge.kind)),items=[];')
    file.write_text(source, 'utf-8')
    main_file = DIST / 'assets/index-DDV0cMc3.js'
    main_source = main_file.read_text('utf-8')
    main_source = re.sub(r'(PaperRelations-3-vizhM_\.js)(?:\?[^"\']*)?', r'\1?kw_graph=' + VERSION, main_source)
    main_file.write_text(main_source, 'utf-8')
    html_file = DIST / 'index.html'
    html = re.sub(r'kw_ui=[^"\']+', 'kw_ui=graph-streamlining-v2', html_file.read_text('utf-8'))
    html_file.write_text(html, 'utf-8')
    info_file = DIST / 'build-info.json'
    info = json.loads(info_file.read_text('utf-8'))
    for asset in (file, main_file, html_file):
        info.setdefault('assets', {})[asset.relative_to(DIST).as_posix()] = hashlib.sha256(asset.read_bytes()).hexdigest()
    info['relationship_display_policy'] = VERSION
    info_file.write_text(json.dumps(info, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    print('Shared-reference edges removed from rendering, layout, legend and visible totals')


if __name__ == '__main__':
    main()
