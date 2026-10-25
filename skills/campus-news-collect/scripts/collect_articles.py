"""Bounded, resumable Media Tools list/download adapter; no article TXT delivery."""
import argparse
import csv
from datetime import datetime
import json
from pathlib import Path
import re
import shutil
import sys
import time
import urllib.parse
from news_common import api, canonical, day, digest, load_plan, now, read_json, safe_name, stamp, validity_label, write_json
from prepare_run import check_favorites


def verify_accounts(plan):
    sources = check_favorites([dict(s) for s in plan['sources']],
        api(plan['tool_url'], '/api/accounts').get('accounts'))
    current = {s['name']: s for s in sources}
    for source in plan['sources']:
        if source['enabled'] and (current[source['name']]['status'] != 'ready'
                or current[source['name']].get('fakeid') != source['fakeid']):
            raise ValueError('收藏列表发生变化，请重新核对：' + source['name'])


def fetch_page(plan, fid, page):
    return api(plan['tool_url'], '/api/articles/list/' + urllib.parse.quote(str(fid), safe='')
        + f'?begin={page * 20}&count=20')


def scan(plan, out, max_pages, delay):
    target = out / '采集记录.json'
    if target.exists():
        raise ValueError('本目录已有采集记录，请用 download/report 继续；新扫描请创建新任务目录')
    verify_accounts(plan)
    state = {'plan': {key: plan[key] for key in ('publish_start', 'publish_end', 'valid_start',
        'valid_end', 'scope_hash')}, 'started_at': now(), 'accounts': []}
    state['plan']['validity_mode'] = plan.get('validity_mode', 'range')
    write_json(target, state)
    global_entries = {}
    for source in plan['sources']:
        if not source['enabled']:
            continue
        item = {'name': source['name'], 'fakeid': source['fakeid'], 'articles': [], 'pages': [], 'duplicate_links': [],
            'scan_status': 'running', 'download_status': 'not_started'}
        state['accounts'].append(item)
        seen = set()
        try:
            for page in range(max_pages):
                result = fetch_page(plan, source['fakeid'], page)
                articles = result.get('articles')
                if not isinstance(articles, list):
                    raise ValueError('文章列表字段缺失或格式错误')
                write_json(out / '列表记录' / f'{safe_name(source["name"])}_{page+1}.json',
                    {k: result.get(k) for k in ('articles', 'begin', 'count', 'total', 'can_msg_continue')})
                known, fresh = [], 0
                for article in articles:
                    if not isinstance(article, dict) or not article.get('link'):
                        raise ValueError('文章记录缺少原文链接，请检查接口版本')
                    key = canonical(article['link'])
                    ts = stamp(article.get('update_time'))
                    if ts:
                        known.append(day(ts))
                    if key in seen:
                        previous = global_entries.get(key)
                        if previous and not previous['list_timestamp'] and ts:
                            previous['list_timestamp'] = ts
                        continue
                    seen.add(key)
                    fresh += 1
                    if key in global_entries:
                        previous = global_entries[key]
                        item['duplicate_links'].append({'url': article['link'], 'primary_id': previous['id']})
                        if not previous['list_timestamp'] and ts:
                            previous['list_timestamp'] = ts
                        continue
                    if not ts or plan['publish_start'] <= day(ts) <= plan['publish_end']:
                        entry = {'id': 'A' + digest(key)[:16], 'canonical_url': key,
                            'article': article, 'list_timestamp': ts, 'download_status': 'not_started'}
                        item['articles'].append(entry)
                        global_entries[key] = entry
                item['pages'].append({'page': page+1, 'returned': len(articles), 'new_links': fresh})
                if not articles:
                    item.update(scan_status='empty_unconfirmed', stop_reason='接口为空，不证明该账号没有发文')
                    break
                if known and min(known) < plan['publish_start']:
                    item.update(scan_status='date_boundary_reached', stop_reason='按历史列表倒序假设到达日期边界；未独立核对官方完整列表')
                    break
                if result.get('can_msg_continue') is False or result.get('can_msg_continue') == 0:
                    item.update(scan_status='api_end_reached', stop_reason='接口报告无后续页，不保证渠道收录完整')
                    break
                if page and fresh == 0:
                    item.update(scan_status='repeated_page', stop_reason='重复页无新链接，停止并保留覆盖疑问')
                    break
                write_json(target, state)
                time.sleep(delay)
            else:
                item.update(scan_status='page_limit_reached', stop_reason=f'达到{max_pages}页上限，覆盖待核验')
        except Exception as error:
            item.update(scan_status='failed', stop_reason=str(error)[:500])
        write_json(target, state)
        print(json.dumps({'source': source['name'], 'status': item['scan_status'],
            'candidates': len(item['articles'])}, ensure_ascii=False), flush=True)
        time.sleep(delay)
    state['scan_finished_at'] = now()
    write_json(target, state)
    report(plan, out, state)


