"""Read an explicit account scope and two manual date ranges; check favorites."""
import argparse
from pathlib import Path
import re
import sys
from news_common import api, date_ranges, digest, now, read_json, validity_label, write_json


def parse_scope(text):
    sources = {}
    for number, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            continue
        match = re.fullmatch(r'\s*(.+?)\s*[,，]\s*(?:（\s*(开|关)\s*）|\(\s*(开|关)\s*\))\s*', raw)
        if not match:
            raise ValueError(f'范围文件第{number}行格式错误，应为：公众号名称，（开）或（关）')
        name, state = match[1].strip(), match[2] or match[3]
        if name in sources and sources[name]['enabled'] != (state == '开'):
            raise ValueError(f'范围文件第{number}行：{name}的开关与前文冲突，请用户更正')
        sources.setdefault(name, {'name': name, 'enabled': state == '开', 'lines': []})['lines'].append(number)
    if not any(item['enabled'] for item in sources.values()):
        raise ValueError('范围文件中没有开启的公众号，请用户修改')
    return list(sources.values())


def check_favorites(sources, accounts):
    if not isinstance(accounts, list) or any(not isinstance(a, dict) for a in accounts):
        raise ValueError('无法读取有效的收藏列表，不能据此判定公众号未收藏')
    for source in sources:
        if not source['enabled']:
            source['status'] = 'disabled'
            continue
        matches = [a for a in accounts if a.get('nickname') == source['name']]
        if len(matches) > 1:
            source['status'] = 'ambiguous'
        elif not matches:
            source['status'] = 'missing_favorite'
        elif not matches[0].get('fakeid'):
            source['status'] = 'missing_account_id'
        else:
            source.update(status='ready', fakeid=matches[0]['fakeid'])
    return sources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope', required=True)
    for flag in ('publish-start', 'publish-end'):
        parser.add_argument('--' + flag, required=True)
    parser.add_argument('--valid-start')
    parser.add_argument('--valid-end')
    parser.add_argument('--valid-unrestricted', action='store_true', help='仅在用户明确要求资讯有效日期不限时使用')
    parser.add_argument('--output', required=True, help='本次新任务目录；阻塞后可在原目录重做检查')
    parser.add_argument('--tool-url', default='http://127.0.0.1:5200')
    parser.add_argument('--favorites', help='离线核对用的收藏列表 JSON；此模式不能直接执行采集')
    args = parser.parse_args()
    dates = date_ranges({**vars(args), 'validity_mode': 'unrestricted' if args.valid_unrestricted else 'range'})
    out = Path(args.output).resolve()
    if (out / '采集记录.json').exists():
        raise ValueError('此目录已有采集记录，请为新任务选择新目录')
    scope_file = Path(args.scope).resolve()
    text = scope_file.read_text(encoding='utf-8-sig')
    sources = parse_scope(text)
    result = read_json(args.favorites) if args.favorites else api(args.tool_url, '/api/accounts')
    sources = check_favorites(sources, result.get('accounts') if isinstance(result, dict) else result)
    blocked = [s for s in sources if s['enabled'] and s['status'] != 'ready']
    plan = {key: dates[key] for key in ('publish_start', 'publish_end', 'valid_start', 'valid_end')}
    plan['validity_mode'] = dates['validity_mode']
    plan.update(schema_version=1, status='blocked' if blocked else ('offline_checked' if args.favorites else 'ready'),
        checked_at=now(), timezone='Asia/Shanghai', scope_file=str(scope_file), scope_hash=digest(text),
        output_dir=str(out), tool_url=args.tool_url, sources=sources)
    write_json(out / 'plan.json', plan)
    lines = ['# 采集前检查', '', f'文章采集日期：{plan["publish_start"]} 至 {plan["publish_end"]}',
        f'资讯有效日期：{validity_label(plan)}', '',
        *[f'- {s["name"]}：{s["status"]}' for s in sources], '']
    if blocked:
        lines.append('请先在 WeChat MP Tools 收藏缺失公众号；如有重名或标识缺失，请核对工具收藏记录。完成后重新执行本检查，不静默跳过。')
    if args.favorites:
        lines.append('本次使用离线收藏快照；开始采集前必须去掉 --favorites，读取实时收藏重新检查。')
    (out / '采集前检查.md').write_text('\n'.join(lines), encoding='utf-8')
    print(__import__('json').dumps({'status': plan['status'], 'blocked': blocked,
        'plan': str(out / 'plan.json')}, ensure_ascii=False))
    return 2 if blocked else 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, OSError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
