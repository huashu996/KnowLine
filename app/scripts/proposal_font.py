"""Make a new Song-font Word copy without rebuilding content, fields or equations."""
import argparse
import json
import os
import tempfile
import zipfile
from pathlib import Path
from lxml import etree as ET

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
M = 'http://schemas.openxmlformats.org/officeDocument/2006/math'
NS = {'w': W, 'm': M}


def set_font(properties, font):
    node = properties.find('w:rFonts', NS)
    if node is None:
        node = ET.Element('{%s}rFonts' % W)
        # rStyle precedes rFonts in CT_RPr.
        properties.insert(1 if len(properties) and properties[0].tag == '{%s}rStyle' % W else 0, node)
    for name in ('asciiTheme', 'hAnsiTheme', 'eastAsiaTheme', 'cstheme', 'csTheme'):
        node.attrib.pop('{%s}%s' % (W, name), None)
    for name in ('ascii', 'hAnsi', 'eastAsia', 'cs'):
        node.set('{%s}%s' % (W, name), font)


def properties(parent):
    node = parent.find('w:rPr', NS)
    if node is None:
        node = ET.SubElement(parent, '{%s}rPr' % W) if parent.tag == '{%s}style' % W else ET.Element('{%s}rPr' % W)
        if node.getparent() is None:
            parent.insert(0, node)
    return node


def convert(source, target, font='宋体'):
    source, target = Path(source).resolve(), Path(target).resolve()
    if source == target or target.exists():
        raise ValueError('Save to a new DOCX path; existing documents are preserved')
    if source.suffix.lower() != '.docx' or target.suffix.lower() != '.docx':
        raise ValueError('DOCX files required')
    count = equations = 0
    parser = ET.XMLParser(resolve_entities=False, no_network=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=target.parent, suffix='.docx')
    os.close(fd)
    try:
        with zipfile.ZipFile(source) as src, zipfile.ZipFile(temporary, 'w') as dst:
            for info in src.infolist():
                data = src.read(info.filename)
                if info.filename.startswith('word/') and info.filename.endswith('.xml'):
                    root = ET.fromstring(data, parser)
                    before_text = root.xpath('//w:t/text() | //w:instrText/text() | //m:t/text()', namespaces=NS)
                    before_math = [ET.tostring(n) for n in root.xpath('//m:oMath', namespaces=NS)]
                    # Include body, headings, hyperlinks, tables, headers and footnotes.
                    runs = root.xpath('//w:r[not(ancestor::m:oMath) and not(ancestor::m:oMathPara)]', namespaces=NS)
                    for run in runs:
                        set_font(properties(run), font)
                    for style in root.xpath('//w:style', namespaces=NS):
                        name = style.find('w:name', NS)
                        label = style.get('{%s}styleId' % W, '') + (name.get('{%s}val' % W, '') if name is not None else '')
                        if any(s in label.casefold() for s in ('math', 'equation', '公式')):
                            continue
                        set_font(properties(style), font)
                    for node in root.xpath('//w:docDefaults/w:rPrDefault/w:rPr | //w:pPr/w:rPr[not(ancestor::m:oMath)]', namespaces=NS):
                        set_font(node, font)
                    assert before_text == root.xpath('//w:t/text() | //w:instrText/text() | //m:t/text()', namespaces=NS)
                    assert before_math == [ET.tostring(n) for n in root.xpath('//m:oMath', namespaces=NS)]
                    count += len(runs)
                    equations += len(before_math)
                    data = ET.tostring(root, encoding='UTF-8', xml_declaration=True, standalone=True)
                dst.writestr(info, data)
        # Exclusive publication keeps a concurrent writer's file safe.
        with open(temporary, 'rb') as src, target.open('xb') as dst:
            import shutil
            shutil.copyfileobj(src, dst)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return {'font': font, 'text_runs': count, 'native_equations_preserved': equations, 'output': str(target)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('target', type=Path)
    parser.add_argument('--font', default='宋体', help='Only override for an explicit user font request')
    args = parser.parse_args()
    print(json.dumps(convert(args.source, args.target, args.font), ensure_ascii=False))
