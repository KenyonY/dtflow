# Changelog

## [0.10.5] - 2026-10-09

### Bug Fixes

- **export**: Preserve OpenAI messages/role/content with matching LLaMA-Factory column and role tags.
- **cli**: Keep export stdout as one JSON summary; send success messages and paths to stderr and honor --quiet.
- **streaming**: Use Polars collect_batches for CSV/TSV, including Polars 2.0.
- **examples**: Emit valid ShareGPT tool results; keep the invalid observation in a separate fixture.

### Documentation

- Align the training-data workbench positioning, clarify dry-run limits, and provide reproducible launch demos.

## [0.10.4] - 2026-10-02

### Bug Fixes

- **view**: 双击列头改名在人手常见节奏下丢失

### Features

- **view**: 单击列头开值面板的延迟 0.15s → 0.2s, 提为常量 _HEADER_CLICK_DELAY

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.10.3...v0.10.4


## [0.10.3] - 2026-09-30

### Bug Fixes

- **deps**: Textual-image 放宽到 >=0.12.0, 恢复 Python 3.10/3.11 可安装

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.10.2...v0.10.3


## [0.10.2] - 2026-09-30

### Bug Fixes

- **view**: 缩略图 QA 修复 —— 同一 URL 并发下载临时文件唯一 (原先崩溃); 调分界/切布局/缩放时擦整屏释放 tmux 存图 (原先残影); 缩略图按比例定宽高 (原先压扁); 弹窗开着时不擦不停画 (原先大图被清空重发)
- **view**: C 的值筛选提示中文与判定一致 (只检测被截断)
- **view**: 看图弹窗 sixel 闪烁 —— 图读好再建弹窗、翻页整屏替换; sixel 同尺寸只发一次, 之后重画只移光标不清空 (tmux 见空格会删图重画); 翻页前清屏让 tmux 释放旧图 (否则每次重画连旧图一起重发); 连按翻页按次数累加; 文档补 tmux 下 sixel 的条件
- **clean**: Key:value 解析报错写明是哪一项 —— CLI 为 --fill/--add-field/--rename, pipeline 为 YAML 键名 fill/add_field/rename
- **clean**: --rename/--add-field/--fill 的 key:value 解析收成 ops.parse_pairs, CLI 与 pipeline 共用; 同一 key 出现两次一律报错 (pipeline 此前静默取后者)
- **view**: 改名框文字起点对齐原列头文字 (数值列右对齐: 变长先向左长), 右缘止于列分隔线; 被截断/藏在冻结列后的列先整列滚入视野再开框
- **view**: 列头改名框与列头文字对齐 (同 padding/加粗/等宽, 边打边长到表格右缘); 矮终端慢双击也能改名; 连续改名 (b→c 再 a→b) 不再崩溃; 退出询问的 写回 改称 保存 (s)
- **view**: 列头重命名 —— 输入框直接盖在列头格上; 双击慢于 0.15s 时值面板不再抢在前面 (面板收到落在列头格的连击即转改名, 大文件时取消进行中的值扫描)
- **view**: QA 修复 —— 图多于 <image> 时照 ms-swift 补到首条非 system 消息 (图不再看不到, 警告分红/黄), file:// 路径, images=null 回退 image, sharegpt 多模态 value; 只在首窗口有图时探测终端且探测失败不影响启动; 解码失败文案; 删去点不到的框外关闭
- **io**: JSONL 的 head/tail/sample 改用 orjson 逐行解析, 不再经 Polars ndjson 改写记录

### Documentation

- **view**: 看图 (VLM) —— view.md 新增 Images 一节与 i 键, imgs(x) 行函数, SKILL/README 同步
- **README**: 设计一节改写为七条第一性原理 (样本为单位 / 一种语言 / 看与处理闭环 / Unix 契约 / 能流式就流式 / 不给静默错误答案 / 函数优于类)
- README/SKILL 补上行函数、describe、group pct/--top、anti-join、目录/glob 输入、concat 转格式、终端表格预览; SKILL 加其他命令一览表

### Features

