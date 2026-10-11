"""Copy only a validated task's owned Office artifact; no existing user document access."""
import os
import time
import zipfile
import xml.etree.ElementTree as ET
from .safety import DomainError


def check(path,kind):
    from .word_bridge import validate_docx
    if kind=='word':validate_docx(path)
    elif kind=='powerpoint':
        try:
            with zipfile.ZipFile(path) as package:
                entries=package.infolist()
                if len(entries)>5000 or sum(e.file_size for e in entries)>64*1024*1024 or 'ppt/presentation.xml' not in package.namelist():raise DomainError('office_fragment_invalid')
                for entry in entries:
                    name=entry.filename.lower()
                    if any(k in name for k in ('vbaproject','activex/','embeddings/')):raise DomainError('office_active_content')
                    if name.endswith('.rels'):
                        for rel in ET.fromstring(package.read(entry)):
                            if rel.get('TargetMode')=='External' and not rel.get('Type','').endswith('/hyperlink'):raise DomainError('office_active_content')
        except (zipfile.BadZipFile,ET.ParseError):raise DomainError('office_fragment_invalid')
    else:raise DomainError('office_fragment_invalid')
    with zipfile.ZipFile(path) as package:
        members=['word/document.xml'] if kind=='word' else [n for n in package.namelist() if n.startswith('ppt/slides/slide') and n.endswith('.xml')]
        equations=sum(len(effective_office_xml(package.read(n)).findall('.//{http://schemas.openxmlformats.org/officeDocument/2006/math}oMath')) for n in members)
        if kind == 'powerpoint':
            for name in members:
                root = effective_office_xml(package.read(name))
                for tag in ('headEnd', 'tailEnd'):
                    for arrow in root.iter('{http://schemas.openxmlformats.org/drawingml/2006/main}' + tag):
                        if arrow.get('type', 'none') not in {'none', 'triangle', 'stealth', 'diamond', 'oval', 'arrow'}:
                            raise DomainError('office_fragment_invalid', reason='invalid_arrow_type', part=name,
                                              value=arrow.get('type'))
    return equations


def _copy_owned(path,kind):
    import pythoncom
    import win32com.client.dynamic
    app=win32com.client.dynamic.Dispatch(pythoncom.CoCreateInstance('Word.Application' if kind=='word' else 'PowerPoint.Application',None,pythoncom.CLSCTX_LOCAL_SERVER,pythoncom.IID_IDispatch))
    security=app.AutomationSecurity
    document=None
    try:
        app.AutomationSecurity=3
        if kind=='word':
            document=app.Documents.Open(str(path),False,True,False,Visible=False)
            if str(document.FullName).casefold()!=str(path).casefold():raise DomainError('office_wrong_document')
            document.Content.Copy()
        else:
            document=app.Presentations.Open(str(path),-1,0,0)
            if str(document.FullName).casefold()!=str(path).casefold():raise DomainError('office_wrong_document')
            if document.Slides.Count!=1:raise DomainError('office_fragment_single_slide_required')
            shapes=document.Slides.Item(1).Shapes
            if not shapes.Count:raise DomainError('office_fragment_empty')
            shapes.Range().Copy()
        return app,document
    except Exception:
        if document is not None:_close_document(document,kind,path)
        raise
    finally:app.AutomationSecurity=security


def _close_document(document,kind,path):
    # COM may reuse an application. Never claim ownership of it or call Quit.
    try:
        if str(document.FullName).casefold()==str(path).casefold():
            document.Close(False) if kind=='word' else document.Close()
    except Exception:pass


def _worker():
    import pythoncom
    import queue
    pythoncom.CoInitialize()
    current=None
    try:
        while True:
            pythoncom.PumpWaitingMessages()
            try:path,kind,future=_requests.get(timeout=.1)
            except queue.Empty:
                if current and time.time()>current[4]:
                    _close_document(current[1],current[2],current[3]);current=None
                continue
            try:
                if path is None:
                    if current:_close_document(current[1],current[2],current[3]);current=None
                    future.set_result(True);continue
                count=check(path,kind)
                app,document=_copy_owned(path,kind)
                if current:_close_document(current[1],current[2],current[3])
                expires=time.time()+600
                current=(app,document,kind,path,expires)
                future.set_result({'copied':True,'target':kind,'native_equations':count,'source_available_seconds':600})
            except Exception as exc:future.set_exception(exc)
    finally:
        if current:_close_document(current[1],current[2],current[3])
        pythoncom.CoUninitialize()


import queue
import threading
from concurrent.futures import Future
_requests=queue.Queue()
_thread=None
_start_lock=threading.Lock()


def copy(path,kind):
    if os.name!='nt':raise DomainError('office_windows_required')
    global _thread
    with _start_lock:
        if _thread is None or not _thread.is_alive():
            _thread=threading.Thread(target=_worker,name='kw-office-clipboard',daemon=True);_thread.start()
    future=Future();_requests.put((path.resolve(),kind,future))
    return future.result(timeout=30)


def release_owned_sources():
    if _thread is not None and _thread.is_alive():
        future=Future();_requests.put((None,None,future));future.result(timeout=10)
def effective_office_xml(data):
    """Resolve mutually exclusive Office compatibility representations once."""
    import io,xml.etree.ElementTree as ET
    prefixes=dict(value for event,value in ET.iterparse(io.BytesIO(data),events=('start-ns',)))
    supported={
        'http://schemas.microsoft.com/office/drawing/2010/main',
        'http://schemas.microsoft.com/office/powerpoint/2010/main',
        'http://schemas.microsoft.com/office/powerpoint/2012/main',
        'http://schemas.microsoft.com/office/word/2010/wordml',
        'http://schemas.openxmlformats.org/officeDocument/2006/math',
    }
    root=ET.fromstring(data);mc='{http://schemas.openxmlformats.org/markup-compatibility/2006}'
    def resolve(parent):
        for child in list(parent):
            if child.tag!=mc+'AlternateContent':resolve(child);continue
            branch=next((choice for choice in child.findall(mc+'Choice') if choice.get('Requires') and all(prefixes.get(prefix) in supported for prefix in choice.get('Requires').split())),None)
            if branch is None:branch=child.find(mc+'Fallback')
            if branch is None:raise DomainError('office_fragment_invalid')
            resolve(branch);index=list(parent).index(child)
            for offset,node in enumerate(list(branch)):parent.insert(index+offset,node)
            parent.remove(child)
    resolve(root);return root
