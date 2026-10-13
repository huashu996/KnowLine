"""Restore existing typed graph edges in the release UI without inventing any.

Preserves the black canvas, star nodes, input handlers and citation palette.
Only this named graph bundle is changed; reruns are idempotent.
"""
import argparse
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
DEFAULT_BUNDLE = APP / 'dist/assets/PaperRelations-3-vizhM_.js'
SUMMARY_OLD = '''function kwRelationSummary(graph,zh){
 const nodes=graph.nodes||[],count=nodes.filter(node=>node.citation_count!=null).length;
 const checked=nodes.filter(node=>node.references_checked===true).length,edges=(graph.edges||[]).filter(edge=>edge.kind==="citation").length;
 return zh?`被引数量已核实 ${count}/${nodes.length} · 参考列表已核查 ${checked}/${nodes.length} · 已核验引用边 ${edges} 条`:`Verified citation counts ${count}/${nodes.length} · Reference lists checked ${checked}/${nodes.length} · ${edges} verified citation edges`;
}'''
SUMMARY_NEW = '''function kwRelationSummary(graph,zh){
 const nodes=graph.nodes||[],edges=graph.edges||[],count=nodes.filter(node=>node.citation_count!=null).length;
 const checked=nodes.filter(node=>node.references_checked===true).length,total=edges.length;
 const citation=edges.filter(edge=>edge.kind==="citation").length,coupling=edges.filter(edge=>edge.kind==="bibliographic_coupling").length,cocitation=edges.filter(edge=>edge.kind==="co_citation").length,semantic=edges.filter(edge=>edge.kind==="semantic_similarity").length;
 return zh?`总关系线 ${total} 条 · 直接引用 ${citation} · 共享参考 ${coupling} · 共同被引 ${cocitation}${semantic?` · 语义推断 ${semantic}`:""} · 被引数量已核实 ${count}/${nodes.length} · 参考列表已核查 ${checked}/${nodes.length}`:`${total} relationship lines · Direct citations ${citation} · Shared references ${coupling} · Co-citations ${cocitation}${semantic?` · Inferred similarity ${semantic}`:""} · Verified citation counts ${count}/${nodes.length} · Reference lists checked ${checked}/${nodes.length}`;
}'''
HELPERS = r'''
function kwRelationStyle(kind,zh){
 const styles={citation:{color:"#8eefff",dash:void 0,arrow:true,label:zh?"来源支持的直接引用（箭头指向被引用论文）":"Sourced direct citation (arrow points to cited paper)"},bibliographic_coupling:{color:"#c4adff",dash:"7 4",arrow:false,label:zh?"共享参考文献":"Shared references"},co_citation:{color:"#6ee7b7",dash:"2 4",arrow:false,label:zh?"共同被其他论文引用":"Co-cited by other papers"},semantic_similarity:{color:"#f69fcc",dash:"9 3 2 3",arrow:false,label:zh?"语义相似（推断，非引用）":"Semantic similarity (inferred, not a citation)"}};
 return styles[kind]||{color:"#cbd5e1",dash:"3 3",arrow:false,label:String(kind||"relationship")};
}
function kwRelationGeometry(edge,edges,a,b,ra,rb){
 const peers=edges.filter(other=>other.source===edge.source&&other.target===edge.target||other.source===edge.target&&other.target===edge.source);
 const lane=(peers.indexOf(edge)-(peers.length-1)/2)*5,dx=b.x-a.x,dy=b.y-a.y,length=Math.hypot(dx,dy)||1,ux=dx/length,uy=dy/length,sign=String(edge.source)<String(edge.target)?1:-1;
 const ox=-uy*sign*lane,oy=ux*sign*lane,start=Math.min(Math.max(12,ra+4),length/3),end=Math.min(Math.max(12,rb+4),length/3);
 return {x1:a.x+ox+ux*start,y1:a.y+oy+uy*start,x2:b.x+ox-ux*end,y2:b.y+oy-uy*end,ux,uy};
}
function kwRelationLegend(edges,zh){
 const kinds=new Set(edges.map(edge=>edge.kind)),items=[];
 if(kinds.has("citation")){items.push({color:"#e8bc73",arrow:true,label:zh?"起点直接引用 →":"Origin citations →"});items.push({color:"#8eefff",arrow:true,label:zh?"其他直接引用 →":"Peer citations →"});}
 for(const kind of kinds){if(kind!=="citation")items.push(kwRelationStyle(kind,zh));}
 return e.jsxs("div",{className:"paper-relation-legend","aria-label":zh?"关系类型与线型说明":"Relationship types and line styles",style:{display:"flex",flexWrap:"wrap",gap:"6px 12px",alignItems:"center"},children:items.map((item,index)=>e.jsxs("span",{style:{display:"inline-flex",alignItems:"center",gap:"5px"},children:[e.jsxs("svg",{width:28,height:10,viewBox:"0 0 28 10","aria-hidden":"true",style:{width:"28px",height:"10px",flex:"0 0 28px"},children:[e.jsx("line",{x1:1,y1:5,x2:24,y2:5,stroke:item.color,strokeWidth:1.3,strokeDasharray:item.dash}),item.arrow&&e.jsx("path",{d:"M20 2 L25 5 L20 8",fill:"none",stroke:item.color,strokeWidth:1.2})]}),item.label]},index))});
}
'''
EDGE_OLD = 'M.map((t,o)=>{const u=K.get(t.source),v=K.get(t.target);if(!u||!v)return null;const N=!!i&&(t.source===i.id||t.target===i.id),E=t.source===s.origin_id||t.target===s.origin_id,A=E?"#e8bc73":"#8eefff",L=Math.min(1.35,.75+t.weight*.2);return e.jsxs("g",{"data-source":t.source,"data-target":t.target,"data-kind":t.kind,"data-center-edge":E,className:"paper-edge "+(i&&!N?"is-muted":""),pointerEvents:"none",children:[e.jsx("line",{className:"paper-edge-glow",x1:u.x,y1:u.y,x2:v.x,y2:v.y,stroke:A,strokeWidth:L+1,opacity:N?.07:.025}),e.jsx("line",{x1:u.x,y1:u.y,x2:v.x,y2:v.y,stroke:A,strokeWidth:L,opacity:N?.95:i?.3:.7}),e.jsx("title",{children:x?"来源支持的直接引用":"Sourced direct citation"})]},o)})'
EDGE_NEW = 'M.map((t,o)=>{const u=K.get(t.source),v=K.get(t.target);if(!u||!v)return null;const N=!!i&&(t.source===i.id||t.target===i.id),E=t.source===s.origin_id||t.target===s.origin_id,style=kwRelationStyle(t.kind,x),A=t.kind==="citation"&&E?"#e8bc73":style.color,L=Math.min(1.35,.75+(Number.isFinite(t.weight)?t.weight:1)*.2),geo=kwRelationGeometry(t,M,u,v,G(u.citation_count,j),G(v.citation_count,j)),alpha=N?.95:i?.3:.7;return e.jsxs("g",{"data-source":t.source,"data-target":t.target,"data-kind":t.kind,"data-center-edge":E,className:"paper-edge "+(i&&!N?"is-muted":""),pointerEvents:"none",children:[e.jsx("line",{className:"paper-edge-glow",x1:geo.x1,y1:geo.y1,x2:geo.x2,y2:geo.y2,stroke:A,strokeWidth:L+1,strokeDasharray:style.dash,opacity:N?.07:.025}),e.jsx("line",{x1:geo.x1,y1:geo.y1,x2:geo.x2,y2:geo.y2,stroke:A,strokeWidth:L,strokeDasharray:style.dash,opacity:alpha}),style.arrow&&e.jsx("polygon",{points:`${geo.x2},${geo.y2} ${geo.x2-geo.ux*6-geo.uy*3},${geo.y2-geo.uy*6+geo.ux*3} ${geo.x2-geo.ux*6+geo.uy*3},${geo.y2-geo.uy*6-geo.ux*3}`,fill:A,opacity:alpha}),e.jsx("title",{children:style.label+(Array.isArray(t.shared_paper_ids)&&t.shared_paper_ids.length?" · "+(x?(t.kind==="bibliographic_coupling"?"共有参考条目 ":"共同引用来源 ")+t.shared_paper_ids.length+" 篇":"Shared papers "+t.shared_paper_ids.length):"")})]},o)})'
LEGEND_OLD = 'e.jsxs("div",{className:"paper-relation-legend","aria-label":x?"关系线说明":"Relationship legend",children:[e.jsxs("span",{children:[e.jsx("i",{className:"center-edge-swatch"}),x?"目标论文引用":"Target citations"]}),e.jsxs("span",{children:[e.jsx("i",{className:"peer-edge-swatch"}),x?"其他论文引用":"Peer citations"]})]})'