- **view**: 详情内缩略图 —— 每条带图消息下方 10 行缩略图条, 点击开大图; 仅 kitty/sixel 终端显示
- **view**: 改名后 f/s/S/F/| 一律按新名写 —— 条件在入口译回磁盘原名存储 (expr.rename_fields 按 AST 位置改写 x.a/x['a']/x.get('a')/'a' in x/get(x,'a…'), 保留原写法), 显示再译回新名; 管道喂改过名的行; P 末段接 dt clean --rename, C 的 --pipe 前置改名段; 管道态不能改名
- **view**: 图片弹窗 —— i 键/点 imgs 单元格/点详情 🖼 行打开, ←/→ 翻图, 线程读图不卡界面; 对话格式启动时探测终端图形协议; --image-root 指定相对路径基准; 依赖 textual-image

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.10.1...v0.10.2


## [0.10.1] - 2026-09-30

### Bug Fixes

- **view**: QA 修复 —— 管道用 bash -o pipefail 且 stderr 出现 dt 错误即判失败; 取消时杀整个进程组; 非对象 JSON 行成占位行; 错误对象不在 stderr 末尾也能取到
- **view**: QA 修复 —— 空视图清副标题, 算出来的文本不画搜索命中, roles 着色缓存
- **view**: 列头重命名写回的 QA 修复 —— 只读目录不崩, 沿用旧血缘链, 与窗口外字段重名时中止, 保留权限/软链, 值面板标题显示新名, --help 补说明

### Documentation

- **view**: | 管道与 --pipe 写进 view.md/cli.md/README/SKILL
- **view**: 详情徽章/代码块底色/边框标题/分批渲染写进 view 文档与 SKILL
- **view**: 重新生成展示截图与 GIF (新表格/详情样式与边框标题)

### Features

- **view**: 多模态图片引用 —— 抽取 image_url/image 片段与样本级 images, 详情显示 🖼 行, <image> 数量不匹配标红, imgs 列与行函数, image.py 读图 (路径/URL/data URI)
- **view**: | 在 view 内跑 shell 管道, 结果替换浏览数据; r 回到原文件; C/P/血缘带上管道; --pipe 启动选项
- **view**: Pipe.py —— 子进程跑 shell 管道 (stdin/stdout NDJSON, 取消即 kill, stderr 尾巴取 dt 的 JSON message)
- **view**: 双击列头重命名, 界面即时生效, 退出时询问写回/丢弃

### Performance

- **view**: 单元格样式推迟到渲染可见行时再套, 派生列按当前格式判断
- **view**: 详情面板合并渲染 + 长样本分批挂载, 分隔线改边框

### Styling

- **view**: 身份信息挂到两区边框标题, 状态栏只留会变的状态
- **view**: 详情角色标题改反色徽章并附字数, 代码/JSON 块铺底
- **view**: 表格数值列右对齐, 截断加省略号, roles 按角色着色, 滚动条降噪

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.10.0...v0.10.1


## [0.10.0] - 2026-09-30

### Bug Fixes

- QA 验收修复 —— 单文件目录/glob 不再被当成 flaxkv; describe 表格转置; help 文案同步; 若干校验
- **i18n**: 语言解析与语言无关的机器输出
- **presets**: 并行工具调用互转不丢不错配; HF 风格 DPO 的消息列表按对话处理; 文档链式示例改用 transform

### CI

- **release**: Changelog 与 release 正文末尾附 Full Changelog 对比链接
- **release**: Release 正文改由 git-cliff 生成, 不再依赖只统计 PR 的自动说明

### Documentation

- 修正 README 链式示例与 SKILL 预设说明; 示例数据加入并行工具调用样本
- README 缩到首屏与导航, 参考内容拆到 docs/ (cli/view/expressions/pipeline/python-api)
- README 改为英文主文档, 中文移至 README_zh.md; 定位改为 dt view 主打
- **README**: Dt view 增加与 VisiData/tabiew/jless/fx/csvlens 的对比表

### Features

- **input**: FILE 接受目录与引号 glob (逐文件校验后首尾相接); concat 放宽为单文件即格式转换
- **join**: --anti 反连接; --strict; 左表键求值失败计数汇总而非静默
- **describe,group,stats**: 看分布 —— 新命令 dt describe; group 输出 pct 与 --top; stats 修两个 bug; token-stats 计 tool 角色
- **pipe**: --format table 真正渲染, 终端默认预览改表格; 统一 sample/split 落盘与 validate 退出码
- **i18n**: 界面支持中英双语, 默认英文, dt lang 切换
- **presets**: 预设按输入形态自动转换; schema 预设接受工具调用; 新增 examples/ 示例数据

