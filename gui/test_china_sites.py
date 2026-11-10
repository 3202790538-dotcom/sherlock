"""Offline regression tests: do not confuse a login/challenge page with an account."""
import unittest
from urllib.parse import parse_qs, urlparse
from requests import Response
from gui import china_sites


def response(code, html, url):
    result = Response()
    result.status_code = code
    result._content = html.encode()
    result.encoding = 'utf-8'
    result.url = url
    return result


class ChinaSitesTests(unittest.TestCase):
    def check(self, key, code, html, url=None):
        site = china_sites.SITES[key]
        target = site['url'].format('example')
        return china_sites.classify(site, 'example', response(code, html, url or target))

    def test_profile_requires_positive_evidence(self):
        for site, html in [
            ('Gitee', '<title>Example (example) - Gitee.com</title>'),
            ('CNblogs', '<title>example - 博客园</title><div id="blogTitle">'),
            ('V2EX', '<title>V2EX › example</title>'),
            ('CSDN', '<title>example的博客-CSDN博客</title><div class="user-profile-head">'),
            ('SegmentFault', '<title>example - SegmentFault 思否</title><div class="profile">'),
            ('Zhihu', '<title>example - 知乎</title><div class="ProfileHeader">'),
            ('Douban', '<title>example</title><div id="profile">'),
        ]:
            with self.subTest(site=site): self.assertEqual(self.check(site, 200, html)[0], 'Claimed')
        self.assertEqual(self.check('Gitee', 200, '<title>Gitee</title>')[0], 'Unknown')
        self.assertEqual(self.check('CNblogs', 200, '<title>登录 - 博客园</title>')[0], 'WAF')

    def test_missing_account_differs_from_blocked_request(self):
        for status, expected in [(404, 'Available'), (410, 'Available'), (403, 'WAF'), (429, 'WAF'), (468, 'WAF'), (521, 'WAF'), (503, 'Unknown')]:
            with self.subTest(status=status): self.assertEqual(self.check('CNblogs', status, '')[0], expected)

    def test_soft_404_and_challenge_are_not_claimed(self):
        self.assertEqual(self.check('CSDN', 200, '<title>404</title>用户不存在')[0], 'Available')
        self.assertEqual(self.check('SegmentFault', 200, '<title>验证</title>/.safeline/static/')[0], 'WAF')
        self.assertEqual(self.check('V2EX', 200, '<title>V2EX › example</title>', 'https://www.v2ex.com/signin')[0], 'WAF')
        self.assertEqual(self.check('V2EX', 200, '<title>V2EX › example</title>', 'https://www.v2ex.com/')[0], 'Unknown')

    def test_username_cannot_change_url_path(self):
        rows = list(china_sites.search_china('../admin?x=1', 5))
        self.assertEqual(len(rows), len(china_sites.SITES))
        self.assertTrue(all(row['status'] == 'Illegal' for row in rows))

    def test_manual_searches_are_encoded_and_not_detection_results(self):
        links = china_sites.manual_searches('张 三&x=1')
        self.assertEqual({r['name'] for r in links}, {'哔哩哔哩', '微博', '抖音', '小红书'})
        bilibili = next(r['url'] for r in links if r['name'] == '哔哩哔哩')
        self.assertEqual(parse_qs(urlparse(bilibili).query), {'keyword': ['张 三&x=1']})
        self.assertTrue(all('status' not in link for link in links))


if __name__ == '__main__': unittest.main()
