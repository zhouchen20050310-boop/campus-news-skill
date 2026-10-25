"""Export AI-authored screening records and render source-linked editorial drafts."""
import argparse
import csv
from html import escape
import json
from pathlib import Path
import re
import sys
import urllib.parse
from news_common import canonical, date_ranges, read_json, validity_label, write_json

STATUSES = ('候选', '限制提醒', '待确认', '长期资源', '排除', '待补读')
FIELDS = [('时间', 'time'), ('地点', 'place'), ('对象', 'audience'), ('亮点', 'highlights'), ('参与方式', 'action')]


def load_inputs(plan_path, index_path, data_path):
    plan = date_ranges(read_json(plan_path))
    index = read_json(index_path)
    data = date_ranges(read_json(data_path))
    for key in ('publish_start', 'publish_end', 'valid_start', 'valid_end'):
        if data[key] != plan[key] or index['plan'][key] != plan[key]:
            raise ValueError('稿件、阅读索引与本次计划的日期不一致：' + key)
    if any(item.get('validity_mode', 'range') != plan.get('validity_mode', 'range') for item in (data, index['plan'])):
        raise ValueError('稿件、阅读索引与计划的有效日期模式不一致')
    articles = {a['id']: a for a in index['articles']}
    if len(articles) != len(index['articles']):
        raise ValueError('阅读索引的文章编号重复')
    reviewed = set()
    for review in data['article_reviews']:
        aid = review['article_id']
        if aid not in articles or aid in reviewed:
            raise ValueError('逐篇阅读记录包含未知或重复编号：' + aid)
        reviewed.add(aid)
        if review['status'] not in STATUSES or not review.get('reason'):
            raise ValueError('每篇须记录筛选状态和理由：' + aid)
        article = articles[aid]
        allowed = {str(Path(p).resolve()) for p in [article.get('markdown', ''),
            *article.get('pdfs', []), *article.get('images', [])] if p}
        if review['status'] != '待补读' and not review.get('read_files'):
            raise ValueError('已阅读的条目须记录实际读取的文件：' + aid)
        for path in review.get('read_files', []):
            if str(Path(path).resolve()) not in allowed or not Path(path).is_file():
                raise ValueError('阅读记录的文件不在原文资料索引内：' + path)
    if reviewed != set(articles):
        raise ValueError('缺少逐篇阅读记录：' + ','.join(sorted(set(articles) - reviewed)))
    seen = set()
    for event in data['events']:
        if not event.get('id') or event['id'] in seen:
            raise ValueError('资讯编号缺失或重复')
        seen.add(event['id'])
        for key in ('title', 'category', 'time', 'highlights', 'action', 'timing_status', 'validity_basis'):
            if not isinstance(event.get(key), str) or not event[key].strip():
                raise ValueError(f'{event["id"]}缺少字段：{key}')
        if not isinstance(event.get('pending', []), list) or any(not isinstance(v, str) for v in event.get('pending', [])):
            raise ValueError('pending 必须为待确认事项的文字数组')
        if event.get('editor_choice', '') not in ('', '入选', '不入选', '待定'):
            raise ValueError('人工选择值无效')
        if not event.get('source_ids') or any(aid not in articles for aid in event['source_ids']):
            raise ValueError('资讯必须引用本次已采集原文编号：' + event['id'])
        for aid in event['source_ids']:
            if not plan['publish_start'] <= articles[aid]['published_at'] <= plan['publish_end']:
                raise ValueError('原文日期越界：' + aid)
        if not event.get('evidence'):
            raise ValueError('资讯缺少原文依据：' + event['id'])
        for evidence in event['evidence']:
            if evidence.get('article_id') not in event['source_ids'] or not evidence.get('quote'):
                raise ValueError('依据必须关联本条原文并含摘录：' + event['id'])
            # Exact-text checks apply to MD quotes; image/PDF observations remain attributed.
            if evidence.get('kind', 'markdown') == 'markdown':
                md = articles[evidence['article_id']].get('markdown')
                if not md or not Path(md).is_file():
                    raise ValueError('Markdown 依据缺少文件')
                normal = lambda s: re.sub(r'\s+', '', s)
                if normal(evidence['quote']) not in normal(Path(md).read_text(encoding='utf-8-sig', errors='replace')):
                    raise ValueError('依据摘录未出现在 Markdown 中：' + event['id'])
    return plan, articles, data


