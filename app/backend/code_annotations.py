"""Validate sidecar annotations against inert, versioned code text."""
import math
from .safety import DomainError


def validate(file, spec):
    if spec.get('kind') not in {'highlight', 'text'}:
        raise DomainError('invalid_annotation')
    if spec.get('file_sha256') != file['sha256']:
        raise DomainError('hash_conflict', 409)
    lines = file['text'].split('\n')
    start, end = spec.get('line_start'), spec.get('line_end')
    if type(start) is not int or type(end) is not int or not 1 <= start <= end <= len(lines):
        raise DomainError('invalid_code_range')
    # Browser offsets use UTF-16 code units, including surrogate pairs.
    widths = lambda s: len(s.encode('utf-16-le')) // 2
    left, right = spec.get('column_start', 0), spec.get('column_end', widths(lines[end-1]))
    if type(left) is not int or type(right) is not int or not 0 <= left <= widths(lines[start-1]) or not 0 <= right <= widths(lines[end-1]) or (start == end and left >= right):
        raise DomainError('invalid_code_range')
    try:
        parts = lines[start-1:end]
        parts[0] = parts[0].encode('utf-16-le')[left*2:].decode('utf-16-le')
        parts[-1] = parts[-1].encode('utf-16-le')[:(right-left if start == end else right)*2].decode('utf-16-le')
    except UnicodeError:
        raise DomainError('invalid_code_range')
    quote = '\n'.join(parts)
    if not quote or spec.get('quote') != quote:
        raise DomainError('code_quote_mismatch', 409)
    comment = spec.get('comment', '')
    color = spec.get('color', [1, .78, .24])
    if not isinstance(comment, str) or len(comment) > 10000 or (spec['kind'] == 'text' and not comment.strip()):
        raise DomainError('invalid_annotation')
    if not isinstance(color, list) or len(color) != 3 or any(type(c) not in {int, float} or not math.isfinite(c) or not 0 <= c <= 1 for c in color):
        raise DomainError('invalid_annotation')
    return {'coordinate_space': 'code_text_v1', 'kind': spec['kind'], 'file': file['path'],
            'file_sha256': file['sha256'], 'encoding': file['encoding'], 'line_start': start, 'line_end': end,
            'column_start': left, 'column_end': right, 'quote': quote, 'comment': comment, 'color': color}
