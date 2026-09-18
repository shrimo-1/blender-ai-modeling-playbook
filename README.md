# Blender AI 建模 Playbook（实证版）

把「让 AI 通过 Blender MCP 建模」从**能跑通**推到**可验收**的一套中文方法论：判定纪律、证据链、单位坐标契约、阶段产物防覆写、以及配套的可运行检查脚本。

全部内容提炼自真实交付过的项目：把 2D 立绘转成 3D 打印浮雕与棋子模型（光固化 / SLA 交付，含 STL 读回校验与切片建议）。踩坑清单里没有演示用的假数据，每条都对应一次实际发生过的事故或其修复；`examples/` 下的口径示例是合成数据，只用于验证工具行为。

> English: An evidence-first playbook for AI-driven Blender modeling via MCP — verdict discipline (`OBSERVED` / `INFERRED` / `UNKNOWN`), coordinate round-trip pre-checks, stage-file guarding, and silhouette/relief verification tooling. Documents are in Chinese. Tools are standard-library only, no third-party dependencies.

---

## 1. 这个仓库解决什么问题

用 AI + Blender 建模，失败几乎从不发生在「写不出 `bpy` 代码」，而发生在下面这五类地方：

| 失败类型 | 典型表现 | 本仓库对应 |
|---|---|---|
| 判定失真 | 把推断写成事实；结果不对就改写验收条件，然后宣布通过 | `docs/01`、`docs/04` 第一节 |
| 自我验证 | 实现者写自己的验收脚本，脚本与实现共享同一个错误假设 | `docs/03` 角色分离 |
| 口径漂移 | 单位 / 像素换算有两套，混用后整体缩放 0.6 倍，此前所有对照结论作废 | `docs/05`、`tools/unit_roundtrip_check.py` |
| 局部代替整体 | 用 ray probe / bbox 证明「形状正确」，但轮廓、比例、面积从没被真正看过 | `docs/01`「局部关系验证 + 整体原画对照」 |
| 静默破坏 | 上一阶段的 `.blend` 被脚本覆盖；修 A 时把 B 的拓扑重建掉了 | `docs/04`、`tools/stage_guard.py` |

## 2. 四条主线

1. **判定纪律**：任何信息必须归入 `OBSERVED` / `INFERRED` / `UNKNOWN`；验收只有 `PASS` / `FAIL` / `UNKNOWN`，`FAIL` 不得被弱化成「还需确认」。见 `docs/01`。
2. **证据链**：`工具执行成功 ≠ 建模成功`。MCP 只回一句 `Code executed successfully`，造型正确性必须靠**渲染截图 + 原画对照**；且局部几何证据（射线命中、包围盒、深度顺序）**不能单独**宣告视觉 `PASS`。
3. **契约先于几何**：单位口径、像素↔毫米常数、坐标轴与往返映射，必须在第一件几何被创建**之前**写进文件并跑通往返预检。
4. **产物可重现**：每个阶段脚本显式声明 `STAGE_NAME`，目标已存在则停止；每轮修改都留下报告 JSON 与证据图，交付说明带 `sha256` 与未解决 `UNKNOWN` 清单。

## 3. 目录结构

```
.
├── README.md
├── UPLOAD.md                              # 如何把本仓库推到 GitHub（cmd 语法）
├── LICENSE
├── docs/
│   ├── 01-visual-analysis-protocol.md     # 长期协议：判定纪律与视觉验收（逐字归档）
│   ├── 02-blender-mcp-agent-prompt.md     # 长期提示词：Blender MCP 建模执行规则（逐字归档）
│   ├── 03-workflow.md                     # 从需求冻结到交付的实际流程与文件机制
│   ├── 04-lessons-learned.md              # 踩坑清单：现象 → 根因 → 规则
│   └── 05-unit-and-coordinate-contract.md # 单位口径与坐标往返契约
├── templates/                             # 可直接复制到新项目的空白模板
│   ├── AGENTS.md
│   ├── REQUIREMENTS.md
│   ├── DECISIONS.md
│   └── UNIT_CONVENTION.md
├── examples/
│   ├── roundtrip.spec.json                # 自洽口径 + 7 个观测锚点 → PASS
│   └── roundtrip_bad.spec.json            # 几何口径被换成相机口径 → FAIL
└── tools/
    ├── unit_roundtrip_check.py            # 坐标往返预检（≥5 个独立观测锚点，误差 ≤0.5 源像素）
    ├── silhouette_diff.py                 # 剪影逐行左右边界差分（几何 vs 原画）
    ├── stage_guard.py                     # 阶段 .blend 防覆写守卫
    └── selftest.py                        # 三个工具的自测（28 项断言，纯标准库）

全部脚本只依赖 Python 标准库，可直接在任意 3.x 上运行；不需要 Blender 就能跑。

## 4. 快速上手

```bat
rem 1) 新建项目目录（cmd 写法；路径含空格要加双引号）
mkdir mymodel_20260101_120000
cd mymodel_20260101_120000

