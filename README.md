# Campus News Skill · 校园资讯采编

将校园公众号的重复采编工作整理成可复用的 Agent Skill：**指定信源与日期 → 采集原文 → 筛选资讯 → 整理文案 → 参考模板排版 → 交接秀米草稿**。

[![Tests](https://github.com/zhouchen20050310-boop/campus-news-skill/actions/workflows/tests.yml/badge.svg)](https://github.com/zhouchen20050310-boop/campus-news-skill/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**本人第一次编写Skill** 本地测试了资讯采集、筛选、文案撰写、排版和秀米导入功能，无误，如其它设备使用过程发现bug，欢迎反馈

## 为什么做这个项目

项目来自校园公众号运营：每周都要查找文章、下载资料、筛出对学生有帮助的信息，再写稿、套模板和导入秀米。

作者是交互设计专业学生、校园公众号运营团队负责人，希望把这套流程变成编辑能够理解、检查和复用的工具。

这里的 Skill 包含工作规则、脚本和排版模板。运行它的 Agent 负责阅读、判断和写稿，外部工具负责取得公众号内容、操作秀米；编辑（也就是你！）保留最终选题、事实复核和发布的决定权。

## 可以做什么

| 环节 | 行为与产物 |
| --- | --- |
| 范围检查 | 读取公众号 TXT 开关，与下载工具收藏列表核对；缺失时提醒用户先收藏 |
| 日期控制 | 文章采集日期与资讯有效日期分开指定；有效日期可明确选择“不限” |
| 采集归档 | 分页读取、去重、下载，保留 PDF、HTML、MD、图片及状态记录； |
| 逐篇筛选 | 先读 MD，需要时才补读图片/PDF，根据你的资讯类型要求筛选资讯，并给出每篇去留理由，如读到汇总资讯，则拆分独立事项 |
| 文案与标题 | 整理时间、对象、亮点、参与或阅读方式、限制、原文链接、标题与概要 |
| 排版 | 生成普通 HTML与秀米兼容 HTML、文案 MD、编辑核对清单 |
| 秀米交接 | 本地转换后导入（需要用户先登录），并尝试分步核对 |

```mermaid
flowchart LR
  A[用户指定信源和日期] --> B[收藏核对]
  B --> C[Media Tools 采集]
  C --> D[Agent 阅读与筛选]
  D --> E[编辑选择与复核]
  E --> F[文案和 HTML 排版]
  F --> G[秀米草稿交接]
```

## 三分钟了解用法

### 1. 准备运行条件

- 支持 Skill 的 Agent，具备本地文件读写、Python 执行及所需浏览器工具。
- Python **3.11+**。主采集、筛选结果导出和排版脚本使用标准库。
- 本机启动并登录 [WeChat MP Tools](https://github.com/x554960766/wechat-mp-tools)，收藏目标公众号。适配器基于本项目已测试的 v2.3.1 接口，默认 `http://127.0.0.1:5200`。
- 需要导入秀米时，另行准备 [all-to-xiumi](https://github.com/hanselhan23/all-to-xiumi)、Selenium、Edge及相应驱动。

**仅下载本仓库不会安装以上桌面软件，也不会取得你的公众号或秀米登录状态。** 云端 Agent 的 localhost 不指向你的电脑；WorkBuddy 等其他宿主的实际兼容性尚未验收。

### 2. 安装 Skill

需要安装的文件夹是 [`skills/campus-news-collect`](skills/campus-news-collect)，不是整个仓库。

将该文件夹放入宿主 Agent 支持的技能目录。

如果你的 Codex 带有 skill-installer，也可以向它提供本仓库中这个 Skill 文件夹的地址：

```text
请使用 skill-installer 安装：
https://github.com/zhouchen20050310-boop/campus-news-skill/tree/main/skills/campus-news-collect
```

### 3. 配置本期信源

创建 UTF-8 TXT，每行一个公众号名称和开关：

例如

```text
鲤工包打听，（开）
其他公众号，（关）
```

“关”只表示本次不采集，不取消收藏。开启的公众号如果没有在下载工具中收藏，Agent 会提醒你先收藏，完成后重新检查，不会悄悄跳过。

### 4. 告诉 Agent 本期输入

```text
使用 $campus-news-collect，帮我做一期校园资讯。
公众号范围 TXT：我提供的本地文件路径
文章采集日期：我指定的开始日期 至 结束日期
资讯有效日期：我指定的开始日期 至 结束日期，或明确填写“不限”
请先生成候选清单、推文文案和排版草稿。
```

也支持“使用校园资讯采编”等自然语言任务匹配，具体调用界面取决于宿主 Agent。

**两种日期各管一件事：**采集日期决定文章是否属于本次材料；有效日期决定其中的信息是否适用于目标时段。没有固定日期，也不会自动沿用上期。“不限”是用户明确选择的模式，不代表缺少输入时默认不限。

## 不登录也能试排版

仓库提供完全虚构的离线示例，不访问微信、不下载文章、不打开秀米：

```bash
python examples/run_offline_demo.py
```

结果写入 `.demo-output/`，可查看文案、候选清单及两版 HTML。示例日期和链接只是演示数据，不是正式采集默认值。详见 [离线示例说明](examples/README.md)。

## 常用入口

- [首次使用与工具连接](docs/quickstart.md)
- [协作方式、结构和验证状态](docs/architecture.md)
- [给 Agent 的完整规则](skills/campus-news-collect/SKILL.md)
- [公众号 TXT 格式](skills/campus-news-collect/references/source-scope.md)
- [筛选及稿件数据格式](skills/campus-news-collect/references/editorial-data.md)
- [秀米操作与验收标准](skills/campus-news-collect/references/xiumi.md)

## 仓库结构

```text
campus-news-skill/
├── README.md                       给使用者看的项目首页
├── LICENSE                         MIT 许可证
├── docs/                           人类阅读的使用和设计说明
├── examples/                       虚构的离线演示
├── scripts/package_skill.py        打包可安装 Skill
├── .github/workflows/tests.yml     自动测试
└── skills/campus-news-collect/
    ├── SKILL.md                    Agent 执行入口
    ├── agents/openai.yaml          调用方式与显示信息
    ├── scripts/                    实际工具接入与排版脚本
    ├── references/                 按需加载的规则和数据结构
    ├── assets/                     排版模板及范围示例
    └── tests/                      离线功能测试
```
## 开发与贡献

在仓库根目录运行：

```bash
python -m unittest discover -s skills/campus-news-collect/tests -v
python examples/run_offline_demo.py
python scripts/package_skill.py
```

打包结果为 `dist/campus-news-collect.zip`，含 Skill 资源和许可证，不包含运行缓存与桌面工具。CI 检查离线测试、示例与打包，不连接真实账号。

欢迎通过 Issue 提供工具版本、复现步骤与预期行为。请使用虚构样本，移除 Cookie、令牌、浏览器登录资料和不宜公开的文章内容。

## 参考与许可

项目组织参考 [Anthropic Skills](https://github.com/anthropics/skills) 和 [OpenAI Plugins](https://github.com/openai/plugins) 的示例结构；工具集成参考其各自项目的接口与实际测试结果。只借鉴组织方式，不将它们的功能或稳定性作为本项目承诺。

- 主采集工具：[wechat-mp-tools](https://github.com/x554960766/wechat-mp-tools)
- 秀米适配工具：[all-to-xiumi](https://github.com/hanselhan23/all-to-xiumi)

本仓库的代码与文档使用 [MIT License](LICENSE)。外部工具按各自许可证和使用条件提供，未随本仓库分发；公众号文章、图片及其他第三方素材不因本仓库采用 MIT 而被重新授权。

## 尾声 

感谢你的阅读！欢迎关注鲤工包打听公众号！
