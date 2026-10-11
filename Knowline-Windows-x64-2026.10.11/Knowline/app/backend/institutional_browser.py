"""Dedicated WebView2: PDF streams and fixed bibliographic fields; no credential export."""
import json
import re
import base64
import os
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit
from .institutional_access import public_destination, stamp, validate_pdf, MAX_PDF, safe_url, grant_site, confirmation_origin
from .safety import atomic_json, digest, DomainError

# Only booleans leave the authentication page, locally. No input values,
# page text, HTML, headers, credentials, cookies or storage are evaluated.
READINESS_SCRIPT = r'''(() => { const present = selector => Array.from(document.querySelectorAll(selector)).some(e => {
  const r=e.getBoundingClientRect(), s=getComputedStyle(e);
  return r.width>0 && r.height>0 && s.display!=='none' && s.visibility!=='hidden';
}); return JSON.stringify({
  loading: document.readyState === 'loading',
  challenge: present('iframe[src*="captcha"],iframe[src*="challenge"],#challenge-form,#cf-challenge-running'),
  login: present('input[type=password],form input[autocomplete=username],form[action*="login"] input,form[action*="signin"] input'),
  authenticated: present('a[href*="logout" i],a[href*="signout" i],a[href*="sign-out" i],button[id*="logout" i],button[aria-label="Sign out" i],button[aria-label="Log out" i]')
}); })()'''


def challenge_resource(uri):
    """Recognize a blocked verification script; this never grants network access."""
    p=urlsplit(str(uri));host=(p.hostname or '').lower()
    return p.scheme=='https' and not p.username and not p.password and p.port in {None,443} and host.endswith(('.token.awswaf.com','.captcha.awswaf.com','.sdk.awswaf.com')) and p.path.lower().endswith(('/challenge.js','/captcha.js'))


def publisher_version(target, data, page_url):
    """Identify IEEE's original PDF only from a matching formal article page."""
    record=target.get('citation_record') or {}
    page=urlsplit(str(page_url));origin=urlsplit(str(record.get('publisher_url','')))
    if (target.get('pdf_version')=='unknown' and record.get('publication_status')=='published'
            and record.get('latest_verified') and page.scheme=='https'
            and page.hostname==origin.hostname=='ieeexplore.ieee.org'
            and re.fullmatch(r'/document/\d+/?',page.path)
            and page.path.rstrip('/')==origin.path.rstrip('/')
            and str(data.get('doi','')).strip().lower()==record.get('doi')
            and urlsplit(str(data.get('pdf',''))).hostname=='ieeexplore.ieee.org'):
        target.update(pdf_version='published',version_basis='IEEE original article page identifies the publisher PDF for the independently verified DOI',
            version_source_url=safe_url(page_url),fallback_reason='')
        return True
    return False


