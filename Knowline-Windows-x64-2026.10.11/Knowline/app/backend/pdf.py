import math
import os
import struct
import zlib
from pathlib import Path
import pymupdf as fitz
from .safety import DomainError, hash_bytes, json_text


def render_region(path, page_index, rect, geometry_hash, target):
    """Crop rendered pixels in displayed-page coordinates, including PDF rotation."""
    if not isinstance(rect,list) or len(rect)!=4 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in rect):raise DomainError('invalid_geometry')
    x0,y0,x1,y1=rect
    if not 0<=x0<x1<=1 or not 0<=y0<y1<=1:raise DomainError('invalid_geometry')
    with open_pdf(path) as doc:
        if isinstance(page_index,bool) or not isinstance(page_index,int) or not 0<=page_index<len(doc):raise DomainError('invalid_page')
        page=doc[page_index]
        if geometry(page)['hash']!=geometry_hash:raise DomainError('geometry_conflict',409)
        # Bound work for exceptionally large PDF pages; ordinary pages render at 180 DPI.
        scale=min(2.5,2400/max(page.rect.width,page.rect.height))
        pix=page.get_pixmap(matrix=fitz.Matrix(scale,scale),colorspace=fitz.csRGB,alpha=False)
        left,top,right,bottom=int(x0*pix.width),int(y0*pix.height),math.ceil(x1*pix.width),math.ceil(y1*pix.height)
        width,height=right-left,bottom-top
        if width<4 or height<4:raise DomainError('invalid_geometry')
        samples=pix.samples
        raw=b''.join(b'\0'+samples[row*pix.stride+left*3:row*pix.stride+right*3] for row in range(top,bottom))
    def chunk(kind,data):return struct.pack('!I',len(data))+kind+data+struct.pack('!I',zlib.crc32(kind+data)&0xffffffff)
    target.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b''))
    return {'path':str(target),'width':width,'height':height,'sha256':hash_bytes(target.read_bytes())}


def open_pdf(path):
    try:
        doc = fitz.open(path)
        if doc.needs_pass:
            doc.close()
            raise DomainError('pdf_encrypted')
        return doc
    except (fitz.FileDataError, RuntimeError):
        raise DomainError('pdf_invalid')


def writable(doc, path, allow_readonly_source=False):
    if doc.is_encrypted or not doc.permissions & fitz.PDF_PERM_ANNOTATE:
        raise DomainError('pdf_restricted')
    if any(doc.xref_get_key(x, 'FT')[1] == '/Sig' for x in range(1, doc.xref_length())):
        raise DomainError('pdf_signed')
    if not allow_readonly_source and not os.access(path, os.W_OK):
        raise DomainError('file_read_only')


def geometry(page):
    raw = {'mediabox': list(page.mediabox), 'cropbox': list(page.cropbox), 'rect': list(page.rect), 'rotation': page.rotation, 'pdf_to_mupdf': list(page.transformation_matrix), 'derotation': list(page.derotation_matrix)}
    raw['hash'] = hash_bytes(json_text(raw).encode())
    return raw


def page_info(path, page_index, editable_path=None, allow_readonly_source=False):
    with open_pdf(path) as doc:
        if page_index < 0 or page_index >= len(doc):
            raise DomainError('invalid_page')
        page = doc[page_index]
        # get_text returns unrotated MuPDF coordinates, including crop adaptation.
        words = [{'rect': list(w[:4]), 'text': w[4], 'block': w[5], 'line': w[6], 'word': w[7]} for w in page.get_text('words')]
        readonly = None
        try:
            writable(doc, editable_path or path, allow_readonly_source)
        except DomainError as exc:
            readonly = exc.code
        return {'page_index': page_index, 'page_label': page.get_label() or str(page_index + 1), 'page_count': len(doc), 'geometry': geometry(page), 'text': page.get_text(), 'words': words, 'readonly': readonly}


def annotations(path):
    result = []
    with open_pdf(path) as doc:
        for page in doc:
            for a in page.annots() or []:
                result.append({'pdf_nm': a.info.get('id'), 'xref': a.xref, 'kind': 'highlight' if a.type[0] == fitz.PDF_ANNOT_HIGHLIGHT else 'text' if a.type[0] == fitz.PDF_ANNOT_TEXT else 'readonly', 'page_index': page.number, 'page_label': page.get_label() or str(page.number + 1), 'comment': a.info.get('content', ''), 'color': a.colors.get('stroke'), 'rect': list(a.rect), 'vertices': a.vertices, 'page_geometry_hash': geometry(page)['hash']})
    return result


