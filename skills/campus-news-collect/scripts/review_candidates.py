"""Validate collector observations; never infer page facts or select articles."""
import argparse
from datetime import date, datetime
import json
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode

TIMING = {'适用周内可用', '适用周内仅可关注', '长期有效', '时间待确认', '不适用'}
COVERAGE = {'已检索', '未检出', '访问受限', '工具不可用', '未检索', '已跳过'}


def identity(url):
    parsed = urlparse(url)
    if parsed.scheme not in {'http', 'https'} or parsed.hostname != 'mp.weixin.qq.com':
        raise ValueError('不是微信原文链接')
    if parsed.path.startswith('/s/') and parsed.path[3:].strip('/'):
        return 'https://mp.weixin.qq.com' + parsed.path.rstrip('/')
    query = parse_qs(parsed.query)
    if parsed.path == '/s' and all(query.get(k) for k in ['__biz', 'mid', 'idx', 'sn']):
        return 'https://mp.weixin.qq.com/s?' + urlencode({k: query[k][0] for k in ['__biz', 'mid', 'idx', 'sn']})
    raise ValueError('缺少微信文章标识，可能是账号主页或不完整链接')


def observed(value):
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return stamp.tzinfo is not None
    except (ValueError, TypeError, AttributeError):
        return False


def review(plan, data):
    sources = {s['source_id']: s for s in plan['sources']}
    low, high = date.fromisoformat(plan['publish_start']), date.fromisoformat(plan['publish_end'])
    coverage = {}
    for item in data.get('coverage', []):
        key = item.get('source_id')
        if key not in sources or key in coverage:
            raise ValueError('覆盖记录包含未知或重复的 source_id')
        item = dict(item)
        if item.get('status') not in COVERAGE:
            raise ValueError('无效的检索状态')
        if item['status'] not in {'未检索', '已跳过', '工具不可用'}:
            if not observed(item.get('checked_at')) or not item.get('queries'):
                raise ValueError('已执行的检索须保留实际检索词和带时区的观察时间')
        coverage[key] = item
    for key, source in sources.items():
        if key not in coverage:
            coverage[key] = {'source_id': key, 'status': '未检索' if source['eligible'] else '已跳过',
                             'queries': [], 'checked_at': '', 'note': '没有提供实际检索记录'}
    items, seen = [], set()
    for item in data.get('articles', []):
        article = dict(item)
        reasons, rejected = [], False
        key = article.get('source_id')
        if key not in sources:
            raise ValueError('文章包含未知 source_id')
        if coverage[key]['status'] in {'未检索', '已跳过', '工具不可用'}:
            reasons.append('缺少该账号的实际检索记录')
        if not sources[key]['eligible']:
            reasons.append('信源不属于本次公众号来源'); rejected = True
        try:
            canonical = identity(article.get('url', ''))
            if canonical in seen:
                continue
            seen.add(canonical)
        except ValueError as error:
            reasons.append(str(error)); rejected = True
        if not article.get('title'):
            reasons.append('缺少原文标题')
        try:
            published = date.fromisoformat(article.get('published_at', ''))
            if not low <= published <= high:
                reasons.append('文章发布日期不在检索区间'); rejected = True
        except (TypeError, ValueError):
            reasons.append('缺少可核验的原文发布日期')
        if article.get('account_status') == '不匹配':
            reasons.append('发布账号与信源不匹配'); rejected = True
        elif article.get('account_status') != '已核对' or not article.get('account'):
            reasons.append('发布账号待核对')
        if article.get('link_status') == '失效':
            reasons.append('原文链接失效'); rejected = True
        elif article.get('link_status') != '已打开':
            reasons.append('原文尚未成功打开核验')
        if not observed(article.get('checked_at')):
            reasons.append('缺少带时区的核验时间')
        evidence = article.get('evidence') or {}
        if any(not evidence.get(k) for k in ['account', 'published_at', 'content']):
            reasons.append('账号、日期或正文的观察依据不完整')
        timing = article.get('timing') or {}
        if timing.get('status') == '不适用':
            reasons.append('资讯不适用于目标周'); rejected = True
        elif timing.get('status') not in TIMING or timing.get('status') == '时间待确认':
            reasons.append('适用时间待确认')
        if not timing.get('basis'):
            reasons.append('缺少与适用周的关联依据')
        if not article.get('student_value') or not article.get('summary'):
            reasons.append('缺少资讯说明或学生价值说明')
        count = article.get('read_count')
        if count is not None and (isinstance(count, bool) or not isinstance(count, int) or count < 0):
            raise ValueError('阅读量必须是非负整数或 null')
        if (count is not None or article.get('read_count_display')) and not evidence.get('read_count'):
            raise ValueError('阅读量没有对应观察依据')
        # These are editorial inputs, never collector decisions.
        article['decision'] = ''
        article['editor_note'] = ''
        article['review_status'] = '排除' if rejected else ('待核验' if reasons else '候选')
        article['review_reasons'] = reasons
        items.append(article)
    return {'plan': plan, 'articles': items, 'coverage': list(coverage.values()),
            'counts': {status: sum(a['review_status'] == status for a in items)
                       for status in ['候选', '待核验', '排除']}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ['plan', 'input', 'output']:
        parser.add_argument('--' + flag, required=True)
    args = parser.parse_args()
    load = lambda path: json.loads(Path(path).read_text(encoding='utf-8-sig'))
    result = review(load(args.plan), load(args.input))
    out = Path(args.output); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result['counts'], ensure_ascii=False))


if __name__ == '__main__':
    main()
