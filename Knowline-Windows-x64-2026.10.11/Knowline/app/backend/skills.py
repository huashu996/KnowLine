"""Read-only inventory of trusted installed skill entrypoints; no execution."""
from pathlib import Path
import re
import yaml

TASK_SKILLS={'discover_papers':'knowline-import-papers','paper_relationships':'knowline-paper-relations','import_graph_papers':'knowline-import-papers'}

def require_task_skill(project,task):
    """Check the exact bundled entrypoint referenced by task instructions."""
    from .layout import app_dir
    from .safety import DomainError
    if task=='proposal_ppt':
        raise DomainError('task_retired',409,task=task)
    name=TASK_SKILLS.get(task)
    if name and not (app_dir(project)/'research-skills'/name/'SKILL.md').is_file():
        raise DomainError('trusted_skill_missing',409,skill=name)
    return name


def inventory(project):
    from .layout import app_dir
    roots=[app_dir(project)/'research-skills',Path(project)/'.agents/skills',Path.home()/'.codex/skills']
    entries=[]
    for root in roots:
        if not root.exists():continue
        for path in root.glob('*/SKILL.md'):
            if path.is_symlink() or path.parent.is_symlink():continue
            text=path.read_text('utf-8-sig',errors='replace')[:2000]
            try:
                frontmatter=yaml.safe_load(text.split('---',2)[1]) if text.startswith('---') else {}
                if not isinstance(frontmatter,dict):frontmatter={}
            except (yaml.YAMLError,IndexError):frontmatter={}
            entries.append({'name':frontmatter.get('name',path.parent.name),'description':str(frontmatter.get('description',''))[:1000], 'provider':'Local AI', 'trusted_root':str(root), 'path':str(path), 'execution':'project_local_agent', 'scope':'project' if root==app_dir(project)/'research-skills' else 'installed'})
    entries.append({'name':'knowledge-job','description':'Shared scope, snapshots and evidence adapter','provider':'Local AI','trusted_root':'adapters/knowledge-job','execution':'manual'})
    return entries
