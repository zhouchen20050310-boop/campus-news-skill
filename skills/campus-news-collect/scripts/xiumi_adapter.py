"""Use a separately installed all-to-xiumi project; never publish to WeChat."""
import argparse
from html.parser import HTMLParser
import importlib
import json
import os
from pathlib import Path
import re
import sys
import time
from news_common import digest, now, read_json, write_json


def normal(value):
    return re.sub(r'\s+', ' ', value or '').strip()


class Paragraphs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paragraphs, self.links, self.titles = [], [], []
        self.current, self.is_title = None, False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'p':
            if self.current is not None:
                raise ValueError('正文出现嵌套段落')
            self.current, self.is_title = [], attrs.get('data-news-title') == 'true'
        if tag == 'a' and attrs.get('href'):
            self.links.append(attrs['href'])

    def handle_data(self, data):
        if self.current is not None:
            self.current.append(data)

    def handle_endtag(self, tag):
        if tag == 'p' and self.current is not None:
            text = normal(''.join(self.current))
            if text:
                self.paragraphs.append(text)
                if self.is_title:
                    self.titles.append(text)
            self.current = None


def source_content(path):
    source = Path(path).read_text(encoding='utf-8')
    match = re.search(r'<main\b[^>]*>([\s\S]*)</main>', source, re.I)
    if not match:
        raise ValueError('缺少推文 main 容器')
    content = match[1]
    if re.search(r'<(?:script|iframe)\b|display\s*:\s*flex', content, re.I):
        raise ValueError('请使用 Skill 生成的秀米兼容版 HTML')
    expected = Paragraphs()
    expected.feed(content)
    if not expected.titles or not expected.paragraphs or expected.paragraphs[-1] != 'END':
        raise ValueError('资讯标题缺失或正文没有以 END 结束')
    return content, expected


def dependency(project, deps):
    if deps:
        sys.path.insert(0, str(Path(deps).resolve()))
    sys.path.insert(0, str(Path(project).resolve()))
    module = importlib.import_module('all_to_xiumi.xiumi_publish')
    for name in ('_xiumi_html_to_blocks', '_make_xiumi_browser', '_open_xiumi_editor',
                 '_fill_xiumi_fields', '_fill_xiumi_body_then_images', '_click_save'):
        if not hasattr(module, name):
            raise RuntimeError('all-to-xiumi 版本不兼容，缺少：' + name)
    return module


