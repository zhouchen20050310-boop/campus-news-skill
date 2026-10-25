"""Shared local-file and Media Tools API helpers (Python standard library)."""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import hashlib
import json
import re
import urllib.parse
import urllib.request

TZ = timezone(timedelta(hours=8))


def now():
    return datetime.now(TZ).isoformat(timespec='seconds')


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def api(base, route, payload=None, timeout=60):
    data = None if payload is None else json.dumps(payload).encode('utf-8')
    request = urllib.request.Request(base.rstrip('/') + route, data=data,
        headers={'Content-Type': 'application/json'} if data is not None else {})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        result = json.load(response)
    if not isinstance(result, dict):
        raise ValueError('下载工具返回的数据不是对象')
    if result.get('error') or result.get('need_verify') or result.get('success') is False:
        raise RuntimeError(str(result.get('error') or result.get('message') or '下载工具要求人工验证'))
    return result


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def canonical(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.hostname != 'mp.weixin.qq.com':
        raise ValueError('不是微信公众号原文链接：' + url)
    if parsed.scheme not in ('http', 'https'):
        raise ValueError('原文链接协议无效')
    query = urllib.parse.parse_qs(parsed.query)
    stable = [(key, query[key][0]) for key in ('__biz', 'mid', 'idx', 'sn') if key in query]
    return urllib.parse.urlunsplit(('https', parsed.netloc, parsed.path,
        urllib.parse.urlencode(stable), ''))


def safe_name(value):
    result = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', value).strip(' .')[:80] or '未命名'
    if re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', result):
        result = '_' + result
    return result


def date_ranges(values):
    mode = values.get('validity_mode', 'range')
    if mode not in ('range', 'unrestricted'):
        raise ValueError('资讯有效日期模式无效')
    if mode == 'unrestricted' and any(values.get(k) is not None for k in ('valid_start', 'valid_end')):
        raise ValueError('有效日期“不限”不能同时填写日期起止值')
    keys = ('publish_start', 'publish_end') + (('valid_start', 'valid_end') if mode == 'range' else ())
    for key in keys:
        if not isinstance(values.get(key), str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', values[key]):
            raise ValueError('日期必须由用户指定并使用 YYYY-MM-DD：' + key)
        date.fromisoformat(values[key])
    if values['publish_start'] > values['publish_end'] or (mode == 'range' and values['valid_start'] > values['valid_end']):
        raise ValueError('每组起始日期必须不晚于结束日期，请用户更正')
    return values


def validity_label(values):
    return '不限（用户明确指定）' if values.get('validity_mode') == 'unrestricted' else f'{values["valid_start"]} 至 {values["valid_end"]}'


def load_plan(path, ready=True):
    plan = date_ranges(read_json(path))
    if ready and plan.get('status') != 'ready':
        raise ValueError('采集前检查尚未通过，请先完成公众号收藏核对')
    scope = Path(plan['scope_file'])
    if not scope.is_file() or digest(scope.read_text(encoding='utf-8-sig')) != plan['scope_hash']:
        raise ValueError('公众号范围文件已变化或不存在，请重新执行采集前检查')
    return plan


def stamp(value):
    try:
        value = float(value or 0)
        if value > 100000000000:
            value /= 1000
        if value < 1000000000 or value > 5000000000:
            return 0
        return int(value)
    except (ValueError, TypeError, OverflowError):
        return 0


def day(value):
    return datetime.fromtimestamp(value, TZ).strftime('%Y-%m-%d') if value else ''
