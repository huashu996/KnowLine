"""Render already authored knowledge into deliverables without repeated model serialization.

Usage: python software/scripts/knowledge_finalize.py context.json analysis.json
analysis contains knowledge_cards, knowledge_build_report, optional knowledge_relations.
No generation, evidence fabrication, service/DB writes, or evaluation bypass.
"""
import copy,hashlib,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.safety import contained

def expand_evidence(analysis):
    """Author each original locator once; the submitted contract stays explicit."""
    value=copy.deepcopy(analysis);catalog=value.pop('evidence_catalog',{})
    if not isinstance(catalog,dict):raise ValueError('evidence_catalog must be an object')
    def resolve(e):
        if isinstance(e,str):
            if e not in catalog:raise ValueError('unknown evidence reference: '+e)
            e=copy.deepcopy(catalog[e])
        if not isinstance(e,dict) or not {'resource_id','version_id','quote'}<=e.keys():raise ValueError('invalid evidence entry')
        return e
    def visit(obj):
        if isinstance(obj,dict):
            for name,item in obj.items():
                if name in {'evidence','expected_evidence'}:
                    if not isinstance(item,list):raise ValueError('evidence must be an array')
                    obj[name]=[resolve(e) for e in item]
                elif name=='execution_log':obj[name]=resolve(item)
                else:visit(item)
        elif isinstance(obj,list):
            for item in obj:visit(item)
    visit(value)
    from backend.research_contracts import normalize_analysis
    return normalize_analysis(value)

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
    analysis=expand_evidence(json.loads(source.read_text('utf-8-sig')))
    cards=analysis['knowledge_cards'];report=analysis['knowledge_build_report']
    if not cards or not isinstance(report,dict):raise ValueError('analysis required')
    artifacts=[]
    def artifact(path,kind):
        artifacts.append({'path':path.relative_to(project).as_posix(),'kind':kind,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    artifact(source,'knowledge_analysis')
    for index,layer in enumerate(context['knowledge_layers']):
        lines=['# '+layer['name'],'',layer['focus'],'']
        for card in cards:
            if layer['id'] not in card.get('layer_ids',[card['layer_id']]):continue
            lines.extend(['## '+card['title'],'',card['content'],''])
            if card.get('method_profile'):
                lines.extend(['### 方法前提、接口与失败条件',''])
                for name,field in card['method_profile'].items():
                    value='未核实' if field['status']=='unknown' else json.dumps(field['value'],ensure_ascii=False)
                    lines.append(f"- {name}: {value}（{field['status']}；主张：{', '.join(field['claim_ids']) or '无'}）")
                lines.append('')
            if card.get('claims'):
                lines.extend(['### 主张与核验状态',''])
                for claim in card['claims']:
                    lines.append(f"- [{claim['id']}] {claim['text']}（{claim['claim_type']}；{claim['verification']}）")
                    for e in claim['evidence']:
                        loc='PDF物理页 '+str(e['page_index']+1) if 'page_index' in e else str(e.get('file','来源描述'))
                        lines.append(f"  - {e['resource_id']} / {e['version_id']} / {loc}：{e['quote'].replace(chr(10),' ')}")
                lines.append('')
            lines.extend(['### 来源与关联',''])
            for e in card['evidence']:
                locator='PDF物理页 '+str(e['page_index']+1) if 'page_index' in e else str(e.get('file','来源描述'))
                lines.extend([f"- `{e['resource_id']}` / `{e['version_id']}` / {locator}",'> '+e['quote'].replace('\n',' '),''])
            if card.get('links'):lines.extend(['关联卡片：'+', '.join(card['links']),''])
        path=output/f'knowledge-layer-{index+1}.md';path.write_text('\n'.join(lines),encoding='utf-8');artifact(path,'knowledge_document')
    path=output/'knowledge-build-report.json';path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');artifact(path,'coverage_report')
    result={'schema_version':2,'job_id':context['job_id'],'status':'completed','artifacts':artifacts,'claims':[],
            'knowledge_cards':cards,'knowledge_build_report':report,'knowledge_relations':analysis.get('knowledge_relations',[]),
            'warnings':analysis.get('warnings',[]),'normalization_log':analysis.get('normalization_log',[]),'knowledge_artifact_contract':context.get('knowledge_build',{}).get('artifact_contract','single-authored-analysis-v3')}
    target=output/'result.json';target.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return {'result':str(target),'cards':len(cards),'layers':len(context['knowledge_layers']),'queries':len(report.get('queries',[])),
            'evidence':sum(len(c['evidence']) for c in cards),'artifacts':len(artifacts)}

if __name__=='__main__':print(json.dumps(finalize(*sys.argv[1:]),ensure_ascii=False))
