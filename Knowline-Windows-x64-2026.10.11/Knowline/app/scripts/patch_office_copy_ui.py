"""Apply the partial-result copy gate to this release's bundled task UI."""
from pathlib import Path
import re


def patch(app):
    html = (app / 'dist/index.html').read_text('utf-8')
    name = re.search(r'src="/assets/([^"?]+\.js)', html).group(1)
    path = app / 'dist/assets' / name
    text = path.read_text('utf-8')
    old = 'disabled:o.status!=="completed",title:o.status!=="completed"?'
    new = 'disabled:!["completed","partial"].includes(o.status),title:!["completed","partial"].includes(o.status)?'
    if text.count(new) == 1:
        return path
    if text.count(old) != 1:
        raise ValueError('Expected exactly one Office-copy status gate')
    anchor = text.index(old)
    if '/copy-office' not in text[anchor:anchor + 400]:
        raise ValueError('Status gate is not the Office copy button')
    path.write_text(text.replace(old, new, 1), encoding='utf-8')
    return path


if __name__ == '__main__':
    print(patch(Path(__file__).resolve().parents[1]))
