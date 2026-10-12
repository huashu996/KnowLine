"""Scoped native Office steps run in the desktop service rather than model sandboxes."""
import json
import os
import subprocess
import threading
from pathlib import Path
from collections import OrderedDict
from .safety import DomainError, atomic_json, contained, digest
from .layout import app_dir
from .office_clipboard import check

_lock = threading.Lock()
_draft_hashes=OrderedDict()
_draft_hash_lock=threading.Lock()


def figure_drafts(store,job):
    """Expose an existing task-owned PPT without accepting its completion claim."""
    import zipfile
    if job.get('task')!='replicate_paper_figure' or job.get('status') not in {'failed','interrupted','partial'}:return []
    try:
        output=contained(store.project,job['context']['output_dir'])
        target=contained(store.project,job['context']['figure_selection']['target_pptx'],False)
        if not target.is_relative_to(output):return []
        registered={(a['path'],a.get('sha256')) for a in (job.get('result') or {}).get('artifacts',[])}
        candidates=[target,*output.glob('*.working.pptx')]
        candidates=sorted(set(candidates),key=lambda p:p.stat().st_mtime_ns if p.is_file() else 0,reverse=True)
        for candidate in candidates:
            if candidate.is_symlink() or not candidate.is_file() or not 0<candidate.stat().st_size<=128*1024*1024:continue
            file=contained(store.project,candidate)
            if not file.is_relative_to(output) or file.suffix.lower()!='.pptx':continue
            # Package identification is not an Office/render/layout acceptance.
            try:
                with zipfile.ZipFile(file) as package:
                    if '[Content_Types].xml' not in package.namelist() or 'ppt/presentation.xml' not in package.namelist():continue
            except (OSError,zipfile.BadZipFile):continue
            path=file.relative_to(store.project).as_posix();stat=file.stat()
            key=(str(file),stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns)
            with _draft_hash_lock:
                sha=_draft_hashes.get(key)
                if sha:_draft_hashes.move_to_end(key)
            if not sha:
                sha=digest(file)
                with _draft_hash_lock:
                    _draft_hashes[key]=sha
                    while len(_draft_hashes)>32:_draft_hashes.popitem(last=False)
            if (path,sha) in registered:continue
            return [{'path':path,'sha256':sha,'bytes':stat.st_size,'validation_status':'not_passed','is_draft':True}]
    except (DomainError,OSError,KeyError,ValueError):pass
    return []


def word_scope(store,job_id,body):
    job=store.job(job_id)
    if job['task']!='proposal_word' or job['status'] not in {'running','failed','partial'} or body.get('operation')!='render_word':
        raise DomainError('office_native_scope_invalid',409)
    output=contained(store.project,job['context']['output_dir'])
    target=contained(store.project,job['context']['proposal']['target_path'],False)
    supplied=contained(store.project,body.get('presentation',''),False)
    if target!=supplied or not target.is_relative_to(output) or not target.is_file() or target.suffix.lower()!='.docx':
        raise DomainError('office_native_scope_invalid',409)
    check(target,'word')
    return job,target,output


def render_word(store,job_id,body):
    """Read-only export of the frozen task's exact DOCX, never another open document."""
    import pythoncom
    import win32com.client
    from .pdf import open_pdf,fitz
    job,target,output=word_scope(store,job_id,body)
    with _lock:
        word_scope(store,job_id,body)
        before=digest(target);review=output/'native-word-review';review.mkdir(exist_ok=True)
        export=review/('.kw-render-'+job_id+'.pdf')
        document=application=None;pages=[]
        pythoncom.CoInitialize()
        try:
            application=win32com.client.DispatchEx('Word.Application')
            application.Visible=False;application.DisplayAlerts=0;application.AutomationSecurity=3
            document=application.Documents.Open(str(target),ConfirmConversions=False,ReadOnly=True,AddToRecentFiles=False,Visible=False)
            if Path(str(document.FullName)).resolve()!=target.resolve():raise DomainError('office_wrong_document')
            document.ExportAsFixedFormat(str(export),17,OpenAfterExport=False)
            document.Close(0);document=None
            with open_pdf(export) as pdf:
                if not 1<=len(pdf)<=150:raise DomainError('office_native_page_limit')
                for index,page in enumerate(pdf):
                    path=review/('page-'+str(index+1)+'.png')
                    scale=min(2,2400/max(page.rect.width,page.rect.height))
                    page.get_pixmap(matrix=fitz.Matrix(scale,scale),alpha=False).save(path)
                    pages.append({'path':path.relative_to(store.project).as_posix(),'sha256':digest(path)})
            if digest(target)!=before:raise DomainError('artifact_hash_mismatch')
            result={'operation':'render_word','document':target.relative_to(store.project).as_posix(),'document_sha256':before,'desktop_service_execution':True,'read_only':True,'page_count':len(pages),'previews':pages,'visual_review_required':True}
            atomic_json(review/'render-report.json',result)
            return result
        except DomainError:raise
        except Exception as exc:
            atomic_json(review/'render-failure.json',{'operation':'render_word','error_type':type(exc).__name__,'reason':'native_word_export_failed'})
            raise DomainError('office_word_render_unavailable',409)
        finally:
            if document is not None:
                try:document.Close(0)
                except Exception:pass
            if application is not None:
                try:
                    if application.Documents.Count==0:application.Quit(0)
                except Exception:pass
            pythoncom.CoUninitialize()
            if export.is_file():export.unlink()


