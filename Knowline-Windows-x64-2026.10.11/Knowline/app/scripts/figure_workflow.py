"""Bounded figure review and hash-preserving publication through the local service.

No COM client, model-generated validators, database writes or automatic ingestion.
Visual/source review remains an explicit human/model assertion, bound to the PNG.
"""
import argparse
from datetime import datetime
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
import urllib.error
import urllib.request
import zipfile

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from backend.layout import project_root, data_path
from backend.safety import atomic_json, contained, digest, DomainError
from backend.office_clipboard import effective_office_xml, check
from backend.document_quality import inspect

P = '{http://schemas.openxmlformats.org/presentationml/2006/main}'
M = '{http://schemas.openxmlformats.org/officeDocument/2006/math}'
VISUAL_CHECKS = ('source_fidelity', 'text_and_formulas', 'connections_and_arrows',
                 'colors_and_layers', 'visible_layout')
VERSION = 1


def engine_sha():
    files = [Path(__file__), APP / 'backend/office_clipboard.py',
             APP / 'backend/document_quality.py', APP / 'backend/office_native.py',
             APP / 'scripts/native-office/audit_powerpoint_native.ps1',
             APP / 'scripts/native-office/insert_powerpoint_office.ps1']
    return hashlib.sha256(''.join(digest(path) for path in files).encode()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text('utf-8-sig'))


def require(condition, code):
    if not condition:
        raise DomainError(code)


def structure(path):
    """Use the same compatibility branch and layout checks as result ingestion."""
    formulas = check(path, 'powerpoint')
    layout = inspect(path, 'powerpoint')
    issues = list(layout['issues'])
    with zipfile.ZipFile(path) as package:
        slides = [n for n in package.namelist()
                  if n.startswith('ppt/slides/slide') and n.endswith('.xml')]
        editable = pictures = 0
        for name in slides:
            root = effective_office_xml(package.read(name))
            ids = [node.get('id') for node in root.iter(P + 'cNvPr')]
            if len(ids) != len(set(ids)):
                issues.append('duplicate_shape_id')
            editable += len(list(root.iter(P + 'sp'))) + len(list(root.iter(P + 'cxnSp')))
            pictures += len(list(root.iter(P + 'pic')))
        if len(slides) != 1:
            issues.append('single_slide_required')
        if editable < 2:
            issues.append('editable_objects_missing')
    return dict(ok=not issues, issues=list(dict.fromkeys(issues)), editable_objects=editable,
                picture_objects=pictures, native_formula_count=formulas, layout=layout)


