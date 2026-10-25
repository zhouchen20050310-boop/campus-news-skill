# 秀米草稿导入

依赖独立的 all-to-xiumi、Selenium 与 Edge 环境。本适配器处理本 Skill 生成的纯文字兼容 HTML，图片由编辑补充；普通版的 flex 装饰不用于此导入。

## 检查格式转换

```text
python scripts/xiumi_adapter.py check --project <all-to-xiumi目录> --deps <可选依赖目录> --html <校园资讯_秀米兼容版.html> --output <转换核对目录>
```

当前 Python 已安装依赖时省略 --deps。此命令检查转换前后的段落与链接是否一致。

## 独立编辑会话

用户要求导入后执行，以宿主管理的后台执行会话保持进程。使用新的空记录目录和独立 profile，不复用用户正在编辑的旧页；登录资料不进包。

```text
python scripts/xiumi_adapter.py start --project <all-to-xiumi目录> --deps <可选依赖目录> --html <校园资讯_秀米兼容版.html> --draft <稿件数据.json> --profile <私有浏览器目录> --output <新的导入记录目录>
```

脚本打开 Edge 并等待命令。Agent 在本次记录目录写 command.json，每条命令使用新的 id：

```json
{"id": "本次唯一编号", "action": "open"}
```

依次发送 open → import → save → reopen；每次等导入状态.json与stdout确认本命令完成，再发下一条，不能并发或提前排队。

| action | 操作和标准 |
| --- | --- |
| open | 登录并打开新编辑页；需要登录时请用户在此 Edge 窗口本人扫码 |
| import | 新页无正文才导入，同会话只导一次；核对标题、作者、概要、全部段落、链接、待确认数量、END及正文宽度 |
| save | 检查当前内容与导入快照一致再保存；数字稿件地址仍不等于完成重开验收 |
| reopen | 已确认保存、同稿且无人工改动才刷新，重验后写 result.json 的 saved_and_reopened=true |
| snapshot | 保存截图与核对结果，不改正文 |

异常时写入 attention 并保留编辑页，说明具体问题。登录、容量或恢复提示由用户处理；部分导入失败时先核对现场，不重复覆盖。检测到人工修改时，先确认应保留的版本。

检查截图中的分类牌、正文宽度、换行和末尾，确认内容与版式完整。

流程只处理秀米草稿。保存并重开后，根据 result.json 确认结果，不执行发布或同步公众号。

编辑页会保持打开，供用户检查和调整；完成保存后可关闭窗口并结束该专用进程。
