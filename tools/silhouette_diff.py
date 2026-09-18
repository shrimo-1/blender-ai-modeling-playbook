#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path


class InputError(Exception):
    pass


def _finite(value, field: str, *, positive=False, nonnegative=False) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise InputError(f"{field} 必须是数值") from exc
    if not math.isfinite(out):
        raise InputError(f"{field} 必须是有限数")
    if positive and out <= 0:
        raise InputError(f"{field} 必须为正数")
    if nonnegative and out < 0:
        raise InputError(f"{field} 不能为负数")
    return out


def load_rows(path: Path) -> dict:
    if not path.is_file():
        raise InputError(f"文件不存在: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InputError(f"{path} 不是合法 JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
        raise InputError(f"{path} 缺少合法 rows 数组")
    width = _finite(data.get("width"), f"{path}.width", positive=True)
    rows = []
    for i, row in enumerate(data["rows"]):
        if row is None:
            rows.append(None)
            continue
        if not (isinstance(row, (list, tuple)) and len(row) == 2):
            raise InputError(f"{path} 第 {i} 行不是 [left, right] 或 null")
        left = _finite(row[0], f"{path}.rows[{i}][0]")
        right = _finite(row[1], f"{path}.rows[{i}][1]")
        if right < left:
            left, right = right, left
        if left < 0 or right > width:
            raise InputError(f"{path} 第 {i} 行边界超出 width={width}")
        rows.append((left, right))
    return {"name": data.get("name", path.stem), "width": width, "rows": rows}


def diff_rows(a: dict, b: dict, tol: float, thin: float, row_range: tuple[int, int] | None) -> dict:
    tol = _finite(tol, "tol", nonnegative=True)
    thin = _finite(thin, "thin", nonnegative=True)
    if float(a.get("width")) != float(b.get("width")):
        raise InputError(f"画布 width 不一致: {a.get('width')} != {b.get('width')}")

    rows_a, rows_b = a["rows"], b["rows"]
    count = max(len(rows_a), len(rows_b))
    if row_range is not None:
        lo, hi = row_range
        if lo < 0 or hi < 0 or lo > hi:
            raise InputError("row range 必须满足 0 <= lo <= hi")
        if count and lo >= count:
            raise InputError(f"row range 起点 {lo} 超出有效范围 0..{count-1}")
    else:
        lo, hi = 0, count - 1

    compared = 0
    fail_rows, thin_rows, presence_rows = [], [], []
    max_dleft = max_dright = 0.0

    if count:
        for index in range(lo, min(hi, count - 1) + 1):
            ra = rows_a[index] if index < len(rows_a) else None
            rb = rows_b[index] if index < len(rows_b) else None
            if ra is None and rb is None:
                continue
            compared += 1
            if ra is None or rb is None:
                presence_rows.append({"row": index, "a": list(ra) if ra else None, "b": list(rb) if rb else None})
                continue
            dleft, dright = abs(ra[0]-rb[0]), abs(ra[1]-rb[1])
            max_dleft, max_dright = max(max_dleft, dleft), max(max_dright, dright)
            if dleft <= tol and dright <= tol:
                continue
            width_a, width_b = ra[1]-ra[0], rb[1]-rb[0]
            entry = {"row": index, "a": list(ra), "b": list(rb), "d_left": round(dleft,3), "d_right": round(dright,3), "width_min": round(min(width_a,width_b),3)}
            (thin_rows if min(width_a, width_b) <= thin else fail_rows).append(entry)

    if compared == 0:
        verdict = "UNKNOWN"
    elif fail_rows or presence_rows:
        verdict = "FAIL"
    elif thin_rows:
        verdict = "UNKNOWN"
    else:
        verdict = "PASS"

    return {
        "a": a["name"], "b": b["name"], "width": a["width"],
        "tol_px": tol, "thin_px": thin,
        "row_range": [lo, min(hi, count-1)] if count else None,
        "rows_compared": compared,
        "max_abs_d_left": round(max_dleft,3), "max_abs_d_right": round(max_dright,3),
        "fail_rows": fail_rows, "thin_rows": thin_rows, "presence_rows": presence_rows,
        "verdict": verdict,
    }


def render(report: dict, sample: int, stream=None) -> None:
    stream = stream or sys.stdout
    print(f"== 剪影逐行差分: {report['a']} vs {report['b']} ==", file=stream)
    print(f"比较 {report['rows_compared']} 行；判定: {report['verdict']}", file=stream)
    if report["rows_compared"] == 0:
        print("  - 没有有效比较行，禁止宣告 PASS。", file=stream)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="剪影逐行左右边界差分")
    parser.add_argument("--a", required=True)
    parser.add_argument("--b", required=True)
    parser.add_argument("--tol", type=float, default=1.0)
    parser.add_argument("--thin", type=float, default=6.0)
    parser.add_argument("--rows", default=None)
    parser.add_argument("--write-report", default=None)
    parser.add_argument("--sample", type=int, default=20)
    args = parser.parse_args(argv)
    try:
        data_a, data_b = load_rows(Path(args.a)), load_rows(Path(args.b))
        row_range = None
        if args.rows:
            parts = args.rows.split(":")
            if len(parts) != 2:
                raise InputError("--rows 格式应为 lo:hi")
            try:
                row_range = (int(parts[0]), int(parts[1]))
            except ValueError as exc:
                raise InputError("--rows 格式应为 lo:hi") from exc
        report = diff_rows(data_a, data_b, args.tol, args.thin, row_range)
    except InputError as exc:
        print(f"[输入错误] {exc}", file=sys.stderr)
        return 2
    render(report, args.sample)
    if args.write_report:
        out = Path(args.write_report)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
