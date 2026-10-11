"""Read-only academic layout checks for newly generated task-owned Office files."""
import re,zipfile,xml.etree.ElementTree as ET
from .safety import DomainError
W='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
M='{http://schemas.openxmlformats.org/officeDocument/2006/math}'
A='{http://schemas.openxmlformats.org/drawingml/2006/main}'
P='{http://schemas.openxmlformats.org/presentationml/2006/main}'

def native_axis_path(node,cx,cy):
    """A straight native freeform can legitimately have one zero extent."""
    if (cx == 0) == (cy == 0) or cx < 0 or cy < 0:return False
    props=node.find(P+'spPr')
    if props is None or props.find(A+'noFill') is None or props.find(A+'ln') is None:return False
    paths=props.findall(A+'custGeom/'+A+'pathLst/'+A+'path')
    if not paths:return False
    axis='x' if cx==0 else 'y'
    for path in paths:
        if any(child.tag not in {A+'moveTo',A+'lnTo'} for child in path):return False
        points=path.findall('.//'+A+'pt')
        if len(points)<2 or len({pt.get(axis) for pt in points})!=1:return False
    return True

def contract(task):
    return {'schema_version':1,'basis':'paper-agent','task':task,'body_alignment':'both','math':'native_editable_no_padding_or_empty_arguments','reference_layout':'hanging_indent','visual_review_required':task in {'proposal_word','proposal_ppt','replicate_paper_figure'},'scope':'new task output only; preserve source and previous outputs'}

def math_issues(root):
    problems=[]
    for math in root.iter(M+'oMath'):
        if not ''.join(t.text or '' for t in math.iter(M+'t')).strip():problems.append('empty_formula')
        for text in math.iter(M+'t'):
            if re.search(r'[\t\r\n]| {2,}|\u00a0{2,}|\u200b',text.text or ''):problems.append('formula_padding')
        for kind,names in [('sSub',['e','sub']),('sSup',['e','sup']),('sSubSup',['e','sub','sup']),('sPre',['e','sub','sup']),('f',['num','den']),('rad',['e'])]:
            for node in math.iter(M+kind):
                for name in names:
                    part=node.find(M+name)
                    if part is None or not ''.join(t.text or '' for t in part.iter(M+'t')).strip():problems.append('empty_math_argument:'+kind+'/'+name)
    return problems

