"""Controlled browser acquisition for settings and bounded paper jobs; no credential export."""
import hashlib
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, unquote, parse_qsl, urlencode
from .safety import DomainError, atomic_json, digest, filename

VERSIONS = {'published', 'accepted_manuscript', 'preprint', 'unknown'}
METHODS = {'publisher', 'proxy', 'campus_vpn'}
STATES = {'unconfigured', 'awaiting_login', 'awaiting_test', 'verified', 'expired'}
MAX_PDF = 128 * 1024 * 1024
# An explicitly published anonymous author copy linked by the official page.
# Authentication and arbitrary HTTP URLs never receive this exception.
LEGACY_PUBLIC_PDFS={'http://doriangalvez.com/papers/GalvezTRO12.pdf'}


def stamp():
    return datetime.now(timezone.utc).isoformat()


def safe_url(value,public_copy=False):
    """Only stable HTTPS URLs enter API/operations/catalog; signed URLs stay in WebView2."""
    if not isinstance(value, str) or len(value) > 2048:
        raise DomainError('institution_url_invalid')
    try:
        p = urlsplit(value)
        host = p.hostname or ''
        legacy=public_copy and value in LEGACY_PUBLIC_PDFS
        if (p.scheme != 'https' and not legacy) or not host or p.username or p.password or p.port not in ({None,80} if legacy else {None,443}) or p.fragment:
            raise ValueError()
        pairs = parse_qsl(p.query,keep_blank_values=True)
        if any(k not in {'id','doi','type','format','download','arnumber','tp','queryText','searchText','query','q','page','record','document','url'} or len(v)>(1200 if k=='url' else 200) or re.search(r'(?i)(token|ticket|password|secret|jwt|[A-Za-z0-9_-]{80,})',v) for k,v in pairs):
            raise ValueError()
        for key,value in pairs:
            if key=='url' and safe_url(value)!=value:raise ValueError()
        if re.search(r'(?i)(token|ticket|signature|password|secret|jwt|[A-Za-z0-9_-]{80,})', unquote(p.path)):
            raise ValueError()
        if host == 'localhost' or host.endswith(('.localhost', '.local')) or '.' not in host:
            raise ValueError()
        try:
            if not ipaddress.ip_address(host).is_global:
                raise ValueError()
        except ValueError:
            if re.fullmatch(r'[0-9.:]+', host):
                raise ValueError()
        return p.scheme+'://' + host.lower() + (p.path or '/') + ('?'+urlencode(pairs) if pairs else '')
    except ValueError:
        raise DomainError('institution_url_invalid')


def public_destination(url, hosts, resolve=True, allow_translated=False,public_copy=False):
    """Ephemeral redirect URLs may contain tokens; return only a boolean, never their value."""
    try:
        p = urlsplit(str(url))
        legacy=public_copy and str(url) in LEGACY_PUBLIC_PDFS
        if (p.scheme != 'https' and not legacy) or p.hostname not in hosts or p.username or p.password or p.port not in ({None,80} if legacy else {None,443}):
            return False
        if resolve:
            addresses = socket.getaddrinfo(p.hostname, 80 if legacy else 443, type=socket.SOCK_STREAM)
            def permitted(value):
                address=ipaddress.ip_address(value)
                return address.is_global or (allow_translated and address.version==4 and address in ipaddress.ip_network('198.18.0.0/15'))
            return bool(addresses) and all(permitted(a[4][0]) for a in addresses)
        return True
    except (OSError, ValueError):
        return False


def confirmation_origin(uri):
    p=urlsplit(str(uri))
    if p.scheme!='https' or p.username or p.password or p.port not in {None,443}:raise DomainError('institution_scope_invalid')
    return safe_url('https://'+(p.hostname or '')+'/')


def configuration(body):
    entry = safe_url(body.get('entry_url'))
    school = str(body.get('school') or '').strip() or urlsplit(entry).hostname
    method=body.get('method') or 'publisher'
    if len(school) > 120 or method not in METHODS or body.get('official_confirmed') is not True:
        raise DomainError('institution_configuration_required')
    origins = body.get('allowed_origins', [])
    if not isinstance(origins, list) or len(origins) > 40:
        raise DomainError('institution_scope_invalid')
    origins = sorted(set([entry] + [safe_url(v) for v in origins]))
    template=str(body.get('proxy_template','')).strip()
    if template:
        if method!='proxy' or template.count('{url}')!=1 or len(template)>1000:raise DomainError('institution_proxy_template_invalid')
        from urllib.parse import quote
        example=safe_url(template.replace('{url}',quote('https://publisher.example.edu/article',safe='')))
        if urlsplit(example).hostname!=urlsplit(entry).hostname:raise DomainError('institution_proxy_path_required')
    return {'school': school, 'name':str(body.get('name') or school)[:120], 'entry_url': entry, 'method': method, 'allowed_origins': origins,
            'proxy_template':template,
            'official_confirmed': True, 'allow_translated_network':body.get('allow_translated_network',True) is True,
            'locale': 'en' if body.get('locale') == 'en' else 'zh'}


