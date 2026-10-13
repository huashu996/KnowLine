"""Evidence and experiment contracts. Structure checks never certify scientific truth."""
import json,copy,hashlib
from .safety import DomainError,contained,digest

CONTRACT='evidence-to-experiment-v4'
TYPES={'source_fact','synthesis','inference','research_idea'}
METHOD_FIELDS=('problem','mechanism','inputs','outputs','coordinate_frame','time_semantics','objective','assumptions','labels','training_data','resources','valid_conditions','failure_conditions','hyperparameters','code')
CATEGORIES={'comparison','formula','code','conflict','unanswerable','research_design','method','limitations'}

def normalize_analysis(analysis):
    """Only weaken whole-card certainty; never upgrade a claim or invent facts."""
    result=copy.deepcopy(analysis);changes=[]
    rank={'source_fact':0,'synthesis':1,'inference':2,'research_idea':3}
    for card in result.get('knowledge_cards',[]):
        kinds=[c.get('claim_type') for c in card.get('claims',[])]
        kinds=[k for k in kinds if k in rank]+([card['claim_type']] if card.get('claim_type') in rank else [])
        if kinds:
            conservative=max(kinds,key=rank.get)
            if conservative!=card.get('claim_type'):
                changes.append({'card_id':card['id'],'field':'claim_type','previous':card.get('claim_type'),'value':conservative,'reason':'contains_more_tentative_claims'})
                card['claim_type']=conservative
        if card.get('card_kind')=='method':
            profile=card.setdefault('method_profile',{})
            if isinstance(profile,dict):
                for name in METHOD_FIELDS:profile.setdefault(name,{'value':None,'status':'unknown','claim_ids':[]})
        if card.get('card_kind')=='failure' and not text(card.get('failure_signature')):
            # A stable provenance identity, not a claim that an experiment ran.
            evidence=sorted(json.dumps(e,ensure_ascii=False,sort_keys=True) for e in card.get('evidence',[]))
            if evidence:
                details=card.get('failure_signature')
                if details is not None:card.setdefault('failure_details',copy.deepcopy(details))
                identity=json.dumps({'evidence':evidence,'details':card.get('failure_details')},ensure_ascii=False,sort_keys=True)
                card['failure_signature']='source-failure:'+hashlib.sha256(identity.encode()).hexdigest()[:24]
                changes.append({'card_id':card['id'],'field':'failure_signature','value':card['failure_signature'],'reason':'stable_source_identity'})
    if changes:result['normalization_log']=result.get('normalization_log',[])+changes
    return result

def require(value,reason):
    if not value:raise DomainError('research_contract_invalid',reason=reason)

def text(value):return isinstance(value,str) and bool(value.strip())
def strings(value):return isinstance(value,list) and all(text(v) for v in value)

def checked_evidence(store,job,values,frozen=None):
    require(isinstance(values,list) and values,'claim_evidence_required')
    identities=[]
    for e in values:
        require(isinstance(e,dict),'invalid_claim_evidence')
        if frozen is not None:identities.append(frozen.validate_any(e))
        else:store.validate_evidence(e,job['context']['resources'])
    return identities

