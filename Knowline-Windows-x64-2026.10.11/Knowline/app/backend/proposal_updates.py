"""Frozen references for iterative proposals; historical outputs stay read-only."""
from .safety import DomainError, contained, digest

def validate(store, previous):
    for entry in [previous['context'],previous['result'],*previous['artifacts']]:
        path=contained(store.project,entry['path'])
        if not path.is_file() or digest(path)!=entry['sha256']:raise DomainError('proposal_previous_changed',409)

def prepare(store, idea, body):
    identifier=body.get('previous_job_id')
    request=body.get('update_request')
    if not identifier:
        if request:raise DomainError('proposal_previous_required')
        return {'mode':'generate','iteration':1}
    if not isinstance(request,str) or not request.strip() or len(request)>10000:raise DomainError('proposal_update_required')
    previous=store.job(identifier)
    store.check(previous,{'base_revision':body.get('previous_job_revision')})
    spec=previous['context'].get('proposal',{})
    if previous['task']!=body['task'] or spec.get('idea_id')!=idea['id']:raise DomainError('scope_violation',409)
    if previous['status'] not in {'completed','partial'} or not previous.get('result'):raise DomainError('proposal_previous_not_ready')
    artifacts=previous['result'].get('artifacts',[])
    if not any(a.get('path')==spec.get('target_path') for a in artifacts):raise DomainError('proposal_previous_not_ready')
    context=contained(store.project,previous['context_path'])
    result=store.state/'jobs'/previous['id']/'result.json'
    if not result.is_file():raise DomainError('proposal_previous_not_ready')
    baseline={'job_id':previous['id'],'job_revision':previous['revision'],'task':previous['task'],'status':previous['status'],
              'idea_revision':spec['idea_revision'],'iteration':spec.get('iteration',1),
              'context':{'path':previous['context_path'],'sha256':digest(context)},
              'result':{'path':result.relative_to(store.project).as_posix(),'sha256':digest(result)},
              'artifacts':artifacts,'target_path':spec['target_path']}
    validate(store,baseline)
    return {'mode':'update','iteration':baseline['iteration']+1,'update_request':request.strip(),'previous':baseline}
