"""Readable output folders with persistent aliases for immutable job references.

All directory creation/migration runs in the application's single writer. The
small alias index is published before a rename; reads fall back to the original
folder until that rename completes, including after an interrupted migration.
"""
import json
import os
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath

from .safety import DomainError, atomic_json, contained, io_path


LABELS = {
    'discover_papers': '论文检索', 'paper_relationships': '论文星图',
    'import_graph_papers': '论文导入', 'refresh_graph_citations': '更新引用次数',
    'read_resources': '资料解读', 'compare_resources': '方法比较',
    'build_knowledge': '构建知识库', 'update_knowledge': '更新知识库',
    'verify_paper_metadata': '核验论文信息',
    'replicate_paper_figure': '论文图复刻_PPT',
    'proposal_word': '科研方案_Word', 'proposal_ppt': '科研方案_PPT',
}
LABELS_EN = {
    'discover_papers': 'Paper Search', 'paper_relationships': 'Paper Star Map',
    'import_graph_papers': 'Paper Import', 'refresh_graph_citations': 'Citation Update',
    'read_resources': 'Resource Analysis', 'compare_resources': 'Method Comparison',
    'build_knowledge': 'Knowledge Build', 'update_knowledge': 'Knowledge Update',
    'verify_paper_metadata': 'Paper Metadata Verification',
    'replicate_paper_figure': 'Paper Figure_PPT',
    'proposal_word': 'Research Proposal_Word', 'proposal_ppt': 'Research Proposal_PPT',
}
# Protocol filenames remain stable; human deliverables and saved copies are localized.
ARTIFACT_NAMES = {
    'fragment.docx': ('正文与公式.docx', 'Text and Equations.docx'),
    'fragment.pptx': ('正文与公式.pptx', 'Text and Equations.pptx'),
    'reconstructed-figure.pptx': ('论文图复刻.pptx', 'Reconstructed Paper Figure.pptx'),
    'research-statement.docx': ('科研方案.docx', 'Research Proposal.docx'),
    'proposal-explainer.pptx': ('科研方案.pptx', 'Research Proposal.pptx'),
    'report.md': ('资料解读.md', 'Resource Analysis.md'),
    'paper-graph.json': ('论文星图.json', 'Paper Star Map.json'),
    'discovery.json': ('论文检索结果.json', 'Paper Search Results.json'),
    'result.json': ('成果清单.json', 'Results Manifest.json'),
    'citation-audit.json': ('引文核验.json', 'Citation Audit.json'),
    'source-region.png': ('来源选区.png', 'Source Region.png'),
    'figure-source.png': ('来源论文图.png', 'Source Figure.png'),
    'preview.pdf': ('成果预览.pdf', 'Output Preview.pdf'),
}
BEIJING = timezone(timedelta(hours=8))
DESCRIPTION = '成果说明.txt'


def locale(context):
    return 'en' if context.get('ui_locale') == 'en' else 'zh'


def deliverable_name(name, language):
    for original, variants in ARTIFACT_NAMES.items():
        if name in (original, *variants):
            return variants[language == 'en']
    return name


def output_filenames(language):
    return {name: deliverable_name(name, language) for name in ARTIFACT_NAMES}


def download_name(name, language, task, sha256):
    localized = deliverable_name(name, language)
    if localized != name or any(name in variants for variants in ARTIFACT_NAMES.values()):
        return localized
    preview = re.fullmatch(r'(?:preview-|预览-|Preview-)([1-9][0-9]*)\.png', name)
    if preview:
        return ('Preview-' if language == 'en' else '预览-') + preview[1] + '.png'
    # Unknown agent-generated names get a localized, collision-resistant save name.
    return task_label(task, {'ui_locale': language}) + '-' + sha256[:8] + Path(name).suffix


def clean_part(value, limit=38):
    text = unicodedata.normalize('NFC', str(value or ''))
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip(' ._')
    # UTF-16 units bound Windows/Office paths, including supplementary symbols.
    result = ''; units = 0
    for char in text:
        units += 2 if ord(char) > 0xffff else 1
        if units > limit:
            break
        result += char
    return result.rstrip(' ._')


def task_label(task, context):
    en = locale(context) == 'en'
    if task == 'copy_office_selection':
        target = context.get('office_selection', {}).get('target', 'word')
        return ('Text and Equations_' if en else '正文公式_') + ('PPT' if target == 'powerpoint' else 'Word')
    return (LABELS_EN if en else LABELS).get(task, 'Research Task' if en else '科研任务')


