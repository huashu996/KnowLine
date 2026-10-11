"""Render already authored knowledge into deliverables without repeated model serialization.

Usage: python software/scripts/knowledge_finalize.py context.json analysis.json
analysis contains knowledge_cards, knowledge_build_report, optional knowledge_relations.
No generation, evidence fabrication, service/DB writes, or evaluation bypass.
"""
import hashlib,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.safety import contained

def finalize(context_path,analysis_path):
    context=json.loads(Path(context_path).read_text('utf-8-sig'))
    project=Path(context['project_root']).resolve() if 'project_root' in context else None
    if project is None:
        current=Path(context_path).resolve()
        project=next((p for p in current.parents if (p/'project-layout.json').is_file()),None)
        if project is None:
            project=next((p for p in current.parents if any((p/name/'project-layout.json').is_file() for name in ['app','软件平台'])),None)
    if project is None:raise ValueError('project root unavailable')
    output=contained(project,context['output_dir'],False);output.relative_to(project)
    source=Path(analysis_path).resolve();source.relative_to(output)
    analysis=json.loads(source.read_text('utf-8-sig'))
    cards=analysis['knowledge_cards'];report=analysis['knowledge_build_report']
    if not cards or not isinstance(report,dict):raise ValueError('analysis required')
    artifacts=[]
    def artifact(path,kind):
        artifacts.append({'path':path.relative_to(project).as_posix(),'kind':kind,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    artifact(source,'knowledge_analysis')
    for index,layer in enumerate(context['knowledge_layers']):
        lines=['# '+layer['name'],'',layer['focus'],'']
        for card in cards:
            if card['layer_id']!=layer['id']:continue
            lines.extend(['## '+card['title'],'',card['content'],'','### 来源与关联',''])
            for e in card['evidence']:
                locator='PDF物理页 '+str(e['page_index']+1) if 'page_index' in e else str(e.get('file','来源描述'))
                lines.extend([f"- `{e['resource_id']}` / `{e['version_id']}` / {locator}",'> '+e['quote'].replace('\n',' '),''])
            if card.get('links'):lines.extend(['关联卡片：'+', '.join(card['links']),''])
        path=output/f'knowledge-layer-{index+1}.md';path.write_text('\n'.join(lines),encoding='utf-8');artifact(path,'knowledge_document')
    path=output/'knowledge-build-report.json';path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');artifact(path,'coverage_report')
    result={'schema_version':2,'job_id':context['job_id'],'status':'completed','artifacts':artifacts,'claims':[],
            'knowledge_cards':cards,'knowledge_build_report':report,'knowledge_relations':analysis.get('knowledge_relations',[]),
            'warnings':analysis.get('warnings',[]),'knowledge_artifact_contract':'single-authored-analysis-v3'}
    target=output/'result.json';target.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return {'result':str(target),'cards':len(cards),'layers':len(context['knowledge_layers']),'queries':len(report.get('queries',[])),
            'evidence':sum(len(c['evidence']) for c in cards),'artifacts':len(artifacts)}

if __name__=='__main__':print(json.dumps(finalize(*sys.argv[1:]),ensure_ascii=False))
