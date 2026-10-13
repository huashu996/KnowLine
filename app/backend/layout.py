"""Physical two-folder layout with explicit compatibility for historical logical paths."""
import json,hashlib
from pathlib import Path


def project_root(path):
    path=Path(path).resolve()
    if (path/'project-layout.json').is_file() and path.name in {'app','软件平台'}:return path.parent
    return path


def app_dir(project):
    project=project_root(project)
    for name in ['app','软件平台']:
        if (project/name/'project-layout.json').is_file():return project/name
    return project


def mapping(project):
    file=app_dir(project)/'project-layout.json'
    return json.loads(file.read_text('utf-8'))['path_mapping'] if file.is_file() else {}


def relative(project,path):
    project=project_root(project);value=str(path).replace('\\','/')
    candidate=Path(path)
    if candidate.is_absolute():
        try:value=candidate.relative_to(project).as_posix()
        except ValueError:
            file=app_dir(project)/'project-layout.json'
            legacy=json.loads(file.read_text('utf-8')).get('legacy_project_root') if file.is_file() else None
            if not legacy:return path
            try:value=candidate.relative_to(legacy).as_posix()
            except ValueError:return path
    for old,new in sorted(mapping(project).items(),key=lambda item:-len(item[0])):
        if value==old or value.startswith(old+'/'):
            value=new+value[len(old):]
            break
    from .output_names import resolve_alias
    return resolve_alias(project,value)


def data_path(project,name):
    return project_root(project)/relative(project,name)

def identity(project):
    project=project_root(project);file=data_path(project,'.knowledge/config.json')
    config=json.loads(file.read_text('utf-8')) if file.is_file() else {}
    marker=app_dir(project)/'project-layout.json'
    origin=json.loads(marker.read_text('utf-8')).get('legacy_project_root') if marker.is_file() else None
    return config.get('project_id') or hashlib.sha256(str(origin or project).encode()).hexdigest()[:16]