def paper_request(body, config,public_copy=False):
    doi = str(body.get('doi', '')).strip().lower().removeprefix('https://doi.org/')
    title = str(body.get('title', '')).strip()
    authors = body.get('authors')
    citation=body.get('citation_record') or {}
    arxiv_only=not doi and isinstance(citation,dict) and citation.get('publication_status')=='preprint' and citation.get('latest_verified') and citation.get('arxiv_id')
    if (not re.fullmatch(r'10\.\d{4,9}/\S{1,180}', doi) and not arxiv_only) or not 8 <= len(title) <= 500 or not isinstance(authors, list) or not 1 <= len(authors) <= 100 or any(not isinstance(a,str) or not 2 <= len(a.strip()) <= 120 for a in authors):
        raise DomainError('institution_identity_required')
    publisher = safe_url(body.get('publisher_url'))
    public_copy=public_copy and body.get('public_oa') is True
    access = safe_url(body.get('access_url') or publisher,public_copy=public_copy)
    # The download landing page describes the actual PDF. Citation verification is independent.
    metadata_url=safe_url(body.get('metadata_url') or access,public_copy=public_copy)
    origins = config['allowed_origins']
    hosts = {urlsplit(u).hostname for u in origins}
    citation_origin=isinstance(citation,dict) and citation.get('latest_verified') and publisher in {citation.get('publisher_url'),citation.get('url')}
    if any(urlsplit(url).hostname not in hosts for url in [access,metadata_url]+([] if citation_origin else [publisher])):
        raise DomainError('institution_scope_invalid')
    if config['method'] == 'proxy' and body.get('public_oa') is not True and urlsplit(access).hostname != urlsplit(config['entry_url']).hostname:
        raise DomainError('institution_proxy_path_required')
    version = body.get('pdf_version', 'unknown')
    basis = str(body.get('version_basis', '')).strip()
    reason = str(body.get('fallback_reason', '')).strip()
    if version not in VERSIONS or len(basis) > 500 or len(reason) > 500 or (version != 'unknown' and len(basis) < 12):
        raise DomainError('institution_version_basis_required')
    if re.search(r'(?i)(?:token|ticket|secret|password|signature)\s*[=:]',basis+' '+reason):raise DomainError('institution_url_invalid')
    if version != 'published' and len(reason) < 8:
        raise DomainError('institution_fallback_reason_required')
    if body.get('identity_confirmed') is not True or body.get('download_permitted') is not True:
        raise DomainError('institution_confirmation_required')
    year=body.get('year')
    if year is not None and (isinstance(year,bool) or not isinstance(year,int) or not 1500<=year<=2200):raise DomainError('institution_identity_required')
    venue=str(body.get('venue') or '').strip()
    if len(venue)>200:raise DomainError('institution_identity_required')
    evidence=safe_url(body.get('version_source_url') or (access if version!='published' else publisher),public_copy=public_copy)
    if urlsplit(evidence).hostname not in hosts:raise DomainError('institution_scope_invalid')
    pdf_identity=body.get('pdf_identity')
    citation=body.get('citation_record')
    if pdf_identity is not None and (not isinstance(pdf_identity,dict) or not isinstance(pdf_identity.get('title'),str) or not isinstance(pdf_identity.get('authors'),list)):raise DomainError('institution_identity_required')
    return {'id': str(uuid.uuid4()), 'doi':doi, 'title':title, 'authors':[a.strip() for a in authors],
            'publisher_url':publisher, 'access_url':access, 'metadata_url':metadata_url,'pdf_version':version,
            'version_basis':basis, 'fallback_reason':reason,
            'version_source_url':evidence,'year':year,'venue':venue,
            'access_method':('public_publisher' if version=='published' else 'public_repository') if body.get('public_oa') is True else config['method'],
            'identity_confirmed':True, 'download_permitted':True,
            'automatic':body.get('automatic') is True, 'asserted_by':body.get('asserted_by','user'),
            **({'pdf_identity':pdf_identity} if pdf_identity else {}),**({'citation_record':citation} if isinstance(citation,dict) else {})}


def normalize(value):
    return re.sub(r'[^\w]', '', unicodedata.normalize('NFKC',value).casefold())


def author_text_normalize(value):
    # PDF extractors can emit TeX accents as spacing marks: Gigu`ere rather
    # than Giguère. Normalize those marks and Unicode accents on both sides,
    # while retaining word boundaries for the all-author surname check.
    value=value.casefold().replace('\u0131','i').replace('\u0237','j')
    value=re.sub(r"(?<=\w)[\-\u00ad\u2010-\u2015'\u2018\u2019`\u00a8\u00b4\u00b8\u02c6\u02dc]\s*(?=\w)",'',value)
    return ''.join(c for c in unicodedata.normalize('NFKD',value) if not unicodedata.combining(c))


