"""Connect a selected original Word document or create an explicitly requested new document.

The local file queue serializes document operations. No model, global source list,
Normal template is never modified. Existing-document sessions write only to the selected original.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from .safety import DomainError, atomic_json, contained, digest, DEVICES
from .word_references import citation_tags,reference_text,reference_bookmark,citation_bookmark

STYLES={'IEEE_SUPERSCRIPT':'IEEE','IEEE':'IEEE','APA':'APA','GB7714':'GB7714'}
SESSION_RE=re.compile(r'^[0-9a-f]{32}$')
ARCHIVE_NS='urn:knowline:word-citations:v1'
ET.register_namespace('kw',ARCHIVE_NS)


def text_hash(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


class ManagedReference:
    """Word rich-text content control backed by the document's source archive."""
    Type=81
    def __init__(self,owner,control):self.owner=owner;self.control=control
    @property
    def Code(self):return self
    @property
    def Start(self):return self.control.Range.Start+1
    @property
    def Text(self):return self.owner.control_codes[self.control.Tag]
    @Text.setter
    def Text(self,value):self.owner.control_codes[self.control.Tag]=value
    @property
    def Result(self):return self.control.Range
    @property
    def Locked(self):return False
    @Locked.setter
    def Locked(self,value):pass
    def Delete(self):
        # Retain the identity map so Word Undo can restore a removed control.
        self.control.Delete(True)


def validate_docx(path):
    """Reject executable/auto-loading content before Word opens an untrusted package."""
    try:
        with zipfile.ZipFile(path) as archive:
            files=archive.infolist()
            if len(files)>5000 or sum(f.file_size for f in files)>64*1024*1024:raise DomainError('word_package_limit')
            if 'word/document.xml' not in archive.namelist():raise DomainError('word_docx_required')
            for entry in files:
                name=entry.filename.lower()
                if any(marker in name for marker in ('vbaproject','activex/','embeddings/')):
                    raise DomainError('word_active_content')
                if name.endswith('.rels'):
                    node=ET.fromstring(archive.read(entry))
                    for rel in node:
                        if rel.get('TargetMode')=='External' and not rel.get('Type','').endswith('/hyperlink'):
                            raise DomainError('word_external_content')
                if name.startswith('word/') and name.endswith('.xml'):
                    node=ET.fromstring(archive.read(entry))
                    # Only the opcode of each field is executable. Searching
                    # all instruction text misidentifies titles/URLs inside
                    # ordinary citation fields as an external LINK command.
                    namespace='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
                    commands=[];stack=[]
                    for item in node.iter():
                        if item.tag==namespace+'fldSimple':commands.append(item.get(namespace+'instr',''))
                        elif item.tag==namespace+'fldChar':
                            kind=item.get(namespace+'fldCharType')
                            if kind=='begin':stack.append([])
                            elif kind in {'separate','end'} and stack:
                                commands.append(''.join(stack[-1]))
                                if kind=='end':stack.pop()
                                else:stack[-1]=[]
                        elif item.tag==namespace+'instrText':
                            if stack:stack[-1].append(item.text or '')
                            else:commands.append(item.text or '')
                    commands.extend(''.join(parts) for parts in stack)
                    for command in commands:
                        match=re.match(r'\s*([A-Za-z]+)\b',command)
                        if match and match.group(1).upper() in {'DDEAUTO','DDE','INCLUDETEXT','INCLUDEPICTURE','LINK','DATABASE'}:
                            raise DomainError('word_active_field',field_type=match.group(1).upper())
    except (OSError,zipfile.BadZipFile,ET.ParseError):raise DomainError('word_docx_required')


def session_folder(project, session):
    if not SESSION_RE.fullmatch(session):raise DomainError('word_session_invalid')
    return contained(project,'.knowledge/word/'+session)


def sessions(project):
    folder=contained(project,'.knowledge/word',False)
    result=[]
    if folder.exists():
        for entry in folder.iterdir():
            if SESSION_RE.fullmatch(entry.name):
                path=contained(project,str(entry.relative_to(project)/'state.json'),False)
                if path.exists():
                    state=json.loads(path.read_text('utf-8'))
                    state['online']=state.get('status')=='ready' and time.time()-state.get('heartbeat',0)<10
                    result.append(state)
    return result


