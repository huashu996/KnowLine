"""Deterministic screenshot transcription -> native Word fragment.

Codex supplies declarative content after viewing the frozen image. This tool
never invokes a model, evaluates input code, or writes outside the job output.
"""
import json
import re
import time
import threading
import zipfile
import xml.etree.ElementTree as E
from datetime import datetime, timezone
from pathlib import Path
from .safety import DomainError, atomic_json, contained, digest
from . import pdf

M='http://schemas.openxmlformats.org/officeDocument/2006/math'
W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
E.register_namespace('w',W);E.register_namespace('m',M)

_native_lock=threading.Lock()

def service_step(store,job_id,action,body):
    """Native Word belongs to the desktop service, not the model sandbox."""
    with _native_lock:
        job=store.job(job_id);store.check(job,body)
        if job['task']!='copy_office_selection' or job['status'] in {'completed','partial'}:raise DomainError('office_fragment_not_ready')
        if action=='prepare':return prepare(store.project,job_id)
        if action in {'build','revise'}:
            content=body.get('content')
            if not isinstance(content,str) or not content:raise DomainError('office_content_invalid')
            return build(store.project,job_id,content,revise=action=='revise')
        raise DomainError('invalid_request')

def tag(ns,name,*children,**attrs):
    node=E.Element('{'+ns+'}'+name,{'{'+ns+'}'+key:str(value) for key,value in attrs.items()})
    node.extend(children);return node

def load_context(project,job_id):
    if not re.fullmatch(r'j_[0-9a-f-]{36}',job_id):raise DomainError('job_invalid')
    file=contained(project,'.knowledge/jobs/'+job_id+'/context.json')
    context=json.loads(file.read_text('utf-8'))
    resources=context.get('resources',[]);selection=context.get('office_selection',{})
    if context.get('job_id')!=job_id or context.get('task')!='copy_office_selection' or len(resources)!=1 or resources[0]['type']!='paper':raise DomainError('scope_violation')
    if selection.get('target')!='word' or selection.get('selection_mode')!='image_region':raise DomainError('office_fast_target_unsupported')
    output=contained(project,context['output_dir'])
    from .output_names import resolve_alias
    expected=contained(project,resolve_alias(project,'outputs/'+job_id))
    if output!=expected:raise DomainError('path_outside_scope')
    resource=resources[0];path=contained(project,resource['snapshot_path']);image=contained(project,selection['image']['path'])
    image.relative_to(output)
    if digest(path)!=resource['sha256'] or digest(image)!=selection['image']['sha256']:raise DomainError('artifact_hash_mismatch')
    with pdf.open_pdf(path) as document:
        page=document[selection['page_index']]
        if pdf.geometry(page)['hash']!=selection['page_geometry_hash']:raise DomainError('geometry_conflict')
    return context,output

def prepare(project,job_id):
    start=time.perf_counter();context,output=load_context(project,job_id)
    path=output/'extraction-timing.json'
    if path.exists():
        timing=json.loads(path.read_text('utf-8'))
        if timing.get('context_sha256')!=digest(contained(project,'.knowledge/jobs/'+job_id+'/context.json')):raise DomainError('scope_violation')
    else:
        timing={'job_id':job_id,'started_at':datetime.now(timezone.utc).isoformat(),'target_seconds':300,
                'context_sha256':digest(contained(project,'.knowledge/jobs/'+job_id+'/context.json')),
                'stages':{'verify_scope_seconds':round(time.perf_counter()-start,3)}}
        atomic_json(path,timing)
    selection=context['office_selection'];resource=context['resources'][0]
    return {'job_id':job_id,'image':selection['image'],'version_id':resource['version_id'],'page':selection['page_index']+1,
            'output_dir':context['output_dir'],'started_at':timing['started_at'],'target_seconds':300,
            'content_schema':'research-skills/knowline-copy-office/references/content-schema.md'}