def rss_pdf_url(doi):
    """RSS's registered DOI encodes the official proceedings volume and paper."""
    match=re.fullmatch(r'10\.15607/rss\.(\d{4})\.([ivxlcdm]+)\.(\d{3})',str(doi or '').lower())
    if not match:return None
    values={'i':1,'v':5,'x':10,'l':50,'c':100,'d':500,'m':1000}
    roman=match[2];volume=sum(-values[c] if i+1<len(roman) and values[c]<values[roman[i+1]] else values[c] for i,c in enumerate(roman))
    if not 1<=volume<=100 or int(match[1])!=2004+volume or not 1<=int(match[3])<=999:return None
    remaining=volume;canonical=''
    for value,symbol in [(100,'c'),(90,'xc'),(50,'l'),(40,'xl'),(10,'x'),(9,'ix'),(5,'v'),(4,'iv'),(1,'i')]:
        amount,remaining=divmod(remaining,value);canonical+=symbol*amount
    if canonical!=roman:return None
    return 'https://www.roboticsproceedings.org/rss'+str(volume).zfill(2)+'/p'+str(int(match[3])).zfill(2)+'.pdf'


def validate_pdf(path, target):
    from .pdf import open_pdf
    path = Path(path)
    if not path.is_file() or not 5 < path.stat().st_size <= MAX_PDF:
        raise DomainError('pdf_invalid')
    with path.open('rb') as f:
        if not f.read(5) == b'%PDF-':
            raise DomainError('pdf_invalid')
    with open_pdf(path) as document:
        if not len(document) or not document.is_pdf:
            raise DomainError('pdf_invalid')
        inspected = min(3,len(document))
        text = '\n'.join(document[i].get_text() for i in range(inspected))
    # Conservative: scanned or abbreviated-title PDFs require existing manual review/import.
    found = set(v.rstrip('.,;)') for v in re.findall(r'10\.\d{4,9}/[^\s<>"\]]+', text.lower()))
    identity=target.get('pdf_identity') or target
    actual_doi=str(identity.get('doi') or target['doi']).lower()
    doi_match = actual_doi in found
    arxiv_id=str(identity.get('arxiv_id') or '')
    citation=target.get('citation_record',{})
    expected_publisher=rss_pdf_url(actual_doi)
    publisher_bound=bool(expected_publisher and identity.get('publisher_pdf_url')==expected_publisher and citation.get('latest_verified') and citation.get('doi')==actual_doi==target['doi'])
    from .official_copy import binding_valid
    official_bound=bool(citation.get('latest_verified') and actual_doi==target['doi']==citation.get('doi') and
                       any(binding_valid(b,identity,citation,path) for b in citation.get('public_copy_bindings',[])))
    identifier_match=doi_match or publisher_bound or official_bound
    pdf_preprint_version=None
    if arxiv_id:
        from .paper_bibliography import arxiv
        match=re.search(r'(?i)arxiv\s*:\s*'+re.escape(arxiv(arxiv_id))+r'(?:v(\d+))?\b',text)
        identifier_match=bool(match);pdf_preprint_version=int(match[1]) if match and match[1] else None
    linked=actual_doi==target['doi'] and not arxiv_id
    if not linked:
        related=citation.get('related_identifiers',[])
        linked=bool(citation.get('latest_verified') and citation.get('doi')==target['doi'] and ('arxiv:'+arxiv_id in related if arxiv_id else 'doi:'+actual_doi in related))
    title_match = normalize(identity['title']) in normalize(text)
    author_text=author_text_normalize(text)
    author_match = bool(identity.get('authors')) and all(len(normalize(author_text_normalize(a.split()[-1])))>=2 and re.search(r'(?<!\w)'+re.escape(normalize(author_text_normalize(a.split()[-1])))+r'(?:[0-9]{1,2})?(?!\w)',author_text) for a in identity['authors'])
    if not (title_match and author_match and identifier_match and linked):
        raise DomainError('institution_pdf_identity_mismatch')
    return {'doi_in_pdf':doi_match,'formal_doi_in_pdf':target['doi'] in found,'publisher_bound_identifier':publisher_bound,'official_copy_bound_identifier':official_bound,'linked_publication':linked,'pdf_identifier':('arxiv:'+arxiv_id if arxiv_id else actual_doi),'pdf_preprint_version':pdf_preprint_version, 'title_in_pdf':True, 'author_in_pdf':True, 'pages_inspected':inspected,'pdf_version':target.get('pdf_version','unknown')}


def private_directory(project, user=None, base=None):
    # Absolute installation path separates copies even when project_id was copied.
    from .layout import app_dir
    marker=app_dir(project)/'project-layout.json'
    installation=json.loads(marker.read_text('utf-8')).get('installation_id','') if marker.is_file() else ''
    if installation and not re.fullmatch(r'[0-9a-f-]{36}',installation):raise DomainError('invalid_request')
    origin=str(Path(project).resolve()).casefold()+(':'+installation if installation else '')
    instance = hashlib.sha256(origin.encode()).hexdigest()[:32]
    account = user or os.environ.get('USERDOMAIN','') + '\\' + os.environ.get('USERNAME','')
    root = Path(base or Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'Knowline' / 'InstitutionalAccess')
    return root / instance / hashlib.sha256(account.encode()).hexdigest()[:24]