def running_documents():
    """Enumerate existing Word documents across instances without opening files."""
    import pythoncom,win32com.client.dynamic
    values=[];seen=set()
    def add(doc):
        try:
            path=str(doc.FullName)
            if str(doc.Path) and path.lower().endswith('.docx') and str(doc.Application.Name)=='Microsoft Word' and os.path.normcase(path) not in seen:
                seen.add(os.path.normcase(path));values.append(doc)
        except Exception:pass
    try:
        app=win32com.client.dynamic.Dispatch(pythoncom.GetActiveObject('Word.Application'))
        for doc in app.Documents:add(doc)
    except Exception:pass
    try:
        rot=pythoncom.GetRunningObjectTable();context=pythoncom.CreateBindCtx(0)
        for moniker in rot.EnumRunning():
            try:
                if moniker.GetDisplayName(context,None).lower().endswith('.docx'):
                    add(win32com.client.dynamic.Dispatch(rot.GetObject(moniker).QueryInterface(pythoncom.IID_IDispatch)))
            except Exception:pass
    except Exception:pass
    return values


def open_documents():
    import pythoncom
    pythoncom.CoInitialize()
    try:return [{'document':str(doc.FullName),'name':str(doc.Name)} for doc in running_documents()]
    finally:pythoncom.CoUninitialize()


def start(project, document=None, name=None, text='', visible=True, direct_original=None):
    from .layout import project_root
    project=project_root(project)
    if os.name!='nt':raise DomainError('word_windows_required')
    if direct_original is None:direct_original=bool(document)
    if direct_original:
        if not isinstance(document,str) or not any(Path(d['document'])==Path(document) for d in open_documents()):raise DomainError('word_original_not_open')
        source=Path(document).absolute();name=source.stem
        for state in sessions(project):
            if state.get('online') and state.get('direct_original') and Path(state['document'])==source:return state
    elif document:
        source=contained(project,document)
        if source.suffix.lower()!='.docx' or not zipfile.is_zipfile(source):raise DomainError('word_docx_required')
        validate_docx(source)
        name=source.stem
    else:
        source=None
    if not name or len(name)>100 or DEVICES.match(name) or re.search(r'[<>:"/\\|?*\x00-\x1f]',name) or name.endswith(('.', ' ')):
        raise DomainError('word_name_invalid')
    sid=uuid.uuid4().hex
    folder=contained(project,'.knowledge/word/'+sid,False);folder.mkdir(parents=True)
    (folder/'requests').mkdir();(folder/'responses').mkdir()
    if direct_original:target=source
    else:
        output=contained(project,'outputs/word/'+sid,False);output.mkdir(parents=True)
        target=output/(name+'.docx')
        if source:shutil.copy2(source,target)
    atomic_json(folder/'config.json',{'session':sid,'document':str(target) if direct_original else str(target.relative_to(project)),
                'direct_original':direct_original,
                'source_document':str(source) if direct_original else str(source.relative_to(project)) if source else None,
                'source_sha256':digest(source) if source else None,'text':text,'visible':visible})
    atomic_json(folder/'state.json',{'session':sid,'status':'starting','heartbeat':time.time(),
                                   'document':str(target) if direct_original else str(target.relative_to(project))})
    log=(folder/'worker.log').open('a',encoding='utf-8')
    try:
        proc=subprocess.Popen(([sys.executable,'--word-worker',sid,'--project',str(project)] if getattr(sys,'frozen',False) else [sys.executable,'-m','backend.word_bridge','--worker',sid,'--project',str(project)]),
                              cwd=Path(__file__).resolve().parents[1],stdout=log,stderr=log,
                              creationflags=subprocess.CREATE_NO_WINDOW)
    finally:log.close()
    for _ in range(60):
        state=json.loads((folder/'state.json').read_text('utf-8'))
        if state['status']=='ready':return state
        if state['status']=='failed':raise DomainError(state.get('code','word_start_failed'),details=state.get('details'))
        if proc.poll() is not None:raise DomainError('word_start_failed',log=str(folder/'worker.log'))
        time.sleep(.5)
    # Do not kill Word if startup is slow; its bounded session remains inspectable.
    raise DomainError('word_start_timeout',session=sid)