def scope(store, job_id, body):
    job = store.job(job_id)
    if job['task'] != 'replicate_paper_figure' or job['status'] not in {'running', 'failed', 'partial'}:
        raise DomainError('office_native_scope_invalid', 409)
    selection = job['context'].get('figure_selection', {})
    output = contained(store.project, job['context']['output_dir'])
    target = contained(store.project, selection['target_pptx'], False)
    working = target.with_name(target.stem + '.working.pptx')
    presentation = contained(store.project, body.get('presentation', ''))
    operation = body.get('operation')
    if operation not in {'equations', 'audit'} or presentation not in {target, working}:
        raise DomainError('office_native_scope_invalid', 409)
    if operation == 'equations' and presentation != working:
        raise DomainError('office_native_working_copy_required', 409)
    manifest = contained(store.project, body.get('manifest', ''))
    for path in (presentation, manifest):
        if not path.is_relative_to(output) or not path.is_file():
            raise DomainError('office_native_scope_invalid', 409)
    image = contained(store.project, selection['image']['path'])
    if digest(image) != selection['image']['sha256']:
        raise DomainError('artifact_hash_mismatch')
    if manifest.suffix != '.json' or manifest.stat().st_size > 512 * 1024:
        raise DomainError('office_native_manifest_invalid')
    payload = json.loads(manifest.read_text('utf-8-sig'))
    if not isinstance(payload, dict):
        raise DomainError('office_native_manifest_invalid')
    check(presentation, 'powerpoint')
    if operation == 'equations':
        equations = payload.get('equations')
        if payload.get('mode') != 'Office' or not isinstance(equations, list) or not 1 <= len(equations) <= 100:
            raise DomainError('office_native_manifest_invalid')
        for item in equations:
            if not isinstance(item, dict) or not isinstance(item.get('native_linear'), str) or not 1 <= len(item['native_linear']) <= 4000:
                raise DomainError('office_native_manifest_invalid')
            placement = item.get('target', {})
            if placement.get('type') != 'powerpoint_shape' or placement.get('slide_index') != 1 or not isinstance(placement.get('shape_name'), str):
                raise DomainError('office_native_manifest_invalid')
            low, high = selection.get('font_size_range_pt', [10, 28])
            # The preview says source first; its 10–28 pt interval is a reference.
            # Faithful physical-size figures may legitimately contain smaller text.
            if selection.get('font_policy') == 'preserve_source_first':
                low, high = 1, 200
            if not isinstance(item.get('font_size'), (int, float)) or not low <= item['font_size'] <= high:
                raise DomainError('office_native_manifest_invalid')
            if not isinstance(item.get('id'), str) or not 1 <= len(item['id']) <= 120:
                raise DomainError('office_native_manifest_invalid')
    else:
        if payload.get('slide_index', 1) != 1 or payload.get('expected_slide_count', 1) != 1:
            raise DomainError('office_native_manifest_invalid')
        for field in ('render_width', 'render_height'):
            value = payload.get(field, 1920 if field == 'render_width' else 1080)
            if not isinstance(value, int) or not 320 <= value <= 4096:
                raise DomainError('office_native_manifest_invalid')
    return job, presentation, manifest, operation


def run(store, job_id, body):
    if os.name != 'nt':
        raise DomainError('office_windows_required')
    if body.get('operation')=='render_word':return render_word(store,job_id,body)
    job, presentation, manifest, operation = scope(store, job_id, body)
    scripts = app_dir(store.project) / 'scripts/native-office'
    script = scripts / ('run_office_pipeline.ps1' if operation == 'equations' else 'audit_powerpoint_native.ps1')
    shell = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    review = presentation.parent / ('native-working-review' if presentation.name.endswith('.working.pptx') else 'native-final-review')
    argv = [str(shell), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(script)]
    if operation == 'equations':
        argv += ['-ManifestPath', str(manifest), '-OutputPath', str(presentation)]
    else:
        argv += ['-PresentationPath', str(presentation), '-ManifestPath', str(manifest), '-OutputDirectory', str(review)]
    with _lock:
        scope(store, job_id, body)
        # Remove only our previous audit, so an unsuccessful process cannot reuse it.
        report_file = review / 'native-audit.json'
        if operation == 'audit' and report_file.is_file():
            report_file.unlink()
        try:
            completed = subprocess.run(argv, cwd=app_dir(store.project), stdin=subprocess.DEVNULL,
                                       capture_output=True, timeout=100, creationflags=subprocess.CREATE_NO_WINDOW)
        except subprocess.TimeoutExpired:
            raise DomainError('office_native_timeout', 409)
        diagnostic = presentation.parent / ('office-native-' + operation + '-process.json')
        atomic_json(diagnostic, {'operation': operation, 'returncode': completed.returncode,
                                'stdout': getattr(completed, 'stdout', b'').decode('utf-8', 'replace')[-8000:],
                                'stderr': getattr(completed, 'stderr', b'').decode('utf-8', 'replace')[-8000:]})
        report = json.loads(report_file.read_text('utf-8-sig')) if operation == 'audit' and report_file.is_file() else None
        if completed.returncode or (operation == 'audit' and not (report and report.get('ok'))):
            raise DomainError('office_native_failed', 409, reason='desktop_office_step_failed',
                              audit_path=report_file.relative_to(store.project).as_posix() if report else None,
                              diagnostic_path=diagnostic.relative_to(store.project).as_posix())
        native_equations = check(presentation, 'powerpoint')
        if operation == 'equations' and native_equations < len(json.loads(manifest.read_text('utf-8-sig'))['equations']):
            raise DomainError('office_native_equations_missing', 409)
        result = {'operation': operation, 'presentation': presentation.relative_to(store.project).as_posix(),
                  'native_equations': native_equations, 'desktop_service_execution': True}
        if report:
            result.update(audit_path=report_file.relative_to(store.project).as_posix(),
                          preview_path=(review / 'slide-1.png').relative_to(store.project).as_posix(), report=report)
        atomic_json(presentation.parent / ('office-native-' + operation + '.json'), result)
        return result