### Miscellaneous

- 忽略本地传播文案草稿目录 .launch-drafts/
- **changelog**: 重生成完整的已发布版本记录 (上一提交误生成为空)
- **changelog**: 模板跳过无提交的版本段, 去掉误生成的空 Unreleased
- **changelog**: 只保留已发布版本, 去掉误生成的 Unreleased 段
- **changelog**: 去掉误生成的 Unreleased 段; ci 提交归入 CI 分组
- **scripts**: Release.sh 归一 changelog 末尾空行, 避免 end-of-file-fixer 打断发版

### Refactor

- **expr**: 行函数 turns/roles/first_user/chars/calls/fulltext/search 进表达式命名空间; view 派生列共用实现

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.9.0...v0.10.0


## [0.9.0] - 2026-09-29

### Bug Fixes

- **output**: 终端模式的结构化错误也打印 context, 多行建议 (表达式+caret) 独占行
- **qa**: 复验收尾: caret 缩进对齐、TTY 预览不再报误导性总数、字段列表逐项拦截 x.、进度条只在 stderr 为终端时显示
- **qa**: 修复 QA 验收报出的契约/数据问题

### Documentation

- 表达式语法/管道化/数据原语同步 README、SKILL、docs、CLAUDE.md; 附迁移对照表; 版本 0.9.0

### Features

- **ops**: 数据原语 dt filter/select/map/explode/sort/shuffle/group/join + stats --schema
- **cli**: 数据命令统一管道化: FILE 支持 -, 无 -o 写 stdout, clean/dedupe 改 -i
- **io**: Jsonl/json 支持 .gz 透明读写
- **expr**: 统一 Python 表达式引擎 dtflow/expr.py
- **core**: DictWrapper 支持 list 元素属性访问与字段写穿; 新增 ListWrapper/unwrap

### Refactor

- **pipeline**: Step 类型 = CLI 命令名, 参数 = 选项名, 复用 dtflow.ops; split 作终态步骤
- **where**: Sample/view/pipeline 的筛选语法统一为 Python 表达式

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.8.7...v0.9.0


## [0.8.7] - 2026-09-29

### Bug Fixes

- **scripts**: Release.sh 换行改为 LF, 修复 bad interpreter
- **view**: Sharegpt function_call 为 dict 时按 JSON 序列化, 标题行叠加搜索高亮
- **view**: 派生列 tools 改名 calls, 坏工具调用一律标红
- **view**: 表格焦点下按 Enter 真正放大样本; 展示素材脚本补依赖声明与连字修正

### Documentation

- README 简介补 calls 列与工具调用渲染
- README 加入 dt view 视觉展示 (GIF + 截图), 附可复现的生成脚本

### Features

- **view**: 渲染 tool_calls / reasoning, 新增 tools 派生列

### Miscellaneous

- Bump version to 0.8.7

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.8.6...v0.8.7


## [0.8.6] - 2026-09-19

### Bug Fixes

- **view**: 作废列宽拖拽时退回按下前的宽度
- **view**: 弹窗压上来时作废主屏拖到一半的鼠标拖拽
- **view**: 弹窗面板压在两区分界上时, 点选项不再被分界拖拽抢走

### Features

- **view**: 默认左右布局, h/l 水平滚动步长改为 4 字符

### Miscellaneous

- Bump version to 0.8.6

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.8.5...v0.8.6


## [0.8.5] - 2026-09-17

### Features

- **view**: 选列面板默认勾上行号列 #
- **view**: 选列面板默认全不选
- **view**: 列值筛选面板默认全不选

### Miscellaneous

- Bump version to 0.8.5

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.8.4...v0.8.5


## [0.8.4] - 2026-09-17

### Features

- **view**: 筛选后保持横向位置, 光标跟住原来那条样本

### Miscellaneous

- Bump version to 0.8.4

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.8.3...v0.8.4


## [0.8.3] - 2026-09-17

### Features

