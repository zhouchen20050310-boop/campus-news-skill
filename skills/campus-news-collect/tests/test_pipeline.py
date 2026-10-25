"""Offline contract and pipeline tests; no real account or network access."""
from datetime import datetime
from pathlib import Path
import copy
import io
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build_news
import collect_articles as collector
import news_common as common
import prepare_run
from xiumi_adapter import Paragraphs, source_content


DATES = dict(publish_start='2026-10-19', publish_end='2026-10-25',
    valid_start='2026-10-26', valid_end='2026-11-01')

TEST_ROOT = Path(__file__).resolve().parents[3] / 'output' / 'skill-validation' / 'scratch'


class WorkspaceTempDir(tempfile.TemporaryDirectory):
    def __init__(self):
        TEST_ROOT.mkdir(parents=True, exist_ok=True)
        super().__init__(dir=TEST_ROOT)

    def cleanup(self):
        if not Path(self.name).resolve().is_relative_to(TEST_ROOT.resolve()):
            raise ValueError('Test cleanup escaped its workspace directory')
        super().cleanup()


class PipelineTests(unittest.TestCase):
    def test_scope_and_conflicts(self):
        sources = prepare_run.parse_scope(' 甲，（开）\n乙,(关)\n甲，（开）\n')
        self.assertEqual(len(sources), 2)
        self.assertEqual(sources[0]['lines'], [1, 3])
        for text in ('甲，（开）\n甲，（关）', '甲，（是）', '甲，（关）', '甲，(开）'):
            with self.assertRaises(ValueError):
                prepare_run.parse_scope(text)

    def test_missing_and_ambiguous_favorites(self):
        sources = prepare_run.parse_scope('甲，（开）\n乙，（开）\n丙，（关）')
        result = prepare_run.check_favorites(sources, [{'nickname': '甲', 'fakeid': 'id'}])
        self.assertEqual([s['status'] for s in result], ['ready', 'missing_favorite', 'disabled'])
        result = prepare_run.check_favorites(prepare_run.parse_scope('甲，（开）'),
            [{'nickname': '甲', 'fakeid': '1'}, {'nickname': '甲', 'fakeid': '2'}])
        self.assertEqual(result[0]['status'], 'ambiguous')
        with self.assertRaises(ValueError):
            prepare_run.check_favorites(sources, None)

    def test_dates_required_and_ordered(self):
        self.assertEqual(common.date_ranges(dict(DATES)), DATES)
        for changes in ({'valid_start': None}, {'publish_end': '2026-10-18'}, {'valid_end': '2026-11-31'}):
            with self.assertRaises(ValueError):
                common.date_ranges({**DATES, **changes})

    def test_api_business_error_despite_http_success(self):
        with patch('urllib.request.urlopen', return_value=io.BytesIO(b'{"error":"need login"}')):
            with self.assertRaises(RuntimeError):
                common.api('http://127.0.0.1:5200', '/api/accounts')

    def test_explicit_unrestricted_validity(self):
        data = {**DATES, 'validity_mode': 'unrestricted', 'valid_start': None, 'valid_end': None}
        common.date_ranges(data)
        self.assertIn('不限', common.validity_label(data))
        with self.assertRaises(ValueError):
            common.date_ranges({**data, 'valid_end': '2026-11-01'})
        with self.assertRaises(ValueError):
            common.date_ranges({**data, 'validity_mode': 'range'})
        with self.assertRaises(ValueError):
            common.date_ranges({**data, 'publish_start': None})

    def test_plan_scope_drift_and_offline_mode(self):
        with WorkspaceTempDir() as temp:
            root = Path(temp)
            scope = root / 'scope.txt'
            scope.write_text('甲，（开）', encoding='utf-8')
            data = {**DATES, 'scope_file': str(scope), 'scope_hash': common.digest('甲，（开）'), 'status': 'offline_checked'}
            common.write_json(root / 'plan.json', data)
            with self.assertRaises(ValueError):
                common.load_plan(root / 'plan.json')
            data['status'] = 'ready'
            common.write_json(root / 'plan.json', data)
            common.load_plan(root / 'plan.json')
            scope.write_text('乙，（开）', encoding='utf-8')
            with self.assertRaises(ValueError):
                common.load_plan(root / 'plan.json')

    def test_scan_download_screen_layout_and_resume(self):
        with WorkspaceTempDir() as temp:
            root = Path(temp)
            out = root / 'run'
            out.mkdir()
            native = root / 'native'
            native.mkdir()
            body = '报名截止2026年10月28日12:00。可参与校内运动指导，面向学生。'
            (native / 'content.md').write_text(body, encoding='utf-8')
            (native / 'content.txt').write_text(body, encoding='utf-8')
            (native / 'article.html').write_text('<main>' + body + '</main>', encoding='utf-8')
            (native / 'article.pdf').write_bytes(b'%PDF-fixture')
            plan = {**DATES, 'status': 'ready', 'output_dir': str(out), 'scope_hash': 'fixture',
                'tool_url': 'http://127.0.0.1:5200', 'sources': [
                    {'name': '甲', 'enabled': True, 'status': 'ready', 'fakeid': 'a'},
                    {'name': '乙', 'enabled': False, 'status': 'disabled'}]}
            ts = lambda s: int(datetime.fromisoformat(s).replace(tzinfo=common.TZ).timestamp())
            future = {'title': '未来记录', 'link': 'https://mp.weixin.qq.com/s/future', 'update_time': ts('2026-10-29')}
            current = {'title': '体育招募', 'link': 'https://mp.weixin.qq.com/s/current?scene=1', 'update_time': ts('2026-10-22') * 1000}
            unknown = {'title': '未知日期', 'link': 'https://mp.weixin.qq.com/s/unknown', 'update_time': 0}
            old = {'title': '旧记录', 'link': 'https://mp.weixin.qq.com/s/old', 'update_time': ts('2026-10-18')}
            calls = []

            def fake_api(base, route, payload=None, **kwargs):
                calls.append((route, payload))
                if route == '/api/accounts':
                    return {'accounts': [{'nickname': '甲', 'fakeid': 'a'}]}
                if '/list/' in route:
                    self.assertIn('/a?', route)
                    page = int(route.split('begin=')[1].split('&')[0]) // 20
                    pages = [[future, unknown], [current, {**current, 'link': 'https://mp.weixin.qq.com/s/current?scene=2'}], [old]]
                    return {'articles': pages[page], 'can_msg_continue': True}
                if route == '/api/articles/download':
                    self.assertEqual(payload['account_name'], '甲')
                    return {'task_id': 'fixture-task'}
                if '/download-status/' in route:
                    return {'status': 'completed', 'completed': 2, 'failed': 0,
                        'results': [{'title': a['title'], 'success': True, 'path': str(native)} for a in [current, unknown]]}
                raise AssertionError('Unexpected route: ' + route)

            with patch.object(collector, 'api', side_effect=fake_api), patch.object(collector.time, 'sleep'):
                collector.scan(plan, out, 10, 0)
                state = common.read_json(out / '采集记录.json')
                self.assertEqual(len(state['accounts'][0]['pages']), 3)
                self.assertEqual(len(state['accounts'][0]['articles']), 2)
                collector.download(plan, out, state, 1, 1)
                collector.download(plan, out, common.read_json(out / '采集记录.json'), 1, 1)
            self.assertEqual(sum(route == '/api/articles/download' for route, _ in calls), 1)
            self.assertFalse(list(out.rglob('*.txt')))
            self.assertTrue((native / 'content.txt').is_file())
            index = common.read_json(out / '阅读索引.json')
            self.assertEqual(len(index['articles']), 1)
            self.assertTrue(list((out / '日期待确认').rglob('*.md')))
            article = index['articles'][0]
            aid = article['id']
            data = {**DATES, 'article_reviews': [{'article_id': aid, 'status': '候选',
                'reason': '下周报名仍开放', 'read_files': [article['markdown']]}],
                'events': [{'id': 'C01', 'title': '体育辅导员招募', 'category': '校园实践',
                    'source_ids': [aid], 'time': '10月28日12:00截止', 'highlights': '参与运动指导',
                    'action': '按原文提交材料', 'timing_status': '有效区间可参与',
                    'validity_basis': '截止在用户指定的有效区间内', 'pending': ['劳务补助金额'],
                    'evidence': [{'article_id': aid, 'quote': '报名截止2026年10月28日12:00。'}]}],
                'post': {'title': '校园资讯｜体育招募', 'summary': '报名截止提醒', 'author': '编辑'}}
            common.write_json(out / 'plan.json', plan)
            common.write_json(out / 'data.json', data)
            parsed = build_news.load_inputs(out / 'plan.json', out / '阅读索引.json', out / 'data.json')
            build_news.screen(*parsed, out / 'screened')
            build_news.render(*parsed, out / 'layout', True)
            content, paragraphs = source_content(out / 'layout/校园资讯_秀米兼容版.html')
            self.assertEqual(len(paragraphs.titles), 1)
            self.assertEqual(paragraphs.paragraphs[-1], 'END')
            self.assertIn('https://mp.weixin.qq.com/s/current?scene=1', paragraphs.links)
            self.assertNotIn('display:flex', content)
            normal = Paragraphs()
            normal.feed((out / 'layout/校园资讯_普通版.html').read_text(encoding='utf-8'))
            self.assertEqual(paragraphs.paragraphs, normal.paragraphs)
            data['events'][0]['evidence'][0]['quote'] = '不存在的虚构报名日期'
            common.write_json(out / 'data.json', data)
            with self.assertRaises(ValueError):
                build_news.load_inputs(out / 'plan.json', out / '阅读索引.json', out / 'data.json')
            data['valid_end'] = '2026-11-02'
            common.write_json(out / 'data.json', data)
            with self.assertRaises(ValueError):
                build_news.load_inputs(out / 'plan.json', out / '阅读索引.json', out / 'data.json')

    def test_submission_unknown_not_resubmitted(self):
        with WorkspaceTempDir() as temp:
            plan = {**DATES, 'sources': [], 'tool_url': 'http://127.0.0.1:5200'}
            state = {'plan': DATES, 'started_at': common.now(), 'accounts': [
                {'name': '甲', 'scan_status': 'api_end_reached', 'download_status': 'submitting',
                    'articles': [{'id': 'a', 'article': {'title': '一', 'link': 'https://mp.weixin.qq.com/s/test'},
                        'download_status': 'not_started'}]}]}
            with patch.object(collector, 'api', return_value={'accounts': []}) as api_mock:
                collector.download(plan, Path(temp), state, 1, 1)
                self.assertEqual(api_mock.call_count, 1)
                self.assertEqual(state['accounts'][0]['download_status'], 'submission_unknown')

    def test_cross_account_link_dedup(self):
        with WorkspaceTempDir() as temp:
            plan = {**DATES, 'sources': [{'name': name, 'enabled': True, 'status': 'ready', 'fakeid': name}
                for name in ('甲', '乙')], 'scope_hash': 'test', 'tool_url': 'http://127.0.0.1:5200'}
            def fake_api(base, route, **kwargs):
                if route == '/api/accounts':
                    return {'accounts': [{'nickname': name, 'fakeid': name} for name in ('甲', '乙')]}
                return {'articles': [{'title': '共享原文', 'link': 'https://mp.weixin.qq.com/s/same', 'update_time': 0}], 'can_msg_continue': False}
            with patch.object(collector, 'api', side_effect=fake_api), patch.object(collector.time, 'sleep'):
                collector.scan(plan, Path(temp), 2, 0)
            state = common.read_json(Path(temp) / '采集记录.json')
            self.assertEqual([len(s['articles']) for s in state['accounts']], [1, 0])
            self.assertEqual(len(state['accounts'][1]['duplicate_links']), 1)


if __name__ == '__main__':
    unittest.main()
