"""Repair the domain shortcut in the installed frontend without touching data."""
import hashlib
import json
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
DIST = APP / 'dist'
MARKER = 'domain-directory-v1'


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError('Unexpected frontend version; patch was not written')
    return text.replace(old, new, 1)


def main():
    bundle = DIST / 'assets/index-DDV0cMc3.js'
    html = DIST / 'index.html'
    css = DIST / 'assets/knowline-design.css'
    source = bundle.read_text('utf-8')
    if 'className:"domain-directory"' in source:
        print('Domain shortcut repair already applied')
        return
    source = replace_once(source,
        'action:()=>{v("domains"),b&&j(!0)}',
        'action:()=>{v("domains"),C(!1),j(!1),r.onModal("domains")}')
    source = replace_once(source,
        'wide:["build","members","job","rename","discovery","groupAssign"].includes(ce)',
        'wide:["build","members","job","rename","discovery","groupAssign","domains"].includes(ce)')
    source = replace_once(source, 'title:c({build:"buildKB",',
        'title:c({domains:"groups",build:"buildKB",')
    source = replace_once(source, 'description:c({build:"buildDescription",',
        'description:c({domains:"groupDescription",build:"buildDescription",')
    directory = '''ce==="domains"&&i.jsxs("section",{className:"domain-directory",children:[i.jsxs("div",{className:"domain-directory-heading",children:[i.jsx("p",{children:r==="zh"?"选择领域查看资料，或按研究方向新建领域。":"Choose a domain to view its resources, or create one for a research topic."}),i.jsxs("button",{className:"button primary",disabled:Q,onClick:()=>Tt("group"),children:[i.jsx(Ql,{size:16}),c("newGroup")]})]}),j.length?i.jsx("div",{className:"domain-directory-list",children:j.map(o=>i.jsxs("button",{className:"domain-directory-item",onClick:()=>{Ge(""),Yt("group:"+o.id)},children:[i.jsx(zh,{size:20}),i.jsxs("span",{className:"domain-directory-label",children:[i.jsx("strong",{children:o.name}),i.jsx("small",{children:r==="zh"?(o.resource_ids||[]).length+" 份资料":(o.resource_ids||[]).length+" resources"})]}),i.jsx(Zl,{size:18})]},o.id))}):i.jsxs("div",{className:"domain-directory-empty",children:[i.jsx(Lh,{size:36}),i.jsx("h3",{children:r==="zh"?"还没有领域":"No domains yet"}),i.jsx("p",{children:r==="zh"?"点击“新建领域”，然后将论文或代码加入其中。":"Create a domain, then add papers or code to it."})]}),i.jsx("div",{className:"modal-actions",children:i.jsx("button",{className:"button",onClick:()=>Ge(""),children:r==="zh"?"关闭":"Close"})})]}),'''
    source = replace_once(source, 'onClose:()=>Ge(""),children:[re&&',
        'onClose:()=>Ge(""),children:[' + directory + 're&&')
    source = replace_once(source, '!["discovery","import"].includes(ce)',
        '!["discovery","import","domains"].includes(ce)')
    style = '''
/* Domain directory: a visible destination for the dock shortcut. */
:root .domain-directory { display:flex;flex-direction:column;gap:20px; }
:root .domain-directory-heading { display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap; }
:root .domain-directory-heading p { margin:0;color:var(--kw-muted);line-height:1.6;flex:1;min-width:220px; }
:root .domain-directory-list { display:grid;gap:12px;max-height:55vh;overflow:auto; }
:root .domain-directory-item { display:flex;align-items:center;gap:16px;width:100%;text-align:left;padding:18px 20px;border:1px solid var(--kw-border);border-radius:14px;background:var(--kw-surface);color:var(--kw-text);cursor:pointer; }
:root .domain-directory-item:hover { background:var(--kw-hover);border-color:var(--kw-accent); }
:root .domain-directory-item:focus-visible { outline:2px solid var(--kw-focus);outline-offset:2px; }
:root .domain-directory-label { display:flex;flex-direction:column;gap:6px;flex:1;min-width:0; }
:root .domain-directory-label strong { overflow-wrap:anywhere;font-size:15px; }
:root .domain-directory-label small { color:var(--kw-muted); }
:root .domain-directory-empty { display:flex;flex-direction:column;align-items:center;gap:12px;text-align:center;padding:32px 16px;color:var(--kw-muted); }
:root .domain-directory-empty h3 { margin:0;color:var(--kw-text); }
:root .domain-directory-empty p { margin:0;line-height:1.6; }
'''
    document = html.read_text('utf-8').replace('kw_ui=brain-nodes-v1', 'kw_ui=' + MARKER)
    document = document.replace('knowline-design.css?v=20261013-8',
                                'knowline-design.css?v=20261013-domain-directory-1')
    bundle.write_text(source, 'utf-8')
    css.write_text(css.read_text('utf-8') + style, 'utf-8')
    html.write_text(document, 'utf-8')
    info_file = DIST / 'build-info.json'
    info = json.loads(info_file.read_text('utf-8'))
    for file in (bundle, css, html):
        relative = file.relative_to(DIST).as_posix()
        info.setdefault('assets', {})[relative] = hashlib.sha256(file.read_bytes()).hexdigest()
    info['domain_navigation_fix'] = {
        'version': MARKER,
        'behavior': 'Dock opens a domain chooser; empty state offers domain creation',
        'application_tests': 'not_run_at_user_request',
    }
    info_file.write_text(json.dumps(info, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    print('Repaired domain shortcut, chooser and cache version; user data unchanged')


if __name__ == '__main__':
    main()