def inspect(path,kind):
    problems=[];counts={}
    with zipfile.ZipFile(path) as z:
        if kind=='word':
            root=ET.fromstring(z.read('word/document.xml'))
            styles=ET.fromstring(z.read('word/styles.xml')) if 'word/styles.xml' in z.namelist() else ET.Element('styles')
            by_id={s.get(W+'styleId'):s for s in styles.findall(W+'style')}
            default=next((s.get(W+'styleId') for s in by_id.values() if s.get(W+'default')=='1' and s.get(W+'type')=='paragraph'),None)
            def property(paragraph,name):
                value=paragraph.find(W+'pPr/'+W+name)
                if value is not None:return value
                link=paragraph.find(W+'pPr/'+W+'pStyle');identifier=link.get(W+'val') if link is not None else default;seen=set()
                while identifier in by_id and identifier not in seen:
                    seen.add(identifier);style=by_id[identifier];value=style.find(W+'pPr/'+W+name)
                    if value is not None:return value
                    link=style.find(W+'basedOn');identifier=link.get(W+'val') if link is not None else None
                return styles.find(W+'docDefaults/'+W+'pPrDefault/'+W+'pPr/'+W+name)
            counts['body_paragraphs']=0;counts['references']=0;counts['native_equations']=len(list(root.iter(M+'oMath')))
            # Body story only: table/caption/formula containers are not restyled.
            for paragraph in root.findall(W+'body/'+W+'p'):
                text=''.join(t.text or '' for t in paragraph.iter(W+'t')).strip()
                if not text or paragraph.find('.//'+W+'drawing') is not None:continue
                if paragraph.find('.//'+M+'oMath') is not None and re.fullmatch(r'\(?[\d.\-]+\)?',text):continue
                link=paragraph.find(W+'pPr/'+W+'pStyle');style_id=link.get(W+'val','') if link is not None else default or ''
                style=by_id.get(style_id);label=style.find(W+'name') if style is not None else None
                label=(style_id+' '+(label.get(W+'val','') if label is not None else '')).casefold()
                if re.search(r'heading|title|caption|toc|标题|题注|目录',label):continue
                if re.search(r'bibliography|reference|参考文献',label):
                    counts['references']+=1;indent=property(paragraph,'ind')
                    if indent is None or int(indent.get(W+'hanging','0'))<=0:problems.append('reference_hanging_indent')
                    continue
                if property(paragraph,'numPr') is not None:continue
                counts['body_paragraphs']+=1;align=property(paragraph,'jc')
                if align is None or align.get(W+'val')!='both':problems.append('body_not_justified')
            problems+=math_issues(root)
        else:
            presentation=ET.fromstring(z.read('ppt/presentation.xml'));size=presentation.find(P+'sldSz')
            if size is None:problems.append('slide_size_missing');width=height=0
            else:width=int(size.get('cx'));height=int(size.get('cy'))
            slides=[n for n in z.namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml',n)]
            counts={'slides':len(slides),'editable_objects':0,'native_equations':0}
            for name in slides:
                from .office_clipboard import effective_office_xml
                root=effective_office_xml(z.read(name));problems+=math_issues(root);counts['native_equations']+=len(list(root.iter(M+'oMath')))
                counts['editable_objects']+=len(list(root.iter(P+'sp')))+len(list(root.iter(P+'cxnSp')))
                tree=root.find(P+'cSld/'+P+'spTree')
                if tree is None:problems.append('slide_empty');continue
                for node in tree:
                    if node.tag not in {P+'sp',P+'pic',P+'graphicFrame'}:continue
                    transform=node.find(P+'spPr/'+A+'xfrm')
                    if transform is None:transform=node.find(P+'xfrm')
                    if transform is None:continue
                    offset=transform.find(A+'off');extent=transform.find(A+'ext')
                    if offset is None or extent is None:continue
                    x,y=int(offset.get('x')),int(offset.get('y'));cx,cy=int(extent.get('cx')),int(extent.get('cy'))
                    invalid_extent=(cx<=0 or cy<=0) and not native_axis_path(node,cx,cy)
                    if x<0 or y<0 or invalid_extent or x+cx>width+12700 or y+cy>height+12700:problems.append('object_outside_slide')
            if not slides:problems.append('slides_missing')
            if not counts['editable_objects']:problems.append('editable_objects_missing')
    return {'passed':not problems,'checks':counts,'issues':list(dict.fromkeys(problems)),'basis':'paper-agent','visual_review':'separate rendered-preview review required'}

def validate(path,kind):
    report=inspect(path,kind)
    if not report['passed']:raise DomainError('office_layout_invalid',issues=report['issues'])
    return report

def review(project,result,artifacts):
    from .safety import contained
    recorded=result.get('layout_review',{})
    if not isinstance(recorded,dict):raise DomainError('office_visual_review_required')
    images=recorded.get('preview_paths',[])
    if not isinstance(images,list) or not 1<=len(images)<=150 or any(not isinstance(p,str) for p in images):raise DomainError('office_visual_review_required')
    indexed={a['path'] for a in artifacts}
    if recorded.get('review_status') not in {'passed','passed_with_notes'} or not images or any(p not in indexed for p in images):raise DomainError('office_visual_review_required')
    for name in images:
        if not name.endswith('.png') or contained(project,name).read_bytes()[:8]!=b'\x89PNG\r\n\x1a\n':raise DomainError('office_visual_review_required')

def native_word_review(project,job,result):
    """A completed image extraction must prove native open, paste and final render."""
    import json
    from .safety import contained,digest
    verified=result.get('native_verify',{})
    if not isinstance(verified,dict) or any(verified.get(k) is not True for k in ('word_open','clipboard_verified','render_verified','math_structure_preserved')):
        raise DomainError('office_native_verification_required')
    entries={a['path'] for a in result['artifacts']}
    path=verified.get('evidence_path')
    if not isinstance(path,str) or path not in entries:raise DomainError('office_native_verification_required')
    evidence=json.loads(contained(project,path).read_text('utf-8-sig'))
    fragment=result['office_fragment']
    source=job['context']['office_selection']['image']
    if evidence.get('job_id')!=job['id'] or evidence.get('source_image_sha256')!=source['sha256'] or evidence.get('fragment_sha256')!=digest(contained(project,fragment['path'])) or evidence.get('native_equations')!=fragment['native_equations'] or evidence.get('clipboard_native_paste') is not True or evidence.get('math_structure_preserved') is not True:
        raise DomainError('office_native_verification_required')
    review(project,result,result['artifacts'])
    previews=evidence.get('preview_sha256',{})
    if not isinstance(previews,dict) or not previews:raise DomainError('office_visual_review_required')
    output=contained(project,job['context']['output_dir'])
    verified_paths=[]
    for name,sha in previews.items():
        page=contained(output,name)
        if digest(page)!=sha:raise DomainError('artifact_hash_mismatch')
        verified_paths.append(page.relative_to(project).as_posix())
    if set(verified_paths)!=set(result['layout_review']['preview_paths']):raise DomainError('office_visual_review_required')