class MathBuilder:
    def __init__(self,definitions):self.definitions=definitions;self.count=0
    def build(self,spec,depth=0):
        self.count+=1
        if depth>40 or self.count>12000:raise DomainError('office_content_limit')
        if isinstance(spec,str):
            if len(spec)>2000:raise DomainError('office_content_limit')
            spec=re.sub(r'\s+',' ',spec).strip()
            spec=re.sub(r'\s*([=+−×÷≤≥≈∈∉±])\s*',r'\1',spec)
            if not spec:return []
            # Combining hats in a math text run attach to the edge of bold T/R
            # in native Word. Represent each marked base as an actual accent.
            marks={'\u0302','\u0303','\u0304','\u0305','\u0307','\u0308','\u20d7'}
            nodes=[];plain=''
            def run(text):
                r=tag(M,'r');t=tag(M,'t');t.text=text;t.set('{http://www.w3.org/XML/1998/namespace}space','preserve');r.append(t);return r
            for char in spec:
                if char in marks:
                    if not plain:raise DomainError('office_math_invalid',reason='accent_without_base')
                    if len(plain)>1:nodes.append(run(plain[:-1]))
                    nodes.append(tag(M,'acc',tag(M,'accPr',tag(M,'chr',val=char)),tag(M,'e',run(plain[-1]))));plain=''
                else:plain+=char
            if plain:nodes.append(run(plain))
            return nodes
        if isinstance(spec,list):return [node for item in spec for node in self.build(item,depth+1)]
        if not isinstance(spec,dict) or len(spec)!=1:raise DomainError('office_math_invalid')
        kind,value=next(iter(spec.items()))
        def body(name,s):
            nodes=self.build(s,depth+1)
            if not nodes:raise DomainError('office_math_invalid',reason='empty_math_argument')
            return tag(M,name,*nodes)
        if kind=='text':
            if not isinstance(value,str) or not value.strip():raise DomainError('office_math_invalid')
            nodes=self.build(re.sub(r'\s+',' ',value).strip(),depth+1)
            nodes[0].insert(0,tag(M,'rPr',tag(M,'nor')))
            return nodes
        if kind=='ref':
            if not isinstance(value,str) or value not in self.definitions:raise DomainError('office_math_reference')
            return self.build(self.definitions[value],depth+1)
        if kind in {'bold','bold_upright'}:
            nodes=self.build(value,depth+1)
            for node in nodes:
                if node.tag not in {'{'+M+'}r','{'+M+'}acc'}:raise DomainError('office_math_invalid')
                for run in node.iter('{'+M+'}r'):
                    run.insert(0,tag(M,'rPr',tag(M,'sty',val='bi' if kind=='bold' else 'b')))
            return nodes
        if kind in {'hat','bar','tilde','dot','ddot','vec'}:
            mark={'hat':'\u0302','bar':'\u0305','tilde':'\u0303','dot':'\u0307','ddot':'\u0308','vec':'\u20d7'}[kind]
            return [tag(M,'acc',tag(M,'accPr',tag(M,'chr',val=mark)),body('e',value))]
        if kind=='subsup':
            if not isinstance(value,list) or len(value)!=3:raise DomainError('office_math_invalid')
            return [tag(M,'sSubSup',body('e',value[0]),body('sub',value[1]),body('sup',value[2]))]
        if kind=='pre':
            # Left scripts share a base. One intentionally absent side is valid;
            # never invent a parenthesis/space as a fake base or script.
            if not isinstance(value,list) or len(value)!=3:raise DomainError('office_math_invalid')
            lower=self.build(value[1],depth+1);upper=self.build(value[2],depth+1)
            if not lower and not upper:raise DomainError('office_math_invalid',reason='empty_prescripts')
            return [tag(M,'sPre',tag(M,'sub',*lower),tag(M,'sup',*upper),body('e',value[0]))]
        if kind in {'underbrace','overbrace'}:
            if not isinstance(value,list) or len(value)!=2:raise DomainError('office_math_invalid')
            below=kind=='underbrace'
            group=tag(M,'groupChr',tag(M,'groupChrPr',tag(M,'chr',val='⏟' if below else '⏞'),
                       tag(M,'pos',val='bot' if below else 'top'),tag(M,'vertJc',val='top' if below else 'bot')),body('e',value[0]))
            return [tag(M,'limLow' if below else 'limUpp',tag(M,'e',group),body('lim',value[1]))]
        if kind in {'sub','sup','frac','func'}:
            if not isinstance(value,list) or len(value)!=2:raise DomainError('office_math_invalid')
            if kind=='func':
                if not isinstance(value[0],str) or value[0] not in {'sin','cos','tan','log','Log','ln','exp','min','max','lim','det'}:raise DomainError('office_math_invalid')
                nodes=self.build(value[0],depth+1);nodes[0].insert(0,tag(M,'rPr',tag(M,'sty',val='p')))
                return [tag(M,'func',tag(M,'fName',*nodes),body('e',value[1]))]
            opposite='sub' if kind=='sup' else 'sup'
            nested=value[0]
            if kind in {'sub','sup'} and isinstance(nested,dict) and set(nested)=={opposite}:
                inner=nested[opposite]
                if not isinstance(inner,list) or len(inner)!=2:raise DomainError('office_math_invalid')
                sub,sup=(inner[1],value[1]) if kind=='sup' else (value[1],inner[1])
                return [tag(M,'sSubSup',body('e',inner[0]),body('sub',sub),body('sup',sup))]
            names={'sub':('sSub','e','sub'),'sup':('sSup','e','sup'),'frac':('f','num','den')}[kind]
            return [tag(M,names[0],body(names[1],value[0]),body(names[2],value[1]))]
        if kind=='root':return [tag(M,'rad',tag(M,'radPr',tag(M,'degHide',val='1')),tag(M,'deg'),body('e',value))]
        if kind=='delim':
            if not isinstance(value,list) or len(value)!=3 or value[0] not in {'(','[','{','|','‖'} or value[2] not in {')',']','}','|','‖'}:raise DomainError('office_math_invalid')
            return [tag(M,'d',tag(M,'dPr',tag(M,'begChr',val=value[0]),tag(M,'endChr',val=value[2])),body('e',value[1]))]
        if kind in {'sum','integral','product'}:
            if not isinstance(value,dict) or set(value)!={'lower','upper','body'}:raise DomainError('office_math_invalid')
            lower=self.build(value['lower'],depth+1);upper=self.build(value['upper'],depth+1)
            return [tag(M,'nary',tag(M,'naryPr',tag(M,'chr',val={'sum':'∑','integral':'∫','product':'∏'}[kind]),tag(M,'limLoc',val='undOvr'),tag(M,'subHide',val='0' if lower else '1'),tag(M,'supHide',val='0' if upper else '1')),tag(M,'sub',*lower),tag(M,'sup',*upper),body('e',value['body']))]
        if kind=='matrix':
            if not isinstance(value,list) or not value or len(value)>30 or any(not isinstance(row,list) or len(row)!=len(value[0]) for row in value) or not 1<=len(value[0])<=30:raise DomainError('office_math_invalid')
            return [tag(M,'m',*[tag(M,'mr',*[body('e',cell) for cell in row]) for row in value])]
        raise DomainError('office_math_invalid',kind=kind)

