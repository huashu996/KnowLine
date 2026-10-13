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
    '视觉闭环检测': 'visual loop closure detection',
    '视觉回环检测': 'visual loop closure detection',
    '闭环检测': 'loop closure detection',
    '回环检测': 'loop closure detection',
    '视觉惯性SLAM': 'visual inertial SLAM',
    '视觉SLAM': 'visual SLAM',
    '激光SLAM': 'LiDAR SLAM',
}

# Venue families are preferences, never topical terms (CCF is not a subject).
VENUE_FAMILY = r'(?:IEEE\s*(?:期刊|会议)(?:\s*[和与及、/]\s*(?:期刊|会议))?|CCF\s*(?:[ABC]\s*类\s*)?(?:会议|期刊|推荐列表|推荐会议))'
VENUE_CONTROL = r'(?:以|优先(?:考虑)?|侧重|偏好)?\s*' + VENUE_FAMILY + r'(?:\s*(?:以及|和|与|及|、|/)\s*' + VENUE_FAMILY + r')*\s*(?:为主|优先|为重点)?'


def plan(request, target_count=None):
    original = request.strip()
    counts = re.findall(r'(?<!\d)(\d{1,3})\s*(?:篇|papers?\b|articles?\b)', original, re.I)
    inferred = int(counts[-1]) if len(set(counts)) == 1 and 1 <= int(counts[-1]) <= 100 else None
    count = target_count if target_count is not None else inferred or 10
    controls = bool(counts or re.search(r'为主|重点|侧重|优先|以.+(?:期刊|会议)|focus(?:ing)? on|' + VENUE_FAMILY, original, re.I))
    venues = []
    venue_groups = ['CCF'] if re.search(r'CCF\s*(?:[ABC]\s*类\s*)?(?:会议|期刊|推荐)', original, re.I) else []
    publisher='IEEE' if controls and re.search(r'(?<![A-Za-z])IEEE(?![A-Za-z])',original,re.I) else None
    topic = original
    if controls:
        clauses = re.split(r'[，,;；]', original)
        topics = []
        for clause in clauses:
            clause = re.sub(r'(?<!\d)\d{1,3}\s*(?:篇|papers?\b|articles?\b)', '', clause, flags=re.I)
            clause = re.sub(VENUE_CONTROL, '', clause, flags=re.I)
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
            clause = re.sub(r'^(?:请|帮我|帮忙|需要|想要|检索|查找|搜索|找|关于|有关|并导入|导入|论文|文献|\s)+', '', clause)
            clause = re.sub(r'(?:论文|文献|为主|为重点|共|总共|等|的|\s)+$', '', clause)
            if clause.strip(): topics.append(clause.strip())
        topic = ' '.join(topics).strip() or original
    for alias, translation in ALIASES.items():
        topic = re.sub(re.escape(alias).replace('SLAM', r'\s*SLAM'), translation, topic, flags=re.I)
    query = topic
    if controls and venues and topic != original:
        query += ' (' + ' OR '.join('"' + name.replace('IEEE ', '') + '"' for name in venues) + ')'
    elif publisher and topic!=original:query+=' IEEE'
    if len(query) > 500: query = original
    return {'version': 2, 'request': original, 'topic_query': topic, 'preferred_venue_groups': venue_groups,
            'preferred_venues': venues, 'preferred_publisher':publisher, 'target_count': count, 'scholar_query': query,
            'normalized': query != original,
            'basis': 'Recognized count and venue controls; original request retained. Venue and topical relevance require source verification.'}


def names(scope):
    return scope.get('discovery_artifacts', {'discovery': 'discovery.json', 'scholar': 'scholar-candidates.json'})


def graph_plan(origin,instructions='',target_count=None):
    """Keep the seed identity separate from preferences and freeform intent."""
    seed=plan(origin,target_count)
    notes=instructions.strip()
    preference=plan('优先 '+notes,target_count) if notes else {}
    venues=list(dict.fromkeys([*seed['preferred_venues'],*preference.get('preferred_venues',[])]))
    title=seed['topic_query'] if seed['preferred_venues'] and seed['normalized'] else origin.strip()
    return {**seed,'version':2,'origin_request':origin.strip(),'origin_query':title,
            'search_instructions':notes,'request':origin.strip()+('\n'+notes if notes else ''),
            'topic_query':title,'scholar_query':title,'preferred_venues':venues,
            'preferred_publisher':preference.get('preferred_publisher') or seed.get('preferred_publisher'),
            'normalized':title!=origin.strip(),
            'unavailable_fulltext':'skip_after_bounded_sources',
            'basis':'Seed identity is searched independently; venue preferences are soft and must be source verified. Freeform instructions remain in the frozen task.'}


def graph_candidate_rank(paper,search_plan):
    """Seed first, then requested venues; this is ranking, not identity proof."""
    normalize=lambda value:re.sub(r'[^a-z0-9\u4e00-\u9fff]','',str(value).casefold())
    origin=normalize(search_plan.get('origin_query',''))
    seed=bool(origin and normalize(paper.get('title','')).startswith(origin))
    venue=str(paper.get('venue',''))
    wanted=search_plan.get('preferred_venues',[])
    preferred=any(normalize(v) in normalize(venue) for v in wanted)
    if not preferred:
        preferred=any(name in wanted and re.search(r'(?<![a-zA-Z])'+re.escape(alias)+r'(?![a-zA-Z])',venue,re.I) for alias,name in VENUES.items())
    return (not seed,not preferred)


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


def supplemental_name(scope, name):
    """Keep normalized retries separate without altering prior task evidence."""
    discovery = names(scope)['discovery']
    if discovery == 'discovery.json':return name + '.json'
    key = hashlib.sha256(discovery.encode()).hexdigest()[:16]
    return name + '-' + key + '.json'


def repository_terms(scope):
    """Build a bounded repository query from the topic, not importer support."""
    topic = scope.get('search_plan', {}).get('topic_query') or plan(scope['query'])['topic_query']
    if re.search(r'visual\s+loop\s+closure', topic, re.I):
        return '(all:"loop closure" AND (all:visual OR all:camera OR all:image))'
    if re.fullmatch(r'visual\s*(?:inertial\s*)?SLAM', topic, re.I):
        return '(ti:"visual SLAM" OR ti:"visual odometry" OR abs:"visual SLAM")'
    if re.fullmatch(r'(?:lidar|laser)\s*SLAM', topic, re.I):
        return '(ti:"LiDAR SLAM" OR ti:"LiDAR odometry" OR abs:"LiDAR SLAM")'
    words = re.findall(r'[\w-]+', topic, re.UNICODE)[:24]
    return '(' + ' AND '.join('all:"' + word + '"' for word in words) + ')' if words else ''