- **view**: 连击分级选中 2 词 · 3 整行 · 4 字段块 · 5 整屏
- **view**: 状态栏常驻"z 布局 · ? 帮助", 且排在最前

### Miscellaneous

- Bump version to 0.8.3

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.8.2...v0.8.3


## [0.8.2] - 2026-09-16

### Bug Fixes

- **view**: 修好拖选的三处失真: 高亮涂没文字 / 空行退化 / 越拖越偏
- **view**: 输入框里的 Ctrl+c 仍归 Input 自己的复制
- **view**: 无选区时 Ctrl+c 给出回应, 不再静默
- **view**: 连击复制上移到 app 层并去抖
- **view**: 拖选复制只认真正的拖选手势, 双击/三击也确定复制
- **view**: 并行分片补回文件快照一致性校验

### Features

- **view**: 拖两区分界调大小; 选区改为 Ctrl+c 复制, 剪贴板走双通道
- **view**: 详情区支持鼠标拖选文本, 松手即复制到剪贴板

### Miscellaneous

- Bump version to 0.8.2

### Performance

- **view**: 全量扫描并行化, 并省掉两类重复扫描

### Testing

- **view**: 值筛选 Ctrl+c 用例别真写系统剪贴板

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.8.1...v0.8.2


## [0.8.1] - 2026-09-14

### Features

- **view**: 为 --where/--search/--sort/--follow 添加短选项

### Miscellaneous

- Bump version to 0.8.1

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.8.0...v0.8.1


## [0.8.0] - 2026-09-14

### Features

- **view**: 表头画出列分隔线, 悬停高亮提示可拖
- **view**: 表头分隔线拖拽调列宽

### Miscellaneous

- Bump version to 0.8.0

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.7.8...v0.8.0


## [0.7.8] - 2026-09-08

### Bug Fixes

- **view**: 窄终端保留完整行号宽度

### Miscellaneous

- Bump version to 0.7.8

### Performance

- **view**: 快速精确计数并按需索引尾窗

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.7.7...v0.7.8


## [0.7.7] - 2026-09-08

### Miscellaneous

- Bump version to 0.7.7

### Performance

- **view**: 按需建立 JSONL 索引以加快首屏

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.7.6...v0.7.7


## [0.7.6] - 2026-09-04

### Features

- **view**: 支持日志追尾与负数尾窗

### Miscellaneous

- Bump version to 0.7.6

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.7.5...v0.7.6


## [0.7.5] - 2026-09-01

### Bug Fixes

- **view**: 优化列宽和水平滚动跨度

### Miscellaneous

- Bump version to 0.7.5

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.7.4...v0.7.5


## [0.7.4] - 2026-09-01

### Bug Fixes

- **view**: 增量发现非等字段列头

### Miscellaneous

- Bump version to 0.7.4

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.7.3...v0.7.4


## [0.7.3] - 2026-08-24

### Bug Fixes

- **view**: 点击筛选卡片外关闭面板

### Documentation

- Add repository working agreements

### Features

- **cli**: Support Codex skill installation

### Miscellaneous

- Bump version to 0.7.3

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.7.2...v0.7.3


## [0.7.2] - 2026-07-24

### Features

- **view**: 列值筛选去掉高基数上限 + 搜索词下应用=勾选∩匹配; 详情面板不截断

### Miscellaneous

- Bump version to 0.7.2

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.7.1...v0.7.2


## [0.7.1] - 2026-07-23

### Features

- **cli**: Dt --version + 帮助头部带版本; 修 view 绕开格式门禁、门禁比实现窄

### Miscellaneous

- Bump version to 0.7.1

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.7.0...v0.7.1


## [0.7.0] - 2026-07-22

### Bug Fixes

- 补齐 Excel/Arrow 后端依赖声明, 修正 xlsx/json 行数统计

### Documentation

- LICENSE 年份更新为 2025-2026
- README 添加 PyPI/License/Downloads 徽章, 补充 MIT LICENSE 文件

### Features

- **view**: 子集导出/可复现命令/全量排序/命中高亮 + 坏行不再拦门
- **view**: 按内容包含筛选 — ~= 运算符 + 值面板搜索框

### Miscellaneous

- Bump version to 0.7.0

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.6.12...v0.7.0