class Workflow:
    def __init__(self, project, context_path):
        self.project = Path(project).resolve()
        self.context_path = contained(self.project, context_path)
        self.context = read(self.context_path)
        require(self.context.get('task') == 'replicate_paper_figure', 'figure_task_required')
        self.job_id = self.context['job_id']
        self.output = contained(self.project, self.context['output_dir'])
        selection = self.context['figure_selection']
        self.target = self.owned(selection['target_pptx'], exists=False)
        require(self.target.suffix.lower() == '.pptx', 'figure_target_pptx_required')
        self.working = self.target.with_name(self.target.stem + '.working.pptx')
        self.source = contained(self.project, selection['image']['path'])
        require(digest(self.source) == selection['image']['sha256'], 'artifact_hash_mismatch')
        self.state_path = self.output / 'figure-workflow-state.json'
        self.context_sha = digest(self.context_path)
        self.state = (read(self.state_path) if self.state_path.exists() else
                      dict(version=VERSION, job_id=self.job_id, context_sha256=self.context_sha,
                           rounds=[], native_calls=0))
        require(self.state.get('version') == VERSION and self.state.get('job_id') == self.job_id
                and self.state.get('context_sha256') == self.context_sha, 'figure_state_scope_mismatch')
        config = read(data_path(self.project, '.knowledge/config.json'))
        self.base = 'http://127.0.0.1:' + str(int(config['port'])) + '/api/v1'

    def owned(self, path, exists=True):
        path = contained(self.project, path, exists)
        return contained(self.output, path, exists)

    def relative(self, path):
        return Path(path).relative_to(self.project).as_posix()

    def request(self, path, body=None):
        headers = {'Content-Type': 'application/json'}
        if body is not None:
            headers['X-KW-Token'] = self.request('/session')['token']
        request = urllib.request.Request(self.base + path,
                  json.dumps(body).encode('utf-8') if body is not None else None, headers)
        # Local reads are short; native operations retain the server's 100 s guard.
        try:
            with urllib.request.urlopen(request, timeout=120 if body is not None else 15) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            error = json.load(exc)
            raise DomainError(error.get('code', 'figure_service_failed'),exc.code,
                              **error.get('params',{})) from None
        except (urllib.error.URLError, TimeoutError):
            raise DomainError('figure_service_unavailable') from None

    def live(self):
        job = self.request('/jobs/' + self.job_id)
        require(job.get('id') == self.job_id and job.get('status') in {'running', 'failed', 'partial'},
                'figure_job_not_active')
        require(job.get('context') == self.context, 'figure_live_scope_mismatch')
        started = (job.get('execution') or {}).get('started_at')
        if started:
            self.state['execution_started_at'] = started
        return job

    def save(self, stage, blockers=None):
        atomic_json(self.state_path, self.state)
        stage_path = self.output / 'stage-result.json'
        progress = read(stage_path) if stage_path.exists() else {}
        require(progress.get('job_id', self.job_id) == self.job_id, 'figure_state_scope_mismatch')
        progress.update(job_id=self.job_id, stage=stage, review_round=len(self.state['rounds']),
                        native_calls=self.state['native_calls'], updated_at=time.time(),
                        blockers=[{'code': code} for code in (blockers or [])])
        if self.state.get('execution_started_at'):
            started=datetime.fromisoformat(self.state['execution_started_at']).timestamp()
            progress['elapsed_task_seconds']=round(max(0,time.time()-started),3)
            progress['timing_basis']='agent execution start; includes image recognition and plan writing'
        atomic_json(stage_path, progress)

    def evidence(self, quote):
        selection = self.context['figure_selection']
        source = self.context['resources'][0]
        require(isinstance(quote, str) and 0 < len(quote) <= 8000, 'figure_quote_required')
        evidence_path = self.output / 'source-page-evidence.json'
        page_path = self.output / 'figure-source-page.json'
        if page_path.exists():
            cached = read(page_path)
            if cached.get('context_sha256') == self.context_sha:
                page = cached['page']
            else:
                page = None
        else:
            page = None
        if page is None:
            page = self.request('/resources/' + source['resource_id'] + '/page/' +
                                str(selection['page_index']) + '?version=' + source['version_id'])
            require(page.get('version_id') == source['version_id'], 'figure_evidence_version_mismatch')
            # Keep only the exact text used by ingestion, not the large page image/geometry.
            page = {'text': page['text'], 'version_id': page['version_id']}
            atomic_json(page_path, dict(context_sha256=self.context_sha, page=page))
        require(' '.join(quote.split()) in ' '.join(page['text'].split()), 'quote_not_found')
        evidence = dict(resource_id=source['resource_id'], version_id=source['version_id'],
                        page_index=selection['page_index'], quote=quote)
        atomic_json(evidence_path, evidence)
        return evidence

    def audit(self, manifest_path):
        self.live()
        manifest_path = self.owned(manifest_path)
        manifest = read(manifest_path)
        require(manifest.get('delivery_gate') is True and manifest.get('require_full_registry') is True
                and isinstance(manifest.get('objects'), list) and manifest['objects']
                and isinstance(manifest.get('expected_formula_count'), int)
                and isinstance(manifest.get('expected_axis_constraint_count'), int),
                'figure_full_audit_manifest_required')
        presentation = self.owned(self.working)
        inputs = dict(presentation_sha256=digest(presentation), manifest_sha256=digest(manifest_path),
                      source_image_sha256=digest(self.source), workflow_sha256=engine_sha())
        key = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
        rounds = self.state['rounds']
        # Only the current round can be reused. Reverting content does not reset the limit.
        if rounds and rounds[-1]['key'] == key:
            record = rounds[-1]
            if record.get('ok'):
                self.verify_record(record)
                return dict(record, reused=True)
            raise DomainError(record.get('error', 'figure_unchanged_audit_failed'))
        require(len(rounds) < 2, 'figure_review_limit_reached')
        require(not (self.output / 'result.json').exists(), 'figure_result_already_published')
        record = dict(inputs, key=key, round=len(rounds) + 1, ok=False,
                      manifest_path=self.relative(manifest_path))
        rounds.append(record)
        self.save('合并审查：结构、原生对象与预览')
        try:
            report = structure(presentation)
            record['structure'] = report
            require(report['ok'], 'figure_structure_invalid')
            self.state['native_calls'] += 1
            self.save('原生打开与渲染；同一文件只执行一次')
            native = self.request('/jobs/' + self.job_id + '/office-native',
                     dict(operation='audit', presentation=self.relative(presentation),
                          manifest=self.relative(manifest_path)))
            require(digest(presentation) == inputs['presentation_sha256']
                    and digest(manifest_path) == inputs['manifest_sha256'], 'figure_audit_input_changed')
            require(native.get('report', {}).get('ok') is True, 'figure_native_audit_failed')
            require(native.get('presentation') == self.relative(presentation), 'figure_native_path_mismatch')
            preview = self.owned(native['preview_path'])
            audit = self.owned(native['audit_path'])
            require(preview.read_bytes()[:8] == b'\x89PNG\r\n\x1a\n', 'figure_preview_invalid')
            require(read(audit).get('ok') is True, 'figure_native_audit_failed')
            record.update(ok=True, preview_path=self.relative(preview), preview_sha256=digest(preview),
                          audit_path=self.relative(audit), audit_sha256=digest(audit))
            self.save('查看同一预览，合并记录全部视觉问题；通过即定稿')
            return dict(record, reused=False)
        except Exception as exc:
            record['error'] = getattr(exc, 'code', 'figure_native_operation_failed')
            record['failure_detail'] = getattr(exc, 'params', {})
            self.save('检查未通过；汇总问题后最多集中修正一次', [record['error']])
            raise

    def verify_record(self, record):
        require(record.get('ok'), 'figure_successful_audit_required')
        for path, expected in ((self.working, record['presentation_sha256']),
                               (self.owned(record['manifest_path']), record['manifest_sha256']),
                               (self.owned(record['preview_path']), record['preview_sha256']),
                               (self.owned(record['audit_path']), record['audit_sha256']),
                               (self.source, record['source_image_sha256'])):
            require(path.is_file() and digest(path) == expected, 'figure_review_stale')
        require(record['workflow_sha256'] == engine_sha(), 'figure_review_stale')

    def finish(self, review_path):
        job = self.live()
        require(self.state['rounds'], 'figure_successful_audit_required')
        record = self.state['rounds'][-1]
        self.verify_record(record)
        review_path = self.owned(review_path)
        review = read(review_path)
        require(review.get('presentation_sha256') == record['presentation_sha256']
                and review.get('preview_sha256') == record['preview_sha256'], 'figure_review_stale')
        require(review.get('review_status') in {'passed', 'passed_with_notes'}, 'figure_visual_review_required')
        checks = review.get('checks', {})
        require(all(checks.get(name) is True for name in VISUAL_CHECKS), 'figure_visual_review_incomplete')
        require(review.get('blockers') == [], 'figure_visual_blockers_remaining')
        require(isinstance(review.get('notes'), list) and review['notes']
                and all(isinstance(note, str) and note.strip() for note in review['notes']),
                'figure_review_notes_required')
        evidence = self.evidence(review.get('quote'))
        job = self.live()
        registered = {contained(self.project, a['path']) for a in (job.get('result') or {}).get('artifacts', [])}
        require(not self.target.exists() or digest(self.target) == record['presentation_sha256']
                or self.target not in registered, 'figure_registered_target_changed')
        # Publication preserves exact bytes. Native evidence remains at its truthful
        # working-file path; the final audit records both paths and identical hashes.
        if not self.target.exists() or digest(self.target) != record['presentation_sha256']:
            staging = self.target.with_name(self.target.name + '.publishing')
            self.owned(staging, exists=False)
            shutil.copyfile(self.working, staging)
            require(digest(staging) == record['presentation_sha256'], 'artifact_hash_mismatch')
            os.replace(staging, self.target)
        require(digest(self.target) == record['presentation_sha256'], 'artifact_hash_mismatch')
        self.verify_record(record)
        audit_path = self.output / 'figure-review.json'
        audit = dict(source_image_sha256=record['source_image_sha256'],
                     presentation_sha256=record['presentation_sha256'],
                     preview_sha256=record['preview_sha256'],
                     editable_objects=record['structure']['editable_objects'],
                     picture_objects=record['structure']['picture_objects'],
                     native_formula_count=record['structure']['native_formula_count'],
                     review_status=review['review_status'], review_round=record['round'],
                     native_audit_path=record['audit_path'], native_audit_sha256=record['audit_sha256'],
                     audited_presentation=self.relative(self.working),
                     delivered_presentation=self.relative(self.target),
                     publication_method='byte_identical_copy', checks=checks, notes=review['notes'],
                     structure=record['structure'])
        atomic_json(audit_path, audit)
        artifacts = [self.target, self.owned(record['preview_path']), audit_path,
                     self.owned(record['audit_path']), review_path, self.output / 'source-page-evidence.json']
        result = dict(schema_version=2, job_id=self.job_id, status='completed', partial=False,
                      artifacts=[dict(path=self.relative(p), sha256=digest(p)) for p in artifacts],
                      claims=[dict(text=evidence['quote'], evidence=[evidence])], proposed_relations=[],
                      warnings=review['notes'] if review['review_status'] == 'passed_with_notes' else [],
                      figure_replica=dict(source_image_sha256=record['source_image_sha256'],
                          pptx_path=self.relative(self.target), preview_path=record['preview_path'],
                          audit_path=self.relative(audit_path)),
                      layout_review=dict(review_status=review['review_status'],
                          preview_paths=[record['preview_path']], notes=review['notes']))
        atomic_json(self.output / 'result.json', result)
        self.save('成果清单已生成，等待任务桥验收')
        return dict(ok=True, manifest=str(self.output / 'result.json'), review_round=record['round'],
                    native_calls=self.state['native_calls'], repeated_final_render=False)


@contextmanager
def task_lock(path):
    # An OS lock releases on crashes; no stale lock-file deletion or round resets.
    with open(path, 'a+b') as stream:
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['evidence', 'audit', 'finish'])
    parser.add_argument('context')
    parser.add_argument('--manifest')
    parser.add_argument('--review')
    parser.add_argument('--quote')
    args = parser.parse_args()
    project = project_root(APP)
    workflow = Workflow(project, args.context)
    with task_lock(workflow.output / 'figure-workflow.lock'):
        workflow = Workflow(project, args.context)
        try:
            if args.action == 'audit':
                require(bool(args.manifest), 'figure_audit_manifest_required')
                value = workflow.audit(args.manifest)
            elif args.action == 'finish':
                require(bool(args.review), 'figure_visual_review_required')
                value = workflow.finish(args.review)
            else:
                workflow.live()
                value = workflow.evidence(args.quote)
            print(json.dumps(value, ensure_ascii=False))
            return 0
        except DomainError as exc:
            workflow.save('流程停止：' + exc.code, [exc.code])
            print(json.dumps(dict(ok=False, code=exc.code, params=exc.params), ensure_ascii=False))
            return 1


if __name__ == '__main__':
    sys.exit(main())