def run(root):
    root = Path(root).resolve()
    config = json.loads((root/'config.json').read_text('utf-8'))
    launch = json.loads((root/'launch.json').read_text('utf-8'))
    incoming = Path(launch['incoming']).resolve()
    hosts = {urlsplit(u).hostname for u in config['allowed_origins']}
    en = config['locale'] == 'en'
    import clr
    clr.AddReference('System.Windows.Forms')
    clr.AddReference('System.Drawing')
    import webview
    lib = Path(webview.__file__).parent/'lib'
    clr.AddReference(str(lib/'Microsoft.Web.WebView2.Core.dll'))
    clr.AddReference(str(lib/'Microsoft.Web.WebView2.WinForms.dll'))
    os.environ['PATH'] = str(lib/'runtimes/win-x64/native') + os.pathsep + os.environ.get('PATH','')
    from System.Drawing import Size, Color, Font
    from System.Threading import Thread, ThreadStart, ApartmentState
    from System.Diagnostics import Process
    from Microsoft.Web.WebView2.WinForms import WebView2, CoreWebView2CreationProperties
    from Microsoft.Web.WebView2.Core import CoreWebView2WebResourceContext,CoreWebView2PermissionState
    import System.Windows.Forms as F

    def window_main():
        F.Application.EnableVisualStyles()
        F.Application.SetCompatibleTextRenderingDefault(False)
        form = F.Form()
        form.Text = 'Knowline · ' + ('Institutional Access · ' if en else '机构访问 · ') + config['school']
        form.Size = Size(1180,850)
        form.Font = Font('Microsoft YaHei UI',10)
        hidden = launch.get('hidden',False)
        if hidden:
            form.Opacity = 0
            form.ShowInTaskbar = False
        browser = WebView2()
        browser.Dock = F.DockStyle.Fill
        browser.DefaultBackgroundColor = Color.White
        props = CoreWebView2CreationProperties()
        props.UserDataFolder = str(root/'profile')
        props.AdditionalBrowserArguments = '--disk-cache-size=16777216 --media-cache-size=8388608 --disable-breakpad --disable-crash-reporter'
        browser.CreationProperties = props
        toolbar = F.FlowLayoutPanel()
        toolbar.Dock = F.DockStyle.Top
        toolbar.Height = 100
        toolbar.AutoScroll = True
        label = F.Label()
        label.AutoSize = True
        label.MaximumSize = Size(1100,0)
        label.Text = 'Sign in yourself; then start a task in Knowline. Each paper’s access is checked on download.' if en else '请自行登录，随后可直接回到知序启动任务。每篇论文的权限在下载时核验。'
        toolbar.Controls.Add(label)
        toolbar.SetFlowBreak(label,True)
        # Separate rows keep BringToFront/loading notices from covering the
        # publisher header (including its Institutional Sign In control).
        content = F.Panel()
        content.Dock = F.DockStyle.Fill
        content.Margin = F.Padding(0)
        content.Controls.Add(browser)
        layout = F.TableLayoutPanel()
        layout.Dock = F.DockStyle.Fill
        layout.ColumnCount = 1
        layout.RowCount = 2
        layout.RowStyles.Add(F.RowStyle(F.SizeType.Absolute,100))
        layout.RowStyles.Add(F.RowStyle(F.SizeType.Percent,100))
        toolbar.Dock = F.DockStyle.Fill
        toolbar.Margin = F.Padding(0)
        layout.Controls.Add(toolbar,0,0)
        layout.Controls.Add(content,0,1)
        form.Controls.Add(layout)
        notice = F.Label()
        notice.Dock = F.DockStyle.Fill
        notice.BackColor = Color.White
        notice.ForeColor = Color.FromArgb(35,45,55)
        notice.Padding = F.Padding(24,24,24,24)
        notice.Text = 'Opening the official website…' if en else '正在打开官方网站…'
        content.Controls.Add(notice)
        notice.BringToFront()
        toolbar.BringToFront()
        target = None
        operation = None
        pending_stream = None
        navigation_failure = None
        path = None
        seen = None
        refs = []  # Keep Python.NET delegates alive through asynchronous download events.
        ready = False
        last_state = {'state':'awaiting_login','reason':'user_login_required'}
        started = 0
        metadata_task = None
        metadata_due = None
        metadata_started = None
        pdf_followed = False
        pdf_destinations = set()
        blocked_navigation = None
        initializing_at = time.monotonic()
        opening_at = None
        login_entry = config['entry_url']
        challenge_blocked = False
        navigation_id = None
        stopped_navigations = set()
        readiness_task = None
        readiness_navigation = None
        readiness_due = None
        page_loaded = False
        connection_confirmed = False
        atomic_json(root/'connection.json',{'confirmed':False})

        def open_entry(entry=None):
            nonlocal opening_at,login_entry,challenge_blocked,blocked_navigation
            if entry is not None:login_entry=entry
            challenge_blocked=False
            blocked_navigation=None
            confirmation_button.Visible=False
            opening_at=time.monotonic()
            explain('Opening the official website…' if en else '正在打开官方网站…')
            browser.CoreWebView2.Navigate(login_entry)

        def show():
            if launch.get('interactive') is False:return # Isolated synthetic test harness only.
            form.Opacity = 1
            form.ShowInTaskbar = True
            # Show/Activate keep a minimized WinForms window minimized. A
            # subsequent Connect must restore it without replacing its profile.
            if form.WindowState == F.FormWindowState.Minimized:
                form.WindowState = F.FormWindowState.Normal
            form.Show()
            form.Activate()
            # Restored/hidden workers deliberately initialize on about:blank.
            # Bringing one forward must open its configured entry in the same profile.
            if ready and target is None and str(browser.CoreWebView2.Source) in {'','about:blank'}:
                open_entry()

        # Fixed selectors, no arbitrary model-provided JavaScript. Authentication
        # fields are only detected as booleans; their values and DOM never leave.
        metadata_script = r'''(() => {
          const flags=JSON.parse(READINESS_FLAGS_SCRIPT);
          if(flags.challenge) return JSON.stringify({challenge:true});
          if(flags.login) return JSON.stringify({login:true});
          const get=(name)=>Array.from(document.querySelectorAll('meta')).filter(m=>m.name.toLowerCase()===name).slice(0,20).map(m=>(m.content||'').slice(0,500));
          const links=Array.from(document.querySelectorAll('a[href]')).slice(0,500);
          const ieee=location.hostname==='ieeexplore.ieee.org'?globalThis.xplGlobal?.document?.metadata||{}:{};
          const pdf=get('citation_pdf_url')[0]||String(ieee.pdfUrl||'')||links.find(a=>/\.pdf(?:\?|$)|\/stamp\/stamp.jsp|\/doi\/pdf\/|\/article\/file\?/i.test(a.href))?.href||Array.from(document.querySelectorAll('iframe[src]')).find(e=>/\.pdf(?:\?|$)|\/stampPDF\/getPDF.jsp/i.test(e.src))?.src||'';
          const records=links.filter(a=>/\/document\/|\/doi\/(?:abs\/)?10\.|\/article\/|\/full-record\//i.test(a.href)&&a.textContent.trim().length>12).slice(0,20).map(a=>({title:a.textContent.trim().slice(0,500),url:a.href}));
          const journal=get('citation_journal_title')[0]||'',conference=get('citation_conference_title')[0]||'',arxiv=get('citation_arxiv_id')[0]||/^(?:export\.)?arxiv\.org$/.test(location.hostname);
          const kind=String(ieee.contentType||'');
          const names=get('citation_author');
          return JSON.stringify({authenticated:flags.authenticated,title:get('citation_title')[0]||String(ieee.title||'').slice(0,500),doi:get('citation_doi')[0]||String(ieee.doi||'').slice(0,200),authors:names.length?names:(Array.isArray(ieee.authors?.authors)?ieee.authors.authors:[]).slice(0,100).map(a=>String(a.name||'').slice(0,120)),date:get('citation_publication_date')[0]||get('citation_date')[0]||String(ieee.publicationYear||'').slice(0,40),venue:arxiv?'arXiv':journal||conference||String(ieee.publicationTitle||'').slice(0,200),source_type:arxiv?'Report':conference||/conference/i.test(kind)?'ConferenceProceedings':journal||/journal/i.test(kind)?'JournalArticle':'',pdf:pdf?new URL(pdf,location.href).href:'',records});
        })()'''.replace('READINESS_FLAGS_SCRIPT',READINESS_SCRIPT)

        def protocol(method,parameters):
            return browser.CoreWebView2.CallDevToolsProtocolMethodAsync(method,json.dumps(parameters))

        def guarded(handler):
            def invoke(sender,args):
                try:
                    handler(sender,args)
                except Exception as exc:
                    try:pause('awaiting_test' if ready else 'awaiting_login','browser_event_failed')
                    except Exception:status('awaiting_test' if ready else 'awaiting_login','browser_event_failed')
            refs.append(invoke)
            return invoke

        def status(state, reason='', **values):
            nonlocal last_state
            last_state = {'state':state,'reason':reason,**values}
            atomic_json(root/'status.json',last_state)
            readable={
                'user_login_required':('Sign in yourself in the official page below.','请在下方官方网站自行登录。'),
                'sign_in_required':('Sign in yourself below; no extra confirmation is needed.','请在下方自行登录，无需再次报告登录完成。'),
                'session_ready_for_tasks':('Connected. Return to Knowline to start a task; PDF access is checked per paper.','已连接。可回到知序启动任务；PDF 权限逐篇核验。'),
                'authenticated_session_ready':('Signed in. Return to Knowline to start a task; PDF access is checked per paper.','已登录。可回到知序启动任务；PDF 权限逐篇核验。'),
                'official_page_loaded':('Official page loaded. Each paper still needs an access check.','官方网站已加载；各篇论文的访问权限仍需分别核验。'),
                'browser_ready':('Session ready. Connect opens the official page.','会话已准备，连接后打开官方网站。'),
                'login_navigation_failed':('Official page failed to load. Use Home / login to retry.','官方网站未能加载，请点击“返回官方登录”重试。'),
                'browser_process_failed':('Browser rendering stopped; close and reconnect.','浏览器渲染已停止，请关闭窗口后重新连接。')}
            label.Text = readable.get(reason,(state+' · '+reason,state+' · '+reason))[0 if en else 1]

        def stage(value,uri=None):
            values={k:v for k,v in last_state.items() if k not in {'state','reason'}}
            values.update(request_stage=value,stage_at=stamp())
            if uri:values['destination_site']=urlsplit(str(uri)).hostname
            status(last_state['state'],last_state.get('reason',''),**values)

        def explain(message):
            notice.Text=message
            notice.Visible=True
            notice.BringToFront()
            toolbar.BringToFront()

        def stop_download():
            nonlocal operation, target, path, pending_stream,metadata_task,metadata_due,metadata_started
            if pending_stream and pending_stream.get('handle') and ready:
                protocol('IO.close',{'handle':pending_stream['handle']})
            pending_stream = None
            if operation is not None:
                try: operation.Cancel()
                except Exception: pass
            operation = None
            target = None
            metadata_task = None
            metadata_due = None
            metadata_started = None
            if ready and not browser.IsDisposed and browser.CoreWebView2 is not None:
                if navigation_id is not None:
                    stopped_navigations.add(navigation_id)
                    if len(stopped_navigations)>8:
                        stopped_navigations.remove(min(stopped_navigations))
                protocol('Fetch.disable',{})
                browser.CoreWebView2.Stop()
            if path and path.exists():
                try:path.unlink()
                except OSError:pass
            path = None

        def pause(state, reason):
            diagnostics={k:last_state[k] for k in ['request_stage','stage_at','destination_site'] if k in last_state}
            stop_download()
            status(state,reason,**diagnostics)
            if state in {'expired','awaiting_login'} or 'requires_user' in reason or reason in {'redirect_scope_blocked','subscription_denied'}:
                show()

        def confirm_navigation(approval):
            nonlocal blocked_navigation
            confirmation_button.Visible=False
            config.update(json.loads((root/'config.json').read_text('utf-8')))
            hosts.update(urlsplit(u).hostname for u in config['allowed_origins'])
            pending=blocked_navigation;blocked_navigation=None
            if pending and pending['id']==approval.get('id') and pending['resume'] and allowed(pending['uri']):
                status('awaiting_login','user_login_required')
                browser.CoreWebView2.Navigate(pending['uri'])
            else:status('awaiting_test','official_site_approved_retry')

        def approve_in_window(s,e):
            approval=last_state.get('approval')
            if not approval:return
            try:confirm_navigation(grant_site(root,{'confirmed':True,'approval_id':approval['id']}))
            except DomainError as exc:label.Text=('Cannot approve this destination: ' if en else '该目标不能批准：')+exc.code

        def button(text, callback):
            control = F.Button()
            control.Text = text
            control.AutoSize = True
            control.Click += callback
            refs.append(callback)
            toolbar.Controls.Add(control)
            return control

        confirmation_button=button('Confirm displayed official site' if en else '确认当前显示的官方站点',approve_in_window)
        confirmation_button.Visible=False
        def return_to_knowline(s,e):
            form.Hide()
            form.ShowInTaskbar=False
        button('Return to Knowline' if en else '返回知序',return_to_knowline)
        # Manual reporting remains available without filling the main toolbar.
        help_menu=F.ContextMenuStrip()
        for title,state,reason in [('Verification challenge / pause' if en else '验证挑战 / 暂停','awaiting_test','challenge_requires_user'),('No subscription' if en else '此论文无订阅权限','awaiting_test','subscription_denied'),('Session expired' if en else '登录已过期','expired','session_expired')]:
            item=F.ToolStripMenuItem(title)
            callback=lambda s,e,state=state,reason=reason:pause(state,reason)
            refs.append(callback);item.Click+=callback;help_menu.Items.Add(item)
        button('Cancel' if en else '取消',lambda s,e:pause('awaiting_test','cancelled'))
        def home(s,e):
            if ready and target is None:
                status('awaiting_login','user_login_required')
                open_entry()
        button('Home / login' if en else '返回官方登录',home)
        def help_click(s,e):help_menu.Show(s,0,s.Height)
        button('Access help' if en else '访问帮助',help_click)

        def allowed(uri):
            return public_destination(str(uri),hosts,allow_translated=config.get('allow_translated_network',False))

        def blocked(uri):
            nonlocal blocked_navigation
            p=urlsplit(str(uri));resume=target is None
            pause('awaiting_test' if target else 'awaiting_login','redirect_scope_blocked')
            try:
                origin=confirmation_origin(uri)
                if p.hostname in hosts:
                    status(last_state['state'],'institution_destination_unsafe',blocked_site=p.hostname)
                    explain('The official page did not finish loading. Return to the sign-in entry to retry; the cause is unconfirmed.' if en else '官方网站加载未完成，可返回登录入口重试；具体原因尚未确认。')
                    return
                approval={'id':str(uuid.uuid4()),'origin':origin,'purpose':'authentication_navigation' if resume else 'paper_navigation'}
                blocked_navigation={'id':approval['id'],'uri':str(uri),'resume':resume}
                status(last_state['state'],'official_site_confirmation_required',blocked_site=p.hostname,approval=approval)
                confirmation_button.Visible=True
                label.Text=('Confirm only if your institution/publisher identifies this official site: ' if en else '仅在学校或出版方确认它为官方服务时，点击确认：')+p.hostname
            except DomainError:status(last_state['state'],'redirect_scope_blocked',blocked_site=p.hostname)

        def navigation(sender,args):
            nonlocal challenge_blocked,navigation_id,page_loaded,readiness_due,readiness_task,metadata_due,metadata_task
            navigation_id=int(args.NavigationId)
            page_loaded=False;readiness_due=None;readiness_task=None
            metadata_due=None;metadata_task=None
            if not allowed(args.Uri):
                args.Cancel = True
                blocked(args.Uri)
            else:
                challenge_blocked=False
                if target is not None:notice.Visible=False

        def resource_requested(sender,args):
            # Apply to every request, including scripts, frames, fetch, WebSocket handshakes.
            if not allowed(args.Request.Uri):
                args.Response = browser.CoreWebView2.Environment.CreateWebResourceResponse(None,403,'Blocked', 'Content-Type: text/plain')
                if challenge_resource(args.Request.Uri):
                    blocked_challenge(args.Request.Uri)

        def blocked_challenge(uri):
            nonlocal blocked_navigation,challenge_blocked
            if last_state.get('approval'):return
            challenge_blocked=True
            resume=target is None
            current=str(browser.CoreWebView2.Source)
            pause('awaiting_test','challenge_requires_user')
            try:
                origin=confirmation_origin(uri)
                approval={'id':str(uuid.uuid4()),'origin':origin,'purpose':'challenge_resource'}
                # Approval reloads the original official document, never the
                # third-party script URL. Automated acquisition stays paused.
                blocked_navigation={'id':approval['id'],'uri':current,'resume':resume}
                status('awaiting_test','official_site_confirmation_required',blocked_site=urlsplit(origin).hostname,approval=approval,challenge_requires_user=True)
                confirmation_button.Visible=True
                label.Text=('Verification service blocked; confirm only if the publisher identifies this official service: ' if en else '验证服务受到访问范围限制；仅在出版方确认此服务时批准：')+urlsplit(origin).hostname
            except DomainError:status('awaiting_test','challenge_requires_user')
            explain('This page requires a verification service outside the approved scope. Confirm it only after checking with the publisher, complete verification yourself, or download manually and import. Automatic acquisition is paused.' if en else '此页需要尚未批准的验证服务。请先向出版方核实，再确认该站点并自行完成验证；也可合法手动下载后导入。自动获取已暂停。')

        def resource_received(sender,args):
            nonlocal challenge_blocked
            if str(args.Request.Uri)!=str(browser.CoreWebView2.Source):return
            headers=args.Response.Headers
            aws=headers.GetHeader('x-amzn-waf-action').lower() if headers.Contains('x-amzn-waf-action') else ''
            cf=headers.GetHeader('cf-mitigated').lower() if headers.Contains('cf-mitigated') else ''
            if aws not in {'challenge','captcha'} and cf!='challenge':return
            challenge_blocked=True
            if last_state.get('approval'):return
            if target is not None:pause('awaiting_test','challenge_requires_user')
            else:
                # Leave the approved page visible for the human's verification.
                notice.Visible=False
                status('awaiting_test','challenge_requires_user')
                label.Text='Complete verification yourself in the official page. Automatic acquisition is paused.' if en else '请在官方网站自行完成验证。自动获取已暂停。'

        def frame_navigation(sender,args):
            # Advertisements and embedded third-party frames are denied without
            # cancelling an otherwise approved publisher PDF request.
            if not allowed(args.Uri):
                args.Cancel = True

        def new_window(sender,args):
            args.Handled = True
            if allowed(args.Uri):
                browser.CoreWebView2.Navigate(str(args.Uri))
            else:
                blocked(args.Uri)

        def completed(sender,args):
            nonlocal navigation_failure,metadata_due,opening_at,page_loaded,readiness_due
            identifier=int(args.NavigationId)
            if identifier in stopped_navigations:
                stopped_navigations.discard(identifier)
                return
            if navigation_id is not None and identifier!=navigation_id:return
            if target is None:
                opening_at=None
                # Stop() may finish a challenged/blocked navigation with
                # ConnectionAborted. Preserve the actionable pause/approval.
                if last_state.get('approval'):return
                if challenge_blocked:
                    status('awaiting_test','challenge_requires_user')
                    return
                if (not args.IsSuccess and str(args.WebErrorStatus)!='OperationCanceled') or int(args.HttpStatusCode)>=400:
                    # A failed article navigation does not invalidate an already
                    # authenticated profile. Only visible login/401 does that.
                    status('awaiting_test' if connection_confirmed else 'awaiting_login','login_navigation_failed',http_status=int(args.HttpStatusCode),web_error=str(args.WebErrorStatus))
                    explain('The official page did not finish loading. Return to the sign-in entry to retry; the cause is unconfirmed.' if en else '官方网站加载未完成，可返回登录入口重试；具体原因尚未确认。')
                elif args.IsSuccess and challenge_blocked and not last_state.get('approval'):
                    status('awaiting_test','challenge_requires_user')
                elif args.IsSuccess and str(browser.CoreWebView2.Source)!='about:blank' and not last_state.get('approval'):
                    notice.Visible=False
                    status(last_state['state'],'official_page_loaded',**{k:v for k,v in last_state.items() if k not in {'state','reason'}})
                    page_loaded=True;readiness_due=time.monotonic()+.5
                return
            code = int(args.HttpStatusCode)
            if code == 401:
                pause('expired','session_expired')
            elif code in {403,429}:
                pause('awaiting_test','permission_or_challenge_requires_user' if code == 403 else 'rate_limit_requires_user')
            elif not args.IsSuccess and operation is None:
                # WebView2 cancels document navigation BEFORE raising DownloadStarting for attachments.
                if str(args.WebErrorStatus) != 'OperationCanceled':
                    navigation_failure = time.monotonic()+2
            elif args.IsSuccess and code==200 and target.get('automatic') and operation is None and pending_stream is None:
                # Allow rendered metadata to settle, then inspect once locally.
                metadata_due=time.monotonic()+2
                stage('article_loaded',browser.CoreWebView2.Source)

        def accept_pdf(output,current):
            nonlocal target,path,pending_stream
            try:
                check = validate_pdf(output,current)
                acquired = stamp()
                atomic_json(root/'verification.json',{'tested_at':acquired,'tested_site':urlsplit(current['access_url']).hostname,'doi':current['doi'],'pdf_version':current['pdf_version']})
                atomic_json(root/'result.json',{'target_id':current['id'],'pdf_ready':True,
                    'sha256':digest(output),'identity_check':check,'acquired_at':acquired,'source_metadata':current.get('source_metadata',{})})
                status('verified','single_paper_pdf_verified',tested_at=acquired,
                    tested_site=urlsplit(current['access_url']).hostname,doi=current['doi'],
                    target_id=current['id'],pdf_ready=True,pdf_version=current['pdf_version'],
                    access_method=current['access_method'])
                target = None
                path = None
                pending_stream = None
                protocol('Fetch.disable',{})
            except DomainError as exc:
                pause('awaiting_test',exc.code)
            except Exception:
                pause('awaiting_test','pdf_validation_failed')

        def response_paused(sender,args):
            nonlocal pending_stream,path,challenge_blocked
            # Read only PDF bodies. Authentication HTML and credential headers stay opaque.
            data = json.loads(args.ParameterObjectAsJson)
            request_id = data['requestId']
            if not allowed(data['request']['url']):
                protocol('Fetch.failRequest',{'requestId':request_id,'errorReason':'BlockedByClient'})
                return
            headers = {h['name'].lower():h['value'] for h in data.get('responseHeaders',[]) if h['name'].lower() in {'content-type','content-length','content-disposition','cf-mitigated','x-amzn-waf-action'}}
            if headers.get('cf-mitigated','').lower() == 'challenge' or headers.get('x-amzn-waf-action','').lower() in {'challenge','captcha'}:
                challenge_blocked=True
                protocol('Fetch.failRequest',{'requestId':request_id,'errorReason':'Aborted'})
                pause('awaiting_test','challenge_requires_user')
                return
            if target and target.get('kind')!='lookup' and operation is None and pending_stream is None and headers.get('content-type','').lower().split(';')[0].strip() == 'application/pdf' and data.get('responseStatusCode') == 200 and 'attachment' not in headers.get('content-disposition','').lower():
                if headers.get('content-length','').isdigit() and int(headers['content-length'])>MAX_PDF:
                    protocol('Fetch.failRequest',{'requestId':request_id,'errorReason':'Aborted'})
                    pause('awaiting_test','pdf_too_large')
                    return
                # Capture the original network stream before the PDF viewer transforms it.
                # No second network request, DOM evaluation, JS bridge or CookieManager.
                path = incoming/('.kw-institution-'+target['id']+'.pdf')
                pending_stream = {'stage':'open','task':protocol('Fetch.takeResponseBodyAsStream',{'requestId':request_id}),
                                  'request_id':request_id,'target':dict(target),'path':path,'size':0}
                stage('pdf_response_stream',data['request']['url'])
            else:
                protocol('Fetch.continueRequest',{'requestId':request_id})

        def download(sender,args):
            nonlocal operation,path
            if not target or target.get('kind')=='lookup' or operation is not None or not allowed(args.DownloadOperation.Uri):
                args.Cancel = True
                return
            op = args.DownloadOperation
            if int(op.TotalBytesToReceive) > MAX_PDF:
                args.Cancel = True
                pause('awaiting_test','pdf_too_large')
                return
            path = incoming/('.kw-institution-'+target['id']+'.pdf')
            args.ResultFilePath = str(path)
            args.Handled = True
            operation = op
            stage('download_started',op.Uri)
            current = dict(target)
            output = path

            def bytes_changed(s,e):
                if int(op.BytesReceived) > MAX_PDF:
                    pause('awaiting_test','pdf_too_large')

            def state_changed(s,e):
                nonlocal operation,target,path
                if operation is not op:
                    return
                state = str(op.State)
                if state == 'Interrupted':
                    pause('awaiting_test','download_interrupted_manual_retry')
                elif state == 'Completed':
                    operation = None
                    accept_pdf(output,current)

            refs.extend([bytes_changed,state_changed])
            op.BytesReceivedChanged += bytes_changed
            op.StateChanged += state_changed

        def initialize(sender,args):
            nonlocal ready
            if not args.IsSuccess:
                status('awaiting_login','webview2_unavailable')
                explain('The browser could not initialize. Close this window and reconnect.' if en else '登录浏览器未能初始化，请关闭此窗口后重新连接。')
                return
            core = browser.CoreWebView2
            settings = core.Settings
            settings.IsWebMessageEnabled = False
            settings.AreHostObjectsAllowed = False
            settings.AreDevToolsEnabled = False
            settings.AreDefaultContextMenusEnabled = False
            settings.AreBrowserAcceleratorKeysEnabled = False
            settings.IsStatusBarEnabled = False
            settings.IsPasswordAutosaveEnabled = False
            settings.IsGeneralAutofillEnabled = False
            core.NavigationStarting += guarded(navigation)
            core.FrameNavigationStarting += guarded(frame_navigation)
            core.NavigationCompleted += guarded(completed)
            core.NewWindowRequested += guarded(new_window)
            core.DownloadStarting += guarded(download)
            receiver = core.GetDevToolsProtocolEventReceiver('Fetch.requestPaused')
            refs.append(receiver)
            receiver.DevToolsProtocolEventReceived += guarded(response_paused)
            core.AddWebResourceRequestedFilter('*',CoreWebView2WebResourceContext.All)
            core.WebResourceRequested += guarded(resource_requested)
            core.WebResourceResponseReceived += guarded(resource_received)
            def deny_permission(s,e):
                e.State = CoreWebView2PermissionState.Deny
            refs.append(deny_permission)
            core.PermissionRequested += deny_permission
            def process_failed(s,e):
                pause('awaiting_test' if target else 'awaiting_login','browser_process_failed')
                explain('The browser stopped rendering. Close this window and reconnect; your session is preserved.' if en else '浏览器渲染已停止。请关闭此窗口后重新连接，现有会话会保留。')
            refs.append(process_failed)
            core.ProcessFailed += guarded(process_failed)
            ready = True
            prior=launch.get('prior',{})
            status('awaiting_test' if launch.get('resume') else 'awaiting_login','browser_ready' if hidden else 'user_login_required',**prior)
            if not hidden or (not launch.get('resume') and launch.get('fixture_login')):open_entry()
            if hidden:form.Hide()

        def tick(sender,args):
            nonlocal seen,target,started,pending_stream,navigation_failure,metadata_task,metadata_due,metadata_started,pdf_followed,pdf_destinations,readiness_task,readiness_due,readiness_navigation,challenge_blocked,blocked_navigation,connection_confirmed
            try:
                if not ready and time.monotonic()-initializing_at>30:
                    explain('Browser initialization is taking too long. Close this window and reconnect.' if en else '登录浏览器初始化超时，请关闭此窗口后重新连接。')
                elif opening_at and time.monotonic()-opening_at>30:
                    explain('The official page is still loading. Check the network or proxy, then use Home / login to retry.' if en else '官方网站加载超时。请检查网络或代理，再点击“返回官方登录”重试。')
                if (page_loaded and target is None and not last_state.get('approval') and not challenge_blocked
                        and last_state.get('reason') in {'official_page_loaded','sign_in_required','session_ready_for_tasks','authenticated_session_ready'}):
                    if readiness_task is None and readiness_due and time.monotonic()>=readiness_due:
                        readiness_navigation=navigation_id
                        readiness_task=browser.CoreWebView2.ExecuteScriptAsync(READINESS_SCRIPT)
                        readiness_due=time.monotonic()+1
                    if readiness_task is not None and readiness_task.IsCompleted:
                        task=readiness_task;readiness_task=None
                        if readiness_navigation==navigation_id and not task.IsFaulted:
                            flags=json.loads(json.loads(task.Result))
                            if flags.get('challenge'):
                                challenge_blocked=True
                                connection_confirmed=False
                                atomic_json(root/'connection.json',{'confirmed':False})
                                status('awaiting_test','challenge_requires_user')
                            elif not flags.get('loading'):
                                state,reason=('awaiting_login','sign_in_required') if flags.get('login') else ('awaiting_test','session_ready_for_tasks')
                                confirmed=bool(flags.get('authenticated') and not flags.get('login'))
                                if confirmed:reason='authenticated_session_ready'
                                if confirmed!=connection_confirmed:
                                    atomic_json(root/'connection.json',{'confirmed':confirmed,'checked_at':stamp(),'basis':'visible_sign_out_control' if confirmed else 'sign_in_check'})
                                    connection_confirmed=confirmed
                                if last_state.get('state')!='verified' or flags.get('login'):
                                    if (last_state.get('state'),last_state.get('reason'))!=(state,reason):status(state,reason,authentication_confirmed=confirmed)
                if metadata_due and time.monotonic()>metadata_due and target and metadata_task is None and operation is None and pending_stream is None:
                    metadata_due=None
                    metadata_task=browser.CoreWebView2.ExecuteScriptAsync(metadata_script)
                    metadata_started=time.monotonic()
                    stage('bibliographic_page_check',browser.CoreWebView2.Source)
                if metadata_task and not metadata_task.IsCompleted and metadata_started and time.monotonic()-metadata_started>20:
                    pause('awaiting_test','publisher_metadata_timeout')
                if metadata_task and metadata_task.IsCompleted:
                    current=target
                    task=metadata_task;metadata_task=None
                    metadata_started=None
                    if current and task.IsFaulted:
                        stage('publisher_metadata_retry')
                        if time.monotonic()-started<45:metadata_due=time.monotonic()+1
                        else:pause('awaiting_test','publisher_metadata_unavailable')
                    if current and not task.IsFaulted:
                        data=json.loads(json.loads(task.Result))
                        stage('publisher_metadata_received')
                        if data.get('challenge') or data.get('login'):
                            connection_confirmed=False;atomic_json(root/'connection.json',{'confirmed':False})
                        elif data.get('authenticated') and not connection_confirmed:
                            connection_confirmed=True;atomic_json(root/'connection.json',{'confirmed':True,'checked_at':stamp(),'basis':'visible_sign_out_control'})
                        if data.get('challenge'):pause('awaiting_test','challenge_requires_user')
                        elif data.get('login'):pause('expired','session_expired')
                        elif current.get('kind')=='lookup':
                            records=[]
                            for record in data.get('records',[])[:20]:
                                try:
                                    url=safe_url(record['url'])
                                    if allowed(url):records.append({'title':record['title'][:500],'url':url})
                                except DomainError:pass
                            from .acquisition_metadata import capture
                            record=capture(data,str(browser.CoreWebView2.Source),stamp())
                            bibliography=record.get('bibliography',{})
                            # Validate DOI rather than persisting arbitrary meta content.
                            import re
                            if not re.fullmatch(r'10\.\d{4,9}/\S{1,180}',str(bibliography.get('doi',''))):bibliography['doi']=''
                            atomic_json(root/'lookup.json',{'target_id':current['id'],'site':urlsplit(current['access_url']).hostname,
                                'retrieved_at':stamp(),'source_url':record.get('url'),'bibliography':bibliography,'records':records,
                                'limitation':'' if records or bibliography.get('title') else 'no_supported_bibliographic_markup',
                                'scope':'metadata_only_not_pdf_entitlement'})
                            prior=current.get('prior_state','awaiting_test')
                            previous=current.get('prior',{})
                            stop_download();status(prior,'metadata_read_no_pdf_verification',**previous)
                        else:
                            from .acquisition_metadata import capture
                            captured=capture(data,str(browser.CoreWebView2.Source),stamp())
                            if captured.get('bibliography',{}).get('doi')==current.get('doi') or not current.get('source_metadata'):
                                current['source_metadata']=captured
                            if publisher_version(current,data,str(browser.CoreWebView2.Source)):
                                atomic_json(root/'target.json',current)
                            destination=data.get('pdf') or (current['access_url'] if not pdf_followed and current['access_url']!=str(browser.CoreWebView2.Source) else '')
                            unseen=bool(destination and destination not in pdf_destinations)
                            if unseen:stage('publisher_pdf_destination_check',destination)
                            if unseen and len(pdf_destinations)<4 and allowed(destination):
                                pdf_destinations.add(destination)
                                pdf_followed=True
                                # Signed PDF links stay ephemeral inside the controlled session.
                                browser.CoreWebView2.Navigate(destination)
                                stage('pdf_navigation',destination)
                            elif unseen and len(pdf_destinations)>=4:pause('awaiting_test','publisher_pdf_navigation_limit')
                            elif unseen:blocked(destination)
                            elif not pdf_followed:
                                # Publisher SPAs often finish rendering citation
                                # fields/PDF controls after NavigationCompleted.
                                if time.monotonic()-started<45:metadata_due=time.monotonic()+1
                                else:pause('awaiting_test','publisher_pdf_link_unavailable')
                if pending_stream and pending_stream['task'].IsCompleted:
                    pending = pending_stream
                    if pending['task'].IsFaulted:
                        pause('awaiting_test','native_pdf_stream_unavailable_manual_download')
                    else:
                        value = json.loads(pending['task'].Result)
                        if pending['stage']=='open':
                            pending['handle']=value['stream']
                            pending['stage']='read'
                            pending['path'].write_bytes(b'')
                        else:
                            chunk = base64.b64decode(value.get('data','')) if value.get('base64Encoded') else value.get('data','').encode('utf-8')
                            pending['size'] += len(chunk)
                            if pending['size'] > MAX_PDF:
                                pause('awaiting_test','pdf_too_large')
                            else:
                                with pending['path'].open('ab') as file:file.write(chunk)
                                if value.get('eof'):
                                    protocol('IO.close',{'handle':pending['handle']})
                                    # Aborting the consumed stream completes its
                                    # navigation asynchronously. Preserve the
                                    # successful PDF result against that event.
                                    if navigation_id is not None:stopped_navigations.add(navigation_id)
                                    protocol('Fetch.failRequest',{'requestId':pending['request_id'],'errorReason':'Aborted'})
                                    pending_stream=None
                                    accept_pdf(pending['path'],pending['target'])
                        if pending_stream:
                            pending['task']=protocol('IO.read',{'handle':pending['handle'],'size':1024*1024})
                if navigation_failure and time.monotonic()>navigation_failure and target and operation is None and pending_stream is None:
                    pause('awaiting_test','navigation_failed_manual_review')
                    navigation_failure = None
                if target and time.monotonic()-started > 300:
                    pause('awaiting_test','test_timeout_manual_retry')
                command_file = root/'command.json'
                if not command_file.exists():
                    return
                command = json.loads(command_file.read_text('utf-8'))
                if command['id'] == seen:
                    return
                if not ready and command['action'] != 'close':
                    return
                seen = command['id']
                if command['action'] == 'close':
                    form.Close()
                elif command['action'] == 'show':
                    show()
                elif command['action'] == 'open_official_entry':
                    config.update(json.loads((root/'config.json').read_text('utf-8')))
                    hosts.clear();hosts.update(urlsplit(u).hostname for u in config['allowed_origins'])
                    entry=safe_url(command.get('target',{}).get('entry_url'))
                    if target is not None or not allowed(entry):return
                    status('awaiting_login','user_login_required')
                    open_entry(entry)
                    show()
                elif command['action'] == 'reload_network':
                    config.update(json.loads((root/'config.json').read_text('utf-8')))
                    hosts.clear();hosts.update(urlsplit(u).hostname for u in config['allowed_origins'])
                    if command.get('target',{}).get('show'):show()
                    if target is None:
                        status('awaiting_login','user_login_required')
                        open_entry()
                elif command['action'] == 'approve_site':
                    confirm_navigation(command['target'])
                elif command['action'] == 'dismiss_public_approval':
                    approval=last_state.get('approval') or {}
                    if target is None and approval.get('id')==command.get('target',{}).get('approval_id') and approval.get('purpose')=='paper_navigation':
                        blocked_navigation=None;confirmation_button.Visible=False
                        status(last_state['state'],'public_source_approval_retired')
                elif command['action'] == 'cancel':
                    pause('awaiting_test','cancelled')
                elif command['action'] == 'test':
                    stop_download()
                    target = command['target']
                    pdf_followed=False
                    pdf_destinations={target.get('metadata_url') or target['access_url']}
                    navigation_failure = None
                    started = time.monotonic()
                    status('awaiting_test','automatic_browser_request' if target.get('automatic') else 'select_pdf_in_this_window',pending=target['id'],request_stage='article_navigation',stage_at=stamp(),destination_site=urlsplit(target.get('metadata_url') or target['access_url']).hostname)
                    if not target.get('automatic'):show()
                    protocol('Fetch.enable',{'patterns':[{'urlPattern':'*','resourceType':'Document','requestStage':'Response'}]})
                    browser.CoreWebView2.Navigate(target.get('metadata_url') or target['access_url'])
            except Exception:
                pause('awaiting_test','browser_action_failed')

        timer = F.Timer()
        timer.Interval = 500
        timer.Tick += tick
        timer.Start()
        browser.CoreWebView2InitializationCompleted += guarded(initialize)
        def shown(s,e):
            try:browser.EnsureCoreWebView2Async(None)
            except Exception:
                status('awaiting_login','webview2_unavailable')
                explain('The browser could not initialize. Close this window and reconnect.' if en else '登录浏览器未能初始化，请关闭此窗口后重新连接。')
        form.Shown += shown
        def closing(s,e):
            timer.Stop()
            if ready and not browser.IsDisposed and browser.CoreWebView2 is not None:
                pid = int(browser.CoreWebView2.BrowserProcessId)
                stop_download()
                browser.Dispose()
                try:Process.GetProcessById(pid).WaitForExit(3000)
                except Exception:pass
        form.FormClosing += closing
        F.Application.Run(form)
        if last_state.get('reason') in {'session_ready_for_tasks','authenticated_session_ready','official_page_loaded'} and last_state['state']=='awaiting_test':
            status('awaiting_test','session_saved_needs_recheck')
        elif (last_state['state'] not in {'verified','expired'} and not last_state.get('approval')
                and 'requires_user' not in last_state.get('reason','')
                and last_state.get('reason') not in {'subscription_denied','redirect_scope_blocked','login_navigation_failed','browser_process_failed','browser_event_failed','browser_action_failed'}):
            status('awaiting_login','browser_closed')

    thread = Thread(ThreadStart(window_main))
    thread.SetApartmentState(ApartmentState.STA)
    thread.Start()
    # Python delegates run on the STA thread; don't hold the GIL in Thread.Join.
    while thread.IsAlive:time.sleep(.1)