def save_annotation(path, candidate, spec, current=None, allow_readonly_source=False):
    with open_pdf(path) as doc:
        writable(doc, path, allow_readonly_source)
        page_count = len(doc)
        page_index = spec.get('page_index', current.get('page_index') if current else -1)
        if not isinstance(page_index, int) or page_index < 0 or page_index >= len(doc):
            raise DomainError('invalid_page')
        page = doc[page_index]
        if spec.get('page_geometry_hash') != geometry(page)['hash']:
            raise DomainError('geometry_conflict', 409)
        action = spec.get('action', 'create')
        color = spec.get('color', current.get('color') if current and current.get('color') else [1, .78, .24])
        if len(color) != 3 or any(not isinstance(c, (float, int)) or not math.isfinite(c) or c < 0 or c > 1 for c in color):
            raise DomainError('invalid_geometry')
        if current:
            found = [a for a in page.annots() or [] if (a.info.get('id') == current['pdf_nm'] if current.get('pdf_nm') else a.xref==current.get('xref'))]
            if len(found) != 1 or found[0].type[0] not in {fitz.PDF_ANNOT_TEXT, fitz.PDF_ANNOT_HIGHLIGHT}:
                raise DomainError('annotation_conflict', 409)
            annot = found[0]
            if action=='move':
                rect=spec.get('rect')
                if current['kind']!='text' or page_index!=current['page_index'] or not isinstance(rect,list) or len(rect)!=4 or any(not isinstance(v,(int,float)) or not math.isfinite(v) for v in rect):raise DomainError('invalid_geometry')
                target_rect=fitz.Rect(rect);bounds=page.rect*page.derotation_matrix
                if target_rect.is_empty or not bounds.contains(target_rect) or abs(target_rect.width-annot.rect.width)>.5 or abs(target_rect.height-annot.rect.height)>.5:raise DomainError('invalid_geometry')
                annot.set_rect(target_rect)
            if action == 'delete':
                page.delete_annot(annot)
                annot = None
        elif spec.get('kind') == 'highlight':
            quads = spec.get('quads', [])
            if not quads or len(quads) > 200:
                raise DomainError('invalid_geometry')
            valid = []
            for quad in quads:
                if len(quad) != 4 or any(len(p) != 2 or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in p) for p in quad):
                    raise DomainError('invalid_geometry')
                q = fitz.Quad(quad)
                bounds = page.rect * page.derotation_matrix
                if not q.is_convex or q.is_empty or not bounds.contains(q.rect):
                    raise DomainError('invalid_geometry')
                valid.append(q)
            # DOM range rectangles can repeat a span or overlap nested text runs.
            # Merge only coplanar horizontal runs; keep rotated quadrilateral geometry intact.
            dedup={tuple(round(v,3) for point in q for v in point):q for q in valid}
            valid=[]
            for q in sorted(dedup.values(),key=lambda q:(round(q.ul.y,1),q.ul.x)):
                horizontal=abs(q.ul.y-q.ur.y)<.1 and abs(q.ll.y-q.lr.y)<.1 and abs(q.ul.x-q.ll.x)<.1 and abs(q.ur.x-q.lr.x)<.1
                prior=valid[-1] if valid else None
                if horizontal and prior and abs(prior.ul.y-q.ul.y)<.5 and abs(prior.ll.y-q.ll.y)<.5 and q.ul.x<=prior.ur.x+.5 and abs(prior.ul.y-prior.ur.y)<.1:
                    valid[-1]=fitz.Quad(fitz.Rect(min(prior.ul.x,q.ul.x),min(prior.ul.y,q.ul.y),max(prior.ur.x,q.ur.x),max(prior.ll.y,q.ll.y)).quad)
                else:valid.append(q)
            if not page.get_text().strip():
                raise DomainError('pdf_no_text')
            annot = page.add_highlight_annot(valid)
        elif spec.get('kind') == 'text':
            point = spec.get('point', [48, 48])
            if len(point) != 2 or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in point) or not (page.rect * page.derotation_matrix).contains(fitz.Point(point)):
                raise DomainError('invalid_geometry')
            annot = page.add_text_annot(point, str(spec.get('comment', ''))[:10000])
        else:
            raise DomainError('invalid_annotation')
        nm = None
        if annot:
            comment=str(spec.get('comment', current.get('comment','') if current else ''))[:10000]
            annot.set_info(content=comment, title='Knowledge Workbench')
            annot.set_colors(stroke=color)
            annot.update()
            nm = annot.info.get('id')
        # Imported annotations may have no /NM. Preserve xrefs as their stable
        # identity instead of renumbering every remaining annotation on save.
        doc.save(candidate, garbage=0, deflate=True)
    with open_pdf(candidate) as verified:
        if len(verified) != page_count:
            raise DomainError('pdf_save_failed')
        if nm:
            verified_page = verified[page_index]
            matches = [a for a in verified_page.annots() or [] if a.info.get('id') == nm]
            if len(matches) != 1 or matches[0].info.get('content') != comment:
                raise DomainError('pdf_save_failed')
    return nm
