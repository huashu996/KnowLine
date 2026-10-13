"""Give one release update a consistent module URL, including lazy imports.

The release edits built bundles in place; their original build hashes otherwise
leave browsers free to reuse old scripts. All module references use the same
revision to avoid loading two copies of the main React application.
"""
from pathlib import Path
import re,sys

APP=Path(__file__).resolve().parents[1]

def version(revision):
    if not re.fullmatch(r'[a-z0-9-]{1,80}',revision):raise ValueError('Invalid revision')
    reference=re.compile(r'([\"\'])((?:\./|/assets/|assets/)[^\"\'\s?#]+\.(?:js|mjs|css))(?:\?kw_(?:ui|graph)=[a-z0-9-]+)?\1')
    changed=[]
    for path in [APP/'dist/index.html',*(APP/'dist/assets').glob('*.js'),*(APP/'dist/assets').glob('*.mjs')]:
        source=path.read_text('utf-8')
        updated=reference.sub(lambda m:m[1]+m[2]+'?kw_ui='+revision+m[1],source)
        # Vite decides whether to create a stylesheet from the extension;
        # the query revision must not turn a CSS preload into a JS preload.
        if path.name=='index-DDV0cMc3.js':
            updated=updated.replace('M.endsWith(".css")','M.split("?",1)[0].endsWith(".css")')
        if updated!=source:
            path.write_text(updated,'utf-8');changed.append(path.name)
    print('Updated consistent frontend asset URLs:',len(changed),'files; revision:',revision)

if __name__=='__main__':version(sys.argv[1])