def knowledge(store,job,result):
    if job['context'].get('knowledge_build',{}).get('research_contract')!=CONTRACT:return
    values=result['knowledge_cards'];layers={l['id'] for l in job['context']['knowledge_layers']}
    require(len({c['id'] for c in values})==len(values),'duplicate_card_id')
    for card in values:
        belongs=card.get('layer_ids')
        require(strings(belongs) and belongs and len(set(belongs))==len(belongs) and set(belongs)<=layers and card['layer_id'] in belongs,'card_layer_membership')
        claims=card.get('claims');require(isinstance(claims,list) and claims,'claim_level_citations_required')
        ids=set()
        for c in claims:
            require(isinstance(c,dict) and text(c.get('id')) and c['id'] not in ids and text(c.get('text')),'claim_identity')
            ids.add(c['id']);require(c.get('claim_type') in TYPES,'claim_type')
            require(c.get('verification') in {'paper_claim','code_present','execution_reported','unverified'},'claim_verification')
            checked_evidence(store,job,c.get('evidence'))
            require(all(e in card['evidence'] for e in c['evidence']),'claim_evidence_not_in_card')
            resources={r['resource_id']:r for r in job['context']['resources']}
            if c['verification']=='paper_claim':require(any(resources[e['resource_id']]['type']=='paper' for e in c['evidence']),'paper_claim_without_paper')
            if c['verification']=='code_present':require(any(resources[e['resource_id']]['type']=='code' and e.get('file') for e in c['evidence']),'code_claim_without_code')
            if c['verification']=='execution_reported':
                # This means a frozen log reports a run, not that Knowline reran it.
                log=c.get('execution_log');require(isinstance(log,dict) and log in c['evidence'] and log.get('file'),'execution_log_required')
                r=store.resource(log['resource_id']);file=store.code_file(r,log['file'],log['version_id'])
                try:run=json.loads(file['text'])
                except (ValueError,TypeError):raise DomainError('research_contract_invalid',reason='execution_log_not_json')
                require(run.get('exit_code')==0 and text(run.get('command')) and text(run.get('environment')),'successful_execution_log_required')
        require(card.get('card_kind') in {'concept','method','experiment','failure','research_idea'},'card_kind_required')
        if card['card_kind']=='research_idea':require(card['claim_type']=='research_idea','idea_mislabeled_as_fact')
        if card['claim_type'] in {'source_fact','synthesis'}:
            require(all(c['claim_type'] in ({'source_fact'} if card['claim_type']=='source_fact' else {'source_fact','synthesis'}) for c in claims),'speculation_in_factual_card')
        if card['card_kind']=='method':
            profile=card.get('method_profile');require(isinstance(profile,dict) and set(METHOD_FIELDS)<=set(profile),'method_profile_required')
            for name in METHOD_FIELDS:
                field=profile[name];require(isinstance(field,dict) and 'value' in field and isinstance(field.get('claim_ids'),list) and set(field['claim_ids'])<=ids,'method_field_claims')
                require(field.get('status') in {'source_reported','inferred','unknown'},'method_field_status')
                if field['status']=='unknown':require(field['value'] is None and not field['claim_ids'],'unknown_must_remain_empty')
                else:
                    require(field['value'] is not None and field['value'] not in ('',[],{}) and field['claim_ids'],'known_method_field_without_claim')
                    matched=[c for c in claims if c['id'] in field['claim_ids']]
                    if field['status']=='source_reported':require(all(c['claim_type']=='source_fact' and c['verification']!='unverified' for c in matched),'inference_as_method_fact')
                if name=='code' and field['status']!='unknown':
                    require(isinstance(field['value'],dict) and {'commit','file','function','config','test_entry','run_status'}<=field['value'].keys(),'code_implementation_locator_required')
                    require(field['value']['run_status'] in {'not_run','log_reports_pass','log_reports_failure'},'code_run_status')
        if card['card_kind']=='failure':require(text(card.get('failure_signature')),'failure_signature_required')
    report=result['knowledge_build_report'];cases=report.get('queries',[])
    require(30<=len(cases)<=50,'thirty_to_fifty_evaluation_cases_required')
    require(len({c['query'].strip().casefold() for c in cases})==len(cases),'duplicate_evaluation_question')
    omitted=report.get('evaluation_not_applicable',[])
    require(isinstance(omitted,list) and all(isinstance(x,dict) and x.get('category') in CATEGORIES and text(x.get('reason')) for x in omitted),'evaluation_exclusions')
    require(CATEGORIES<={c.get('category') for c in cases}|{x['category'] for x in omitted},'evaluation_category_coverage')
    require({'zh','en'}<={c.get('language') for c in cases},'bilingual_evaluation_required')
    for case in cases:
        require(case.get('category') in CATEGORIES and isinstance(case.get('expected_evidence'),list),'evaluation_evidence_required')
        require(case.get('purpose','evidence') in {'evidence','inspiration'},'evaluation_purpose')
        if case['category']=='unanswerable':require(not case['expected_card_ids'] and not case['expected_evidence'] and text(case.get('missing_evidence_reason')),'negative_case_needs_reason')
        else:checked_evidence(store,job,case['expected_evidence'])
        require(strings(case.get('answer_checks')) and case['answer_checks'],'answer_quality_checks_required')