def topic(context):
    value = (context.get('proposal', {}).get('title')
             or context.get('knowledge_base_name')
             or context.get('scope', {}).get('kb_name')
             or context.get('literature_search', {}).get('query')
             or context.get('query'))
    if not value:
        resources = context.get('resources', [])
        value = resources[0].get('title') if resources else None
        if value:
            short = re.split(r'[:：]', value, maxsplit=1)[0].strip()
            if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9+_. -]{1,23}', short):
                value = short
            if len(resources) > 1:
                value += (' and '+str(len(resources))+' resources' if locale(context)=='en' else '等' + str(len(resources)) + '份资料')
    value = clean_part(value)
    if locale(context) == 'en' and re.search(r'[\u3400-\u9fff]', value):
        return 'Selected Topic'
    return value or ('Unspecified Topic' if locale(context)=='en' else '未指定主题')


def directory_name(job_id, task, context, created_at):
    parts = [task_label(task, context), topic(context)]
    selection = context.get('figure_selection') or context.get('office_selection') or {}
    page = selection.get('page_index')
    if isinstance(page, int) and not isinstance(page, bool) and page >= 0:
        parts.append(('Page ' + str(page + 1)) if locale(context)=='en' else '第' + str(page + 1) + '页')
    try:
        moment = datetime.fromisoformat(str(created_at).replace('Z', '+00:00'))
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=BEIJING)
        parts.append(moment.astimezone(BEIJING).strftime('%Y-%m-%d_%H%M%S'))
    except ValueError:
        parts.append('Time Unavailable' if locale(context)=='en' else '时间未记录')
    return '_'.join(parts)


def _index_path(project):
    return contained(project, '.knowledge/output-directories.json', False)


def _valid_name(name):
    return (isinstance(name, str) and name not in {'', '.', '..'}
            and not re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
            and not name.endswith((' ', '.')))


def _load_index(project):
    file = _index_path(project)
    data = json.loads(file.read_text('utf-8')) if file.exists() else {'schema_version': 1, 'jobs': {}}
    if data.get('schema_version') != 1 or not isinstance(data.get('jobs'), dict):
        raise DomainError('invalid_output_directory_index')
    for job_id, entry in data['jobs'].items():
        if (not re.fullmatch(r'j_[A-Za-z0-9-]+', job_id) or not isinstance(entry, dict)
                or not _valid_name(entry.get('directory'))):
            raise DomainError('invalid_output_directory_index')
    return data


def resolve_alias(project, value):
    """Called after layout prefix mapping; never changes frozen JSON strings."""
    parts = value.split('/')
    if len(parts) < 2 or parts[0] != 'outputs':
        return value
    if any(part in {'.', '..'} for part in parts):
        raise DomainError('path_outside_scope')
    if not parts[1].startswith('j_'):
        return value
    entry = _load_index(project)['jobs'].get(parts[1])
    if not entry:
        return value
    target = Path(project) / 'outputs' / entry['directory']
    original = Path(project) / 'outputs' / parts[1]
    if not target.exists() and original.exists():
        return value
    return '/'.join(['outputs', entry['directory'], *parts[2:]])


def _unique_name(root, index, name):
    occupied = {entry['directory'].casefold() for entry in index['jobs'].values()}
    occupied.update(child.name.casefold() for child in root.iterdir())
    candidate = name; number = 2
    while candidate.casefold() in occupied:
        candidate = name + '_' + str(number)
        number += 1
    return candidate


def create_output(project, job_id, task, context, created_at):
    root = contained(project, 'outputs', False)
    root.mkdir(parents=True, exist_ok=True)
    index = _load_index(project)
    if job_id in index['jobs'] or not re.fullmatch(r'j_[A-Za-z0-9-]+', job_id):
        raise DomainError('output_directory_conflict')
    name = _unique_name(root, index, directory_name(job_id, task, context, created_at))
    output = contained(project, 'outputs/' + name, False)
    output.mkdir(exist_ok=False)
    index['jobs'][job_id] = {'directory': name}
    try:
        atomic_json(_index_path(project), index)
    except Exception:
        output.rmdir()  # Only the empty directory just created by this operation.
        raise
    return output


