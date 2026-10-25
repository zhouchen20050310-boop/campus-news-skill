"""Read a source XLSX without third-party dependencies and prepare a search plan."""
import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import posixpath
import re
import xml.etree.ElementTree as ET
from zipfile import ZipFile

NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'


def text(node):
    return ''.join(node.itertext()) if node is not None else ''


def read_xlsx(path):
    with ZipFile(path) as archive:
        shared = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            shared = [''.join(t.text or '' for t in n.findall('.//m:t', NS))
                      for n in ET.fromstring(archive.read('xl/sharedStrings.xml'))]
        relationships = ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))
        targets = {n.attrib['Id']: n.attrib['Target'] for n in relationships}
        book = ET.fromstring(archive.read('xl/workbook.xml'))
        for sheet in book.find('m:sheets', NS):
            target = targets[sheet.attrib[f'{{{REL}}}id']]
            member = target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/' + target)
            rows = []
            for row in ET.fromstring(archive.read(member)).findall('.//m:sheetData/m:row', NS):
                cells = {}
                for cell in row.findall('m:c', NS):
                    col = re.sub(r'\d', '', cell.attrib['r'])
                    kind = cell.attrib.get('t')
                    value = cell.find('m:v', NS)
                    if kind == 's' and value is not None:
                        value = shared[int(value.text)]
                    elif kind == 'inlineStr':
                        value = ''.join(t.text or '' for t in cell.findall('.//m:t', NS))
                    else:
                        value = value.text if value is not None else ''
                    cells[col] = str(value).strip()
                rows.append((int(row.attrib['r']), cells))
            yield sheet.attrib['name'], rows


def prepare(path, publish_start, publish_end, valid_start, valid_end):
    dates = [date.fromisoformat(v) for v in [publish_start, publish_end, valid_start, valid_end]]
    if dates[0] > dates[1] or dates[2] > dates[3]:
        raise ValueError('每组起始日期必须不晚于结束日期')
    sources = {}
    count = 0
    for sheet, rows in read_xlsx(path):
        headers = None
        for number, cells in rows:
            if headers is None:
                if '来源（账号名称）' in cells.values():
                    headers = {v: k for k, v in cells.items() if v}
                continue
            get = lambda key: cells.get(headers.get(key, ''), '')
            name = get('来源（账号名称）')
            if not name:
                continue
            count += 1
            key = re.sub(r'\s+', '', name).casefold()
            if key not in sources:
                sources[key] = {
                    'source_id': 'src-' + hashlib.sha256(key.encode()).hexdigest()[:10],
                    'account': name, 'types': [], 'nature': [], 'topics': [],
                    'entries': [], 'original_rows': [], 'warnings': [],
                }
            item = sources[key]
            item['original_rows'].append(f'{sheet}!{number}')
            for dest, src in [('types', '账号类型'), ('nature', '性质'),
                              ('topics', '账号发布内容'), ('entries', '平台链接/入口')]:
                value = get(src)
                if value and value not in item[dest]:
                    item[dest].append(value)
    if not sources:
        raise ValueError('没有找到含“来源（账号名称）”表头的信源数据')
    for item in sources.values():
        item['eligible'] = any('公众号' in t for t in item['types'])
        if not item['eligible']:
            item['warnings'].append('当前规则只收集公众号原文，此来源暂跳过')
        if any(e.startswith('http') and 'mp.weixin.qq.com' not in e for e in item['entries']):
            item['warnings'].append('表内网址不是公众号原文入口，需另行定位公众号')
        if len(item['nature']) > 1:
            item['warnings'].append('原表性质标记不一致，需核对')
        item['queries'] = [f'site:mp.weixin.qq.com/s "{item["account"]}" {dates[0].year}年{dates[0].month}月']
    ordered = sorted(sources.values(), key=lambda s: ('官号' not in s['nature'], not s['eligible']))
    return {
        'source_file': str(Path(path).resolve()),
        'publish_start': publish_start, 'publish_end': publish_end,
        'valid_start': valid_start, 'valid_end': valid_end,
        'source_rows': count, 'sources': ordered,
        'eligible_sources': sum(s['eligible'] for s in ordered),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', required=True)
    for flag in ['publish-start', 'publish-end', 'valid-start', 'valid-end']:
        parser.add_argument('--' + flag, required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    result = prepare(args.sources, args.publish_start, args.publish_end, args.valid_start, args.valid_end)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'source_rows': result['source_rows'], 'unique_sources': len(result['sources']),
                      'eligible_sources': result['eligible_sources']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