def proposal_policy():
    return {'contract':CONTRACT,'candidate_count':[2,3],'search_lanes':['similar_problem','mechanism','counterevidence','code'],
            'max_search_rounds':3,'max_queries':12,'top_k_per_query':12,'novelty_scope':'selected_sources',
            'minimum_experiment_required':True,'unknowns_must_be_explicit':True}

def design(store,job,result):
    if job['context'].get('proposal',{}).get('research_policy',{}).get('contract')!=CONTRACT:return
    value=result.get('research_design');require(isinstance(value,dict),'research_design_required')
    from .proposal_evidence import FrozenKnowledge
    frozen=FrozenKnowledge(store,job)
    failures=value.get('failure_records',[]);require(isinstance(failures,list),'failure_records')
    for failure in failures:
        require(all(text(failure.get(k)) for k in ('signature','hypothesis','conditions','observed_failure')),'failure_record_fields')
        checked_evidence(store,job,failure.get('evidence'),frozen)
    problem=value.get('problem');fields={'failure','inputs','outputs','baseline','metrics','compute','data','latency','time_budget','allowed_changes','frozen_components'}
    require(isinstance(problem,dict) and fields<=problem.keys(),'problem_constraints_required')
    require(all(v is None or text(v) or isinstance(v,(list,dict)) for v in problem.values()) and strings(value.get('unknowns')),'explicit_unknowns_required')
    require(all(k in value['unknowns'] or problem[k] is not None for k in fields),'missing_problem_unknown')
    candidates=value.get('candidates');require(isinstance(candidates,list) and 2<=len(candidates)<=3,'distinct_candidates_required')
    require(len({c.get('id') for c in candidates})==len(candidates) and len({c.get('strategy') for c in candidates})==len(candidates),'duplicate_candidate')
    require(value.get('selected_candidate_id') in {c['id'] for c in candidates},'candidate_selection_required')
    from .knowledge_evidence import source_identity
    identities={r['resource_id']:source_identity(store.resource(r['resource_id'])) for r in job['context']['resources']}
    nearest_count=min(3,len({identities[r['resource_id']] for r in job['context']['resources'] if r['type']=='paper'}|set(frozen.identities)))
    source_ids={r['resource_id'] for r in job['context']['resources']}
    for c in candidates:
        require(text(c.get('id')) and c.get('strategy') in {'minimal_change','method_combination','assumption_test'},'candidate_strategy')
        for field in ('hypothesis','falsifier','mechanism','difference','most_likely_failure'):require(text(c.get(field)),'candidate_'+field)
        for field in ('reuse','modify','add','unknowns'):require(strings(c.get(field)),'candidate_'+field)
        require(c['modify'] or c['add'],'no_concrete_change')
        checked_evidence(store,job,c.get('evidence'),frozen)
        novelty=c.get('novelty');require(isinstance(novelty,dict) and novelty.get('label') in {'transfer','incremental','not_seen_in_searched_scope'},'unsupported_novelty_claim')
        require(novelty.get('scope')=='selected_sources' and text(novelty.get('limitations')),'novelty_scope_required')
        nearest=novelty.get('nearest');require(isinstance(nearest,list) and nearest_count<=len(nearest)<=5,'nearest_work_comparison_required')
        nearest_identities=[]
        for n in nearest:
            require(all(text(n.get(k)) for k in ('problem','mechanism','assumptions','implementation','experiment')),'nearest_work_dimensions')
            keys=set(checked_evidence(store,job,n.get('evidence'),frozen));require(len(keys)==1,'nearest_work_identity')
            identity=next(iter(keys));nearest_identities.append(identity)
            if n.get('resource_id') is not None:
                require(n['resource_id'] in source_ids and identities[n['resource_id']]==identity,'nearest_work_identity')
            else:
                require(all(e.get('kind')=='frozen_knowledge_card' for e in n['evidence']),'nearest_work_identity')
                for field in ('source_key','source_id','imported_document_id'):
                    if n.get(field) is not None:require(all(e.get(field)==n[field] for e in n['evidence']),'nearest_work_identity')
        require(len(set(nearest_identities))==len(nearest),'duplicate_independent_nearest_work')
        counter=c.get('counterevidence');require(isinstance(counter,dict) and strings(counter.get('findings')) and text(counter.get('search_result')),'counterevidence_search_required')
        if counter['findings']:checked_evidence(store,job,counter.get('evidence'),frozen)
        interfaces=c.get('interfaces');require(isinstance(interfaces,list) and interfaces,'interface_check_required')
        for interface in interfaces:
            require(all(k in interface for k in ('from','to','coordinates','time','shape','objective','status','bridge','unknowns')),'interface_dimensions')
            require(text(interface['from']) and text(interface['to']) and strings(interface['unknowns']),'interface_identity')
            require(interface['status'] in {'compatible','bridge_required','incompatible','unknown'},'interface_status')
            require(all(interface[k] is not None or k in interface['unknowns'] for k in ('coordinates','time','shape','objective')),'interface_unknown_not_recorded')
            if interface['status']=='compatible':
                require(all(text(interface[k]) for k in ('coordinates','time','shape','objective')),'unknown_interface_cannot_be_compatible')
                checked_evidence(store,job,interface.get('evidence'),frozen)
            elif interface.get('evidence'):checked_evidence(store,job,interface['evidence'],frozen)
            if interface['status']=='bridge_required':require(text(interface['bridge']),'missing_coordinate_or_time_bridge')
        if c['id']==value['selected_candidate_id']:
            require(not any(i['status']=='incompatible' for i in interfaces),'selected_candidate_incompatible')
        exp=c.get('experiment');require(isinstance(exp,dict),'minimal_experiment_required')
        for field in ('baseline','dataset','split','metrics','budget','controls','ablations','failure_conditions','continue_if','stop_if','first_step'):
            require(field in exp and (text(exp[field]) or isinstance(exp[field],(dict,list)) and bool(exp[field])),'experiment_'+field)
        comparison=exp.get('comparison_contract')
        require(text(comparison) or isinstance(comparison,dict) and strings(comparison.get('identical')) and bool(comparison['identical']) and
                text(comparison.get('failure_accounting')) and text(comparison.get('threshold_status')),'dataset_split_budget_comparability')
    path=result.get('research_design_artifact')
    artifact=next((a for a in result.get('artifacts',[]) if a['path']==path),None)
    require(artifact is not None,'design_artifact_required')
    saved=json.loads(contained(store.project,path).read_text('utf-8-sig'))
    require(saved==value,'design_artifact_mismatch')
    trace=store.one('SELECT value FROM settings WHERE key=?',('research_search:'+job['id'],))
    require(trace is not None,'bounded_research_search_required')
    trace=json.loads(trace['value']);lanes={q['lane'] for q in trace['queries']}
    require(set(proposal_policy()['search_lanes'])<=lanes,'research_search_lane_coverage')
    result['research_validation']={'contract':CONTRACT,'candidates':len(candidates),'search_queries':len(trace['queries']),
                                   'status':'structural_and_source_checks_passed','semantic_correctness':'requires_researcher_review',
                                   'novelty_scope':'selected_sources','independent_sources':len({frozen.validate_any(e) for c in candidates for e in c['evidence']}),
                                   'knowledge_citations_supported':True,'knowledge_citations_verify':'frozen_card_content_only'}
