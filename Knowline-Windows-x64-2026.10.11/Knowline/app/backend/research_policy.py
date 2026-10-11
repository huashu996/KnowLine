"""Research execution policy, shared by the dispatcher and persistent worker."""
PUBLIC_PROVIDERS = ['Crossref', 'Semantic Scholar']


def source_priority(source, record=None):
    """A publisher landing page is tried before author/repository copies."""
    from urllib.parse import urlsplit
    host=urlsplit(str(source.get('access_url') or source.get('publisher_url',''))).hostname
    if host in {'arxiv.org','export.arxiv.org'}:return 4
    if source.get('pdf_version')=='published':return 1 if source.get('public_oa') is True else 0
    if ((record or {}).get('publication_status')=='published'
            and source.get('publisher_url')==(record or {}).get('publisher_url')
            and source.get('public_oa') is not True):return 0
    return 3 if source.get('pdf_version') in {'preprint','accepted_manuscript'} else 2


def institution_timeout(body, job):
    # Public metadata's 10-second budget is insufficient for rendered publisher
    # pages and a session-authenticated PDF transfer. Each request stays bounded.
    requested=body.get('institution_timeout_seconds',body.get('timeout_seconds',
        job['context'].get('literature_search',{}).get('source_request_timeout_seconds',10)))
    return max(60,min(120,float(requested)))


def acquisition_limits(job):
    target=job['context'].get('literature_search',{}).get('target_count',10)
    return {'target_verified_fulltexts':target,'maximum_discovery_requests':5,'maximum_candidates':min(100,max(10,target*10)),'source_retry_limit':0}


def total_budget(job):
    # All tasks run until completion or cancellation, including retries whose
    # immutable context still carries a legacy time budget. Individual I/O
    # timeouts and lease/connection checks remain independent of this policy.
    return None


def public_fallback_allowed(job):
    policy = job['context'].get('literature_search', {}).get('source_policy', {})
    return (job['task'] in {'paper_relationships','discover_papers'}
            and policy.get('public_citation_fallback') == PUBLIC_PROVIDERS
            and policy.get('fallback_on') == ['rate_limited'])


def enable_public_fallback(policy):
    return {**policy, 'discovery': 'official_public_apis', 'public_citation_fallback': list(PUBLIC_PROVIDERS),
            'fallback_on': ['rate_limited'], 'automatic_discovery': 'official_public_apis',
            'scholar_access': 'normal_browser_only'}