def request(project, session, action, operation_id=None, **params):
    folder=session_folder(Path(project).resolve(),session)
    operation=hashlib.sha256(str(operation_id).encode()).hexdigest()[:32] if operation_id else uuid.uuid4().hex
    payload={'id':operation,'action':action,**params}
    payload_hash=text_hash(json.dumps(payload,sort_keys=True,ensure_ascii=False))
    response=folder/'responses'/(operation+'.json')
    def unpack():
        result=json.loads(response.read_text('utf-8'))
        if result.get('payload_hash')!=payload_hash:raise DomainError('operation_id_reused')
        if result.get('error'):raise DomainError(result['error']['code'],**result['error'].get('params',{}))
        return result['result']
    if response.exists():return unpack()
    state=json.loads((folder/'state.json').read_text('utf-8'))
    if state['status']!='ready' or time.time()-state.get('heartbeat',0)>15:
        raise DomainError('word_session_offline',session=session)
    atomic_json(folder/'requests'/(str(time.time_ns())+'_'+operation+'.json'),payload)
    for _ in range(120):
        if response.exists():
            return unpack()
        time.sleep(.25)
    raise DomainError('word_operation_timeout',operation_id=operation,session=session)


class WordDocument:
    """All COM access is confined to this worker's STA and one document."""
    def __init__(self,project,config):
        import pythoncom
        import win32com.client.dynamic
        self.project=project;self.config=config;self.doc=None;self.app=None;self.formatting={};self.archive={};self.rendered_refs=[];self.control_codes={}
        pythoncom.CoInitialize()
        self.direct_original=config.get('direct_original',False)
        self.app=None if self.direct_original else win32com.client.dynamic.Dispatch(pythoncom.CoCreateInstance('Word.Application',None,pythoncom.CLSCTX_LOCAL_SERVER,pythoncom.IID_IDispatch))
        try:
            target=Path(config['document']) if self.direct_original else contained(project,config['document'],False)
            if self.direct_original:
                self.doc=next((doc for doc in running_documents() if os.path.normcase(str(doc.FullName))==os.path.normcase(str(target))),None)
                if self.doc is None:raise DomainError('word_original_not_open')
                self.app=self.doc.Application
            else:self.app.AutomationSecurity=3;self.app.DisplayAlerts=0;self.app.Visible=False
            if self.direct_original:pass
            elif target.exists():
                self.doc=self.app.Documents.Open(str(target),False,False,False)
            else:
                self.doc=self.app.Documents.Add()
                self.doc.Content.Text=config.get('text','').replace('\r\n','\n').replace('\r','\n').replace('\n','\r')
                self.doc.SaveAs2(str(target),16)
            self.assert_editable()
            self.ensure_supported()
            parts=self.doc.CustomXMLParts.SelectByNamespace(ARCHIVE_NS)
            if parts.Count>1:raise DomainError('word_archive_conflict')
            if parts.Count:
                root=ET.fromstring(parts.Item(1).XML)
                for item in root.findall('{'+ARCHIVE_NS+'}source'):
                    self.archive[item.get('tag')]=ET.tostring(item[0],encoding='unicode')
                self.rendered_refs=[item.get('tag') for item in root.findall('{'+ARCHIVE_NS+'}reference')]
                self.control_codes={item.get('tag'):item.get('code') for item in root.findall('{'+ARCHIVE_NS+'}control')}
                fmt=root.find('{'+ARCHIVE_NS+'}format')
                if fmt is not None:
                    self.formatting={k:float(v) if k in {'size','spacing'} else v=='True' if k=='citation_superscript' else v for k,v in fmt.attrib.items()}
            if not self.fields(96) and not self.fields(97):
                self.doc.Bibliography.BibliographyStyle='IEEE'
                self.formatting['citation_superscript']=True
            if not self.direct_original:
                self.app.Visible=config.get('visible',True)
                if self.app.Visible:self.app.DisplayAlerts=-1
        except Exception:
            self.close();raise

    def assert_editable(self):
        if self.doc.ReadOnly or self.doc.ProtectionType!=-1:raise DomainError('word_document_readonly')
        if self.doc.TrackRevisions or self.doc.Revisions.Count:raise DomainError('word_track_changes_pending')

    def ensure_supported(self):
        for field in self.doc.Fields:
            if field.Type==81 and re.search(r'EN\.CITE|ZOTERO|MENDELEY',field.Code.Text,re.I):
                raise DomainError('word_other_citation_system')
        for story in self.doc.StoryRanges:
            if story.StoryType!=1 and any(field.Type in (96,97) for field in story.Fields):
                raise DomainError('word_citation_outside_body')
        if any(cc.Tag in self.control_codes and cc.Range.StoryType!=1 for cc in self.doc.ContentControls):raise DomainError('word_citation_outside_body')

    def fields(self,kind):
        marker={96:'KW.CITE',97:'KW.BIB'}.get(kind)
        result=[field for field in self.doc.Fields if field.Type==kind]
        if marker:
            result.extend(ManagedReference(self,cc) for cc in self.doc.ContentControls if cc.Tag in self.control_codes and marker in self.control_codes[cc.Tag])
        return sorted(result,key=lambda f:f.Code.Start)

    def delete_reference_field(self,field):
        if isinstance(field,ManagedReference):field.Delete()
        else:field.Delete()

    def convert_reference_fields(self,linked):
        # Native citation results reject embedded hyperlinks. Rich-text controls
        # retain stable source IDs and editable linked results in the saved DOCX.
        changed=False
        for kind in (96,97):
            for field in reversed(self.fields(kind)):
                if linked==isinstance(field,ManagedReference):continue
                tags=citation_tags(field.Code.Text) if kind==96 else []
                if kind==96 and not tags:raise DomainError('word_mixed_native_sources')
                text=' ' if linked else field.Result.Text
                anchor=self.doc.Range(field.Code.Start-1,field.Code.Start-1).Duplicate
                field.Locked=False;self.delete_reference_field(field)
                start=min(anchor.Start,self.doc.Content.End-1)
                if linked:code=('KW.CITE '+' '.join(tags)) if kind==96 else 'KW.BIB linked'
                else:code=(tags[0]+''.join(' \\m '+tag for tag in tags[1:])+' \\l 1033') if kind==96 else '\\l 1033'
                if linked:
                    cc=self.doc.ContentControls.Add(0,self.doc.Range(start,start))
                    cc.Tag=('KW.CITE.' if kind==96 else 'KW.BIB.')+uuid.uuid4().hex
                    cc.Title='引用' if kind==96 else '参考文献'
                    self.control_codes[cc.Tag]=code
                    cc.Range.Text=text
                else:self.doc.Fields.Add(self.doc.Range(start,start),kind,code,True)
                changed=True
        if changed:self.persist_archive()

    def signature(self):
        return (self.doc.Bibliography.BibliographyStyle,
                tuple((field.Code.Text.strip(),field.Result.Text) for field in self.fields(96)),
                tuple(field.Result.Text for field in self.fields(97)),
                tuple((tag,self.reference_present(tag)) for tag in self.rendered_refs),
                tuple(source.XML for source in self.doc.Bibliography.Sources))

    def refresh(self):
        self.assert_editable();self.ensure_supported()
        if self.linked_mode():
            self.reconcile_reference_deletions()
            self.sync_sources()
            if self.fields(96):self.ensure_bibliography()
            self.convert_reference_fields(True)
            self.render_linked_references()
            self.apply_format()
            return
        self.sync_sources()
        self.convert_reference_fields(False)
        # Never update unrelated equations, hyperlinks, TOCs, EndNote or other fields.
        # The bibliography computes Word's RefOrder. A second citation pass is
        # necessary after a deletion/move; individual citation updates can see stale order.
        for kind in (96,97,96):
            for field in self.fields(kind):
                field.Locked=False;field.Update()
        self.apply_format()

    def persist_archive(self):
        root=ET.Element('{'+ARCHIVE_NS+'}archive')
        for tag,xml in self.archive.items():
            item=ET.SubElement(root,'{'+ARCHIVE_NS+'}source',tag=tag);item.append(ET.fromstring(xml))
        for tag in self.rendered_refs:ET.SubElement(root,'{'+ARCHIVE_NS+'}reference',tag=tag)
        for tag,code in self.control_codes.items():ET.SubElement(root,'{'+ARCHIVE_NS+'}control',tag=tag,code=code)
        ET.SubElement(root,'{'+ARCHIVE_NS+'}format',{k:str(v) for k,v in self.formatting.items()})
        xml=ET.tostring(root,encoding='unicode')
        parts=list(self.doc.CustomXMLParts.SelectByNamespace(ARCHIVE_NS))
        # LoadXML cannot reload an already-loaded Word CustomXMLPart. Add first so
        # a COM failure never removes the existing archive, then delete old owned parts.
        self.doc.CustomXMLParts.Add(xml)
        for part in parts:part.Delete()

    def sync_sources(self):
        # Word's bibliography includes the entire current source list, including unused sources.
        # Keep only our cited sources there; keep frozen removed records inside the document
        # so restoring a managed citation still has its source, independent of the project.
        used={tag for f in self.fields(96) for tag in re.findall(r'\bKW[0-9a-f]{24}\b',f.Code.Text)}
        current={s.Tag:s for s in self.doc.Bibliography.Sources}
        changed=False
        for tag in used-current.keys():
            if tag in self.archive:self.doc.Bibliography.Sources.Add(self.archive[tag])
        for tag,source in current.items():
            if re.fullmatch(r'KW[0-9a-f]{24}',tag) and tag not in used:
                if tag not in self.archive:self.archive[tag]=source.XML;changed=True
                source.Delete()
        if changed:self.persist_archive()

    def linked_mode(self):
        return bool(self.formatting.get('citation_superscript')) and self.doc.Bibliography.BibliographyStyle=='IEEE'

    def reference_present(self,tag):
        name=reference_bookmark(tag)
        return self.doc.Bookmarks.Exists(name) and bool(self.doc.Bookmarks.Item(name).Range.Text.strip())

    def reconcile_reference_deletions(self):
        removed={tag for tag in self.rendered_refs if not self.reference_present(tag)}
        for field in reversed(self.fields(96)):
            tags=citation_tags(field.Code.Text)
            if not tags:continue
            kept=[tag for tag in tags if tag not in removed]
            if isinstance(field,ManagedReference) and self.rendered_refs:
                # Removing one linked numeral from a group removes that occurrence,
                # while the same source can remain cited elsewhere in the document.
                links={h.SubAddress for h in field.Result.Hyperlinks if re.fullmatch(r'\d+',h.Range.Text.strip())}
                kept=[tag for tag in kept if reference_bookmark(tag) in links]
            if not kept or not field.Result.Text.strip():self.delete_reference_field(field)
            elif kept!=tags:
                field.Code.Text=(' ADDIN KW.CITE '+' '.join(kept)+' ') if field.Type==81 else (' CITATION '+kept[0]+''.join(' \\m '+tag for tag in kept[1:])+' \\l 1033 ')

    def bookmark(self,name,range):
        if self.doc.Bookmarks.Exists(name):self.doc.Bookmarks.Item(name).Delete()
        self.doc.Bookmarks.Add(name,range)

    def link(self,range,target,superscript=False):
        self.doc.Hyperlinks.Add(Anchor=range,Address='',SubAddress=target)
        range.Font.Color=0;range.Font.Underline=0;range.Font.Superscript=superscript

    def render_linked_references(self):
        citations=self.fields(96)
        if any(not citation_tags(f.Code.Text) for f in citations):raise DomainError('word_mixed_native_sources')
        ordered=list(dict.fromkeys(tag for field in citations for tag in citation_tags(field.Code.Text)))
        sources={**self.archive,**{s.Tag:s.XML for s in self.doc.Bibliography.Sources}}
        if any(tag not in sources for tag in ordered):raise DomainError('citation_source_missing')
        numbers={tag:i for i,tag in enumerate(ordered,1)}
        for tag in self.rendered_refs:
            for name in (reference_bookmark(tag),citation_bookmark(tag)):
                if self.doc.Bookmarks.Exists(name):self.doc.Bookmarks.Item(name).Delete()
        bibliographies=self.fields(97)
        if not ordered:
            for field in reversed(bibliographies):self.delete_reference_field(field)
            self.rendered_refs=[];self.persist_archive()
            return
        for field in bibliographies:
            field.Locked=False
            for table in list(field.Result.Tables):table.ConvertToText(1,True)
            field.Result.Text='\r'.join('['+str(numbers[tag])+'] '+reference_text(sources[tag]) for tag in ordered)
            start=field.Result.Start
            for tag in ordered:
                text='['+str(numbers[tag])+'] '+reference_text(sources[tag])
                length=len(text.encode('utf-16-le'))//2
                self.bookmark(reference_bookmark(tag),self.doc.Range(start,start+length))
                start+=length+1
        for field in reversed(citations):
            tags=citation_tags(field.Code.Text)
            field.Locked=False
            field.Result.Text=' ['+', '.join(str(numbers[tag]) for tag in tags)+']'
            # Insert from right to left; Word expands ranges when hyperlink fields are added.
            offsets=[];offset=2
            for tag in tags:
                offsets.append((tag,offset,len(str(numbers[tag]))));offset+=len(str(numbers[tag]))+2
            for tag,offset,length in reversed(offsets):
                anchor=self.doc.Range(field.Result.Start+offset,field.Result.Start+offset+length)
                self.bookmark(citation_bookmark(tag),anchor)
                self.link(anchor,reference_bookmark(tag),True)
        for tag in ordered:
            name=reference_bookmark(tag)
            if self.doc.Bookmarks.Exists(name):
                entry=self.doc.Bookmarks.Item(name).Range.Duplicate
                anchor=self.doc.Range(entry.Start,entry.Start+len('['+str(numbers[tag])+']'))
                self.link(anchor,citation_bookmark(tag))
                self.bookmark(name,entry)
        for field in [*citations,*bibliographies]:field.Locked=True
        if self.rendered_refs!=ordered:
            self.rendered_refs=ordered;self.persist_archive()

    def apply_format(self):
        for field in self.fields(96):
            if re.search(r'\bKW[0-9a-f]{24}\b',field.Code.Text):
                field.Result.Font.Superscript=bool(self.formatting.get('citation_superscript'))
        for field in self.fields(97):
            r=field.Result
            r.Font.Superscript=False
            # Word can retain tiny column widths when a table-based numbered
            # bibliography replaces an author-year bibliography. Fit only the
            # generated reference table to its text area, leaving body tables alone.
            for table in r.Tables:
                setup=r.Sections.Item(1).PageSetup
                width=setup.PageWidth-setup.LeftMargin-setup.RightMargin-setup.Gutter
                if setup.TextColumns.Count>1:width=min(c.Width for c in setup.TextColumns)
                table.PreferredWidthType=3;table.PreferredWidth=width
                table.AllowAutoFit=False
                # The native style has a trailing merged row, so Columns.Item
                # cannot be used. Work by cells without splitting/merging any row.
                for row in table.Rows:
                    if row.Cells.Count==2:
                        row.Cells.Item(1).SetWidth(26,0)
                        row.Cells.Item(2).SetWidth(max(50,width-26),0)
                    elif row.Cells.Count==1:row.Cells.Item(1).SetWidth(width,0)
            if self.formatting.get('font'):r.Font.Name=self.formatting['font']
            if self.formatting.get('size'):r.Font.Size=self.formatting['size']
            if self.formatting.get('spacing'):
                r.ParagraphFormat.LineSpacingRule=5
                r.ParagraphFormat.LineSpacing=12*self.formatting['spacing']

    def inspect(self):
        paragraphs=[{'index':i,'text':p.Range.Text,'text_hash':text_hash(p.Range.Text)} for i,p in enumerate(self.doc.Paragraphs,1)]
        sel=self.doc.ActiveWindow.Selection
        return {'document':self.config['document'],'style':self.doc.Bibliography.BibliographyStyle,
                'styles':list(STYLES),'paragraphs':paragraphs,
                'selection':{'text':sel.Range.Text,'text_hash':text_hash(sel.Range.Text),'start':sel.Start,'end':sel.End,
                             'context_hash':text_hash(sel.Range.Paragraphs.Item(1).Range.Text)},
                'citations':[{'index':i,'code':f.Code.Text,'text':f.Result.Text,'superscript':f.Result.Font.Superscript==-1} for i,f in enumerate(self.fields(96),1)],
                'bibliographies':[f.Result.Text for f in self.fields(97)],
                'reference_entries':[{'tag':tag,'bookmark':reference_bookmark(tag),'present':self.reference_present(tag)} for tag in self.rendered_refs],
                'bibliography_tables':sum(f.Result.Tables.Count for f in self.fields(97)),
                'reference_links':[{'text':h.Range.Text,'target':h.SubAddress} for h in self.doc.Hyperlinks if str(h.SubAddress).startswith(('KWREF','KWBACK'))],
                'sources':[{'tag':s.Tag,'xml':s.XML} for s in self.doc.Bibliography.Sources],
                'track_changes':bool(self.doc.TrackRevisions),'saved':bool(self.doc.Saved),'bibliography_format':self.formatting}

    def citation_range(self,params):
        # Guard stale prose and scope before inserting any sources or fields.
        if params.get('selection'):
            sel=self.app.Selection
            if str(sel.Document.FullName).casefold()!=str(self.doc.FullName).casefold():raise DomainError('word_wrong_selection')
            r=sel.Range.Duplicate
            if params.get('allow_cursor'):
                if params.get('selection_start')!=r.Start or params.get('selection_end')!=r.End:
                    raise DomainError('word_text_conflict')
                if r.Start==r.End and params.get('if_context_hash')!=text_hash(r.Paragraphs.Item(1).Range.Text):
                    raise DomainError('word_text_conflict')
            elif r.Start==r.End:raise DomainError('word_selection_required')
        else:
            index=params.get('paragraph')
            if not isinstance(index,int) or not 1<=index<=self.doc.Paragraphs.Count:raise DomainError('word_paragraph_invalid')
            r=self.doc.Paragraphs.Item(index).Range.Duplicate
        if not params.get('if_text_hash') or text_hash(r.Text)!=params['if_text_hash']:
            raise DomainError('word_text_conflict',current_hash=text_hash(r.Text))
        # Citation placement inside a field, table, header or generated bibliography is ambiguous.
        if r.StoryType!=1 or r.Information(12):raise DomainError('word_unsupported_location')
        for f in [*self.doc.Fields,*self.fields(96),*self.fields(97)]:
            if isinstance(f,ManagedReference) and f.Result.Start<=r.End<f.Result.End:raise DomainError('word_inside_field')
            if (f.Type==97 and r.Start<f.Result.End and r.End>f.Result.Start) or (r.End>f.Code.Start and r.End<=f.Result.End):
                raise DomainError('word_inside_field')
        end=r.End
        while end>r.Start and self.doc.Range(end-1,end).Text in ('\r','\x07'):end-=1
        return self.doc.Range(end,end)

    def execute(self,action,params):
        if action=='inspect':return self.inspect()
        self.assert_editable();self.ensure_supported()
        if action=='cite':
            position=self.citation_range(params)
            sources=params.get('sources',[])
            if not sources:raise DomainError('citation_selection_required')
            existing={**self.archive,**{s.Tag:s.XML for s in self.doc.Bibliography.Sources}}
            # Embedded sources are frozen at first insertion. Metadata changes need explicit sync.
            for source in sources:
                if not re.fullmatch(r'KW[0-9a-f]{24}',source['tag']):raise DomainError('citation_tag_invalid')
                if source['tag'] in existing:
                    node=ET.fromstring(existing[source['tag']])
                    # Word rewrites the legacy source namespace into OOXML on insertion.
                    comments=next((n for n in node if n.tag.endswith('}Comments')),None)
                    if comments is None or 'version='+source['version_id']+';' not in (comments.text or '') or 'sha256='+source['sha256'] not in (comments.text or ''):
                        raise DomainError('citation_embedded_version_conflict',resource_id=source['resource_id'])
            for source in sources:
                if source['tag'] not in {s.Tag for s in self.doc.Bibliography.Sources}:
                    self.doc.Bibliography.Sources.Add(source['xml'])
                self.archive.setdefault(source['tag'],source['xml'])
            self.persist_archive()
            code=sources[0]['tag']+''.join(' \\m '+s['tag'] for s in sources[1:])+' \\l 1033'
            self.doc.Fields.Add(position,96,code,True)
            self.ensure_bibliography()
        elif action=='bibliography':
            self.ensure_bibliography()
        elif action=='style':
            if params.get('name') not in STYLES:raise DomainError('word_style_invalid',styles=list(STYLES))
            self.doc.Bibliography.BibliographyStyle=STYLES[params['name']]
            self.formatting['citation_superscript']=params['name']=='IEEE_SUPERSCRIPT'
            if params['name']!='IEEE_SUPERSCRIPT':self.rendered_refs=[]
            self.persist_archive()
        elif action=='format':
            values=params.get('formatting',{})
            if set(values)-{'font','size','spacing'}:raise DomainError('word_format_invalid')
            if 'font' in values and (not isinstance(values['font'],str) or not values['font'].strip() or len(values['font'])>100):raise DomainError('word_format_invalid')
            if 'size' in values and not 6<=float(values['size'])<=72:raise DomainError('word_format_invalid')
            if 'spacing' in values and not .5<=float(values['spacing'])<=3:raise DomainError('word_format_invalid')
            self.formatting.update(values)
            self.persist_archive()
        elif action=='refresh':pass
        elif action=='save':
            self.refresh();self.doc.Save();return self.inspect()
        elif action=='close':
            self.refresh();self.doc.Save();return {'document':self.config['document'],'saved':True}
        else:raise DomainError('word_action_invalid')
        self.refresh()
        return self.inspect()

    def ensure_bibliography(self):
        if not self.fields(97):
            end=self.doc.Content.End-1
            self.doc.Range(end,end).InsertAfter('\r')
            end=self.doc.Content.End-1
            self.doc.Fields.Add(self.doc.Range(end,end),97,'\\l 1033',True)

    def close(self):
        if getattr(self,'direct_original',False):return
        if self.doc is not None:
            try:self.doc.Close(0)
            except Exception:pass
        if self.app is not None:
            try:
                # Someone may have opened another document in our visible instance. Leave it alone.
                if self.app.Documents.Count==0:self.app.Quit(0)
            except Exception:pass


