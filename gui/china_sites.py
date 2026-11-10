"""Conservative public-profile checks for Chinese-language platforms.

A successful HTTP response alone is not evidence of an account. Unrecognized
HTML, login pages and anti-bot responses remain explicitly inconclusive.
"""
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import unescape
from urllib.parse import quote, urlparse

import requests

SITES = {
    'Gitee': {'name': 'Gitee 码云', 'url': 'https://gitee.com/{}'},
    'CNblogs': {'name': '博客园', 'url': 'https://www.cnblogs.com/{}'},
    'V2EX': {'name': 'V2EX 中文社区', 'url': 'https://www.v2ex.com/member/{}'},
    'CSDN': {'name': 'CSDN', 'url': 'https://blog.csdn.net/{}'},
    'SegmentFault': {'name': '思否 SegmentFault', 'url': 'https://segmentfault.com/u/{}'},
    'Zhihu': {'name': '知乎', 'url': 'https://www.zhihu.com/people/{}'},
    'Douban': {'name': '豆瓣', 'url': 'https://www.douban.com/people/{}/'},
}


def classify(site, username, response):
    """Return (Sherlock status, explanation) without interpreting WAFs as absence."""
    code, text = response.status_code, response.text
    title_match = re.search(r'<title\b[^>]*>(.*?)</title>', text, re.I | re.S)
    title = unescape(title_match.group(1)).strip() if title_match else ''
    final = urlparse(response.url)
    if code in (404, 410):
        return 'Available', '公开主页不存在'
    if code in (401, 403, 412, 418, 429, 461, 468, 521, 567):
        return 'WAF', f'网站限制访问（HTTP {code}），无法确认账号'
    if (re.search(r'登录|安全验证|人机验证|验证码|captcha|access denied|just a moment', title, re.I)
            or re.search(r'/(?:login|signin|passport|sign_in)(?:/|$)', final.path, re.I)
            or final.hostname and final.hostname.startswith(('passport.', 'login.'))
            or any(marker in text.lower() for marker in (
                '/.safeline/static/', 'cf-chl-', 'challenge-platform', 'acw_sc__v2',
            ))):
        return 'WAF', '网站要求登录或安全验证，请手动核实'
    if not 200 <= code < 300:
        return 'Unknown', f'网站响应异常（HTTP {code}）'
    if re.search(r'^404\b|页面不存在|用户不存在|用户未找到|page not found', title, re.I):
        return 'Available', '网站提示该公开主页不存在'
    expected = urlparse(site['url'].format(quote(username, safe='')))
    if (final.netloc.casefold(), final.path.rstrip('/').casefold()) != (
            expected.netloc.casefold(), expected.path.rstrip('/').casefold()):
        return 'Unknown', '主页发生跳转，无法确认账号'

    name = site['name']
    # Require a profile-specific structure, not just a generic application shell.
    evidence = {
        'Gitee 码云': bool(re.search(r'\(' + re.escape(username) + r'\)\s*-\s*Gitee\.com', title, re.I)),
        '博客园': '博客园' in title and bool(re.search(r'id=[\"\']blogTitle[\"\']', text)),
        'V2EX 中文社区': bool(re.fullmatch(r'V2EX\s*[›»]\s*' + re.escape(username), title, re.I)),
        'CSDN': 'CSDN' in title and bool(re.search(r'class=[\"\'][^\"\']*user-profile-head', text)),
        '思否 SegmentFault': 'SegmentFault' in title and bool(re.search(r'class=[\"\'][^\"\']*\bprofile\b', text)),
        '知乎': '知乎' in title and 'ProfileHeader' in text,
        '豆瓣': bool(re.search(r'id=[\"\']profile[\"\']', text)),
    }.get(name, False)
    if evidence:
        return 'Claimed', '检测到公开个人主页；同名不代表同一人'
    return 'Unknown', '未识别到可靠的个人主页标记，请手动核实'


def _check(key, site, username, timeout):
    row = dict(site=key, display_name=site['name'], region='china', username=username,
               url=site['url'].format(quote(username, safe='')))
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}', username):
        row.update(status='Illegal', detail='需要主页中的账号 ID 或英文标识，不能使用显示昵称')
        return row
    try:
        response = requests.get(row['url'], timeout=timeout,
                                headers={'User-Agent': 'Mozilla/5.0'})
        status, detail = classify(site, username, response)
    except requests.RequestException as exc:
        status, detail = 'Unknown', f'无法访问主页（{type(exc).__name__}），请手动核实'
    row.update(status=status, detail=detail)
    return row


def search_china(username, timeout):
    """Yield results as each site completes; cancellation is owned by GUI process."""
    with ThreadPoolExecutor(max_workers=len(SITES)) as executor:
        futures = [executor.submit(_check, key, site, username, timeout)
                   for key, site in SITES.items()]
        for future in as_completed(futures):
            yield future.result()


def manual_searches(username):
    if not username:
        return []
    encoded = quote(username, safe='')
    return [
        {'name': '哔哩哔哩', 'url': f'https://search.bilibili.com/upuser?keyword={encoded}'},
        {'name': '微博', 'url': f'https://s.weibo.com/user?q={encoded}'},
        {'name': '抖音', 'url': f'https://www.douyin.com/search/{encoded}'},
        {'name': '小红书', 'url': f'https://www.xiaohongshu.com/search_result?keyword={encoded}'},
    ]