def screen(plan, articles, data, out):
    out.mkdir(parents=True, exist_ok=True)
    candidates = []
    for event in data['events']:
        candidates.append({'编号': event['id'], '人工选择': event.get('editor_choice', ''),
            '编辑备注': event.get('editor_note', ''), '类别': event['category'], '资讯标题': event['title'],
            '时间': event['time'], '有效性判断': event['timing_status'], '时间依据': event['validity_basis'],
            '地点': event.get('place', ''), '对象': event.get('audience', ''), '亮点': event['highlights'],
            '参与方式': event['action'], '待确认': '；'.join(event.get('pending', [])),
            '来源编号': '；'.join(event['source_ids']),
            '原文链接': '\n'.join(articles[a]['url'] for a in event['source_ids'])})
    fields = ['编号', '人工选择', '编辑备注', '类别', '资讯标题', '时间', '有效性判断', '时间依据', '地点', '对象', '亮点', '参与方式', '待确认', '来源编号', '原文链接']
    with (out / '候选资讯清单.csv').open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(candidates)
    with (out / '逐篇筛选记录.csv').open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=['原文编号', '标题', '状态', '理由', '实际阅读文件'])
        writer.writeheader()
        writer.writerows({'原文编号': r['article_id'], '标题': articles[r['article_id']]['title'],
            '状态': r['status'], '理由': r['reason'], '实际阅读文件': '\n'.join(r.get('read_files', []))}
            for r in data['article_reviews'])
    lines = ['# 资讯筛选与编辑交接', '', f'文章采集日期：{plan["publish_start"]} 至 {plan["publish_end"]}',
        f'资讯有效日期：{validity_label(plan)}',
        f'逐篇记录：{len(data["article_reviews"])}；候选事项：{len(candidates)}。',
        '脚本验证数据及摘录对应，不代替编辑判断，也不能证明 Agent 已实际读懂全部材料。', '']
    for event in data['events']:
        lines += [f'## {event["id"]} {event["title"]}', '',
            '有效性：' + event['timing_status'] + '；' + event['validity_basis']]
        lines += [(event.get('action_label', label) if key == 'action' else label) + '：' + event[key] for label, key in FIELDS if event.get(key)]
        lines += ['【待确认】' + v for v in event.get('pending', [])]
        lines += ['原文链接：' + articles[a]['url'] for a in event['source_ids']]
        lines += ['']
    (out / '筛选交接.md').write_text('\n'.join(lines), encoding='utf-8')
    write_json(out / '筛选数据.json', data)


def paragraph(text, style='', label=''):
    return '<p style="margin:0 0 10px;line-height:1.85;overflow-wrap:anywhere;' + style + '">' + (
        '<strong>【' + escape(label) + '】</strong>' if label else '') + escape(text) + '</p>'


def hyperlink(url, label='原文链接'):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        raise ValueError('无法输出无效链接：' + url)
    return '<p style="margin:0 0 12px;font-size:12px;line-height:1.7;word-break:break-all;">' + escape(label) + '：<a style="color:#5682ae;word-break:break-all;" href="' + escape(url, quote=True) + '">' + escape(url) + '</a></p>'


