"""Original-source parents and bounded recall windows, separate from authored cards."""
import ast
import hashlib
import json
import re
from .safety import contained,digest,DomainError

VERSION='evidence-parents-v1'
def key(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:32]

def source_identity(resource):
    meta=resource.get('metadata',{})
    verified=meta.get('verified') or meta.get('verification_status')=='verified' or meta.get('metadata_status')=='verified'
    return 'doi:'+str(meta['doi']).strip().lower() if verified and meta.get('doi') else 'resource:'+resource['id']

def windows(text,limit=360):
    """Prefer paragraph/sentence ends; all characters remain in the stored parent.

    Long equations/functions may span recall windows. Consumers receive the full
    parent and locator, not an isolated window masquerading as complete context.
    """
    start=0
    while start<len(text):
        end=min(start+limit,len(text))
        if end<len(text):
            candidates=[m.end()+start for m in re.finditer(r'\n\s*\n|[。！？.!?](?:\s|$)',text[start:end])]
            candidates=[p for p in candidates if p-start>=limit//2]
            if candidates:end=candidates[-1]
        if text[start:end].strip():yield start,end,text[start:end]
        if end==len(text):break
        start=max(start+1,end-40)

def code_sections(text,name):
    lines=text.splitlines(keepends=True)
    starts=[0]
    if name.endswith('.py'):
        try:
            tree=ast.parse(text)
            starts+=sorted({max(0,min([n.lineno]+[d.lineno for d in getattr(n,'decorator_list',[])])-1)
                            for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))})
        except SyntaxError:pass
    else:
        starts+=[i for i,line in enumerate(lines) if re.match(r'^(?:[\w:*<>]+\s+){0,5}[\w:]+\([^;]*\)\s*(?:const\s*)?\{|^(?:export\s+)?(?:async\s+)?function\s+\w+',line)]
    starts=sorted(set(starts+[len(lines)]))
    for a,b in zip(starts,starts[1:]):
        value=''.join(lines[a:b])
        if value.strip():yield a+1,b,value

def raw_parents(store,resources):
    result=[]
    for source in resources:
        resource=store.resource(source['resource_id']);path=store.snapshot(resource,source['version_id'])
        if digest(path)!=source['sha256']:raise DomainError('snapshot_corrupt')
        source_key=source_identity(resource)
        common={'resource_id':source['resource_id'],'version_id':source['version_id']}
        rows=[]
        if source['type']=='paper':
            from . import pdf
            with pdf.open_pdf(path) as doc:
                for page in doc:
                    text=page.get_text()
                    if text.strip():rows.append(({'page_index':page.number},text))
        elif source['type']=='code':
            for name in source.get('allowed_files',[]):
                file=store.code_file(resource,name,source['version_id'])
                for a,b,text in code_sections(file['text'],name):
                    rows.append(({'file':name,'file_sha256':file['sha256'],'line_start':a,'line_end':b},text))
        else:
            rows.append(({'snapshot_sha256':digest(path),'source_kind':'link_descriptor_only'},path.read_text('utf-8-sig')))
        for locator,text in rows:
            result.append({'id':'raw:'+key([common,locator]),'title':resource['title'],'kind':'raw_evidence','claim_type':'original_source',
                           'content':text,'evidence':[{**common,**locator}], 'source_key':source_key,'card_id':None,'layer_ids':[],'links':[],
                           'aliases':[],'terms':[],'verification_status':'source_text_not_independently_verified'})
    return result

def card_parents(cards):
    parents=[]
    for card in cards:
        common={'title':card['title'],'kind':'knowledge_card','card_id':card['id'],
                'layer_ids':card.get('layer_ids',[card['layer_id']]),'links':card.get('links',[]),
                'aliases':card.get('aliases',[]),'terms':card.get('terms',[]),'claim_type':card['claim_type'],
                'source_key':None,'verification_status':'authored_requires_source_check'}
        for index,section in enumerate(re.split(r'(?m)(?=^#{1,3} )',card['content'])):
            if section.strip():parents.append({**common,'id':'card:'+card['id']+':'+str(index),'content':section,'evidence':card['evidence']})
        for claim in card.get('claims',[]):
            parents.append({**common,'id':'claim:'+card['id']+':'+claim['id'],'content':claim['text'],
                            'claim_id':claim['id'],'claim_type':claim['claim_type'],'evidence':claim['evidence'],
                            'verification_status':claim['verification']})
        if card.get('method_profile'):
            for status in ('source_reported','inferred'):
                fields={k:v for k,v in card['method_profile'].items() if v['status']==status}
                if fields:
                    parents.append({**common,'id':'method:'+card['id']+':'+status,'content':json.dumps(fields,ensure_ascii=False),
                                    'claim_type':'inference' if status=='inferred' else 'source_fact','evidence':card['evidence']})
    return parents

def units_from_parents(parents):
    units=[]
    for parent in parents:
        is_card=parent['kind']=='knowledge_card'
        # Authored bilingual terms bridge English sources and Chinese cards.
        # Prefix + window stays below the 512-token encoder's character bound.
        prefix=(parent['title'][:60]+'\n'+' '.join(parent['aliases']+parent['terms'])[:118]) if is_card else parent['title'][:90]
        for n,(a,b,text) in enumerate(windows(parent['content'],320 if is_card else 360)):
            evidence=[]
            for original in parent['evidence']:
                e=dict(original)
                if parent['kind']=='raw_evidence':
                    e['quote']=text.strip()
                    if 'file' in e:
                        e['line_start']=original['line_start']+parent['content'][:a].count('\n')
                        e['line_end']=e['line_start']+text.rstrip('\n').count('\n')
                evidence.append(e)
            context=prefix+'\n'+text
            units.append({'id':parent['id']+':w'+str(n),'parent_id':parent['id'],'card_id':parent.get('card_id'),
                          'layer_id':next(iter(parent['layer_ids']),None),'title':parent['title'],'content':text,
                          'evidence':evidence,'links':parent['links'],'aliases':parent['aliases'],'terms':parent['terms'],
                          'context':context,'hash':hashlib.sha256(context.encode()).hexdigest(),'kind':parent['kind'],
                          'claim_type':parent['claim_type'],'layer_ids':parent['layer_ids'],'offset':[a,b]})
    return units

def stale_dependencies(cards,versions):
    changed=[]
    for card in cards:
        stale=[e for e in card['evidence'] if versions.get(e['resource_id'])!=e['version_id']]
        if stale:changed.append({'card_id':card['id'],'claim_ids':[c['id'] for c in card.get('claims',[]) if any(versions.get(e['resource_id'])!=e['version_id'] for e in c['evidence'])],
                                 'status':'needs_revalidation','source_ids':sorted({e['resource_id'] for e in stale})})
    return changed
