"""Research execution policy, shared by the dispatcher and persistent worker."""
PUBLIC_PROVIDERS = ['Crossref', 'Semantic Scholar']


def fulltext_policy():
    """Exact-paper lookup is independent of topic discovery and index health."""
    return {'version':'exact-paper-fulltext-v6',
            'pdf_sources':['authorized_publisher','registered_doi_pdf_links','official_publisher_oa','author_known_repository','arxiv','github','author_university_repository','openalex_exact_doi','semantic_scholar_exact_doi','sci_hub_doi'],
            'sci_hub_lookup':'one_exact_doi_request_after_other_sources_no_mirror_rotation',
            'sci_hub_role':'user_requested_fulltext_only_not_open_license_or_publication_evidence',
            'publisher_account_route':'check_authenticated_account_first_else_public_only',
            'unlogged_publisher':'skip_subscription_page_and_download_request',
            'open_access_evidence':'license_or_exact_index_oa_never_pdf_link_alone',
            'publisher_identity_binding':'primary_citation_doi_plus_pdf_link_saved_as_immutable_proof',
            'repository_domains':'exact_doi_title_all_authors_index_scoped_links',
            'publisher_queue':'installation_shared_bounded_wait',
            'publication_identity':'formal_doi_then_repository_declared_link',
            'author_initials':'supporting_evidence_only_under_explicit_formal_doi',
            'github_lookup':'one_exact_title_repository_query_max_three_pages',
            'arxiv_lookup':'exact_query_then_known_original_abs_page_on_transport_failure',
            'publisher_public_lookup':'known_open_access_article_only',
            'failed_index':'record_cooldown_continue_independent_sources',
            'failed_cache':'diagnostic_only_never_skip_new_authorized_lookup',
            'unavailable_fulltext':'skip_pdf_after_bounded_sources_preserve_graph_node_continue_next',
            'replacement':'never_replace_graph_paper_because_pdf_is_unavailable',
            'graph_preservation':'retain_all_verified_nodes_edges_and_citation_counts_independent_of_pdf',
            'source_coverage':'record_each_checked_failed_cooldown_unconfigured_source',
            'arxiv_doi_links':'verify_repository_record_never_download_doi_resolver',
            'file_validation':'actual_pdf_identifier_title_authors_before_registration'}


def authenticated_account(state):
    """An online browser or a reported login alone is not authentication."""
    return bool(state.get('online') and state.get('authentication_confirmed') is True
                and state.get('state') not in {'unconfigured','awaiting_login','expired'}
                and not state.get('approval') and not state.get('challenge_requires_user'))


def known_open_access(record):
    return (record or {}).get('open_access_verified') is True


def public_source(source,record):
    """Keep repository copies; require OA evidence for publisher PDF links."""
    if source.get('source_provider')=='Sci-Hub':
        from .sci_hub import valid_source
        return valid_source(source,record)
    if source.get('public_oa') is not True:return False
    if source.get('open_access_verified') is True:return True
    from urllib.parse import urlsplit
    from .research_download import publisher_hosts
    url=source.get('access_url') or source.get('url') or source.get('publisher_url','')
    host=urlsplit(str(url)).hostname
    bindings=[b for b in (record or {}).get('public_copy_bindings',[]) if b.get('pdf_url')==url]
    if any(b.get('match_basis')=='registered_doi_pdf_link_candidate_only' for b in bindings):
        return known_open_access(record)
    formal=urlsplit((record or {}).get('publisher_url','')).hostname
    if host and formal and (host==formal or host in publisher_hosts(formal)):
        return known_open_access(record)
    return True


def source_priority(source, record=None):
    """A publisher landing page is tried before author/repository copies."""
    if source.get('source_provider')=='Sci-Hub':return 99
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
    pdf=fulltext_policy()
    return {**policy, 'pdf_sources':pdf['pdf_sources'],'fulltext_policy':pdf,
            'discovery': 'official_public_apis', 'public_citation_fallback': list(PUBLIC_PROVIDERS),
            'fallback_on': ['rate_limited'], 'automatic_discovery': 'official_public_apis',
            'scholar_access': 'normal_browser_only'}
