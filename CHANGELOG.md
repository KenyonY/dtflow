# Changelog

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

## [0.8.6] - 2026-09-19

### Bug Fixes

- **view**: 作废列宽拖拽时退回按下前的宽度
- **view**: 弹窗压上来时作废主屏拖到一半的鼠标拖拽
- **view**: 弹窗面板压在两区分界上时, 点选项不再被分界拖拽抢走

### Features

- **view**: 默认左右布局, h/l 水平滚动步长改为 4 字符

### Miscellaneous

- Bump version to 0.8.6

## [0.8.5] - 2026-09-17

### Features

- **view**: 选列面板默认勾上行号列 #
- **view**: 选列面板默认全不选
- **view**: 列值筛选面板默认全不选

### Miscellaneous

- Bump version to 0.8.5

## [0.8.4] - 2026-09-17

### Features

- **view**: 筛选后保持横向位置, 光标跟住原来那条样本

### Miscellaneous

- Bump version to 0.8.4

## [0.8.3] - 2026-09-17

### Features

- **view**: 连击分级选中 2 词 · 3 整行 · 4 字段块 · 5 整屏
- **view**: 状态栏常驻"z 布局 · ? 帮助", 且排在最前

### Miscellaneous

- Bump version to 0.8.3

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

## [0.8.1] - 2026-09-14

### Features

- **view**: 为 --where/--search/--sort/--follow 添加短选项

### Miscellaneous

- Bump version to 0.8.1

## [0.8.0] - 2026-09-14

### Features

- **view**: 表头画出列分隔线, 悬停高亮提示可拖
- **view**: 表头分隔线拖拽调列宽

### Miscellaneous

- Bump version to 0.8.0

## [0.7.8] - 2026-09-08

### Bug Fixes

- **view**: 窄终端保留完整行号宽度

### Miscellaneous

- Bump version to 0.7.8

### Performance

- **view**: 快速精确计数并按需索引尾窗

## [0.7.7] - 2026-09-08

### Miscellaneous

- Bump version to 0.7.7

### Performance

- **view**: 按需建立 JSONL 索引以加快首屏

## [0.7.6] - 2026-09-04

### Features

- **view**: 支持日志追尾与负数尾窗

### Miscellaneous

- Bump version to 0.7.6

## [0.7.5] - 2026-09-01

### Bug Fixes

- **view**: 优化列宽和水平滚动跨度

### Miscellaneous

- Bump version to 0.7.5

## [0.7.4] - 2026-09-01

### Bug Fixes

- **view**: 增量发现非等字段列头

### Miscellaneous

- Bump version to 0.7.4

## [0.7.3] - 2026-08-24

### Bug Fixes

- **view**: 点击筛选卡片外关闭面板

### Documentation

- Add repository working agreements

### Features

- **cli**: Support Codex skill installation

### Miscellaneous

- Bump version to 0.7.3

## [0.7.2] - 2026-07-24

### Features

- **view**: 列值筛选去掉高基数上限 + 搜索词下应用=勾选∩匹配; 详情面板不截断

### Miscellaneous

- Bump version to 0.7.2

## [0.7.1] - 2026-07-23

### Features

- **cli**: Dt --version + 帮助头部带版本; 修 view 绕开格式门禁、门禁比实现窄

### Miscellaneous

- Bump version to 0.7.1

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

## [0.6.12] - 2026-07-21

### Bug Fixes

- **ci**: Test_persistent 整文件在 flaxkv2 缺失时跳过
- **ci**: 对齐 textual 版本 + flaxkv2 缺失跳过, 修 CI 测试
- **ci**: 补 pytest-asyncio 依赖, 修 CI 收集 asyncio marker 报错

### Miscellaneous

- Bump version to 0.6.12
- 忽略私有目录, 不纳入版本管理
- 更新 project.urls 为新仓库地址 KenyonY/dtflow

## [0.6.11] - 2026-07-21

### Bug Fixes

- **view**: 值筛选面板加宽, 修四按钮中"取消"被裁看不见

## [0.6.10] - 2026-07-21

### Features

- **view**: Excel 式列值勾选筛选 + 面板鼠标按钮

## [0.6.9] - 2026-07-21

### Features

- **view**: 冻结 # 索引列, 水平滚动时始终可见

## [0.6.8] - 2026-07-21

### Features

- **view**: 全量筛选子集 + 派生列/多列筛选 + 列快照

### Performance

- **view**: 消除 DataTable 定宽列逐格 measure, 首屏/翻页提速约 4-5x

## [0.6.7] - 2026-07-20

### Bug Fixes