## [0.6.12] - 2026-07-21

### Bug Fixes

- **ci**: Test_persistent 整文件在 flaxkv2 缺失时跳过
- **ci**: 对齐 textual 版本 + flaxkv2 缺失跳过, 修 CI 测试
- **ci**: 补 pytest-asyncio 依赖, 修 CI 收集 asyncio marker 报错

### Miscellaneous

- Bump version to 0.6.12
- 忽略私有目录, 不纳入版本管理
- 更新 project.urls 为新仓库地址 KenyonY/dtflow

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.6.11...v0.6.12


## [0.6.11] - 2026-07-21

### Bug Fixes

- **view**: 值筛选面板加宽, 修四按钮中"取消"被裁看不见

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.6.10...v0.6.11


## [0.6.10] - 2026-07-21

### Features

- **view**: Excel 式列值勾选筛选 + 面板鼠标按钮

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.6.9...v0.6.10


## [0.6.9] - 2026-07-21

### Features

- **view**: 冻结 # 索引列, 水平滚动时始终可见

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.6.8...v0.6.9


## [0.6.8] - 2026-07-21

### Features

- **view**: 全量筛选子集 + 派生列/多列筛选 + 列快照

### Performance

- **view**: 消除 DataTable 定宽列逐格 measure, 首屏/翻页提速约 4-5x

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.6.7...v0.6.8


## [0.6.7] - 2026-07-20

### Bug Fixes

