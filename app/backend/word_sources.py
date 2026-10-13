"""Compile project-scoped Word source records without guessing bibliographic facts."""
import hashlib
import re
import uuid
import xml.etree.ElementTree as ET
from .project_catalog import read, resolve
from .safety import DomainError

NS='http://schemas.microsoft.com/office/word/2004/10/bibliography'
ET.register_namespace('b',NS)


def tag_for(project, resource_id):
    return 'KW'+hashlib.sha256((str(project.resolve())+'\0'+resource_id).encode()).hexdigest()[:24]


def author_names(value):
    # Crossref/platform authors are an ordered array. A string is not guessed into authors.
    if not isinstance(value,list) or not value:
        raise DomainError('citation_metadata_incomplete',fields=['authors'])
    people=[]
    for author in value:
        if isinstance(author,dict):
            last=str(author.get('family',author.get('last',''))).strip()
            first=str(author.get('given',author.get('first',''))).strip()
        elif isinstance(author,str) and author.strip():
            name=author.strip()
            if ',' in name:
                last,first=map(str.strip,name.split(',',1))
            else:
                parts=name.rsplit(' ',1)
                first,last=(parts[0],parts[1]) if len(parts)==2 else ('',name)
        else:
            raise DomainError('citation_metadata_incomplete',fields=['authors'])
        if not last or len(last+first)>300:
            raise DomainError('citation_metadata_incomplete',fields=['authors'])
        people.append({'last':last,'first':first})
    return people


def source_record(project, resource):
    meta=resource.get('metadata',{})
    record=meta.get('publication_record')
    if meta.get('publication_record_id'):
        current=read(project)
        record=next((r for r in current.get('paper_records',[]) if r['id']==meta['publication_record_id']),None)
        for _ in range(5):
            if not record or not record.get('alias_of'):break
            record=next((r for r in current.get('paper_records',[]) if r['id']==record['alias_of']),None)
        if not record or record.get('alias_of'):raise DomainError('citation_relation_invalid',409)
    if record:
        from .paper_bibliography import fresh
        if not record.get('latest_verified') or not fresh(record.get('latest_checked_at'),300):raise DomainError('citation_refresh_required',409)
        meta={**meta,**{k:record.get(k) for k in ['authors','year','venue','doi','source_type','volume','issue','pages','url','metadata_status']}}
    title=record['title'] if record else resource.get('title')
    required={'title':title,'year':meta.get('year'),'venue':meta.get('venue'),'authors':meta.get('authors'),'source_type':meta.get('source_type')}
    missing=[key for key,value in required.items() if not value]
    if missing or not re.fullmatch(r'(1[5-9]|20|21)\d{2}',str(required['year'])):
        raise DomainError('citation_metadata_incomplete',resource_id=resource['id'],fields=missing or ['year'])
    people=author_names(required['authors'])
    tag=tag_for(project,resource['id'])
    node=ET.Element('{'+NS+'}Source')
    def add(parent,key,value):
        child=ET.SubElement(parent,'{'+NS+'}'+key);child.text=str(value);return child
    add(node,'Tag',tag)
    # A conference title alone does not prove the source type; use verified metadata when supplied.
    kind=meta['source_type']
    if kind not in {'JournalArticle','ConferenceProceedings','Report','Book'}:
        raise DomainError('citation_source_type_invalid')
    add(node,'SourceType',kind);add(node,'Guid','{'+str(uuid.uuid5(uuid.NAMESPACE_URL,tag))+'}');add(node,'LCID',1033)
    names=ET.SubElement(ET.SubElement(ET.SubElement(node,'{'+NS+'}Author'),'{'+NS+'}Author'),'{'+NS+'}NameList')
    for person in people:
        entry=ET.SubElement(names,'{'+NS+'}Person');add(entry,'Last',person['last']);add(entry,'First',person['first'])
    add(node,'Title',required['title']);add(node,'Year',required['year'])
    add(node,'JournalName' if kind=='JournalArticle' else 'ConferenceName' if kind=='ConferenceProceedings' else 'Publisher',required['venue'])
    for key,xml_key in [('doi','DOI'),('volume','Volume'),('issue','Issue'),('pages','Pages'),('url','URL')]:
        if meta.get(key):add(node,xml_key,meta[key])
    note='Knowline resource='+resource['id']+'; version='+resource['version_id']+'; sha256='+resource['sha256']
    if record and record['publication_status']=='preprint':note+='; preprint v'+str(record.get('preprint_version'))+'; formal publication not verified'
    add(node,'Comments',note)
    return {'resource_id':resource['id'],'version_id':resource['version_id'],'sha256':resource['sha256'],
            'title':title,'tag':tag,'xml':ET.tostring(node,encoding='unicode'),
            'metadata_status':meta.get('metadata_status','needs_review')}


def domain_sources(project, name, resource_ids=None, require_verified=True):
    data=read(project);domain=resolve(data['domains'],name,'group')
    members={r['id']:r for r in data['resources'] if r['id'] in domain['resource_ids'] and r['type']=='paper' and r['state']=='ready'}
    linked={r['metadata'].get('publication_record_id') for r in members.values()}
    linked.update(r['alias_of'] for r in data.get('paper_records',[]) if r['id'] in linked and r.get('alias_of'))
    for record in data.get('paper_records',[]):
        if domain['id'] in record['domain_ids'] and record['id'] not in linked and not record.get('alias_of'):
            members[record['id']]={'id':record['id'],'title':record['title'],'version_id':'metadata','sha256':record['evidence_sha256'],'metadata':{**record,'publication_record':record}}
    if resource_ids is not None:
        if not resource_ids or len(resource_ids)>100:
            raise DomainError('citation_selection_required')
        # Previously inserted metadata-only citation IDs remain selectable after a formal upgrade.
        records={r['id']:r for r in data.get('paper_records',[])}
        for identifier in resource_ids:
            if identifier in members:continue
            record=records.get(identifier)
            for _ in range(5):
                if not record or not record.get('alias_of'):break
                record=records.get(record['alias_of'])
            if record and not record.get('alias_of') and domain['id'] in record['domain_ids']:
                members[identifier]={'id':identifier,'title':record['title'],'version_id':'metadata','sha256':record['evidence_sha256'],'metadata':{**record,'publication_record':record}}
        outside=[rid for rid in resource_ids if rid not in members]
        if outside:raise DomainError('citation_outside_domain',resource_ids=outside)
        resources=[members[rid] for rid in dict.fromkeys(resource_ids)]
    else:resources=list(members.values())
    sources=[];unavailable=[]
    for resource in resources:
        try:
            record=source_record(project,resource)
            if require_verified and record['metadata_status']!='verified':
                raise DomainError('citation_metadata_unverified',resource_id=resource['id'])
            sources.append(record)
        except DomainError as exc:
            unavailable.append({'resource_id':resource['id'],'title':resource['title'],'code':exc.code,**exc.params})
    if resource_ids is not None and unavailable:
        raise DomainError('citation_sources_unavailable',sources=unavailable)
    return {'domain':{'id':domain['id'],'name':domain['name']},'catalog_sequence':data['event_sequence'],
            'sources':sources,'unavailable':unavailable}