- **view**: 新版 textual 下 DuplicateIds 崩溃与详情锚点失效 (#1)

### Miscellaneous

- Bump version to 0.6.7

## [0.6.6] - 2026-07-16

### Bug Fixes

- **view**: Tmux/screen 下 OSC52 剪贴板穿透

## [0.6.5] - 2026-07-16

### Bug Fixes

- 用户数据含伪 Rich markup ([/quote] 等) 时渲染崩溃

### Features

- **view**: 跳行支持负数索引 (-1 为末行, 语义同 Python 负索引)

### Miscellaneous

- Bump version to 0.6.5

## [0.6.4] - 2026-07-15

### Features

- **view**: 详情字段级导航与定位 (widget 化重构)

## [0.6.3] - 2026-07-15

### Features

- **view**: 详情面板切样本保持字段位置

## [0.6.2] - 2026-07-15

### Documentation

- 补充 dt view 交互式浏览器文档 (README + SKILL)

### Features

- **view**: 管道模式 dt view - + 位置参数 NUM
- **view**: 大文件偏移索引窗口化浏览 + 列宽修复

## [0.6.1] - 2026-07-10

### Features

- **view**: 交互精简与列宽/CSV 优化

## [0.6.0] - 2026-07-09

### Bug Fixes

- Stats 值分布支持低基数数值列

### Features

- 新增 dt view 交互式数据浏览器 + 预览渲染统一

## [0.5.14] - 2026-04-08

### Features

- CLI Agent 友好改造 (按 Agent CLI Guide 10 条原则)
- 支持 TSV 格式的输入和输出

### Miscellaneous

- Bump version to 0.5.14

## [0.5.13] - 2026-03-12

### Miscellaneous

- Bump version to 0.5.13

### Refactor

- FlaxList 从 DataTransformer 持久化后端降级为纯 I/O 格式

## [0.5.12] - 2026-02-24

### Documentation

- 更新 skill 文件和文档，同步 stats 新功能说明

### Features

- StreamingTransformer 新增 dedupe/flat_map/tail/sample/peek/shuffle/split 方法
- FlaxList 升级为 DataTransformer 的 Layer 2 持久化后端

### Miscellaneous

- Bump version to 0.5.12

## [0.5.11] - 2026-02-13

### Features

- FlaxKV 后端切换到 FlaxList，支持 .kv 后缀
- 添加 FlaxKV 数据库格式支持

### Miscellaneous

- 清理过时的 dtflow 核心文档

## [0.5.10] - 2026-02-04

### Miscellaneous

- 版本更新至 0.5.10

## [0.5.9] - 2026-02-04

### Bug Fixes

- 修复 eval 报告中 accuracy 类型导致的 KeyError

### Features

- 新增 slice/eval 命令，修正 skill 文档过时参数
- 新增 split/export 命令，clean 支持 token 过滤

### Miscellaneous

- 版本更新至 0.5.9

## [0.5.8] - 2026-02-01

### Documentation

- 更新 README 和 SKILL 文档，添加 --workers 参数说明

### Features

- Clean 命令新增 rename/promote/add-field/fill/reorder 参数
- Dt stats 命令支持字段过滤和 List 展开统计
- Token-stats 和 validate 命令添加多进程支持

### Miscellaneous

- 版本更新至 0.5.8，完善 skill 描述

## [0.5.7] - 2026-01-24

### Features

- 添加 install-skill 命令，支持安装 Claude Code skill

### Refactor

- 移除 mcp 模块

## [0.5.6] - 2026-01-22

### Features

- Sample 命令添加 --where 筛选参数

## [0.5.5] - 2026-01-20

### Miscellaneous

- Sample 命令默认采样方式改为 random，版本更新至 0.5.5

## [0.5.4] - 2026-01-19

### Miscellaneous

- Bump version to 0.5.4

### Performance

- Head/tail/sample 大文件预览跳过行数统计

## [0.5.3] - 2026-01-19

### Bug Fixes

- 修复代码逻辑错误并添加 CLI 测试覆盖

### Miscellaneous

- 更新 ruff 配置格式
- 添加 pre-commit 配置和发版脚本

### Styling

- 修复 ruff lint 问题

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

## [0.5.0] - 2026-01-08

## [0.4.3] - 2026-01-07

### Features

- Dt sample/head/tail 添加 --raw 参数支持完整 JSON 输出
- 添加 validate() 数据验证方法

## [0.4.2] - 2025-12-27

## [0.4.1] - 2025-12-27

## [0.4.0] - 2025-12-24

## [0.3.2] - 2025-12-23

### Bug Fixes

- Concat 命令支持非流式格式文件

## [0.3.1] - 2025-12-23

### Documentation

- 精简路线图，删除重复功能

## [0.3.0] - 2025-12-17

### Features

- 添加 messages token 统计和训练框架格式支持

## [0.2.0] - 2025-12-17

### Features

- 添加 tokenizers 和 converters 模块

## [0.1.6] - 2025-12-16

### Performance

- 性能优化 - 流式采样、并行处理

## [0.1.5] - 2025-12-16

### Features

- 添加 dt clean 数据清洗命令
- 添加数据去重和拼接功能

## [0.1.3] - 2025-12-15

## [0.1.2] - 2025-12-07

## [0.1.1] - 2025-12-07

### Features

- 添加SFT数据集分析模块和项目重构
