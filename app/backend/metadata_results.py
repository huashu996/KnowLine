"""Expose one frozen batch with per-resource verification and version protection."""
import json

def unresolved_reason(metadata, missing):
    sources=metadata.get("field_sources",{})
    outcome=sources.get("metadata_status",{})
    basis=outcome.get("basis",{}) if isinstance(outcome,dict) else {}
    details=[]
    if isinstance(basis,dict):
        for key in ["failures","conflicts"]:
            for value in basis.get(key,[]) or []:
                details.append(value if isinstance(value,str) else json.dumps(value,ensure_ascii=False))
        if basis.get('missing_fields'):details.append('获取来源缺少字段：'+'、'.join(basis['missing_fields']))
    for key in missing:
        source=sources.get(key,{})
        if isinstance(source,dict) and source.get("reason"):details.append(str(source["reason"]))
    if not details and missing:details.append("缺少已核实字段："+"、".join(missing))
    return "；".join(dict.fromkeys(details)) or "尚无完整原始来源核验"

def summary(store, job):
    rows=[]
    for frozen in job['context']['resources']:
        resource=store.resource(frozen['resource_id'])
        metadata=resource['metadata']
        changed=resource['version_id']!=frozen['version_id']
        proven=all(isinstance(metadata.get('field_sources',{}).get(k),dict) and metadata['field_sources'][k].get('url') for k in ['title','authors','year','venue'])
        status='version_changed' if changed else 'verified' if metadata.get('metadata_status')=='verified' and proven else 'partial' if metadata.get('field_sources') else 'pending'
        missing=[k for k in ['authors','year','venue','doi'] if not metadata.get(k)]
        rows.append({'resource_id':resource['id'],'title':resource['title'],'status':status,'missing_fields':missing,'reason':'当前版本已变更，冻结结果不能覆盖新版本' if changed else unresolved_reason(metadata,missing) if status!='verified' else ''})
    return {'total':len(rows),'verified_count':sum(r['status']=='verified' for r in rows),'unresolved_count':sum(r['status']!='verified' for r in rows),'rows':rows}