def replace(source, old, new):
    if old in source:
        if source.count(old) != 1:
            raise ValueError('Expected one release-bundle edit anchor')
        return source.replace(old, new, 1)
    if new in source:
        return source
    raise ValueError('Expected one release-bundle edit anchor')


def patch(source):
    source = replace(source, 'M=f.useMemo(()=>s.edges.filter(t=>t.kind==="citation"),[s])',
                     'M=f.useMemo(()=>s.edges||[],[s])')
    source = replace(source, 'r===n||l===n||d.kind==="semantic_similarity"||', 'r===n||l===n||')
    source = replace(source, 'const m=d.weight*(d.kind==="semantic_similarity"?.65:1)',
                     'const m=(Number.isFinite(d.weight)?d.weight:1)*(d.kind==="semantic_similarity"?.65:1)')
    source = replace(source, 'x?"条引用":"citations"', 'x?"条关系线":"relationship lines"')
    source = replace(source, EDGE_OLD, EDGE_NEW)
    source = replace(source, LEGEND_OLD, 'kwRelationLegend(M,x)')
    source = replace(source, SUMMARY_OLD, SUMMARY_NEW)
    if 'function kwRelationStyle(' not in source:
        source += HELPERS
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, default=DEFAULT_BUNDLE)
    args = parser.parse_args()
    source = args.bundle.read_text('utf-8')
    updated = patch(source)
    if updated != source:
        args.bundle.write_text(updated, encoding='utf-8')


if __name__ == '__main__':
    main()
