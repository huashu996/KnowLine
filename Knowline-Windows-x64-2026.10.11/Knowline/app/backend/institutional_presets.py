"""Maintained official product entries, reviewed 2026-10-09.

Use stable product home pages; session-specific authentication URLs belong only
in WebView2 memory. The publisher's own institution selector handles school SSO.
"""
import re
from .safety import DomainError
PRESETS=[
 {'id':'ieee','name':'IEEE Xplore','entry_url':'https://ieeexplore.ieee.org/','aliases':['IEEE','IEEE Xplore','IEEE数据库','IEEE数字图书馆'],
  # IEEE's institution selector uses these two documented SeamlessAccess
  # services. Ads/analytics and arbitrary school SSO origins are excluded.
  'allowed_origins':['https://ieeexplore.ieee.org/','https://service.seamlessaccess.org/','https://md.seamlessaccess.org/'],
  'official_source':'https://ieeexplore.ieee.org/Xplorehelp/administrators-and-librarians/getting-started-guide',
  'dependency_sources':['https://innovate.ieee.org/wp-content/uploads/2024/02/2024-IEL-Brochure-pages-23-PIM-1018-rev.pdf','https://seamlessaccess.org/coming-up-storage-access-api-and-idp-filtering-ready-for-testing','https://seamlessaccess.org/work/SA_User-DataFlow.pdf'],
  'instructions_zh':'在官网选择 Institutional Sign In，并由您选择学校、完成认证。','instructions_en':'Choose Institutional Sign In on the official site, then select your institution and sign in.'},
 {'id':'webofscience','name':'Web of Science','entry_url':'https://www.webofscience.com/','aliases':['Web of Science','WOS','科学引文索引','科学网数据库'],
  'allowed_origins':['https://www.webofscience.com/','https://webofscience.com/','https://access.clarivate.com/'],
  'official_source':'https://clarivate.com/accessibility/web-of-science/',
  'instructions_zh':'在官网选择登录或机构登录；学校入口和文献全文权限分别判断。','instructions_en':'Choose sign-in or institution access on the official site; database and full-text permissions are assessed separately.'},
 {'id':'sciencedirect','name':'Elsevier · ScienceDirect','entry_url':'https://www.sciencedirect.com/','aliases':['Elsevier','爱思唯尔','ScienceDirect','Science Direct','SD'],
  'allowed_origins':['https://www.sciencedirect.com/'],
  'official_source':'https://www.elsevier.support/sciencedirect/answer/how-do-i-get-access-to-sciencedirect-from-anywhere',
  'instructions_zh':'在官网选择 Sign in / 机构访问。此入口对应 ScienceDirect，其他 Elsevier 产品权限单独判断。','instructions_en':'Choose Sign in / institution access on ScienceDirect. Other Elsevier products have separate permissions.'}
]
def presets():return [{**p,'reviewed_at':'2026-10-09'} for p in PRESETS]
def resolve(value):
 key=re.sub(r'\s+','',str(value or '').casefold())
 for item in PRESETS:
  if key in {re.sub(r'\s+','',str(v).casefold()) for v in [item['id'],item['name'],*item['aliases']]}:return item
 raise DomainError('institution_preset_unknown',404)
