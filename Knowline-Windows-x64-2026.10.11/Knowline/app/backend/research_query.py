"""Separate recognized request controls from bibliographic search terms.

The original request remains authoritative. This is a small, explicit parser,
not a claim that arbitrary natural language has been translated or understood.
"""
import hashlib
import json
import re

VENUES = {
    'TRO': 'IEEE Transactions on Robotics',
    'RAL': 'IEEE Robotics and Automation Letters',
    'RA-L': 'IEEE Robotics and Automation Letters',
    'ICRA': 'International Conference on Robotics and Automation',
    'IROS': 'International Conference on Intelligent Robots and Systems',
    'RSS': 'Robotics: Science and Systems',
    'CVPR': 'Computer Vision and Pattern Recognition',
    'ICCV': 'International Conference on Computer Vision',
    'ECCV': 'European Conference on Computer Vision',
}
ALIASES = {
    '视觉惯性SLAM': 'visual inertial SLAM',
    '视觉SLAM': 'visual SLAM',
    '激光SLAM': 'LiDAR SLAM',
}


def plan(request, target_count=None):
    original = request.strip()
    counts = re.findall(r'(?<!\d)(\d{1,3})\s*(?:篇|papers?\b|articles?\b)', original, re.I)
    inferred = int(counts[-1]) if len(set(counts)) == 1 and 1 <= int(counts[-1]) <= 100 else None
    count = target_count if target_count is not None else inferred or 10
    controls = bool(counts or re.search(r'为主|重点|侧重|优先|以.+(?:期刊|会议)|focus(?:ing)? on', original, re.I))
    venues = []
    publisher='IEEE' if controls and re.search(r'(?<![A-Za-z])IEEE(?![A-Za-z])',original,re.I) else None
    topic = original
    if controls:
        clauses = re.split(r'[，,;；]', original)
        topics = []
        for clause in clauses:
            clause = re.sub(r'(?<!\d)\d{1,3}\s*(?:篇|papers?\b|articles?\b)', '', clause, flags=re.I)
            if re.fullmatch(r'\s*(?:以)?IEEE\s*(?:为主|优先|重点|期刊|会议|顶会顶刊)?\s*',clause,re.I):continue
            clause=re.sub(r'\bIEEE\s*(?:为主|优先|重点)','',clause,flags=re.I)
            found = []
            for abbreviation, name in VENUES.items():
                pattern = r'(?<![a-zA-Z])' + re.escape(abbreviation) + r'(?![a-zA-Z])'
                if re.search(pattern, clause, re.I):
                    if name not in venues: venues.append(name)
                    found.append(pattern)
            if found:
                # A comma-delimited venue preference is a control, not a topic.
                if re.search(r'为主|重点|侧重|优先|期刊|会议|顶会|顶刊', clause):
                    prefix = re.split(r'以|重点|侧重|优先', clause, maxsplit=1)[0]
                    for pattern in found: prefix = re.sub(pattern, '', prefix, flags=re.I)
                    clause = re.sub(r'等.*|(?:机器人)?顶会.*|为主.*|期刊.*|会议.*', '', prefix)
                else:
                    for pattern in found: clause = re.sub(pattern, '', clause, flags=re.I)
            clause = re.sub(r'^(?:请|帮我|帮忙|需要|想要|检索|查找|搜索|找|并导入|导入|论文|文献|\s)+', '', clause)
            clause = re.sub(r'(?:论文|文献|为主|为重点|共|总共|等|\s)+$', '', clause)
            if clause.strip(): topics.append(clause.strip())
        topic = ' '.join(topics).strip() or original
        for alias, translation in ALIASES.items():
            topic = re.sub(re.escape(alias).replace('SLAM', r'\s*SLAM'), translation, topic, flags=re.I)
    query = topic
    if controls and venues and topic != original:
        query += ' (' + ' OR '.join('"' + name.replace('IEEE ', '') + '"' for name in venues) + ')'
    elif publisher and topic!=original:query+=' IEEE'
    if len(query) > 500: query = original
    return {'version': 1, 'request': original, 'topic_query': topic,
            'preferred_venues': venues, 'preferred_publisher':publisher, 'target_count': count, 'scholar_query': query,
            'normalized': query != original,
            'basis': 'Recognized count and venue controls; original request retained. Venue and topical relevance require source verification.'}


def names(scope):
    return scope.get('discovery_artifacts', {'discovery': 'discovery.json', 'scholar': 'scholar-candidates.json'})


def revised_names(search_plan):
    key = hashlib.sha256(json.dumps(search_plan, sort_keys=True).encode()).hexdigest()[:16]
    return {'discovery': 'discovery-' + key + '.json', 'scholar': 'scholar-candidates-' + key + '.json'}


def public_response_name(scope):
    """Keep each normalized retry's source evidence separate from the original."""
    discovery = names(scope)['discovery']
    if discovery == 'discovery.json':
        return 'public-citation-responses.json'
    key = hashlib.sha256(discovery.encode()).hexdigest()[:16]
    return 'public-citation-responses-' + key + '.json'
