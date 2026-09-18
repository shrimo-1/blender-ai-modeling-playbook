#!/usr/bin/env python3
"""剪影逐行左右边界差分（纯标准库）。

用途
----
比较两份「剪影逐行区间」：通常是**几何渲染剪影**与**原画剪影**，也可以是同一模型在两个阶段
的产物（回归比较）。比整体 IoU 更有判别力：IoU 对轮廓的局部变形不敏感，而逐行边界差能直接
指出「哪一行、左边还是右边、差了多少像素」。

输入格式（JSON）
----------------
{
  "name": "geometry front silhouette",
  "width": 296,
  "rows": [[12, 240], [13, 241], null, ...]
}

rows 数组的索引即行号；null（或省略）表示该行为空行。生成方负责先做行填充
（原画线稿的深色描边在阈值化后会变成背景，需要按每行首末非背景像素填充后再取区间）。

判定规则
--------
- 每行的左/右边界差都 <= tol（默认 1 px）：一致；
- 超差且该行两侧区间宽度都 > thin（默认 6 px）：计为 FAIL 行；
- 超差但至少一侧区间宽度 <= thin：计为「细碎/亚像素归属」行，只记 UNKNOWN，不判 FAIL
  （对应长期规则：细碎区间上的小差值属亚像素归属，不得为了凑 0 而改口径）；
- 一行有内容、另一行为空：计为结构差异，判 FAIL。

退出码：0 = PASS；1 = UNKNOWN 或 FAIL；2 = 输入错误
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


class InputError(Exception):
    """输入文件缺失或结构不合法。"""


def load_rows(path: Path) -> dict:
    if not path.is_file():
        raise InputError(f"文件不存在: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InputError(f"{path} 不是合法 JSON: {exc}") from exc
    if not isinstance(data, dict) or "rows" not in data:
        raise InputError(f"{path} 缺少 rows 字段")
    rows = data["rows"]
    if not isinstance(rows, list):
        raise InputError(f"{path} 的 rows 必须是数组")
    normalised = []
    for index, row in enumerate(rows):
        if row is None:
            normalised.append(None)
            continue
        if not (isinstance(row, (list, tuple)) and len(row) == 2):
            raise InputError(f"{path} 第 {index} 行不是 [left, right] 或 null")
        left, right = float(row[0]), float(row[1])
        if right < left:
            left, right = right, left
        normalised.append((left, right))
    return {"name": data.get("name", path.stem), "width": data.get("width"), "rows": normalised}


def diff_rows(a: dict, b: dict, tol: float, thin: float, row_range: tuple[int, int] | None) -> dict:
    rows_a, rows_b = a["rows"], b["rows"]
    count = max(len(rows_a), len(rows_b))
    lo, hi = (0, count - 1) if row_range is None else row_range

    compared = 0
    fail_rows: list[dict] = []
    thin_rows: list[dict] = []
    presence_rows: list[dict] = []
    max_dleft = 0.0
    max_dright = 0.0

    for index in range(lo, min(hi, count - 1) + 1):
        ra = rows_a[index] if index < len(rows_a) else None
        rb = rows_b[index] if index < len(rows_b) else None
        if ra is None and rb is None:
            continue
        compared += 1
        if ra is None or rb is None:
            presence_rows.append(
                {"row": index, "a": list(ra) if ra else None, "b": list(rb) if rb else None}
            )
            continue
        dleft = abs(ra[0] - rb[0])
        dright = abs(ra[1] - rb[1])
        max_dleft = max(max_dleft, dleft)
        max_dright = max(max_dright, dright)
        if dleft <= tol and dright <= tol:
            continue
        width_a = ra[1] - ra[0]
        width_b = rb[1] - rb[0]
        entry = {
            "row": index,
            "a": [ra[0], ra[1]],
            "b": [rb[0], rb[1]],
            "d_left": round(dleft, 3),
            "d_right": round(dright, 3),
            "width_min": round(min(width_a, width_b), 3),
        }
        if min(width_a, width_b) <= thin:
            thin_rows.append(entry)
        else:
            fail_rows.append(entry)

    if fail_rows or presence_rows:
        verdict = "FAIL"
    elif thin_rows:
        verdict = "UNKNOWN"
    else:
        verdict = "PASS"

    return {
        "a": a["name"],
        "b": b["name"],
        "tol_px": tol,
        "thin_px": thin,
        "row_range": [lo, min(hi, count - 1)],
        "rows_compared": compared,
        "max_abs_d_left": round(max_dleft, 3),
        "max_abs_d_right": round(max_dright, 3),
        "fail_rows": fail_rows,
        "thin_rows": thin_rows,
        "presence_rows": presence_rows,
        "verdict": verdict,
    }


def render(report: dict, sample: int, stream=None) -> None:
    if stream is None:  # 延迟到调用时取，便于测试里 redirect_stdout
        stream = sys.stdout
    print(f"== 剪影逐行差分: {report['a']}  vs  {report['b']} ==", file=stream)
    print(
        "行范围 [{0}, {1}]，比较 {2} 行，容差 {3} px，细碎阈值 {4} px".format(
            report["row_range"][0], report["row_range"][1],
            report["rows_compared"], report["tol_px"], report["thin_px"],
        ),
        file=stream,
    )
    print(
        f"最大左边界差 {report['max_abs_d_left']} px，最大右边界差 {report['max_abs_d_right']} px",
        file=stream,
    )
    print(
        "FAIL 行 {0}，细碎(UNKNOWN)行 {1}，单侧缺行 {2}".format(
            len(report["fail_rows"]), len(report["thin_rows"]), len(report["presence_rows"])
        ),
        file=stream,
    )

    for label, rows in (("FAIL", report["fail_rows"]), ("细碎", report["thin_rows"]), ("缺行", report["presence_rows"])):
        if not rows:
            continue
        print(f"\n-- {label}（最多显示 {sample} 行） --", file=stream)
        for entry in rows[:sample]:
            if label == "缺行":
                print(f"row {entry['row']:<6} a={entry['a']}  b={entry['b']}", file=stream)
            else:
                print(
                    "row {row:<6} a=({a0:.0f}, {a1:.0f})  b=({b0:.0f}, {b1:.0f})  "
                    "dL={dl:<7} dR={dr:<7} 窄侧宽度={w}".format(
                        row=entry["row"], a0=entry["a"][0], a1=entry["a"][1],
                        b0=entry["b"][0], b1=entry["b"][1],
                        dl=entry["d_left"], dr=entry["d_right"], w=entry["width_min"],
                    ),
                    file=stream,
                )
        if len(rows) > sample:
            print(f"... 其余 {len(rows) - sample} 行见报告 JSON", file=stream)

    print(f"\n判定: {report['verdict']}", file=stream)
    if report["verdict"] == "FAIL":
        print("  - 结构差异或超容差偏移：先按 FAIL 行定位是左边界、右边界还是整段缺失。", file=stream)
    elif report["verdict"] == "UNKNOWN":
        print("  - 仅有细碎区间差异：属亚像素归属类，记 UNKNOWN，不得为凑 0 改口径。", file=stream)
    else:
        print("  - 逐行边界在容差内一致。仍然需要整体观感对照才能宣告视觉 PASS。", file=stream)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="剪影逐行左右边界差分（几何 vs 原画，或阶段回归）")
    parser.add_argument("--a", required=True, help="A 侧区间 JSON（如几何剪影）")
    parser.add_argument("--b", required=True, help="B 侧区间 JSON（如原画剪影）")
    parser.add_argument("--tol", type=float, default=1.0, help="每行左右边界允许的最大差（默认 1 px）")
    parser.add_argument("--thin", type=float, default=6.0, help="细碎区间宽度阈值（默认 6 px）")
    parser.add_argument("--rows", default=None, help="只比较指定行范围，格式 lo:hi（含端点）")
    parser.add_argument("--write-report", default=None, help="把完整报告写成 JSON")
    parser.add_argument("--sample", type=int, default=20, help="终端里每类最多显示多少行")
    args = parser.parse_args(argv)

    try:
        data_a = load_rows(Path(args.a))
        data_b = load_rows(Path(args.b))
        row_range = None
        if args.rows:
            try:
                lo, hi = (int(v) for v in args.rows.split(":"))
            except ValueError as exc:
                raise InputError("--rows 格式应为 lo:hi") from exc
            row_range = (lo, hi)
        report = diff_rows(data_a, data_b, args.tol, args.thin, row_range)
    except InputError as exc:
        print(f"[输入错误] {exc}", file=sys.stderr)
        return 2

    render(report, args.sample)
    if args.write_report:
        out = Path(args.write_report)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n报告已写入: {out}")

    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
