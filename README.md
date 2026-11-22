# snowglass

把 Qwen3.5-9B 的真实权重画成三维「水晶内雕」结构的实验项目。当前阶段是自用观察／调试器，不是可直接交付的产品编辑器。

## 主文件是哪个

**当前唯一在用的主文件：**

```
prototype/editor_ux/20261122-055413-124110/index.html
```

访问入口 `http://127.0.0.1:8128/`。当前 8128 的服务目录已指向这个版本目录，所以打开就是编辑器；若改用项目根作为服务目录，项目根的 `index.html` 会跳到这里。

目录名是生成的批次时间戳，不是版本号。换主批次时需同步项目根 `index.html`、`scripts/serve_editor.py` 的 `BUNDLE` 和此处入口说明；当前没有新建编辑器版本。

启动命令（项目根执行）：

```powershell
uv run --offline --script scripts/serve_editor.py
```

计算服务同时监听 `127.0.0.1` 和 `::1` 的回环接口，兼容浏览器与 IDE 内嵌预览，不对局域网开放。以前的 `http.server --bind ::` 只能看静态页面，而且监听全网接口；有计算接口后不再使用它。请求需要同源与本机任务令牌，令牌不写入工程文件。

必须走 http，不能双击 `index.html` 用 `file://` 打开：浏览器会以 403 拦掉同目录的拓扑与统计文件，页面会显示提示横幅而不是数据。

## 目录

| 路径 | 作用 |
|---|---|
| `prototype/editor_ux/20261122-055413-124110/` | **当前主版本**：index.html、assets（脚本与样式）、data（拓扑与统计缓存）、originals（原始副本）、verification（历次自动检查报告） |
| `prototype/data/` | 共享拓扑与数据 |
| `prototype/contrast_survey/` | 独立的对比度调研页，自带数据与文档，不属于编辑器 |
| `prototype/_archive/` | 已归档的历史页面，见下节 |
| `docs/` | 决策与规格：`decisions.md`、`editor_spec.md`、`qwen35_9b_facts.md` 等 |
| `scripts/` | 原统计核心保留；`preprocess.py` 按选项生成统计，`slice1.py` 管任务，`serve_editor.py` 提供本机服务 |
| `out/slices/` | 新切片任务、不可覆盖的张量结果和链路验证报告；旧缓存不移入、不覆盖 |
| `tests/` | 自动检查；编辑器用 `test_editor_ux.py` |
| `data/` | 本地原始权重，已进 `.gitignore`，不入库 |

## 归档内容

历史页面已按用途移入 `prototype/_archive/`，原文件名不变：

- `_archive/real_config/`：`real_config.html`、`real_config2.html`、`real_config4.html`、`real_config4.1.html`、`real_config4.2.html`、`real_config_4.2_configdata.md`。这些是布局与几何口径的早期试验页，**4.1 是界面配色的参照来源**，4.2 是默认布局基准。
- `_archive/editor_legacy/snowglass_editor.html`：编辑器第一版（只有选择、手动矩阵、全选变换，无组、无撤销）。已被当前版本取代，不再修改。
- `_archive/surveys/`：`type_survey.*`、`gray_samples.*`、`gray_support.js`、`colored_llm.html`、`grammar_candidates.html`、`model_preview_v0.html`。灰度与字体观感的独立调研页。

归档只移动位置，不删内容。要回看直接按上表路径打开（同样需要 http 服务，且这些页面依赖 `prototype/data`，用项目根作为服务目录更容易）。

## 检查报告

自动检查输出在 `prototype/editor_ux/20261122-055413-124110/verification/run-<时间戳>/checks.json`。此前散落在版本目录根部的 24 份报告已一并移入 `verification/`，文件名未改，`docs/editor_spec.md` 里按旧名引用的报告也都在这里。

运行方式：

```powershell
uv run --offline --script tests/test_editor_ux.py --folder prototype/editor_ux/20261122-055413-124110 --phase full
```

## 一级切片怎么用

1. 选择对象或组，在参数栏的“一级切片 · 统计生成”中调整三轴网格上限，数字框和滑块共用参数；未覆盖项继承上级。默认 `16×16×32` 沿用原实验，实际格数可能更少，每格合并多少以 `counts` 为准，不把固定网格冒充已拍板的固定压缩倍数 n。
2. “输出灰度 · 即时缓存映射”中的“统计来源”同时决定需要生成哪些统计：`full`只直接池化，`rowcol`才算行列强度，`feature/residual`才运行原SVD并成对生成。已有匹配通道即时映射；未生成的通道提示点击切片，不用full冒充，也不自动启动计算。
3. “一级切片 · 统计生成”中另有“权重数值约定”（GGUF原值／HF约定对齐）和“额外诊断统计”。新工程默认GGUF原值、诊断关闭；旧工程缺新增字段时保留HF旧约定，新增诊断开关默认关闭。HF对齐不是找回量化前精度。读取／解量化、全覆盖池化、计数与必要校验始终保留。
4. 右上切片范围选“作品范围”或“所选对象”，确认清单、谱／行列／诊断块数后才执行。各块继承后的来源、约定、网格及诊断选项形成固定快照，不能只看全局值而忽略局部覆盖。
5. 显示逐张量进度、心跳、复用与失败数量；可取消。失败或取消不删除已完成结果。再次建立同一配置任务会核对签名、当前原张量字节 SHA256 和结果 SHA256，只补缺项。
6. 完成后自动进入预览，画全部已载入统计。网格、约定、缺失来源或所需诊断改变时显示“待切片”；旧结果若继续显示会明确标示。不同约定／网格缓存分开保存，同一配置补一个通道不丢掉其他通道。灰度、窗口、已算通道、曲线、包络、排布和小块毫米边长不使源统计过期。包络变化会重新摆放中心点，小块自身仍保持毫米边长。
7. 工程保存切片任务编号，重新打开可恢复引用。新产物在 `out/slices/jobs/<任务编号>/` 和 `out/slices/artifacts/<签名>/<尝试编号>/`；已完成任务拒绝覆盖。

离线入口仍可用：`uv run --offline --script scripts/slice1.py --request <请求JSON路径>`，请求为 `{"blocks":[{"id":"L00.attn_norm","grid":[16,16,32],"source":"full","convention":"gguf","diagnostics":false}]}`。省略后三项也采用这组轻量默认值，选项进入计算签名；feature与residual共享成对谱结果的签名。每次新建任务，通过完成张量复用实现续跑，不覆写原实验目录。

合成核验：`uv run --offline --script tests/test_slice1.py`。界面／真实小样核验用 `tests/test_slice1_flow.py --real --url http://127.0.0.1:8128/`，只触及 `L00.attn_norm` 一个4096元素张量，报告在 `out/slices/verification/`。

## 现状边界

已接入：本机一级切片任务、按需统计、可选HF约定对齐／额外诊断、作品／所选范围、局部继承网格、进度／取消／完成项复用、结果引用恢复与准备／预览两态，以及原有几何和灰度编辑。完整拓扑的任务清单是369块／761张量；本轮仅核验一个真实小张量及合成数据，**不自动重跑完整模型**。此前全范围任务已取消，本轮保留其完成项，不覆盖或自动续跑。原有65组／124张量代表缓存继续保留。

未接入：二级加工导出、任意解析式、自适应、可调谱求解配方、字形轮廓与固定朝向、厂家读取契约。完整模型的运行时间、全部量化变体与全量渲染性能还未验证；不把接口可提交全范围宣称为全模型数据已经补齐。