- **view**: 新版 textual 下 DuplicateIds 崩溃与详情锚点失效 (#1)

### Miscellaneous

- Bump version to 0.6.7

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.6.6...v0.6.7


## [0.6.6] - 2026-07-16

### Bug Fixes

- **view**: Tmux/screen 下 OSC52 剪贴板穿透

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.6.5...v0.6.6


## [0.6.5] - 2026-07-16

### Bug Fixes

- 用户数据含伪 Rich markup ([/quote] 等) 时渲染崩溃

### Features

- **view**: 跳行支持负数索引 (-1 为末行, 语义同 Python 负索引)

### Miscellaneous

- Bump version to 0.6.5

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.6.4...v0.6.5


## [0.6.4] - 2026-07-15

### Features

- **view**: 详情字段级导航与定位 (widget 化重构)

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.6.3...v0.6.4


## [0.6.3] - 2026-07-15

### Features

- **view**: 详情面板切样本保持字段位置

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.6.2...v0.6.3


## [0.6.2] - 2026-07-15

### Documentation

- 补充 dt view 交互式浏览器文档 (README + SKILL)

### Features

- **view**: 管道模式 dt view - + 位置参数 NUM
- **view**: 大文件偏移索引窗口化浏览 + 列宽修复

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.6.1...v0.6.2


## [0.6.1] - 2026-07-10

### Features

- **view**: 交互精简与列宽/CSV 优化

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.6.0...v0.6.1


## [0.6.0] - 2026-07-09

### Bug Fixes

- Stats 值分布支持低基数数值列

### Features

- 新增 dt view 交互式数据浏览器 + 预览渲染统一

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.5.14...v0.6.0


## [0.5.14] - 2026-04-08

### Features

- CLI Agent 友好改造 (按 Agent CLI Guide 10 条原则)
- 支持 TSV 格式的输入和输出

### Miscellaneous

- Bump version to 0.5.14

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.5.13...v0.5.14


## [0.5.13] - 2026-03-12

### Miscellaneous

- Bump version to 0.5.13

### Refactor

- FlaxList 从 DataTransformer 持久化后端降级为纯 I/O 格式

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.5.12...v0.5.13


## [0.5.12] - 2026-02-24

### Documentation

- 更新 skill 文件和文档，同步 stats 新功能说明

### Features

- StreamingTransformer 新增 dedupe/flat_map/tail/sample/peek/shuffle/split 方法
- FlaxList 升级为 DataTransformer 的 Layer 2 持久化后端

### Miscellaneous

- Bump version to 0.5.12

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.5.11...v0.5.12


## [0.5.11] - 2026-02-13

### Features

- FlaxKV 后端切换到 FlaxList，支持 .kv 后缀
- 添加 FlaxKV 数据库格式支持

### Miscellaneous

- 清理过时的 dtflow 核心文档

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.5.10...v0.5.11


## [0.5.10] - 2026-02-04

### Miscellaneous

- 版本更新至 0.5.10

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.5.9...v0.5.10


## [0.5.9] - 2026-02-04

### Bug Fixes

- 修复 eval 报告中 accuracy 类型导致的 KeyError

### Features

- 新增 slice/eval 命令，修正 skill 文档过时参数
- 新增 split/export 命令，clean 支持 token 过滤

### Miscellaneous

- 版本更新至 0.5.9

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.5.8...v0.5.9


## [0.5.8] - 2026-02-01

### Documentation

- 更新 README 和 SKILL 文档，添加 --workers 参数说明

### Features

- Clean 命令新增 rename/promote/add-field/fill/reorder 参数
- Dt stats 命令支持字段过滤和 List 展开统计
- Token-stats 和 validate 命令添加多进程支持

### Miscellaneous

- 版本更新至 0.5.8，完善 skill 描述

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.5.7...v0.5.8


## [0.5.7] - 2026-01-24

### Features

- 添加 install-skill 命令，支持安装 Claude Code skill

### Refactor

- 移除 mcp 模块

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.5.6...v0.5.7


## [0.5.6] - 2026-01-22

### Features

- Sample 命令添加 --where 筛选参数

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.5.5...v0.5.6


## [0.5.5] - 2026-01-20

### Miscellaneous

- Sample 命令默认采样方式改为 random，版本更新至 0.5.5

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.5.4...v0.5.5


## [0.5.4] - 2026-01-19

### Miscellaneous

- Bump version to 0.5.4

### Performance

- Head/tail/sample 大文件预览跳过行数统计

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.5.3...v0.5.4


## [0.5.3] - 2026-01-19

### Bug Fixes

- 修复代码逻辑错误并添加 CLI 测试覆盖

### Miscellaneous

- 更新 ruff 配置格式
- 添加 pre-commit 配置和发版脚本

### Styling

- 修复 ruff lint 问题

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.5.2...v0.5.3


## [0.5.2] - 2026-01-12

### Documentation

- 添加测试运行说明

### Features

- 优化 sample 命令文本预览显示
- 补充 tail/token-stats/validate 性能测试
- 补充 random 采样性能测试用例
- 添加 ShareGPT 真实数据性能测试脚本
- 添加核心 CLI 方法性能测试

### Miscellaneous

- Bump version to 0.5.2

### V0.5.1

- 功能增强和测试完善

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.5.0...v0.5.2


## [0.5.0] - 2026-01-08

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.4.3...v0.5.0


## [0.4.3] - 2026-01-07

### Features

- Dt sample/head/tail 添加 --raw 参数支持完整 JSON 输出
- 添加 validate() 数据验证方法

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.4.2...v0.4.3


## [0.4.2] - 2025-12-27

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.4.1...v0.4.2


## [0.4.1] - 2025-12-27

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.4.0...v0.4.1


## [0.4.0] - 2025-12-24

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.3.2...v0.4.0


## [0.3.2] - 2025-12-23

### Bug Fixes

- Concat 命令支持非流式格式文件

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.3.1...v0.3.2


## [0.3.1] - 2025-12-23

### Documentation

- 精简路线图，删除重复功能

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.3.0...v0.3.1


## [0.3.0] - 2025-12-17

### Features

- 添加 messages token 统计和训练框架格式支持

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.2.0...v0.3.0


## [0.2.0] - 2025-12-17

### Features

- 添加 tokenizers 和 converters 模块

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.1.6...v0.2.0


## [0.1.6] - 2025-12-16

### Performance

- 性能优化 - 流式采样、并行处理

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.1.5...v0.1.6


## [0.1.5] - 2025-12-16

### Features

- 添加 dt clean 数据清洗命令
- 添加数据去重和拼接功能

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.1.3...v0.1.5


## [0.1.3] - 2025-12-15

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.1.2...v0.1.3


## [0.1.2] - 2025-12-07

**Full Changelog**: https://github.com/KenyonY/dtflow/compare/v0.1.1...v0.1.2


## [0.1.1] - 2025-12-07

### Features

- 添加SFT数据集分析模块和项目重构
