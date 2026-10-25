# 筛选与稿件数据

Agent 实际阅读后写 JSON。日期及有效日期模式复制本次 plan，文章编号来自本次阅读索引，文案根据对应原文生成。用户明确选择“不限”时，添加 validity_mode=unrestricted，valid_start/valid_end 都为 null；不能漏传模式或换成虚构日期。不限时可将有价值的新闻报道归为“新闻动态”，不要求它另有未来活动日期，但已截止的参与机会仍不能写成开放。build_news.py 不会自动执行语义筛选或调用模型 API。

```json
{
  "publish_start": "用户指定的YYYY-MM-DD",
  "publish_end": "用户指定的YYYY-MM-DD",
  "valid_start": "用户指定的YYYY-MM-DD",
  "valid_end": "用户指定的YYYY-MM-DD",
  "article_reviews": [
    {"article_id": "索引中的编号", "status": "候选", "reason": "本次筛选的理由", "read_files": ["实际读取的文件绝对路径"]}
  ],
  "events": [
    {
      "id": "C01",
      "title": "一项具体资讯的标题",
      "category": "编辑需要的分类",
      "source_ids": ["索引中的编号"],
      "time": "活动、报名和办理时间分别列明",
      "place": "地点；原文未说明可留空",
      "audience": "对象及限制",
      "highlights": "具体亮点与对学生的帮助",
      "action": "可执行的参与方式",
      "timing_status": "有效区间可参与",
      "validity_basis": "具体时间与有效区间的关系、哪些环节仍开放",
      "pending": [],
      "evidence": [{"article_id": "索引中的编号", "kind": "markdown", "quote": "已读MD中原样摘录的依据"}],
      "detail_links": [],
      "editor_choice": "",
      "editor_note": ""
    }
  ],
  "post": {"title": "推文标题", "summary": "主要亮点和时效概要", "author": "编辑指定作者", "intro": ["栏目引言", "本期有效日期说明", "栏目署名"]}
}
```

- 每篇原文恰有一条 article_reviews。状态：候选、限制提醒、待确认、长期资源、排除、待补读。read_files 须来自该篇索引，不虚填读取；待补读可空，不算完成阅读。
- 汇总文章可拆成多项 event，同一事件可关联多个来源。每条说明时间依据、学生价值和原文摘录，不固定候选数量或编造评分。
- timing_status 建议使用“有效区间可参与”“有效区间仅限已报名者”“有效区间仅可关注”“长期有效”“待确认”。活动期覆盖有效区间不等于报名开放。
- MD 摘录会做去空白的文本对应检查。图片或 PDF 依据用 kind=image/pdf，并在 read_files 记录实际读取路径；脚本不能证明图像解读正确，须保留人工复核。
- 缺少参与方式可写“【待确认】原文未说明参与方式”，并加入 pending。缺少有效日期的事项设为“待确认”，不会进入默认候选排版。
- editor_choice：空、入选、不入选、待定。用户确认后顶层加 selection_basis，记录其真实选择依据。用户要求先看候选排版可用 --provisional，不需要编造确认。
- 排版保留时间、地点、对象、亮点、参与方式、pending及来源；内部证据与阅读记录保存在JSON及交接文件中。
- 补充的官方链接可放 detail_links，每项含 url、title、checked_at及用途。未打开的单项链接写明未核验。
- CSV 供 Excel 阅读与修改，链接以完整文本输出。若用户明确需要 Word 或真正Excel，使用宿主文档/表格能力，不把 CSV 改扩展名冒充 xlsx。
