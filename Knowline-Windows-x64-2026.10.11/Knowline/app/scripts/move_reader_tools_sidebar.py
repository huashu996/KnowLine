"""Keep resource-specific Office tools in the PDF reader's own left sidebar."""
from pathlib import Path
import re

APP=Path(__file__).resolve().parents[1]

HELPER='''
function kwReaderOfficeTools({label,children}){
 return e.jsx("aside",{className:"reader-office-fallback is-active","aria-label":label,
  children:e.jsxs("section",{className:"reader-office-tools","aria-label":label,
   children:[e.jsx("h3",{children:label}),children]})});
}
'''

CSS='''
/* knowline-reader-tools-sidebar */
.reader-office-tools{margin:0 0 16px;padding:12px;border:1px solid #dfe7e2;border-radius:10px;background:#f4f7f5;min-width:0}
.reader-office-tools h3{margin:0 0 10px;font-size:13px;font-weight:650;color:#527261}
.reader-office-tools .office-copy-bar{position:static;inset:auto;z-index:auto;display:flex;flex-direction:column;align-items:stretch;gap:9px;flex-wrap:nowrap;padding:0;border:0;background:transparent;opacity:1;transform:none;pointer-events:auto;transition:none;box-shadow:none;font-size:12px}
.reader-office-tools .office-copy-bar select{width:100%;min-width:0;min-height:36px;font-size:12px}
.reader-office-tools .office-copy-bar>.small-button{width:100%;min-height:40px;display:flex;align-items:center;justify-content:flex-start;gap:8px;text-align:left;white-space:normal;line-height:1.5;padding:8px 10px;font-size:12px}
.reader-office-tools .office-copy-bar>.small-button svg{flex-shrink:0}
.reader-office-tools .office-copy-bar>span{white-space:normal;line-height:1.6;font-size:11px}
.pdf-reader{display:grid;grid-template-columns:minmax(0,1fr);grid-template-rows:auto auto minmax(0,1fr) auto;min-width:0}
.pdf-reader>.reader-toolbar{grid-column:1/-1;grid-row:1}
.pdf-reader>.placement-status{grid-column:1/-1;grid-row:2}
.pdf-reader>.pdf-scroll{grid-column:1;grid-row:3;min-width:0;min-height:0}
.pdf-reader>.reader-footnote{grid-column:1;grid-row:4}
.reader-office-fallback{display:none}
.pdf-reader:has(>.reader-office-fallback.is-active){grid-template-columns:180px minmax(0,1fr)}
.reader-office-fallback.is-active{display:block;grid-column:1;grid-row:2/5;overflow:auto;min-height:0;padding:12px;background:#fbfcfb;border-right:1px solid #e3e8e5}
.reader-office-fallback .reader-office-tools{padding:0;border:0;background:transparent}
.pdf-reader:has(>.reader-office-fallback.is-active)>.pdf-scroll,.pdf-reader:has(>.reader-office-fallback.is-active)>.placement-status,.pdf-reader:has(>.reader-office-fallback.is-active)>.reader-footnote{grid-column:2}
@media(max-width:700px){.pdf-reader:has(>.reader-office-fallback.is-active){grid-template-columns:142px minmax(0,1fr)}.reader-office-fallback.is-active{padding:9px}.reader-office-tools .office-copy-bar>.small-button{padding:7px;font-size:11px}}
/* end-knowline-reader-tools-sidebar */
'''

def balanced_call(text,at):
    start=text.index('(',at);depth=0;quote=None;escaped=False
    for index in range(start,len(text)):
        char=text[index]
        if quote:
            if escaped:escaped=False
            elif char=='\\':escaped=True
            elif char==quote:quote=None
        elif char in ('"',"'",'`'):quote=char
        elif char=='(':depth+=1
        elif char==')':
            depth-=1
            if not depth:return index+1
    raise ValueError('Unclosed JSX call')

def patch():
    index=(APP/'dist/index.html').read_text('utf-8')
    main=APP/'dist/assets'/re.search(r'src="/assets/([^"?]+\.js)',index).group(1)
    source=main.read_text('utf-8')
    reader=main.parent/re.search(r'import\("\./(Readers-[^"?]+\.js)(?:\?[^\"]*)?"\)',source).group(1)
    css=main.parent/'Readers-BFx-3cGW.css'
    body=reader.read_text('utf-8');styles=css.read_text('utf-8')
    if 'function kwReaderOfficeTools(' in body:
        start=body.index('function kwReaderOfficeTools(')
        end=body.index('export{Pt as CodeReader,Mt as PDFReader};',start)
        body=body[:start]+HELPER.lstrip()+body[end:]
        source=source.replace('i.jsx("div",{id:"reader-office-tools-slot"}),','')
        styles=re.sub(r'/\* knowline-reader-tools-sidebar \*/.*?/\* end-knowline-reader-tools-sidebar \*/',CSS.strip(),styles,flags=re.S)
        for path,value in [(main,source),(reader,body),(css,styles)]:path.write_text(value,'utf-8')
        print('Reader controls now belong only to the PDF left sidebar.');return
    anchor='className:"nav-content",ref:G,children:['
    assert source.count(anchor)==1
    assert source.count('export{_h as A,')==1
    source=source.replace('export{_h as A,','export{fg as kwOfficePortal,_h as A,',1)
    for old,new in {
        'captureTextEquations:"截图识别正文与公式"':'readerTools:"阅读工具",captureTextEquations:"截图识别正文与公式"',
        'captureTextEquations:"Recognize text and equations from a screenshot"':'readerTools:"Reading tools",captureTextEquations:"Recognize text and equations from a screenshot"',
    }.items():
        assert source.count(old)==1;source=source.replace(old,new,1)
    body=body.replace('import{c as Re,','import{kwOfficePortal,c as Re,',1)
    old='onPointerMove:t=>He(t.clientY>t.currentTarget.getBoundingClientRect().bottom-90),onPointerLeave:()=>He(!1),'
    assert body.count(old)==1;body=body.replace(old,'',1)
    start=body.index('e.jsxs("div",{className:"office-copy-bar "+(We||ze?"is-visible":""),')
    end=balanced_call(body,start)
    bar=body[start:end].replace('className:"office-copy-bar "+(We||ze?"is-visible":"")','className:"office-copy-bar"',1)
    body=body[:start]+'e.jsx(kwReaderOfficeTools,{label:a("readerTools"),children:'+bar+'})'+body[end:]
    # The confirmation dialog must not inherit sidebar overflow/transforms.
    start=body.index('k&&e.jsx("div",{className:"modal-backdrop",')+3
    end=balanced_call(body,start)
    body=body[:start]+'kwOfficePortal.createPortal('+body[start:end]+',document.body)'+body[end:]
    assert body.count('export{Pt as CodeReader,Mt as PDFReader};')==1
    body=body.replace('export{Pt as CodeReader,Mt as PDFReader};',HELPER+'export{Pt as CodeReader,Mt as PDFReader};',1)
    styles=re.sub(r'\.pdf-reader \.office-copy-bar(?:\.is-visible,\.pdf-reader \.office-copy-bar:focus-within)?\{[^}]*\}','',styles)
    source_path=[main,reader,css]
    for path,value in zip(source_path,[source,body,styles+CSS]):path.write_text(value,'utf-8')
    print('Moved Office controls into the PDF reader left sidebar with body-level dialogs.')

if __name__=='__main__':patch()
