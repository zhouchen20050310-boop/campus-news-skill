import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';

const artifact = process.env.NEWS_NODE_MODULES
  ? await import(pathToFileURL(createRequire(path.resolve(process.env.NEWS_NODE_MODULES, '..', 'package.json')).resolve('@oai/artifact-tool')).href)
  : await import('@oai/artifact-tool');
const { Workbook, SpreadsheetFile } = artifact;

const [input, output] = process.argv.slice(2);
if (!input || !output) throw new Error('用法: node export_candidates.mjs <reviewed.json> <output.xlsx>');
const data = JSON.parse((await fs.readFile(input, 'utf8')).replace(/^\uFEFF/, ''));
const wb = Workbook.create();
const plan = data.plan;
const sourceMap = new Map(plan.sources.map(s => [s.source_id, s]));
const period = `发布：${plan.publish_start} 至 ${plan.publish_end}；适用：${plan.valid_start} 至 ${plan.valid_end}`;
const incomplete = data.coverage.some(c => ['未检索', '访问受限', '工具不可用'].includes(c.status));
const beijingStamp = value => value ? new Date(Date.parse(value) + 8 * 60 * 60 * 1000) : '';
// Treat all collected page text as literal text, including formula-like strings.
const literal = value => typeof value === 'string' && /^[=+@-]/.test(value) ? "'" + value : value;
function matrix(sheet, row, values) {
  if (values.length) sheet.getRangeByIndexes(row - 1, 0, values.length, values[0].length).values = values.map(r => r.map(literal));
}
function setup(name, headers, rows, widths) {
  const s = wb.worksheets.add(name);
  s.showGridLines = false;
  const end = Math.max(7, rows.length + 6);
  s.getRangeByIndexes(0, 0, end, headers.length).format.font = {name: 'Microsoft YaHei', size: 10, color: '#223047'};
  s.getRange('A2').values = [[name]];
  s.getRange('A2').format.font = {name: 'Microsoft YaHei', size: 14, bold: true};
  s.getRange('A3').values = [[period]];
  s.getRange('A4').values = [[name === '检索覆盖' ? `输入信源：${plan.source_file}` :
    `${incomplete ? '检索未完成，请查看检索覆盖。' : ''}已核验候选 ${data.counts['候选']} 条；待核验 ${data.counts['待核验']} 条；排除 ${data.counts['排除']} 条。人工选择留给编辑填写。`]];
  // Keep context outside data rows; allow it to span otherwise empty cells visually.
  s.getRange('A3:A4').format.wrapText = false;
  matrix(s, 6, [headers, ...rows]);
  s.getRangeByIndexes(5, 0, 1, headers.length).format = {
    fill: '#244664', font: {name: 'Microsoft YaHei', size: 10, bold: true, color: '#FFFFFF'},
    horizontalAlignment: 'center', verticalAlignment: 'center', rowHeight: 30,
  };
  s.getRangeByIndexes(6, 0, Math.max(1, rows.length), headers.length).format.verticalAlignment = 'top';
  s.getRangeByIndexes(6, 0, Math.max(1, rows.length), headers.length).format.wrapText = true;
  widths.forEach((width, i) => s.getRangeByIndexes(5, i, Math.max(2, rows.length + 1), 1).format.columnWidth = width);
  if (rows.length) {
    s.tables.add(`A6:${String.fromCharCode(64 + headers.length)}${rows.length + 6}`, true,
      name === '候选资讯' ? 'NewsCandidates' : name === '待核验' ? 'NeedsReview' : 'SearchCoverage');
    s.getRangeByIndexes(6, 0, rows.length, headers.length).format.autofitRows();
  }
  s.freezePanes.freezeRows(6);
  return s;
}
const headers = ['人工选择','编辑备注','标题','发布账号','发布日期','类别','资讯概要','学生价值','适用判断','时间依据','活动时间','报名截止','施行或服务时间','阅读量','原文链接','核验时间（北京时间）'];
function articleRow(a) {
  const t = a.timing || {};
  return ['', '', a.title || '', a.account || '', a.published_at ? new Date(a.published_at + 'T00:00:00Z') : '',
    a.category || '', a.summary || '', a.student_value || '', t.status || '', t.basis || '',
    t.event_time || '', t.registration_deadline || '', t.effective_time || '',
    a.read_count ?? a.read_count_display ?? '', a.url || '', beijingStamp(a.checked_at)];
}
const eligible = data.articles.filter(a => a.review_status === '候选');
const other = data.articles.filter(a => a.review_status !== '候选');
const widths = [12,24,42,25,14,18,45,36,22,42,28,24,28,12,40,27];
const candidates = setup('候选资讯', headers, eligible.map(articleRow), widths);
const pending = setup('待核验', ['处理状态', '待补证据或排除原因', ...headers.slice(2)],
  other.map(a => [a.review_status, a.review_reasons.join('；'), ...articleRow(a).slice(2)]), widths);
if (eligible.length) {
  candidates.getRange(`A7:A${eligible.length + 6}`).dataValidation = {rule: {type: 'list', values: ['入选','不入选','待定']}};
  candidates.getRange(`A7:B${eligible.length + 6}`).format.fill = '#FFF3CD';
}
for (const [s, n] of [[candidates, eligible.length], [pending, other.length]]) {
  if (n) {
    s.getRange(`E7:E${n + 6}`).setNumberFormat('yyyy-mm-dd');
    s.getRange(`P7:P${n + 6}`).setNumberFormat('yyyy-mm-dd hh:mm');
  }
}
const coverage = setup('检索覆盖', ['账号','表内性质','检索状态','实际查询','检索时间（北京时间）','备注','原表位置'],
  data.coverage.map(c => {
    const s = sourceMap.get(c.source_id);
    return [s.account, s.nature.join('、'), c.status, (c.queries || []).join('\n'), beijingStamp(c.checked_at),
      [c.note || '', ...s.warnings].filter(Boolean).join('；'), s.original_rows.join('、')];
  }), [35,15,18,65,27,65,25]);
coverage.getRange(`E7:E${data.coverage.length + 6}`).setNumberFormat('yyyy-mm-dd hh:mm');
coverage.getRange(`C7:C${data.coverage.length + 6}`).conditionalFormats.add('containsText', {
  text: '未检索', format: {fill: '#FFF3CD'},
});
wb.recalculate();
await fs.mkdir(path.dirname(output), {recursive:true});
const file = await SpreadsheetFile.exportXlsx(wb);
await file.save(output);
// Optional QA previews, kept next to the workbook only when explicitly requested.
if (process.env.NEWS_PREVIEW_DIR) {
  await fs.mkdir(process.env.NEWS_PREVIEW_DIR, {recursive:true});
  for (const [name, range] of [['候选资讯', 'A1:J10'], ['待核验', 'A1:J10'], ['检索覆盖', 'A1:G12']]) {
    const preview = await wb.render({sheetName:name, range, scale:1, format:'png'});
    await fs.writeFile(path.join(process.env.NEWS_PREVIEW_DIR, name + '.png'), new Uint8Array(await preview.arrayBuffer()));
  }
}
console.log(JSON.stringify({output, counts:data.counts}, null, 2));
