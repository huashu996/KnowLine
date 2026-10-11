"""Stable identities and plain paragraph text for linked numeric references."""
import re
import xml.etree.ElementTree as ET


def citation_tags(code):
    return list(dict.fromkeys(re.findall(r'\bKW[0-9a-f]{24}\b',code)))


def reference_text(xml):
    root=ET.fromstring(xml)
    def value(name):
        return next((n.text or '' for n in root if n.tag.endswith('}'+name)), '').strip()
    authors=[]
    for person in root.iter():
        if person.tag.endswith('}Person'):
            names={n.tag.rsplit('}',1)[-1]:n.text or '' for n in person}
            authors.append(' '.join(filter(None,[names.get('Last'),names.get('First'),names.get('Middle')])).strip())
    if not authors:
        authors=[n.text for n in root.iter() if n.tag.endswith('}Corporate') and n.text]
    kind=value('SourceType')
    mark={'JournalArticle':'J','ConferenceProceedings':'C','Book':'M','Report':'R'}.get(kind,'')
    title=value('Title')+('['+mark+']' if mark else '')
    if 'formal publication not verified' in value('Comments'):title+='（预印本，正式出版未核实）'
    venue=value('JournalName') or value('ConferenceName') or value('BookTitle') or value('Publisher')
    publication=', '.join(filter(None,[venue,value('Year')]))
    volume=value('Volume')+('('+value('Issue')+')' if value('Issue') else '')
    if volume:publication+=', '+volume
    if value('Pages'):publication+=': '+value('Pages')
    parts=[', '.join(authors),title,publication]
    if value('DOI'):parts.append('DOI: '+value('DOI'))
    elif value('URL'):parts.append(value('URL'))
    return '. '.join(p.rstrip('.') for p in parts if p)+'.'


def reference_bookmark(tag):return 'KWREF'+tag[2:]
def citation_bookmark(tag):return 'KWBACK'+tag[2:]