def describe(project, job, output):
    context = job['context']
    en = locale(context) == 'en'
    file = contained(project, (output / ('Output description.txt' if en else DESCRIPTION)).relative_to(project).as_posix(), False)
    if file.exists():
        return
    lines = ['任务：' + task_label(job['task'], context), '主题：' + topic(context)]
    for resource in context.get('resources', []):
        lines.append('来源资料：' + str(resource.get('title', '')))
    selection = context.get('figure_selection') or context.get('office_selection') or {}
    if isinstance(selection.get('page_index'), int):
        lines.append('来源页码：第' + str(selection['page_index'] + 1) + '页')
    lines.append('任务创建时间：' + str(job.get('created_at', '未记录')))
    descriptions = {'.pptx': '可编辑 PowerPoint 成果', '.docx': '可编辑 Word 成果',
                    '.png': '图片或成果预览', '.pdf': 'PDF 文档', '.md': '文字成果',
                    '.json': '核验或数据清单'}
    known_files = {'reconstructed-figure.pptx': '复刻的可编辑论文图（PowerPoint）',
                   'fragment.docx': '识别的正文与可编辑公式（Word）',
                   'fragment.pptx': '识别的正文与可编辑公式（PowerPoint）',
                   'paper-graph.json': '论文星图及来源信息', 'discovery.json': '论文检索结果',
                   'result.json': '成果校验清单', 'citation-audit.json': '引文来源核验'}
    artifacts = (job.get('result') or {}).get('artifacts', [])
    if artifacts:
        lines.append('\n已登记成果：')
        for artifact in artifacts:
            name = PurePosixPath(artifact['path'].replace('\\', '/')).name
            lines.append('- ' + name + '：' + known_files.get(name, descriptions.get(Path(name).suffix.lower(), '任务成果')))
    else:
        lines.extend(['\n成果文件类型：', '.docx 为可编辑 Word 文档；.pptx 为可编辑 PowerPoint；',
                      '.png 为图片或预览；.md 为文字成果；.json 为数据或核验清单。'])
    lines.extend(['\n其余文件用于来源核验、制作过程和审查。',
                  '在知序“智能体任务”中展开“任务结果”，可查看已登记成果。',
                  '\n内部任务编号：' + job['id'],
                  '程序读取任务编号应使用 context.job_id，不能从目录名推导。'])
    if en:
        lines = ['Task: '+task_label(job['task'],context), 'Topic: '+topic(context)]
        lines.extend('Source: '+str(r.get('title','')) for r in context.get('resources',[]))
        if isinstance(selection.get('page_index'),int):lines.append('Source page: '+str(selection['page_index']+1))
        lines.append('Created: '+str(job.get('created_at','Unavailable')))
        lines.append('\nRegistered outputs:' if artifacts else '\nOutput formats: DOCX (Word), PPTX (PowerPoint), PNG (preview), PDF, Markdown and JSON.')
        lines.extend('- '+PurePosixPath(a['path']).name for a in artifacts)
        lines.extend(['\nOther files record source verification, production and review.',
                      'Open Task results in Knowline to view registered outputs.',
                      '\nInternal task ID: '+job['id'], 'Read context.job_id; do not infer the task ID from the folder name.'])
    temporary = file.with_name(file.name + '.tmp')
    with temporary.open('w', encoding='utf-8-sig') as stream:
        stream.write('\n'.join(lines) + '\n')
        stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary, file)


def migrate(store):
    """Rename owned, inactive task folders only; hashes and records stay frozen."""
    root = contained(store.project, 'outputs', False)
    root.mkdir(parents=True, exist_ok=True)
    index = _load_index(store.project)
    moves = []; jobs = []; deferred = []; missing = []
    for row in store.rows('SELECT id FROM jobs ORDER BY created_at,id'):
        job = store.job(row['id'])
        if job['status'] in {'queued', 'running'}:
            deferred.append(job['id']); continue
        current = contained(store.project, job['context']['output_dir'], False)
        if current.parent != root:
            raise DomainError('path_outside_scope')
        if not current.is_dir():
            missing.append(job['id']); continue
        if current.name == job['id']:
            entry = index['jobs'].get(job['id'])
            name = entry['directory'] if entry else _unique_name(root, index, directory_name(job['id'], job['task'], job['context'], job['created_at']))
            target = contained(store.project, 'outputs/' + name, False)
            if target.exists():
                raise DomainError('output_directory_conflict')
            # Validate the complete owned tree before any move; no link traversal.
            for child in current.rglob('*'):
                contained(store.project, child.relative_to(store.project).as_posix())
            index['jobs'][job['id']] = {'directory': name}
            moves.append((current, target, job['id']))
            current = target
        else:
            old = root / job['id']
            if old.exists():
                raise DomainError('output_directory_conflict')
            index['jobs'][job['id']] = {'directory': current.name}
        jobs.append((job, current))
    if jobs:
        atomic_json(_index_path(store.project), index)
    for source, target, job_id in moves:
        # Recheck absolute scope and destination immediately before atomic rename.
        if source.resolve().parent != root.resolve() or target.resolve().parent != root.resolve() or target.exists():
            raise DomainError('output_directory_conflict')
        os.rename(io_path(source), io_path(target))
    for job, output in jobs:
        describe(store.project, job, output)
    return {'renamed': [{'job_id': job_id, 'directory': target.name} for _, target, job_id in moves],
            'readable_directories': len(jobs), 'deferred_active_jobs': deferred,
            'missing_output_jobs': missing, 'frozen_records_changed': False,
            'artifact_bytes_changed': False}