def render(plan, articles, data, out, provisional):
    post = data.get('post', {})
    if not post.get('title') or not post.get('summary'):
        raise ValueError('排版前请生成推文标题和概要并写入 post.title / post.summary')
    selected = [e for e in data['events'] if e.get('editor_choice') == '入选' or
        (provisional and e.get('editor_choice', '') in ('', '待定') and e['timing_status'] != '待确认')]
    if not selected:
        raise ValueError('没有入选资讯；如用户要求先看候选排版草稿，使用 --provisional 并明确标注未确认')
    if not provisional and not data.get('selection_basis'):
        raise ValueError('缺少编辑确认依据，请记录用户实际选择；不替编辑编造确认')
    out.mkdir(parents=True, exist_ok=True)
    template = (Path(__file__).resolve().parents[1] / 'assets' / 'layout.html').read_text(encoding='utf-8')
    period = f'文章发布：{plan["publish_start"]} 至 {plan["publish_end"]}' if plan.get('validity_mode') == 'unrestricted' else validity_label(plan)
    intro = post.get('intro') or ['校园资讯栏目继续更新！', period, '资讯汇总、尽在鲤工包打听']
    top = '<section style="text-align:center;margin:20px 0 28px;">' + ''.join(paragraph(s, 'text-align:center;') for s in intro) + '</section>'
    md = ['# ' + post['title'], '', '概要：' + post['summary'], '', *intro, '']
    if provisional:
        md += ['【待确认】本稿为候选排版，编辑尚未确认最终选题。', '']
    bodies = {'普通版': [top], '秀米兼容版': [top]}
    groups = list(dict.fromkeys(e['category'] for e in selected))
    checks = ['# 编辑核对清单', '', '稿件状态：' + ('候选排版，尚未确认选题' if provisional else '依据记录的编辑选择生成'),
        '标题：' + post['title'], '概要：' + post['summary'], '', '未自动加入头图和活动配图；需要时由编辑替换。', '']
    number = 0
    for category in groups:
        cat = '<section style="text-align:center;margin:24px 0 20px;"><p style="margin:0;text-align:center;line-height:2.5;"><span style="display:inline-block;background-color:#3885ee;color:#fff;border:2px solid #333;padding:3px 14px;font-size:18px;font-weight:700;box-shadow:3px 3px 0 #fff,4px 4px 0 #333;">' + escape(category) + '</span></p></section>'
        for body in bodies.values():
            body.append(cat)
        md += ['## ' + category, '']
        for event in [e for e in selected if e['category'] == category]:
            number += 1
            title = f'{number:02d}  {event["title"]}'
            card = '<section data-news-id="' + escape(event['id'], quote=True) + '" style="margin:0 0 24px;">'
            card += '<p data-news-title="true" style="margin:0 0 16px;padding:9px 10px;background-color:#edf9fc;border-bottom:1px solid #b5ddfa;color:#1b1b1b;font-size:16px;line-height:1.8;font-weight:700;">' + escape(title) + '</p>'
            md += ['### ' + title, '']
            for label, key in FIELDS:
                if event.get(key):
                    if key == 'action':
                        label = event.get('action_label', label)
                    card += paragraph(event[key], label=label)
                    md += ['【' + label + '】' + event[key], '']
            for pending in event.get('pending', []):
                card += paragraph('【待确认】' + pending, 'padding:9px 10px;background-color:#fff8e7;color:#8a6300;font-size:13px;')
                md += ['【待确认】' + pending, '']
                checks.append(f'- {title}：【待确认】{pending}')
            for aid in event['source_ids']:
                article = articles[aid]
                canonical(article['url'])
                card += paragraph(f'来源：{article["account"]}｜{article["published_at"]}', 'color:#6b7280;font-size:13px;') + hyperlink(article['url'])
                md += ['来源：' + article['account'] + '｜' + article['published_at'], '原文链接：' + article['url'], '']
            for link in event.get('detail_links', []):
                card += hyperlink(link['url'], '具体活动原文')
                md += ['具体活动原文：' + link['url'], '']
            card += '</section>'
            bodies['秀米兼容版'].append(card)
            dots = '<section style="display:flex;justify-content:center;gap:5px;margin:0 0 12px;">' + '<span style="display:inline-block;width:5px;height:5px;border-radius:50%;background:#b5ddfa;">&#8203;</span>' * 3 + '</section>'
            bodies['普通版'].append(card + dots)
    end = '<section data-end="true" style="margin:28px 0 32px;text-align:center;">' + paragraph('END', 'text-align:center;font-weight:700;letter-spacing:4px;') + '</section>'
    for name, sections in bodies.items():
        sections.append(end)
        output = template.replace('{{TITLE}}', escape(post['title'])).replace('{{CONTENT}}', ''.join(sections))
        (out / f'校园资讯_{name}.html').write_text(output, encoding='utf-8')
    md += ['END', '']
    (out / '推文文案.md').write_text('\n'.join(md), encoding='utf-8')
    (out / '编辑核对清单.md').write_text('\n'.join(checks), encoding='utf-8')
    write_json(out / '稿件数据.json', {**data, 'rendered_ids': [e['id'] for e in selected], 'provisional': provisional})
    write_json(out / '排版检查.json', {'entry_count': number, 'categories': len(groups),
        'pending_count': sum(len(e.get('pending', [])) for e in selected), 'same_content': True,
        'images_inserted': 0, 'ends_at_END': True, 'visual_review': '尚未执行',
        'xiumi_import': '尚未执行', 'xiumi_save_and_reopen': '尚未执行'})
    print(json.dumps({'output': str(out), 'entries': number, 'provisional': provisional}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('screen', 'layout'))
    for flag in ('plan', 'index', 'data', 'output'):
        parser.add_argument('--' + flag, required=True)
    parser.add_argument('--provisional', action='store_true')
    args = parser.parse_args()
    plan, articles, data = load_inputs(args.plan, args.index, args.data)
    if args.action == 'screen':
        screen(plan, articles, data, Path(args.output))
    else:
        render(plan, articles, data, Path(args.output), args.provisional)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
