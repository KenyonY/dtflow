# 30 天增长执行包

目标：300 总 Stars，零预算，每天约 30 分钟；这是拉伸目标，不承诺结果。
对外定位：Inspect, clean, transform and ship LLM training data from one CLI;
`dt view` is the interactive entry point.

## 入口与材料

- [X 三条线程和完整工作流后续帖](x-draft.md)
- [V2EX 实战帖](v2ex-draft.md)
- [Textual 社区已发布更新](textual-update.md) / [公开帖子](https://github.com/Textualize/textual/discussions/6722#discussioncomment-18839713)
- [回复与反馈记录](feedback.md)
- [入口视频](../images/growth/entry.mp4) / [截图](../images/growth/entry.png)
- [工作流视频](../images/growth/workflow.mp4) / [截图](../images/growth/workflow.png)

两段视频由真实 TUI 操作、真实 CLI 返回生成，是离散操作帧的演示；停留时间供阅读，
不表示执行耗时或吞吐量。全部数据为仓库生成器产生的 synthetic 数据。
2026-10-10，维护者授权代为发布和注册项目账号。已使用维护者的 GitHub 账号，在
Textual 原有 Show and tell 主题发布一次实测更新，并同步工作台定位，避免重复投稿。
X 注册页在当前浏览器返回 HTTP 403；V2EX 的 Google 新账号需要邀请码，
现阶段没有可用登录或注册验证条件。账号条件具备后继续发布准备好的 X/V2EX 文案。
[实际发布记录与 72 小时复盘时间](feedback.md)。

## 复现

从仓库根目录运行，需要已安装 `uv`（`python -m pip install uv`）。
输出目录必须是新目录，避免覆盖上一轮证据。

```bash
pip install dtflow==0.10.6
python scripts/growth_demo.py --from dtflow==0.10.6 --output .growth/reproduce
```

`--from` 使用 `uv tool run --isolated`。每条命令的输入数据、完整 stdout/stderr 和退出码保存在
输出目录；`evidence.json` 是证据索引。安装前验收可把 `--from` 改成本地 wheel 的绝对路径。
命令链为 stats → filter → dedupe → validate → transform → validate → export，
包含 OpenAI → ShareGPT → OpenAI 转换往返。

实测：308 条输入；本例为普通文本 SFT 排除工具调用和末轮空回复后剩 259 条；
按 id 去重剩 252 条；转换前后均 252/252 有效；导出 252 条。所有步骤退出码 0。
工具调用仍可在浏览器查看和格式间转换；本例的 LLaMA-Factory 验证覆盖标准文本对话，
不代表验证了工具训练、多模态训练或实际 GPU 训练。

生成媒体需要本地 dtflow 源码依赖、Playwright/Chromium、Pillow 和 ffmpeg：

```bash
python -m pip install playwright pillow
python -m playwright install chromium
python scripts/growth_media.py --demo .growth/reproduce
```

入口视频直接打开同一份 `chat.jsonl`，窗口只载入 20 条，搜索 `refund` 后展示全文件
67/308 命中，叠加筛选后用 `w` 导出。可复制入口：
`dt view .growth/reproduce/chat.jsonl --cap 20`，随后 `/` 搜索、`f` 筛选、`w` 导出。
工作流视频保留命令与退出码；长报告在画面中截取前 22 行，完整报告见证据文件。

适用边界：VisiData 用于表格 join/pivot/列图；tabiew 用于 SQL；jless 用于单个 JSON 文档；
dtflow 用于训练样本的浏览、清洗、转换和导出。不宣称全面优于这些工具。

## 每日数据

```bash
gh auth status
python scripts/growth_snapshot.py
```

脚本保存 Stars、forks、open issues、GitHub views/clones 的每日明细和 unique、referrer、
PyPI recent downloads 到 `.growth/snapshots/`。`gh` 账号需要有读取仓库 traffic 的权限。
某个接口失败仍保存其它成功数据，记录 `errors`，退出码 1；缺失值不会当作零。
PyPI 下载统计有服务缓存，下载次数也不是独立用户数。

维护者本机已配置每天 09:00（系统时区）采集，截止 2026-11-07 UTC；
电脑关机时不会补采。日志在 `.growth/snapshot.log`。这是本机 cron 配置，clone 不会安装任务；
截止后脚本直接退出，不再请求接口。仍应每天查看错误、记录帖子问题并计算 Star 增量。

GitHub traffic 只保留最近 14 天。每日快照中的 14 天累计值相互重叠，**不要相加**；
按返回的 UTC `timestamp` 对齐每日行，以后一次快照更新同日数据。每天的 unique 也不能
相加当作整月独立访客。Star 增量取连续两次快照总数差；第一份没有增量。
[GitHub Traffic API](https://docs.github.com/en/rest/metrics/traffic)。

2026-10-09 首份快照：6 Stars；14 天 188 views / 20 uniques，514 clones / 205 uniques；
PyPI last_day 21 / last_week 213 / last_month 1923。原始快照保存在本地，不把访问量包装成用户数。

## 30 天节奏与判断

| 时间 | 动作 | 检查点 |
|---|---|---|
| 第 1–3 天 | 修复承接链，隔离安装、测试、QA、发布 | 导出映射与机器输出能真实使用 |
| 第 4–7 天 | 核对两段演示、截图和一条命令入口 | 第 7 天 25 Stars |
| 第 8–14 天 | 账号条件具备后发 X + V2EX；每天回复技术问题、记录链接、修正文档 | 第 14 天 60 Stars；首帖发布后 72 小时判断 |
| 第 15–21 天 | 按反馈修激活路径；用一个真实问题写第二个案例 | 第 21 天 150 Stars |
| 第 22–30 天 | 发布解决真实反馈的小版本；仅在访问不足时考虑新渠道 | 第 30 天 300 Stars |

首轮帖后 72 小时：访问不足先改标题/分发；有访问但 Star 低先核对首屏/安装；
Star 增长但无 clone/下载先补完整工作流；出现使用反馈先修阻塞。
这些是诊断信号，单次访问、下载和 Star 不足以证明因果或长期采用。
在 [反馈表](feedback.md) 记录帖子 URL、发布时间、平台可见数据及用户具体问题。

第 4 周版本内容由实际问题决定，不能提前宣称尚未修复的问题已经解决。
HN 若后来选用，由维护者本人按社区规则撰写；不直接复制生成稿。
不购买 Stars、不刷互动、不批量重复投稿。