def run(args):
    content, expected = source_content(args.html)
    source_hash = digest(Path(args.html).read_text(encoding='utf-8'))
    xp = dependency(args.project, args.deps)
    blocks = xp._xiumi_html_to_blocks(content)
    if not blocks:
        raise ValueError('秀米本地转换没有生成正文块')
    converted = Paragraphs()
    for block in blocks:
        converted.feed(block['text'])
    if converted.paragraphs != expected.paragraphs:
        raise ValueError('秀米本地转换前后段落内容不一致')
    if not set(expected.links).issubset(converted.links):
        raise ValueError('秀米本地转换丢失原文链接')
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / '本地转换检查.json', {'checked_at': now(), 'entries': len(expected.titles),
        'blocks': len(blocks), 'paragraphs_preserved': True, 'links_preserved': True, 'uploaded': False})
    if args.action == 'check':
        print('本地转换检查通过；未启动浏览器或上传。')
        return
    if not args.draft or not args.profile:
        raise ValueError('start 需要 --draft 稿件数据.json 和独立的 --profile 目录')
    if (out / 'command.json').exists() or (out / '导入状态.json').exists():
        raise ValueError('导入记录目录已存在，请另选空目录，避免重放旧命令')
    draft = read_json(args.draft)
    post = draft['post']
    if not post.get('title') or not post.get('summary'):
        raise ValueError('缺少标题或概要')
    expected_fields = {'input.title': post['title'], 'input.author': post.get('author', ''),
        'textarea.desc': post['summary']}
    os.environ['WANYOU_SELENIUM_BROWSER'] = 'edge'
    # Keep dependency logs and driver caches in this private run, not its source tree.
    xp._XIUMI_DEBUG_LOG_PATH = out / '工具调试.jsonl'
    xp.config.SELENIUM_CACHE_DIR = str(out / 'driver-cache')
    browser = xp._make_xiumi_browser(Path(args.profile).resolve())
    imported_hash = None
    opened, imported, saved_url = False, False, None

    def snapshot(stage):
        observed = browser.execute_script(r"""
          const nodes=Array.from(document.querySelectorAll('[contenteditable="true"]'))
            .filter(e=>e.getBoundingClientRect().width>0);
          return {content:nodes.map(e=>e.innerText).join('\n'),body:document.body.innerText,
            links:nodes.flatMap(e=>Array.from(e.querySelectorAll('a')).map(a=>a.href)),
            widths:nodes.map(e=>Math.round(e.getBoundingClientRect().width*10)/10),
            fields:{'input.title':document.querySelector('input.title')?.value,
                    'input.author':document.querySelector('input.author')?.value,
                    'textarea.desc':document.querySelector('textarea.desc')?.value}};
        """)
        observed_content = normal(observed['content'])
        body = observed['body']
        state = {'stage': stage, 'time': now(), 'url': browser.current_url,
            'entry_count': sum(t in observed_content for t in expected.titles),
            'missing_paragraphs': [p for p in expected.paragraphs if p not in observed_content],
            'missing_links': sorted(set(expected.links) - set(observed['links'])),
            'ends_at_END': observed_content.endswith('END'),
            'pending_count': observed['content'].count('【待确认】'),
            'expected_pending_count': sum(p.count('【待确认】') for p in expected.paragraphs),
            'editor_widths': observed['widths'], 'content_hash': digest(observed_content),
            'field_mismatches': [key for key, value in expected_fields.items() if observed['fields'].get(key) != value],
            'capacity_full': bool(re.search(r'容量.{0,16}(?:已满|不足)|空间.{0,16}(?:已满|不足)', body)),
            'recovery_prompt': '上次没有保存' in body or '是否恢复' in body}
        browser.save_screenshot(str(out / (stage + '.png')))
        write_json(out / (stage + '.json'), state)
        return state

    def recovery_guard(b):
        body = b.execute_script('return document.body.innerText')
        if '上次没有保存' in body or '是否恢复' in body:
            raise RuntimeError('遇到旧稿恢复提示，已保留页面，请用户处理后再继续')
        return {'text': None}

    def require_complete(state, check_changes=True):
        if (state['missing_paragraphs'] or state['missing_links'] or state['field_mismatches']
                or not state['ends_at_END'] or state['capacity_full'] or state['recovery_prompt']
                or state['entry_count'] != len(expected.titles)
                or state['pending_count'] != state['expected_pending_count']
                or not state['editor_widths'] or min(state['editor_widths']) < 150):
            raise RuntimeError('正文、字段、链接或版式检查不一致，已保留页面并停止保存/重开')
        if check_changes and imported_hash and state['content_hash'] != imported_hash:
            raise RuntimeError('页面正文已被编辑，不覆盖或重开，请用户确认以哪份内容为准')

    def manual_login(b, timeout):
        print('LOGIN_REQUIRED：请用户在此 Edge 窗口本人完成扫码。', flush=True)
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if xp._xiumi_login_state(b).get('authenticated'):
                return True
            time.sleep(2)
        return False

    xp._dismiss_xiumi_recover_dialog = recovery_guard
    xp._wait_for_manual_login = manual_login
    browser.get(xp.config.XIUMI_HOME_URL)
    write_json(out / '导入状态.json', {'stage': 'waiting_command', 'time': now(),
        'message': '浏览器已打开；发送 open 命令开始，登录由用户完成。'})
    print('XIUMI_READY：通过本目录 command.json 依次发送 open/import/save/reopen/snapshot。', flush=True)
    last_id = None
    while True:
        command_path = out / 'command.json'
        try:
            if command_path.exists():
                command = read_json(command_path)
                if command.get('id') is None:
                    raise ValueError('命令缺少唯一 id')
                if command['id'] == last_id:
                    time.sleep(1)
                    continue
                last_id = command['id']
                action = command['action']
                if digest(Path(args.html).read_text(encoding='utf-8')) != source_hash:
                    raise RuntimeError('导入源文件已变化，请保留当前编辑页，重新核对源稿')
                recovery_guard(browser)
                if action == 'open':
                    if opened or imported:
                        raise ValueError('编辑页已打开，不重复创建或覆盖')
                    xp._open_xiumi_editor(browser, xp.config.XIUMI_HOME_URL, 45, 30)
                    opened = True
                    snapshot('new-editor')
                elif action == 'import':
                    if not opened or imported:
                        raise ValueError('须先 open；同一会话只导入一次，保护人工编辑')
                    before = browser.execute_script("return Array.from(document.querySelectorAll('[contenteditable=\"true\"]')).map(e=>e.innerText).join('').trim()")
                    if before:
                        raise RuntimeError('新编辑页含正文，不覆盖，请用户核对')
                    imported = True  # even a partial failure must not silently overwrite on retry
                    xp._fill_xiumi_fields(browser, post['title'], post.get('author', ''), '', post['summary'])
                    xp._fill_xiumi_body_then_images(browser, content, Path(args.html).resolve(), preserve_styles=True)
                    state = snapshot('imported')
                    require_complete(state, False)
                    imported_hash = state['content_hash']
                elif action == 'save':
                    if not imported_hash:
                        raise ValueError('尚未完成导入核对')
                    require_complete(snapshot('before-save'))
                    xp._click_save(browser)
                    time.sleep(5)
                    state = snapshot('after-save')
                    require_complete(state)
                    if not re.search(r'/paper/for/\d+/cube/', state['url']):
                        raise RuntimeError('未取得已保存草稿地址，请核对登录、容量或保存提示；不刷新页面')
                    saved_url = state['url']
                elif action == 'reopen':
                    if not saved_url or browser.current_url != saved_url:
                        raise ValueError('尚未核对保存结果或页面已切换，不重开')
                    require_complete(snapshot('before-reopen'))
                    browser.refresh()
                    xp._wait_editor_ready(browser, 30)
                    time.sleep(2)
                    state = snapshot('saved-and-reopened')
                    require_complete(state)
                    write_json(out / 'result.json', {**state, 'saved_and_reopened': True})
                elif action == 'snapshot':
                    snapshot('current')
                else:
                    raise ValueError('不支持此命令')
                write_json(out / '导入状态.json', {'stage': action + '_done', 'time': now(),
                    'command_id': last_id, 'saved_and_reopened': (out / 'result.json').exists()})
                print('ACTION_DONE ' + str(last_id), flush=True)
        except Exception as error:
            write_json(out / '导入状态.json', {'stage': 'attention', 'time': now(),
                'error': str(error), 'command_id': last_id, 'saved_and_reopened': False})
            print('ATTENTION: ' + str(error), flush=True)
        time.sleep(1)
    # Deliberately keep this dedicated browser alive; never quit a user's editing page.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('check', 'start'))
    for flag in ('project', 'html', 'output'):
        parser.add_argument('--' + flag, required=True)
    parser.add_argument('--deps')
    parser.add_argument('--draft')
    parser.add_argument('--profile')
    run(parser.parse_args())


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, OSError, ImportError, KeyError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
