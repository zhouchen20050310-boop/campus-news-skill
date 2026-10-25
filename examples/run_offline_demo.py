"""Render synthetic editorial data; no network, account, model or browser calls."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/campus-news-collect/scripts'))
from news_common import write_json
from build_news import load_inputs, render, screen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default=str(ROOT / '.demo-output'))
    args = parser.parse_args()
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    md = out / '虚构原文.md'
    body = ('# 虚构示例：资料整理工作坊\n\n'
        '公众号：示例校园号。发布日期：2027-03-06。\n\n'
        '本示例完全虚构，只用于演示Skill排版。\n\n'
        '报名截止为2027年3月12日18:00，活动于3月13日下午举行。\n\n'
        '内容包括资料命名、分类与共享协作方法，面向对学习资料整理感兴趣的同学。\n\n'
        '示例未提供真实场地或报名入口。\n')
    md.write_text(body, encoding='utf-8')
    dates = {'publish_start': '2027-03-01', 'publish_end': '2027-03-07',
        'validity_mode': 'range', 'valid_start': '2027-03-08', 'valid_end': '2027-03-14'}
    aid = 'DEMO001'
    article = {'id': aid, 'account': '示例校园号（虚构）', 'title': '资料整理工作坊（虚构）',
        'url': 'https://mp.weixin.qq.com/s/example-not-a-real-article', 'published_at': '2027-03-06',
        'date_evidence': '虚构演示日期', 'markdown': str(md), 'pdfs': [], 'images': []}
    data = {**dates, 'demo_only': True,
        'article_reviews': [{'article_id': aid, 'status': '候选',
            'reason': '虚构事项的报名和活动都处于演示有效区间，体现资料整理价值。', 'read_files': [str(md)]}],
        'events': [{'id': 'D01', 'title': '学习资料整理工作坊（虚构示例）', 'category': '学习资源',
            'source_ids': [aid], 'time': '报名截止2027年3月12日18:00；活动为3月13日下午。',
            'audience': '对资料整理感兴趣的同学；本例不是实际招募。',
            'highlights': '围绕资料命名、分类与共享协作，展示如何把原文信息整理成清晰的资讯卡片。',
            'action': '本条为离线演示，未提供真实报名入口。', 'timing_status': '有效区间可参与',
            'validity_basis': '虚构活动及报名日期均在演示有效区间内，正式运行不得沿用这些日期。',
            'pending': ['正式稿需核对活动场地与报名入口。'],
            'evidence': [{'article_id': aid, 'kind': 'markdown',
                'quote': '报名截止为2027年3月12日18:00，活动于3月13日下午举行。'}], 'editor_choice': ''}],
        'post': {'title': '离线演示｜把学习资料整理成清晰的一期资讯',
            'summary': '完全虚构的排版示例，不连接微信或秀米。', 'author': '示例编辑',
            'intro': ['完全虚构 · 请勿直接发布', '校园资讯采编 Skill 离线演示', '日期、活动及链接均为结构示例']}}
    write_json(out / 'plan.json', {**dates, 'demo_only': True})
    write_json(out / '阅读索引.json', {'plan': dates, 'articles': [article]})
    write_json(out / '稿件输入.json', data)
    inputs = load_inputs(out / 'plan.json', out / '阅读索引.json', out / '稿件输入.json')
    screen(*inputs, out / 'screened')
    render(*inputs, out / 'layout', True)
    print('离线演示完成：' + str(out))


if __name__ == '__main__':
    main()
