"""Update annotation overlays in place and allow clicking highlights to remove them."""
from pathlib import Path
import re


HIT_TEST = '''/* knowline-highlight-hit-test */
function kwPdfHighlightAt(notes,page,point){
    for(let n=notes.length-1;n>=0;n--){
        const note=notes[n],data=note.data;
        if(data?.kind!=="highlight"||data.page_index!==page)continue;
        const vertices=data.vertices||data.quads?.flat()||[];
        for(let j=0;j+3<vertices.length;j+=4){
            const quad=[vertices[j],vertices[j+1],vertices[j+3],vertices[j+2]];
            if(!quad.every(p=>Array.isArray(p)&&p.length===2&&p.every(Number.isFinite)))continue;
            let positive=false,negative=false,area=0;
            for(let k=0;k<4;k++){
                const a=quad[k],b=quad[(k+1)%4];
                const cross=(b[0]-a[0])*(point[1]-a[1])-(b[1]-a[1])*(point[0]-a[0]);
                positive ||= cross>1e-6;negative ||= cross< -1e-6;
                area+=a[0]*b[1]-b[0]*a[1];
            }
            if(Math.abs(area)>1e-6&&!(positive&&negative))return note;
        }
    }
}
/* end-knowline-highlight-hit-test */
'''

OLD_CLICK = 'function Ze(t){if(!N||F)return;const n=t.target.closest("[data-page-index]");if(!n)return;const r=Number(n.dataset.pageIndex),X=y.current.get(r);if(!X||X.info.readonly)return;const T=X.layer.getBoundingClientRect();if(t.clientX<T.left||t.clientX>T.right||t.clientY<T.top||t.clientY>T.bottom)return;const[B,Q]=X.viewport.convertToPdfPoint(t.clientX-T.left,t.clientY-T.top),O=X.info.geometry.pdf_to_mupdf;K({kind:"text",page_index:r,page_geometry_hash:X.info.geometry.hash,point:[O[0]*B+O[2]*Q+O[4],O[1]*B+O[3]*Q+O[5]]}),j(r),l(""),me(!1),t.preventDefault()}'
NEW_CLICK = '''function Ze(t){
    if(F||t.target.closest(".pdf-note-handle,button,a,input,textarea,select"))return;
    if(!N&&window.getSelection()?.isCollapsed===false)return;
    const n=t.target.closest("[data-page-index]");if(!n)return;
    const r=Number(n.dataset.pageIndex),X=y.current.get(r);if(!X||X.info.readonly)return;
    const T=X.layer.getBoundingClientRect();
    if(t.clientX<T.left||t.clientX>T.right||t.clientY<T.top||t.clientY>T.bottom)return;
    const[B,Q]=X.viewport.convertToPdfPoint(t.clientX-T.left,t.clientY-T.top),O=X.info.geometry.pdf_to_mupdf;
    const point=[O[0]*B+O[2]*Q+O[4],O[1]*B+O[3]*Q+O[5]];
    if(!N){fe(kwPdfHighlightAt(ke,r,point));return}
    K({kind:"text",page_index:r,page_geometry_hash:X.info.geometry.hash,point}),j(r),l(""),me(!1),t.preventDefault()
}'''


def patch(app):
    index=(app/'dist/index.html').read_text('utf-8')
    main=app/'dist/assets'/re.search(r'src="/assets/([^"?]+\.js)',index).group(1)
    bundle=re.search(r'import\("\./(Readers-[^"?]+\.js)(?:\?[^\"]*)?"\)',main.read_text('utf-8')).group(1)
    path=main.parent/bundle
    source=path.read_text('utf-8')
    changes={
        '(Ne(L.notes),Se(L.resource.version_id))':'Ne(L.notes)',
        'return Ne(r),J?.(n.resource,r),Se(n.resource.version_id),r':'return Ne(r),J?.(n.resource,r),r',
    }
    for old,new in changes.items():
        if source.count(old)==1:source=source.replace(old,new,1)
        elif source.count(old)==0 and source.count(new)==1:continue
        else:raise ValueError('Unexpected PDF annotation update path: '+old)
    if source.count(OLD_CLICK)==1:
        if '/* knowline-highlight-hit-test */' in source:
            raise ValueError('Unexpected existing highlight helper')
        source=source.replace(OLD_CLICK,NEW_CLICK,1)
        source=source.replace('function Mt(',HIT_TEST+'function Mt(',1)
    elif source.count(NEW_CLICK)!=1 or source.count(HIT_TEST)!=1:
        raise ValueError('Unexpected PDF highlight click path')
    labels=main.read_text('utf-8')
    for old,new in {
        'selectionHint:"选中文字后添加高亮；批注会写入真实 PDF。"':'selectionHint:"选中文字后添加高亮；点击已有高亮可删除，批注会写入真实 PDF。"',
        'selectionHint:"Select text to highlight. Annotations are saved in the actual PDF."':'selectionHint:"Select text to highlight; click an existing highlight to remove it. Annotations are saved in the actual PDF."',
    }.items():
        if labels.count(old)==1:labels=labels.replace(old,new,1)
        elif labels.count(old)==0 and labels.count(new)==1:continue
        else:raise ValueError('Unexpected PDF annotation help text')
    path.write_text(source,encoding='utf-8')
    main.write_text(labels,encoding='utf-8')
    return path


if __name__=='__main__':print(patch(Path(__file__).resolve().parents[1]))