def publication_date(folder, entry, started):
    raw_time = 0
    for path in folder.glob('*.html'):
        text = path.read_text(encoding='utf-8', errors='replace')
        match = re.search(r'\b(?:ct|publish_time)\s*=\s*["\']?(\d{10,13})\b', text)
        if match and stamp(match[1]):
            raw_time = stamp(match[1])
            break
    listed = entry['list_timestamp']
    if raw_time and listed and day(raw_time) != day(listed):
        return '', '原文时间与历史列表冲突，需人工核验'
    if raw_time:
        return day(raw_time), '正文 HTML 赋值中的时间戳；需核对是否确为发布时间'
    if listed:
        return day(listed), '工具历史列表时间；未独立核验公众号原文时间'
    meta = folder / 'metadata.json'
    if meta.is_file():
        value = stamp(read_json(meta).get('publish_time'))
        if value and value < datetime.fromisoformat(started).timestamp() - 120:
            return day(value), '工具解析的正文元数据，早于本次采集；未独立复核，不采信下载时间回填'
    return '', '没有可用的发布时间证据；不以下载时间替代'


def archive(entry, result, source, plan, out, started):
    folder = Path(result['path']).resolve()
    if not folder.is_dir():
        raise ValueError('下载工具返回的正文目录不存在')
    published, basis = publication_date(folder, entry, started)
    group = ('日期待确认' if not published else '区间内推文' if
        plan['publish_start'] <= published <= plan['publish_end'] else '范围外_保留核对')
    destination = out / group / safe_name(source) / (entry['id'] + '_' + safe_name(entry['article']['title']))
    if not destination.resolve().is_relative_to(out.resolve()):
        raise ValueError('输出路径超出本次目录')
    # Never follow links out of a returned article folder; keep native files intact.
    for path in folder.rglob('*'):
        if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
            raise ValueError('文章目录包含链接，未归档，请人工核对')
    shutil.copytree(folder, destination, dirs_exist_ok=True,
        ignore=shutil.ignore_patterns('*.txt', '*.TXT', '__pycache__'))
    md_files = sorted(destination.glob('*.md'), key=lambda p: (p.name != 'content.md', p.name))
    content = md_files[0].read_text(encoding='utf-8-sig', errors='replace') if md_files else ''
    entry.update(download_status='success', published_at=published, date_evidence=basis,
        classification=group, saved_path=str(destination), markdown=str(md_files[0]) if md_files else '',
        body_chars=len(content.strip()), pdfs=[str(p) for p in destination.glob('*.pdf')],
        images=[str(p) for p in destination.rglob('*') if p.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp', '.gif')])


def download(plan, out, state, poll_seconds, wait_seconds):
    verify_accounts(plan)
    manifest = out / '采集记录.json'
    for source in state['accounts']:
        entries = source['articles']
        if source['download_status'] in ('finished', 'submission_unknown') or not entries:
            continue
        if not source.get('task_id'):
            if source.get('download_status') == 'submitting':
                source['download_status'] = 'submission_unknown'
                source['download_error'] = '上次提交是否成功未知，请在工具界面核对，不自动重复提交'
                write_json(manifest, state)
                continue
            source['download_status'] = 'submitting'
            write_json(manifest, state)
            try:
                task = api(plan['tool_url'], '/api/articles/download',
                    {'account_name': source['name'], 'articles': [e['article'] for e in entries]})
                if not task.get('task_id'):
                    raise ValueError('提交未返回任务标识')
                source.update(task_id=task['task_id'], download_status='running')
                write_json(manifest, state)
            except Exception as error:
                source.update(download_status='submission_unknown', download_error=str(error)[:500])
                write_json(manifest, state)
                continue
        deadline = time.monotonic() + wait_seconds
        while True:
            task = api(plan['tool_url'], '/api/articles/download-status/' +
                urllib.parse.quote(str(source['task_id']), safe=''))
            source['task_status'] = {k: task.get(k) for k in ('status', 'total', 'completed', 'failed')}
            write_json(manifest, state)
            print(json.dumps({'source': source['name'], **source['task_status']}, ensure_ascii=False), flush=True)
            if task.get('status') in ('completed', 'failed', 'cancelled'):
                break
            if time.monotonic() >= deadline:
                report(plan, out, state)
                print('任务仍在运行；稍后用相同 plan 执行 download 继续轮询，不会重复提交。', flush=True)
                return
            time.sleep(poll_seconds)
        results = task.get('results', [])
        for entry in entries:
            if entry['download_status'] == 'success':
                continue
            matches = [r for r in results if r.get('title') == entry['article'].get('title')]
            same_title_entries = [e for e in entries if e['article'].get('title') == entry['article'].get('title')]
            if len(matches) != 1 or len(same_title_entries) != 1:
                entry.update(download_status='unmatched', download_error='任务结果缺失或标题不唯一，未按顺序猜测匹配')
                continue
            result = matches[0]
            if result.get('success') and result.get('path'):
                try:
                    archive(entry, result, source['name'], plan, out, state['started_at'])
                except Exception as error:
                    entry.update(download_status='archive_failed', download_error=str(error)[:500])
            else:
                entry.update(download_status='failed', download_error=str(result.get('error') or '未取得正文目录'))
        source['download_status'] = 'finished'
        write_json(manifest, state)
        time.sleep(2)
    state['download_finished_at'] = now()
    write_json(manifest, state)
    report(plan, out, state)


def report(plan, out, state):
    rows, index = [], []
    for source in state['accounts']:
        for entry in source['articles']:
            row = {'编号': entry['id'], '公众号': source['name'], '标题': entry['article'].get('title', ''),
                '发布日期': entry.get('published_at', ''), '日期依据': entry.get('date_evidence', ''),
                '原文链接': entry['article']['link'], '分类': entry.get('classification', '未完成'),
                '下载状态': entry['download_status'], 'Markdown': entry.get('markdown', ''),
                'PDF数量': len(entry.get('pdfs', [])), '错误': entry.get('download_error', '')}
            rows.append(row)
            if row['分类'] == '区间内推文' and entry['download_status'] == 'success':
                index.append({'id': entry['id'], 'account': source['name'], 'title': row['标题'],
                    'url': row['原文链接'], 'published_at': row['发布日期'], 'date_evidence': row['日期依据'],
                    'markdown': entry.get('markdown', ''), 'pdfs': entry.get('pdfs', []), 'images': entry.get('images', []),
                    'body_chars': entry.get('body_chars', 0)})
    fields = ['编号', '公众号', '标题', '发布日期', '日期依据', '原文链接', '分类', '下载状态', 'Markdown', 'PDF数量', '错误']
    for name, selected in [('文章清单.csv', rows), ('区间内文章清单.csv', [r for r in rows if r['分类'] == '区间内推文'])]:
        with (out / name).open('w', encoding='utf-8-sig', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(selected)
    write_json(out / '阅读索引.json', {'plan': state['plan'], 'articles': index})
    combined = ['# 区间内推文正文合集', '', f'发布区间：{plan["publish_start"]} 至 {plan["publish_end"]}', '']
    for article in index:
        path = Path(article['markdown']) if article['markdown'] else None
        combined += ['---', '', f'## {article["id"]} {article["title"]}', '',
            '公众号：' + article['account'], '发布日期：' + article['published_at'],
            '日期依据：' + article['date_evidence'], '原文链接：' + article['url'], '',
            path.read_text(encoding='utf-8-sig', errors='replace') if path and path.is_file() else '【待确认】MD缺失，请补读原始图文。', '']
    (out / '推文正文合集.md').write_text('\n'.join(combined), encoding='utf-8')
    summary = ['# 采集记录与限制', '', f'报告时间：{now()}',
        f'采集日期：{plan["publish_start"]} 至 {plan["publish_end"]}；资讯有效日期：{validity_label(plan)}',
        f'候选下载条目：{len(rows)}；归档成功：{sum(r["下载状态"] == "success" for r in rows)}；区间内：{len(index)}。',
        '目录不交付文章 TXT；下载工具可能在自己的目录内部生成 TXT，本 Skill 不修改其源码和下载设置。',
        '任务成功、接口分页结束和到达日期边界均不证明渠道收录完整。采集结束日未结束时，也不覆盖当日后续发文。', '',
        '| 公众号 | 扫描状态 | 下载状态 | 终止原因 |', '| --- | --- | --- | --- |']
    actual = {s['name']: s for s in state['accounts']}
    for source in plan.get('sources', []):
        if not source['enabled']:
            continue
        s = actual.get(source['name'])
        if not s:
            summary.append(f'| {source["name"]} | 未扫描 | 未下载 | 任务尚未执行到此公众号 |')
        else:
            summary.append(f'| {s["name"]} | {s["scan_status"]} | {s["download_status"]} | {s.get("stop_reason", "")}；同链接重复{len(s.get("duplicate_links", []))}条 |')
    (out / '采集汇总.md').write_text('\n'.join(summary), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('scan', 'download', 'report'))
    parser.add_argument('--plan', required=True)
    parser.add_argument('--max-pages', type=int, default=50)
    parser.add_argument('--delay', type=float, default=2)
    parser.add_argument('--poll-seconds', type=float, default=5)
    parser.add_argument('--wait-seconds', type=float, default=600)
    args = parser.parse_args()
    if args.max_pages < 1 or args.delay < 0 or args.poll_seconds <= 0 or args.wait_seconds <= 0:
        raise ValueError('分页及等待参数无效')
    plan = load_plan(args.plan)
    out = Path(plan['output_dir'])
    if args.action == 'scan':
        scan(plan, out, args.max_pages, args.delay)
        return
    state = read_json(out / '采集记录.json')
    if any(state['plan'].get(k) != (plan.get(k, 'range') if k == 'validity_mode' else plan[k]) for k in state['plan']):
        raise ValueError('计划与已采集任务的日期或范围不一致，请勿修改运行中的计划')
    if args.action == 'download':
        download(plan, out, state, args.poll_seconds, args.wait_seconds)
    else:
        report(plan, out, state)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
