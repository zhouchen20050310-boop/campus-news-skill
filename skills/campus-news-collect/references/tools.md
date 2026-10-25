# 工具接入与执行

## 运行条件

- Agent 需要读写本地文件、执行 Python 3.11+，并访问用户电脑上的 WeChat MP Tools HTTP 服务。云端 Agent 的 127.0.0.1 不指向用户电脑，不能直接套用本地地址。
- 用户安装、启动并登录 WeChat MP Tools，收藏需要采集的公众号。适配器使用 v2.3.1 的 API 约定，默认地址 `http://127.0.0.1:5200`，可用 --tool-url 指定实际地址。
- 采集与排版脚本使用 Python 标准库。桌面工具需能生成 MD、PDF、HTML、图片；Skill 不修改其源码、下载设置或授权信息，格式缺失时报告并指导用户检查设置。
- 秀米需要单独准备 [all-to-xiumi](https://github.com/hanselhan23/all-to-xiumi)、Selenium、Edge及驱动。通过 --project 指定项目目录，--deps 指定可选的 Python 依赖目录；更新工具后检查转换与导入结果。
- 第三方工具、依赖和浏览器登录资料单独管理。适配器使用下载工具已有的登录状态，无需读取或导出账号池 Cookie。

## 命令

在 Skill 根目录执行。尖括号为占位说明，运行时换成用户指定路径、YYYY-MM-DD日期：

```text
python scripts/prepare_run.py --scope <公众号范围.txt> --publish-start <采集开始日> --publish-end <采集结束日> --valid-start <有效开始日> --valid-end <有效结束日> --output <新任务目录>
python scripts/collect_articles.py scan --plan <新任务目录/plan.json>
python scripts/collect_articles.py download --plan <新任务目录/plan.json>
python scripts/build_news.py screen --plan <plan.json> --index <阅读索引.json> --data <Agent撰写的筛选数据.json> --output <筛选目录>
python scripts/build_news.py layout --plan <plan.json> --index <阅读索引.json> --data <已完善文案的筛选数据.json> --output <排版目录> --provisional
```

选题由用户确认后，记录真实 selection_basis 及 editor_choice，排版时去掉 --provisional。用户在 CSV 中填写选择后按资讯编号合并回 JSON，不编造确认。

有效日期也可由用户明确指定“不限”：prepare_run 使用 --valid-unrestricted，不再传 --valid-start/--valid-end，计划记录 validity_mode=unrestricted 且两端为 null；没有用户这项输入时不能自行默认不限。后续筛选和排版必须沿用该模式，采集发布日期范围仍为必填。

prepare_run 返回2表示收藏或名称匹配阻塞；返回1表示参数、输入或连接错误。离线核对 offline_checked 不能采集。范围文件变化后重新检查；已提交任务的目录不能改作另一组日期。

scan 默认每账号最多50页、页间2秒。实际到达日期边界、接口末页、重复页或错误时记录终止原因。未知日期的最新封面条目也下载以核对，下载后未知或越界内容独立归档。时间均按 Asia/Shanghai。

download 每次只为一个账号提交任务，默认5秒轮询，本次单账号等待最多600秒。宿主以可管理的后台进程和短轮询执行，并向用户更新进度。超时后工具可能仍在下载，再运行同一命令继续轮询，不重复提交。提交结果未知时先核对工具界面，不猜测重试。

## API

| 调用 | 用途 |
| --- | --- |
| GET /api/accounts | accounts 数组，nickname、fakeid |
| GET /api/articles/list/账号标识?begin=0&count=20 | articles、can_msg_continue；update_time 可能为0或毫秒 |
| POST /api/articles/download | account_name、articles，返回 task_id |
| GET /api/articles/download-status/任务标识 | status、results（title、success、path/error） |

HTTP 200仍需核对 error、need_verify、success。收藏检查只读，不自动添加或取消收藏。

## 输出与预览

采集前 plan.json、采集前检查.md；采集后采集记录.json、列表记录、区间内/日期待确认/范围外资料、两份 CSV、阅读索引.json、推文正文合集.md 和采集汇总。每篇归档省略 .txt；下载工具内部文件保持原样。归档成功不等于 PDF已生成、正文已核验或渠道已收齐。

截图使用宿主已有浏览器能力。HTTP 预览可在排版目录运行 `python -m http.server <空闲端口> --bind 127.0.0.1`，仅作为本地预览。