def worker(project,session):
    project=Path(project).resolve();folder=session_folder(project,session)
    config=json.loads((folder/'config.json').read_text('utf-8'));word=None
    state={'session':session,'document':config['document'],'source_document':config.get('source_document'),'direct_original':config.get('direct_original',False),
           'status':'starting','auto_refresh':True,'refresh_count':0,'heartbeat':time.time()}
    try:
        word=WordDocument(project,config)
        import win32process
        state.update(status='ready',word_version=word.app.Version,
                     word_pid=win32process.GetWindowThreadProcessId(word.doc.ActiveWindow.Hwnd)[1])
        previous=word.signature();pending=None;last_heartbeat=0
        while True:
            __import__('pythoncom').PumpWaitingMessages()
            for file in sorted((folder/'requests').glob('*.json')):
                file=contained(project,str(file.relative_to(project)))
                params=json.loads(file.read_text('utf-8'))
                payload_hash=text_hash(json.dumps(params,sort_keys=True,ensure_ascii=False))
                operation=params.pop('id');action=params.pop('action')
                if not SESSION_RE.fullmatch(operation):raise DomainError('word_operation_invalid')
                response_file=folder/'responses'/(operation+'.json')
                if response_file.exists():
                    # A timed-out caller may retry; each stable operation executes once.
                    file.unlink();continue
                try:
                    result=word.execute(action,params)
                    response={'result':result}
                    if action!='inspect':
                        previous=word.signature();pending=None;state.pop('warning',None)
                except DomainError as exc:response={'error':{'code':exc.code,'params':exc.params}}
                except Exception as exc:response={'error':{'code':'word_operation_failed','params':{'details':str(exc)}}}
                response['payload_hash']=payload_hash
                atomic_json(response_file,response)
                file.unlink()
                if action=='close' and 'result' in response:
                    state['status']='closed';return
            try:
                current=word.signature()
                if current!=previous:
                    if pending!=current:pending=current;changed=time.monotonic()
                    elif time.monotonic()-changed>.6:
                        word.refresh();previous=word.signature();pending=None
                        state['refresh_count']+=1;state.pop('warning',None)
            except DomainError as exc:state['warning']=exc.code
            except Exception as exc:
                # Busy Word/dialogs are transient. Do not mistake an RPC rejection for closure.
                state.update(warning='word_busy',warning_details=str(exc))
                try:
                    target=str(Path(config['document']) if config.get('direct_original') else contained(project,config['document'])).casefold()
                    if not any(str(d.FullName).casefold()==target for d in word.app.Documents):
                        state['status']='closed';return
                except Exception as connection:
                    if getattr(connection,'hresult',None) in {-2147417848,-2147220995,-2147023174}:
                        state['status']='closed';return
            if time.monotonic()-last_heartbeat>1:
                try:state['style']=word.doc.Bibliography.BibliographyStyle
                except Exception:pass
                state['heartbeat']=time.time();atomic_json(folder/'state.json',state);last_heartbeat=time.monotonic()
            time.sleep(.2)
    except DomainError as exc:state.update(status='failed',code=exc.code,details=exc.params)
    except Exception as exc:state.update(status='failed',code='word_start_failed',details=str(exc))
    finally:
        if word:word.close()
        state['heartbeat']=time.time();atomic_json(folder/'state.json',state)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--project',required=True);parser.add_argument('--worker',required=True)
    args=parser.parse_args();worker(args.project,args.worker)