def protect_directory(path):
    path.mkdir(parents=True,exist_ok=True)
    if path.is_symlink() or getattr(path.stat(), 'st_file_attributes', 0) & 0x400:
        raise DomainError('institution_profile_unsafe')
    if os.name == 'nt':
        # Explicit owner SID; remove inherited access, permit owner and SYSTEM only.
        from System.Security.Principal import WindowsIdentity
        sid = str(WindowsIdentity.GetCurrent().User.Value)
        result = subprocess.run(['icacls',str(path),'/inheritance:r','/grant:r','*'+sid+':(OI)(CI)F','*S-1-5-18:(OI)(CI)F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode:
            raise DomainError('institution_profile_protection_failed')
    else:
        path.chmod(0o700)


def grant_site(root,body):
    """Explicit native/settings confirmation only; no credentials or raw redirect URL."""
    root=Path(root)
    state=json.loads((root/'status.json').read_text('utf-8'));approval=state.get('approval',{})
    if body.get('confirmed') is not True or not approval or body.get('approval_id')!=approval.get('id'):
        raise DomainError('institution_confirmation_required',409)
    config=json.loads((root/'config.json').read_text('utf-8'))
    origin=safe_url(approval['origin']);host=urlsplit(origin).hostname
    if not public_destination(origin,{host},allow_translated=config.get('allow_translated_network',False)):
        raise DomainError('institution_destination_unsafe',409)
    if len(config['allowed_origins'])>=40:raise DomainError('institution_scope_invalid')
    config['allowed_origins']=sorted(set(config['allowed_origins']+[origin]))
    atomic_json(root/'config.json',config)
    state.pop('approval',None);state.pop('blocked_site',None);state['reason']='official_site_approved_retry'
    atomic_json(root/'status.json',state)
    return approval


class InstitutionalSession:
    def __init__(self, store, private_root=None):
        self.store = store
        self.root = Path(private_root) if private_root else private_directory(store.project)
        self.process = None
        self.lock = threading.RLock()
        self.rate = {'last_attempt':0,'attempts':{}}
        self.broker_lock = threading.Lock()

    @property
    def last_attempt(self):return self.rate['last_attempt']

    @last_attempt.setter
    def last_attempt(self,value):self.rate['last_attempt']=value

    @property
    def attempts(self):return self.rate['attempts']

    def read(self, name, default):
        path = self.root / name
        return json.loads(path.read_text('utf-8')) if path.is_file() else default

    def status(self):
        with self.lock:
            config = self.read('config.json',None)
            state = self.read('status.json',{'state':'awaiting_login' if config else 'unconfigured','reason':''})
            online = self.process is not None and self.process.poll() is None
            # Retire only obsolete paper-source prompts from the old public
            # download route. This never approves an authentication origin or
            # changes the profile, entitlement, or an active download.
            approval=state.get('approval') or {}
            public_host=urlsplit(approval.get('origin','')).hostname
            if (config and not self.broker_lock.locked() and not state.get('pending') and not state.get('pdf_ready')
                    and state.get('reason')=='official_site_confirmation_required'
                    and approval.get('purpose') in {'paper_request','paper_navigation','public_pdf'}
                    and public_host in {'arxiv.org','www.frontiersin.org','frontiersin.org'}):
                state={k:v for k,v in state.items() if k not in {'approval','blocked_site'}}
                state['reason']='public_source_approval_retired'
                atomic_json(self.root/'status.json',state)
                if online and approval.get('purpose')=='paper_navigation':
                    self.command('dismiss_public_approval',{'approval_id':approval.get('id')})
            if state.get('state') == 'verified':
                try:
                    age = (datetime.now(timezone.utc)-datetime.fromisoformat(state['tested_at'])).total_seconds()
                    if age > 43200:
                        state.update(state='awaiting_test',reason='verification_stale')
                except (KeyError,ValueError):
                    state.update(state='awaiting_test',reason='verification_stale')
            verification=self.read('verification.json',None)
            if not verification and state.get('tested_at'):
                verification={k:state[k] for k in ['tested_at','tested_site','doi','pdf_version'] if k in state}
            reported=self.read('login-report.json',{}).get('reported_at')
            connection=self.read('connection.json',{})
            if reported and state.get('reason')=='browser_closed':
                state.update(state='awaiting_test',reason='session_saved_needs_recheck')
            return {'config':config,'online':online,**state,'login_reported_at':reported,'verified_pdf':verification,
                'authentication_confirmed':bool(online and connection.get('confirmed') and state.get('state') not in {'awaiting_login','expired','unconfigured'} and not state.get('approval') and not state.get('challenge_requires_user') and 'requires_user' not in state.get('reason','') and state.get('reason') not in {'browser_starting','browser_process_failed','browser_event_failed','browser_action_failed','webview2_unavailable'}),
                'task_ready':bool(config and state.get('state') in {'awaiting_test','verified'} and not state.get('approval') and not state.get('challenge_requires_user') and 'requires_user' not in state.get('reason','') and state.get('reason') not in {'subscription_denied','redirect_scope_blocked','browser_starting','browser_process_failed','browser_event_failed','browser_action_failed','webview2_unavailable'})}

    def configure(self, body):
        value = configuration(body)
        with self.lock:
            if self.process and self.process.poll() is None:
                raise DomainError('institution_close_session_first',409)
            prior = self.read('config.json',None)
            if prior and prior != value:
                self.clear()
            # pythonnet is already bundled for WebView2; no credentials enter project state.
            if os.name == 'nt':
                import clr
                clr.AddReference('System')
            protect_directory(self.root)
            atomic_json(self.root/'config.json',value)
            atomic_json(self.root/'status.json',{'state':'awaiting_login','reason':'configured'})
            return self.status()

    def command(self, action, target=None):
        atomic_json(self.root/'command.json',{'id':str(uuid.uuid4()),'action':action,'target':target})

    def require_site(self,url,purpose='paper_request'):
        # Only a host and random confirmation ID persist; raw authentication URLs
        # (including SAML tickets) stay in the renderer memory.
        p=urlsplit(str(url));origin=confirmation_origin(url)
        with self.lock:
            config=self.read('config.json',None)
            if not config:raise DomainError('institution_configuration_required')
            prior=self.read('status.json',{'state':'awaiting_login'})
            if prior.get('pending') or prior.get('pdf_ready'):raise DomainError('institution_download_busy',409)
            if prior.get('approval'):return self.status()
            prior.pop('pending',None)
            prior.update(reason='official_site_confirmation_required',blocked_site=p.hostname,
                approval={'id':str(uuid.uuid4()),'origin':origin,'purpose':purpose})
            atomic_json(self.root/'status.json',prior)
            return self.status()

    def approve_site(self,body):
        with self.lock:
            approval=grant_site(self.root,body)
            if self.process and self.process.poll() is None:self.command('approve_site',approval)
            return self.status()

    def connect(self, hidden=False):
        with self.lock:
            config=self.read('config.json',None)
            if not config:
                raise DomainError('institution_configuration_required')
            # Preserve existing profiles while supporting official HTTPS hosts
            # mapped to the proxy fake-IP range; loopback/LAN remain blocked.
            changed=config.get('allow_translated_network') is not True
            if changed:
                config['allow_translated_network']=True
                atomic_json(self.root/'config.json',config)
            if self.process and self.process.poll() is None:
                if changed:self.command('reload_network',{'show':not hidden})
                elif not hidden:self.command('show')
                return self.status()
            from .layout import app_dir
            entry = app_dir(self.store.project)/'desktop_entry.py'
            prior=self.status()
            if prior.get('verified_pdf'):atomic_json(self.root/'verification.json',prior['verified_pdf'])
            atomic_json(self.root/'launch.json',{'incoming':str(self.store.root),'hidden':hidden,
                'resume':hidden and prior.get('state') in {'awaiting_test','verified'},'prior':{k:prior[k] for k in ['tested_at','tested_site'] if k in prior}})
            command = [sys.executable,'--institution-worker',str(self.root)] if getattr(sys,'frozen',False) else [sys.executable,str(entry),'--institution-worker',str(self.root)]
            # Discard browser diagnostics: raw request/redirect URLs must never be logged.
            env = dict(os.environ)
            for key in list(env):
                if key.startswith('WEBVIEW2_'):
                    env.pop(key)
            atomic_json(self.root/'status.json',{'state':prior.get('state','awaiting_login') if hidden else 'awaiting_login','reason':'browser_starting'})
            self.discard_staged()
            for name in ['command.json','result.json']:
                (self.root/name).unlink(missing_ok=True)
            self.process = subprocess.Popen(command,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            return self.status()

    def test(self, body):
        with self.lock:
            status = self.status()
            if status.get('approval'):raise DomainError('institution_human_resolution_required',409)
            denied=self.read('target.json',{})
            same_denied_paper=denied.get('doi')==body.get('doi') and denied.get('access_url')==(body.get('access_url') or body.get('publisher_url'))
            if 'requires_user' in status.get('reason','') or status.get('reason')=='redirect_scope_blocked' or (status.get('reason')=='subscription_denied' and same_denied_paper and body.get('public_oa') is not True):
                raise DomainError('institution_human_resolution_required',409)
            if body.get('public_oa') is True and status.get('config') and not status['online']:
                self.connect(hidden=body.get('automatic') is True)
                status = self.status()
            if not status['online'] or (body.get('public_oa') is not True and status['state'] in {'unconfigured','awaiting_login','expired'}):
                raise DomainError('institution_login_required',409)
            if status.get('pending') or status.get('pdf_ready'):
                raise DomainError('institution_download_busy',409)
            if time.monotonic()-self.last_attempt < 5:
                raise DomainError('institution_rate_limited',429)
            target = paper_request(body,status['config'])
            key = hashlib.sha256((target['doi']+target['access_url']).encode()).hexdigest()
            if self.attempts.get(key,0) >= 2:
                raise DomainError('institution_manual_download_required',409)
            self.attempts[key] = self.attempts.get(key,0)+1
            self.last_attempt = time.monotonic()
            self.discard_staged()
            (self.root/'result.json').unlink(missing_ok=True)
            atomic_json(self.root/'target.json',target)
            # Set pending before queueing so concurrent commands cannot replace a test.
            atomic_json(self.root/'status.json',{'state':'awaiting_test','pending':target['id'],'reason':'single_paper_test'})
            self.command('test',target)
            return self.status()

    def cancel(self):
        with self.lock:
            if not self.read('config.json',None):raise DomainError('institution_configuration_required')
            if self.status().get('pdf_ready'):
                self.discard_staged()
                atomic_json(self.root/'status.json',{'state':'awaiting_test','reason':'cancelled'})
                (self.root/'result.json').unlink(missing_ok=True)
            self.command('cancel')
            return self.status()

    def prepare_manual(self, body):
        with self.lock:
            state=self.status()
            if not state.get('config'):raise DomainError('institution_configuration_required')
            if state.get('pending') or state.get('pdf_ready'):raise DomainError('institution_download_busy',409)
            target=paper_request(body,state['config'])
            target['access_method']='manual_import'
            self.discard_staged()
            atomic_json(self.root/'target.json',target)
            (self.root/'result.json').unlink(missing_ok=True)
            atomic_json(self.root/'status.json',{'state':'awaiting_test','reason':'manual_file_required','manual_upload_allowed':True})
            return self.status()

    def manual_upload(self, data):
        with self.lock:
            if not self.status().get('manual_upload_allowed'):raise DomainError('institution_pdf_not_ready',409)
            if not data or len(data)>MAX_PDF:raise DomainError('pdf_invalid')
            target=self.read('target.json',{})
            identifier=str(uuid.UUID(target['id']))
            path=self.store.root/('.kw-institution-'+identifier+'.pdf')
            if path.exists():raise DomainError('institution_download_busy',409)
            try:
                path.write_bytes(data)
                check=validate_pdf(path,target)
                acquired=stamp()
                atomic_json(self.root/'result.json',{'target_id':identifier,'pdf_ready':True,'sha256':digest(path),'identity_check':check,'acquired_at':acquired})
                atomic_json(self.root/'status.json',{'state':'awaiting_test','reason':'manual_pdf_checked_no_session_verification','pdf_ready':True,'target_id':identifier,'pdf_version':target['pdf_version']})
                return self.status()
            except Exception:
                path.unlink(missing_ok=True)
                raise

    def discard_staged(self):
        target=self.read('target.json',{})
        try:identifier=str(uuid.UUID(target.get('id','')))
        except (ValueError,AttributeError):return
        path=self.store.root/('.kw-institution-'+identifier+'.pdf')
        if path.exists():
            if path.is_symlink() or not path.resolve().is_relative_to(self.store.root.resolve()):raise DomainError('institution_profile_unsafe')
            try:path.unlink()
            except OSError:raise DomainError('institution_clear_pending',409)

    def clear(self):
        with self.lock:
            if self.process and self.process.poll() is None:
                self.command('close')
                try:
                    self.process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    # Stop only the worker we own. Never kill shared/daily browser processes.
                    self.process.terminate()
                    self.process.wait(timeout=5)
            self.process = None
            self.discard_staged()
            if self.root.exists():
                # Fixed instance/user leaf, checked before any recursive deletion.
                if self.root.is_symlink() or getattr(self.root.stat(),'st_file_attributes',0) & 0x400:
                    raise DomainError('institution_profile_unsafe')
                try:
                    shutil.rmtree(self.root)
                except OSError:
                    raise DomainError('institution_clear_pending',409)
            self.attempts.clear()
            return {'config':None,'state':'unconfigured','online':False,'reason':'session_cleared'}

    def import_result(self, body):
        """Called only under the existing single-writer transaction."""
        with self.lock:
            result = self.read('result.json',{})
            target = self.read('target.json',{})
            if result.get('target_id') != target.get('id') or not result.get('pdf_ready'):
                raise DomainError('institution_pdf_not_ready',409)
            path = self.store.root / ('.kw-institution-'+target['id']+'.pdf')
            final = self.store.root / filename(target.get('year'),target['title'],target.get('venue') or None,target['id'],self.store.root,self.store.config['ui_locale'])
            if not path.exists() and final.exists():
                path = final
            validate_pdf(path,target)
            if digest(path) != result['sha256']:
                raise DomainError('hash_conflict',409)
            group = None
            if body.get('domain'):
                from .project_catalog import resolve
                group = resolve(self.store.groups(),body['domain'],'group')
            # import_local owns hash deduplication, evidence links and immutable versions.
            if path != final:
                path.replace(final)
            imported = self.store.import_local({'path':str(final),'kind':'paper'})
            if imported.get('duplicate') and Path(imported['resource']['path']).name != final.name:
                final.unlink(missing_ok=True)
            resource = imported['resource']
            metadata = {'publisher_url':target['publisher_url'],'access_method':target['access_method'],
                        'pdf_identity':target.get('pdf_identity') or {k:target[k] for k in ['doi','title','authors']},
                        'pdf_version':target['pdf_version'],'pdf_version_basis':{'statement':target['version_basis'],
                            'source':target.get('version_source_url',target['publisher_url']),'asserted_by':target.get('asserted_by','user'),'identity_check':result['identity_check']},
                        'acquired_at':result['acquired_at'],'fallback_reason':target['fallback_reason']}
            if not imported.get('duplicate'):
                resource = self.store.update_resource(resource['id'],{'base_revision':resource['revision'],
                    'title':target['title'],'doi':target['doi'],'authors':target['authors'],
                    **({'year':target['year']} if target.get('year') else {}),**({'venue':target['venue']} if target.get('venue') else {}),**metadata,
                    'field_sources':{k:{'source':'acquisition_hint','locked':False} for k in ['title','doi','authors','year','venue',*metadata]}})['resource']
            from .acquisition_metadata import apply as apply_acquisition_metadata
            resource,verification=apply_acquisition_metadata(self.store,resource,target,result,bool(imported.get('duplicate')))
            # Never silently change prior version labels or user fields on a duplicate.
            if group and resource['id'] not in group['resource_ids']:
                self.store.group_members(group['id'],{'base_revision':group['revision'],'resource_ids':group['resource_ids']+[resource['id']]})
            state=self.read('status.json',{'state':'awaiting_test'})
            state.update(pdf_ready=False,imported_resource_id=resource['id'])
            state.pop('pending',None)
            atomic_json(self.root/'status.json',state)
            return {**imported,'resource':self.store.resource(resource['id']),'acquisition':metadata,
                    'metadata_verification':verification,'existing_annotations_preserved':bool(imported.get('duplicate'))}


class InstitutionalAccess(InstitutionalSession):
    """Registry over independent controlled profiles; the original leaf is untouched."""
    def __init__(self,store,private_root=None):
        super().__init__(store,private_root)
        self.children={}
        self.request_site_id=None

    @property
    def registry_root(self):return self.root.parent/(self.root.name+'-sites')

    def registry(self):
        if self.registry_root.is_symlink() or (self.registry_root.exists() and getattr(self.registry_root.stat(),'st_file_attributes',0)&0x400):raise DomainError('institution_profile_unsafe')
        path=self.registry_root/'registry.json'
        try:value=json.loads(path.read_text('utf-8')) if path.exists() else {'schema_version':1,'sites':[]}
        except (OSError,ValueError):raise DomainError('institution_registry_invalid',409)
        if not isinstance(value,dict) or value.get('schema_version')!=1 or not isinstance(value.get('sites'),list) or len(value['sites'])>20:
            raise DomainError('institution_registry_invalid',409)
        ids=[]
        for site in value['sites']:
            if not isinstance(site,dict) or not re.fullmatch(r'site_[a-f0-9]{32}',str(site.get('id',''))) or not isinstance(site.get('name'),str) or len(site['name'])>120:raise DomainError('institution_registry_invalid',409)
            ids.append(site['id'])
        if len(set(ids))!=len(ids):raise DomainError('institution_registry_invalid',409)
        return value

    def session(self,site_id='legacy'):
        if site_id=='legacy':return self
        if not any(site['id']==site_id for site in self.registry()['sites']):raise DomainError('institution_site_not_found',404)
        if site_id not in self.children:
            root=self.registry_root/site_id
            if root.is_symlink() or (root.exists() and getattr(root.stat(),'st_file_attributes',0)&0x400):raise DomainError('institution_profile_unsafe')
            child=InstitutionalSession(self.store,root);child.rate=self.rate;child.broker_lock=self.broker_lock
            self.children[site_id]=child
        return self.children[site_id]

    def all_sessions(self):return [('legacy',self)]+[(s['id'],self.session(s['id'])) for s in self.registry()['sites']]

    def site_status(self,site_id,session,name=None):
        state=InstitutionalSession.status(session)
        config=state.get('config')
        if not config:return None
        host=urlsplit(config['entry_url']).hostname
        return {**state,'id':site_id,'name':name or config.get('name') or host,'hostname':host,'entry_url':config['entry_url'],'isolated_session':True}

    def status(self):
        with self.lock:
            state=super().status();sites=[]
            legacy=self.site_status('legacy',self)
            if legacy:sites.append(legacy)
            for item in self.registry()['sites']:
                site=self.site_status(item['id'],self.session(item['id']),item['name'])
                if site:sites.append(site)
            from .institutional_presets import presets
            return {**state,'sites':sites,'presets':presets(),'multi_site':True,'busy_site_id':self.request_site_id if self.broker_lock.locked() else None}

    def connect_preset(self,body):
        from .institutional_presets import resolve
        preset=resolve(body.get('preset_id') or body.get('name'))
        # A deliberate preset selection confirms only these documented product origins.
        # Never replace an existing custom entry/profile with a preset configuration.
        value=self.add_site({'name':preset['name'],'school':preset['name'],'entry_url':preset['entry_url'],
            'allowed_origins':preset['allowed_origins'],'method':'publisher','locale':body.get('locale','zh'),'official_confirmed':True})
        session=self.session(value['site_id'])
        with session.lock:
            config=session.read('config.json',{})
            origins=sorted(set(config['allowed_origins']+preset['allowed_origins']))
            if len(origins)>40:raise DomainError('institution_scope_invalid')
            if origins!=config['allowed_origins']:
                atomic_json(session.root/'config.json',{**config,'allowed_origins':origins})
        self.site_action(value['site_id'],'connect',{})
        # Reuse the existing controlled profile but honor the selected product's
        # stable login entry, even if its saved custom entry is a paper URL.
        session.command('open_official_entry',{'entry_url':preset['entry_url']})
        return {**self.status(),'site_id':value['site_id'],'preset_id':preset['id'],'instructions':preset['instructions_en' if body.get('locale')=='en' else 'instructions_zh']}

    def add_site(self,body):
        with self.lock:
            prior=self.read('config.json',{})
            entry=safe_url(body.get('entry_url'));host=urlsplit(entry).hostname
            name=str(body.get('name') or host).strip()
            if not name or len(name)>120:raise DomainError('invalid_request')
            for site in self.status()['sites']:
                if site['hostname']==host:return {**self.status(),'site_id':site['id'],'duplicate':True}
            value={**body,'entry_url':entry,'school':body.get('school') or prior.get('school') or name,
                'allow_translated_network':body.get('allow_translated_network',prior.get('allow_translated_network',False))}
            # Validation is complete before any profile or registry is created.
            configuration(value)
            if not prior:
                super().configure(value)
                return {**self.status(),'site_id':'legacy','duplicate':False}
            registry=self.registry()
            if len(registry['sites'])>=19:raise DomainError('institution_site_limit',409)
            protect_directory(self.registry_root)
            identifier='site_'+uuid.uuid4().hex
            child=InstitutionalSession(self.store,self.registry_root/identifier)
            child.rate=self.rate;child.broker_lock=self.broker_lock
            child.configure(value)
            registry['sites'].append({'id':identifier,'name':name})
            atomic_json(self.registry_root/'registry.json',registry)
            self.children[identifier]=child
            return {**self.status(),'site_id':identifier,'duplicate':False}

    def configure(self,body):
        prior=self.read('config.json',None)
        if prior and urlsplit(safe_url(body.get('entry_url'))).hostname!=urlsplit(prior['entry_url']).hostname:
            return self.add_site(body)
        return super().configure(body)

    def route_session(self,url,site_id=None,public=False):
        host=urlsplit(safe_url(url)).hostname
        if site_id:
            session=self.session(site_id)
            if not session.read('config.json',None):raise DomainError('institution_configuration_required',409)
            return site_id,session
        sites=self.status()['sites']
        exact=[s for s in sites if s['hostname']==host]
        matches=exact or [s for s in sites if host in {urlsplit(u).hostname for u in s['config']['allowed_origins']}]
        if not matches:
            proxies=[s for s in sites if s['config']['method']=='proxy']
            if len(proxies)==1:matches=proxies
        if len(matches)==1:return matches[0]['id'],self.session(matches[0]['id'])
        if not matches and public and sites:return sites[0]['id'],self.session(sites[0]['id'])
        raise DomainError('institution_site_ambiguous' if matches else 'institution_site_required',409,site=host)

    def site_action(self,site_id,action,body=None):
        with self.lock:
            session=self.session(site_id);body=body or {};state=InstitutionalSession.status(session)
            if action=='approve-site':
                session.approve_site(body)
            elif action in {'connect','relogin','logout'}:
                if state.get('pending') or state.get('pdf_ready') or (self.broker_lock.locked() and (action!='connect' or self.request_site_id==site_id)):
                    raise DomainError('institution_download_busy',409)
                config=session.read('config.json',None)
                if not config:raise DomainError('institution_configuration_required')
                if action in {'relogin','logout'}:
                    # Each leaf owns exactly one profile; other websites are siblings.
                    session.clear()
                    InstitutionalSession.configure(session,config)
                    atomic_json(session.root/'status.json',{'state':'awaiting_login','reason':'site_session_cleared'})
                if action in {'connect','relogin'}:session.connect()
            else:raise DomainError('invalid_request')
            return {**self.status(),'site_id':site_id}

    def connect_entry(self,entry,body):
        value=self.add_site({**body,'entry_url':entry,'official_confirmed':True})
        return self.site_action(value['site_id'],'connect')

    def close_workers(self):
        for _,session in self.all_sessions():
            if session.process and session.process.poll() is None:session.command('close')