rem 2) 从模板起手，先把契约写死，再动几何
copy <repo>\templates\REQUIREMENTS.md       .
copy <repo>\templates\DECISIONS.md          .
copy <repo>\templates\UNIT_CONVENTION.md    .

rem 3) 坐标往返预检：先把示例跑通，再换成自己的锚点
python <repo>\tools\unit_roundtrip_check.py --spec <repo>\examples\roundtrip.spec.json
python <repo>\tools\unit_roundtrip_check.py --spec <repo>\examples\roundtrip_bad.spec.json

rem 4) 阶段脚本里加守卫，避免覆盖上一阶段产物
python <repo>\tools\stage_guard.py --stage stage2_volumes --dir .

rem 5) 验证三个工具本身的行为（28 项断言）
python <repo>\tools\selftest.py
```

期望结果：第 3 步第一条 `PASS`（退出码 0）、第二条 `FAIL`（退出码 1）；第 5 步打印「全部 28 项断言通过」。
`<repo>` 换成你克隆/解压后的实际目录。

三个脚本都可以 `python <script> --help` 看参数。`silhouette_diff.py` 的输入是两份「逐行左右边界」JSON
（`{"rows": [[left, right], null, ...]}`），生成方需要先做行填充以消除线稿描边造成的孔洞。

## 5. 验证状态

本仓库的工具不是示意代码，随仓库自带的 `tools/selftest.py` 覆盖了这些真实判定路径（**28 项断言，全部通过**）：

- 自洽口径 + 7 个观测锚点 → `PASS`；几何口径误用相机口径 → `FAIL`；锚点不足 5 个 → `UNKNOWN`（不允许 `PASS`）；
- 剪影：完全一致 / 1 px 内偏移 → `PASS`；宽行边界差 5 px → `FAIL`；≤6 px 窄区间的边界差 → `UNKNOWN`（亚像素归属，不判 `FAIL`）；单侧缺行 → `FAIL`；
- 阶段守卫：目标不存在 → 放行；已存在且未授权 → 阻止且**不改动任何文件**；dry-run 不产生备份；两次授权覆盖依次得到 `_dev1` / `_dev2`；
- CLI 契约：`PASS`→0、`FAIL`→1、spec 缺失→2、仅自检时不宣告 `PASS`。

未验证范围：脚本未在 macOS / Linux 上跑过（只用 `pathlib` 与标准库，理论上可移植）；`silhouette_diff.py`
不直接解析 PNG，掩膜到行区间的转换需要调用方提供（见 `docs/04` 的 B-09）。

## 6. 适用与不适用

**适用**：AI 通过 Blender MCP（或 `bpy` 批处理）做的建模、浮雕、道具、棋子、可打印件的工程化验收；任何「必须有截图/数值证据才算完成」的 3D 任务。

**不适用**：纯概念探索与风格草图（此时判定纪律会拖慢你）；不打算验收的一次性脚本。

**不包含**：具体角色的原画、`.blend`/`.stl` 产物、任何第三方美术资源。本仓库只有方法、模板与工具。

## 7. 来源与脱敏

- `docs/01`、`docs/02` 是长期协议的**逐字归档**（`sha256` 前缀分别为 `987DE6B004D96C89`、`8345B89308F99F27`），只做了文件名调整。
- `docs/03`–`docs/05`、`templates/`、`tools/`、`examples/` 由多个真实项目的执行记录提炼：事故记录、审查轮次报告、交付说明与独立验证结果。项目专有数值已参数化或明确标注为示例。
- `UPLOAD.md` 是**给本机用户的操作手册**，因此保留了实测的本地路径与 GitHub 账号名；发布到公开仓库前可按需替换。
- 全仓库不含任何密钥或令牌：`UPLOAD.md` 中的凭据一律从环境变量或 `gh` 的凭据存储读取，不写入文件。

## 8. 许可

MIT，见 `LICENSE`。若你想把文档改为 CC BY 4.0、代码保留 MIT，直接改 `LICENSE` 并在 README 说明即可。