def text_run(text):
    if not isinstance(text,str):raise DomainError('office_content_invalid')
    run=tag(W,'r')
    for index,part in enumerate(text.split('\t')):
        if index:run.append(tag(W,'tab'))
        node=tag(W,'t');node.text=part;node.set('{http://www.w3.org/XML/1998/namespace}space','preserve');run.append(node)
    return run

def create_docx(content,target):
    if content.get('schema_version')!=1 or not isinstance(content.get('math',{}),dict):raise DomainError('office_content_invalid')
    blocks=content.get('blocks')
    if not isinstance(blocks,list) or not 1<=len(blocks)<=150:raise DomainError('office_content_limit')
    math=MathBuilder(content.get('math',{}));body=tag(W,'body');count=0
    def expression(value):
        # Preserve legacy named references; structured one-offs need no extra
        # definition. Literal math strings use {"text": ...} explicitly.
        return math.build({'ref':value} if isinstance(value,str) else value)
    for block in blocks:
        if not isinstance(block,dict) or set(block)-{'runs','equation','number','role'} or ('runs' in block)==('equation' in block):raise DomainError('office_content_invalid')
        role=block.get('role','body')
        if role not in {'body','heading','caption','reference'}:raise DomainError('office_content_invalid')
        paragraph=tag(W,'p');props=tag(W,'pPr')
        paragraph.append(props)
        if 'equation' in block:
            props.append(tag(W,'keepLines'))
            # A4 width 11906 minus two 1080 margins is 9746 twips.
            props.append(tag(W,'tabs',tag(W,'tab',val='center',pos='4873'),tag(W,'tab',val='right',pos='9746')))
            props.append(tag(W,'spacing',after='0',line='276',lineRule='auto'))
            paragraph.append(tag(W,'r',tag(W,'tab')))
            paragraph.append(tag(M,'oMath',*expression(block['equation'])));count+=1
            number=block.get('number')
            if number is not None:
                if not isinstance(number,str) or len(number)>20:raise DomainError('office_content_invalid')
                paragraph.append(tag(W,'r',tag(W,'tab')));paragraph.append(text_run('('+number+')'))
        else:
            props.append(tag(W,'pStyle',val={'body':'Normal','heading':'KnowlineHeading','caption':'Caption','reference':'Bibliography'}[role]))
            if role=='heading':props.append(tag(W,'keepNext'))
            if role=='reference':props.append(tag(W,'tabs',tag(W,'tab',val='left',pos='360')))
            props.append(tag(W,'spacing',after='0',line='276',lineRule='auto'))
            if role=='reference':props.append(tag(W,'ind',left='360',hanging='360'))
            props.append(tag(W,'jc',val='center' if role=='caption' else 'left' if role=='heading' else 'both'))
            runs=block['runs']
            if not isinstance(runs,list) or len(runs)>150:raise DomainError('office_content_limit')
            for item in runs:
                if isinstance(item,str):paragraph.append(text_run(item))
                elif isinstance(item,dict) and set(item)=={'math'}:
                    paragraph.append(tag(M,'oMath',*expression(item['math'])));count+=1
                else:raise DomainError('office_content_invalid')
        body.append(paragraph)
    body.append(tag(W,'sectPr',tag(W,'pgSz',w='11906',h='16838'),tag(W,'pgMar',top='1296',bottom='1296',left='1080',right='1080',header='360',footer='360',gutter='0')))
    document=tag(W,'document',body)
    styles=tag(W,'styles',tag(W,'docDefaults',tag(W,'rPrDefault',tag(W,'rPr',tag(W,'rFonts',ascii='Times New Roman',hAnsi='Times New Roman',eastAsia='宋体'),tag(W,'sz',val='24'))),tag(W,'pPrDefault',tag(W,'pPr',tag(W,'jc',val='both')))),tag(W,'style',tag(W,'name',val='Normal'),type='paragraph',default='1',styleId='Normal'),tag(W,'style',tag(W,'name',val='Knowline Heading'),tag(W,'basedOn',val='Normal'),tag(W,'rPr',tag(W,'b'),tag(W,'sz',val='28')),type='paragraph',styleId='KnowlineHeading'),tag(W,'style',tag(W,'name',val='Caption'),tag(W,'basedOn',val='Normal'),type='paragraph',styleId='Caption'),tag(W,'style',tag(W,'name',val='Bibliography'),tag(W,'basedOn',val='Normal'),type='paragraph',styleId='Bibliography'))
    settings=tag(W,'settings',tag(M,'mathPr',tag(M,'mathFont',val='Cambria Math')))
    files={'word/document.xml':E.tostring(document,encoding='utf-8',xml_declaration=True),
           'word/styles.xml':E.tostring(styles,encoding='utf-8',xml_declaration=True),'word/settings.xml':E.tostring(settings,encoding='utf-8',xml_declaration=True),
           '[Content_Types].xml':b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/><Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/></Types>',
           '_rels/.rels':b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
           'word/_rels/document.xml.rels':b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/></Relationships>'}
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as package:
        for name,data in files.items():package.writestr(name,data)
    return count

def math_signature(path):
    """Compare math structure/arguments after native paste, ignoring styling."""
    def normalize(node):
        name=node.tag.split('}')[-1]
        if name=='acc':
            mark=node.find('{'+M+'}accPr/{'+M+'}chr')
            return ('acc',mark.get('{'+M+'}val') if mark is not None else '\u0302',normalize(node.find('{'+M+'}e')))
        if not node.tag.startswith('{'+M+'}') or name.endswith('Pr') or name in {'ctrlPr'}:return None
        if name=='r':
            import unicodedata
            # Word canonicalizes U+2212 to '-' and mathematical alphabet
            # glyphs to base letters plus math font properties during paste.
            return unicodedata.normalize('NFKC',''.join(n.text or '' for n in node.iter() if n.tag=='{'+M+'}t')).replace('−','-').replace('∗','*')
        children=[]
        for child in node:
            value=normalize(child)
            if value is None:continue
            if isinstance(value,str) and children and isinstance(children[-1],str):children[-1]+=value
            else:children.append(value)
        return (name,tuple(children))
    with zipfile.ZipFile(path) as package:root=E.fromstring(package.read('word/document.xml'))
    return [normalize(node) for node in root.findall('.//{'+M+'}oMath')]

def native_verify(output,count,fragment_name='fragment.docx'):
    """One native Word pass; owned documents only, no global settings or Quit."""
    import pythoncom
    import win32com.client.dynamic
    pythoncom.CoInitialize();app=None;source=None;target=None;security=None
    start=time.perf_counter()
    fragment=contained(output,fragment_name)
    try:
        app=win32com.client.dynamic.Dispatch(pythoncom.CoCreateInstance('Word.Application',None,pythoncom.CLSCTX_LOCAL_SERVER,pythoncom.IID_IDispatch))
        security=app.AutomationSecurity;app.AutomationSecurity=3
        source=app.Documents.Open(str(fragment),False,True,False,Visible=False)
        if Path(source.FullName).resolve()!=fragment:raise DomainError('office_wrong_document')
        if source.OMaths.Count!=count:raise DomainError('office_fragment_invalid')
        source.ExportAsFixedFormat(str(output/'preview.pdf'),17)
        source.Content.Copy();target=app.Documents.Add(Visible=False);target.Content.Paste()
        if target.OMaths.Count!=count:raise DomainError('office_fragment_invalid')
        target.SaveAs2(str(output/'paste-check.docx'),16)
        target.Close(False);target=None;source.Close(False);source=None
        if math_signature(fragment)!=math_signature(output/'paste-check.docx'):raise DomainError('office_math_paste_mismatch')
        pages=[]
        with pdf.open_pdf(output/'preview.pdf') as document:
            if len(document)>12:raise DomainError('office_content_limit')
            for i,page in enumerate(document):
                image=output/f'preview-{i+1}.png';page.get_pixmap(matrix=__import__('pymupdf').Matrix(1.6,1.6),alpha=False).save(image);pages.append(image.name)
        return {'native_equations':count,'clipboard_native_paste':True,'math_structure_preserved':True,'preview_images':pages,'native_verify_seconds':round(time.perf_counter()-start,3)}
    finally:
        if target is not None:target.Close(False)
        if source is not None:source.Close(False)
        if app is not None and security is not None:app.AutomationSecurity=security
        pythoncom.CoUninitialize()

def revise_unsubmitted(output,content,content_hash,fragment_name='fragment.docx',job_id=None):
    """One concentrated correction; accepted jobs are rejected by the service."""
    previous_path=output/'previous-build.json'
    fragment=contained(output,fragment_name)
    if previous_path.exists():raise DomainError('office_revision_limit')
    state=json.loads((output/'build-state.json').read_text('utf-8'))
    validation_path=output/'validation.json'
    if validation_path.is_file():
        validation=json.loads(validation_path.read_text('utf-8'))
    else:
        # A failed native verification can leave a genuine build but no
        # validation report. Recover only the exact hash-tracked draft; do not
        # treat that draft as a verified or accepted result.
        if not isinstance(job_id,str) or not re.fullmatch(r'j_[0-9a-f-]{36}',job_id):raise DomainError('office_fragment_not_ready')
        if state.get('revision_count',0) or not re.fullmatch(r'[0-9a-f]{64}',str(state.get('fragment_sha256',''))):raise DomainError('office_fragment_not_ready')
        if any(output.glob('preview-*.png')):raise DomainError('office_visual_review_required')
        validation={'job_id':job_id,'fragment_sha256':state['fragment_sha256'],'preview_sha256':{},'native_verification_incomplete':True}
    if content_hash==state['content_sha256']:raise DomainError('office_revision_unchanged')
    if digest(fragment)!=validation['fragment_sha256']:raise DomainError('artifact_hash_mismatch')
    files=[output/name for name in [fragment_name,'validation.json','build-state.json','paste-check.docx','preview.pdf']]
    for name,sha in validation['preview_sha256'].items():
        if not re.fullmatch(r'preview-[1-9][0-9]*\.png',name):raise DomainError('office_visual_review_required')
        path=contained(output,name)
        if digest(path)!=sha:raise DomainError('artifact_hash_mismatch')
        files.append(path)
    result_path=output/'result.json'
    if result_path.exists():
        result=json.loads(result_path.read_text('utf-8-sig'))
        if result.get('job_id')!=validation['job_id'] or result.get('office_fragment',{}).get('path') is None:raise DomainError('office_output_exists')
        files.append(result_path)
    candidate=contained(output,'revision-candidate.docx',must_exist=False)
    if candidate.exists():raise DomainError('office_output_exists')
    count=create_docx(content,candidate)
    # Only generated outputs with known names are replaced, never source files.
    atomic_json(previous_path,{'job_id':validation['job_id'],'previous_fragment_sha256':validation['fragment_sha256'],'previous_content_sha256':state['content_sha256'],'previous_preview_sha256':validation['preview_sha256'],'revision_count':1})
    for path in files:
        checked=contained(output,path.name,must_exist=False)
        if checked.exists():checked.unlink()
    candidate.replace(fragment)
    atomic_json(output/'build-state.json',{'content_sha256':content_hash,'fragment_sha256':digest(fragment),'native_equations':count,'revision_count':1})

def build(project,job_id,content_path,revise=False):
    start=time.perf_counter();prepare(project,job_id);context,output=load_context(project,job_id)
    fragment_name=context.get('output_filenames',{}).get('fragment.docx','fragment.docx')
    fragment=contained(output,fragment_name,must_exist=False)
    content_path=contained(output,content_path)
    if content_path.stat().st_size>250000:raise DomainError('office_content_limit')
    content=json.loads(content_path.read_text('utf-8-sig'));selection=context['office_selection'];resource=context['resources'][0]
    if content.get('source_image_sha256')!=selection['image']['sha256'] or content.get('source_version_id')!=resource['version_id']:raise DomainError('scope_violation')
    if revise:revise_unsubmitted(output,content,digest(content_path),fragment_name,job_id)
    if any((output/name).exists() for name in ('result.json','validation.json')):raise DomainError('office_output_exists')
    state_path=output/'build-state.json';content_hash=digest(content_path)
    if fragment.exists():
        if not state_path.exists():raise DomainError('office_output_exists')
        state=json.loads(state_path.read_text('utf-8'))
        if state['content_sha256']!=content_hash or state['fragment_sha256']!=digest(fragment):raise DomainError('office_output_exists')
        count=state['native_equations']
    else:
        count=create_docx(content,fragment)
        atomic_json(state_path,{'content_sha256':content_hash,'fragment_sha256':digest(fragment),'native_equations':count})
    from .office_clipboard import check
    if check(fragment,'word')!=count:raise DomainError('office_fragment_invalid')
    generated=time.perf_counter()-start
    validation=native_verify(output,count,fragment_name)
    validation.update({'job_id':job_id,'source_image_sha256':selection['image']['sha256'],'source_version_id':resource['version_id'],
                       'uncertain':content.get('uncertain',[]),'build_seconds':round(time.perf_counter()-start,3),
                       'fragment_sha256':digest(fragment),
                       'preview_sha256':{name:digest(contained(output,name)) for name in validation['preview_images']}})
    atomic_json(output/'validation.json',validation)
    timing_path=output/'extraction-timing.json';timing=json.loads(timing_path.read_text('utf-8'))
    elapsed=(datetime.now(timezone.utc)-datetime.fromisoformat(timing['started_at'])).total_seconds()
    timing['stages'].update({'generate_seconds':round(generated,3),'native_verify_seconds':validation['native_verify_seconds']})
    timing.update({'elapsed_to_build_seconds':round(elapsed,3),'within_target_to_build':elapsed<=300,'awaiting_visual_review':True})
    atomic_json(timing_path,timing)
    return {**validation,'output_dir':context['output_dir'],'elapsed_seconds':round(elapsed,3),'target_seconds':300,'next':'View preview images, then kw office finish with the expected revision.'}

def finish(project,job_id,reviewed):
    context,output=load_context(project,job_id);validation=json.loads((output/'validation.json').read_text('utf-8'))
    fragment=contained(output,context.get('output_filenames',{}).get('fragment.docx','fragment.docx'))
    if set(reviewed)!=set(validation['preview_images']):raise DomainError('office_visual_review_required')
    from .office_clipboard import check
    if check(fragment,'word')!=validation['native_equations']:raise DomainError('office_fragment_invalid')
    fragment_hash=validation.get('fragment_sha256')
    if not fragment_hash or digest(fragment)!=fragment_hash:raise DomainError('artifact_hash_mismatch')
    for name,expected_hash in validation.get('preview_sha256',{}).items():
        if name not in reviewed or digest(contained(output,name))!=expected_hash:raise DomainError('artifact_hash_mismatch')
    if set(validation.get('preview_sha256',{}))!=set(reviewed):raise DomainError('office_visual_review_required')
    validation['visual_review_images']=reviewed;atomic_json(output/'validation.json',validation)
    def artifact(path):return {'path':path.relative_to(project).as_posix(),'sha256':digest(path)}
    result={'schema_version':2,'job_id':job_id,'status':'completed','claims':[],
            'artifacts':[artifact(fragment),artifact(contained(project,context['office_selection']['image']['path'])),artifact(output/'validation.json')]+[artifact(contained(output,name)) for name in reviewed],
            'office_fragment':{'path':fragment.relative_to(project).as_posix(),'target':'word','native_equations':validation['native_equations'],'source_image_sha256':context['office_selection']['image']['sha256']},
            'native_verify':{'word_open':True,'clipboard_verified':validation['clipboard_native_paste'],'render_verified':True,'status':'passed','math_structure_preserved':validation['math_structure_preserved'],'evidence_path':(output/'validation.json').relative_to(project).as_posix()},
            'layout_review':{'review_status':'passed','preview_paths':[(output/name).relative_to(project).as_posix() for name in reviewed],'notes':['Reviewed the final native Word previews; text order and editable formulas preserve the selected source.']},
            'warnings':validation['uncertain']}
    file=output/'result.json';atomic_json(file,result);return result,file

def mark_ingested(project,job_id,revision):
    _,output=load_context(project,job_id);file=output/'extraction-timing.json';timing=json.loads(file.read_text('utf-8'))
    elapsed=(datetime.now(timezone.utc)-datetime.fromisoformat(timing['started_at'])).total_seconds()
    timing.update({'elapsed_seconds':round(elapsed,3),'within_target':elapsed<=300,'completed_at':datetime.now(timezone.utc).isoformat(),'ingested_revision':revision,'awaiting_visual_review':False})
    atomic_json(file,timing);return timing
