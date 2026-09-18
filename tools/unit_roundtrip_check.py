#!/usr/bin/env python3
"""坐标往返预检 / 口径一致性检查（纯标准库，不依赖 bpy 或 numpy）。

用途
----
在动任何几何之前，验证「源图像素 -> 世界坐标 -> 渲染图像素」这条链路的口径是对的。
它检查的不是数学可逆性（那必然成立），而是**你声明的口径能否复现独立观测到的对应关系**。

为什么需要独立观测锚点
----------------------
把 src 经 world 换算成 pixel 再换算回 src，只要两段用的是同一套参数，往返就必然闭合——
即使参数整体错了。所以真正有判别力的输入是 anchors：**同一个特征点**在源图与渲染图上的
像素坐标（人工目视确认）。口径错、缩放错、两套口径混用，都会让 anchor 残差超差。

spec 文件（JSON）字段
---------------------
{
  "name": "front",
  "geometry": {"mm_per_px": 0.4054055, "origin_src": [141.5, 402.0]},
  "camera":   {"resolution": [296, 402], "ortho_scale": 145.0, "center_world": [0.0, 0.0]},
  "tol_px": 0.5,
  "anchors": [{"id": "hat_top", "src": [141.5, 12.0], "pixel": [148.0, 15.5]}],
  "self_check_points": [{"id": "c1", "src": [10.0, 10.0]}]
}

字段说明
--------
geometry.mm_per_px   几何口径 K：源图 1 px 对应多少毫米（由参考图两个已知语义点反推）
geometry.origin_src  世界原点在源图中的像素位置 [ox, oz]
camera.resolution    渲染分辨率 [W, H]
camera.ortho_scale   正交相机 ortho_scale（Blender：作用于渲染的较长边）
camera.center_world  渲染画面中心对应的世界 (X, Z)
tol_px               允许的最大残差（源像素），默认 0.5
anchors              独立观测锚点，至少 5 个；每个给同一特征的 src 与 pixel 坐标
self_check_points    可选：只做数值往返自检的点（**不构成口径正确性证据**）

退出码：0 = PASS；1 = 残差超差；2 = spec 缺失/字段错误
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

REQUIRED_GEOMETRY = ("mm_per_px", "origin_src")
REQUIRED_CAMERA = ("resolution", "ortho_scale")
MIN_ANCHORS = 5


class SpecError(Exception):
    """spec 缺失或字段不合法。"""


def load_spec(path: Path) -> dict:
    if not path.is_file():
        raise SpecError(f"spec 文件不存在: {path}")
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SpecError(f"spec 不是合法 JSON: {exc}") from exc
    if not isinstance(spec, dict):
        raise SpecError("spec 顶层必须是对象")

    geometry = spec.get("geometry")
    camera = spec.get("camera")
    if not isinstance(geometry, dict):
        raise SpecError("缺少 geometry 段")
    if not isinstance(camera, dict):
        raise SpecError("缺少 camera 段")
    for key in REQUIRED_GEOMETRY:
        if key not in geometry:
            raise SpecError(f"geometry 缺少字段: {key}")
    for key in REQUIRED_CAMERA:
        if key not in camera:
            raise SpecError(f"camera 缺少字段: {key}")

    mm_per_px = float(geometry["mm_per_px"])
    if mm_per_px <= 0:
        raise SpecError("geometry.mm_per_px 必须为正数")
    origin = geometry["origin_src"]
    if not (isinstance(origin, (list, tuple)) and len(origin) == 2):
        raise SpecError("geometry.origin_src 必须是 [ox, oz]")
    resolution = camera["resolution"]
    if not (isinstance(resolution, (list, tuple)) and len(resolution) == 2):
        raise SpecError("camera.resolution 必须是 [W, H]")
    if float(camera["ortho_scale"]) <= 0:
        raise SpecError("camera.ortho_scale 必须为正数")
    spec.setdefault("tol_px", 0.5)
    spec.setdefault("anchors", [])
    spec.setdefault("self_check_points", [])
    spec.setdefault("center_world", camera.get("center_world", [0.0, 0.0]))
    return spec


class Contract:
    """把 spec 里的口径实现成可正逆变换的三段映射。"""

    def __init__(self, spec: dict) -> None:
        geometry = spec["geometry"]
        camera = spec["camera"]
        self.k = float(geometry["mm_per_px"])
        self.ox, self.oz = (float(v) for v in geometry["origin_src"])
        self.w, self.h = (float(v) for v in camera["resolution"])
        self.ortho_scale = float(camera["ortho_scale"])
        self.cx, self.cz = (float(v) for v in spec.get("center_world", [0.0, 0.0]))
        # Blender 的 ortho_scale 作用于渲染的较长边
        self.mm_per_px_render = self.ortho_scale / max(self.w, self.h)

    # --- 几何口径：源图像素 <-> 世界 (X, Z) ---
    def src_to_world(self, px: float, py: float) -> tuple[float, float]:
        return ((px - self.ox) * self.k, (self.oz - py) * self.k)

    def world_to_src(self, x: float, z: float) -> tuple[float, float]:
        return (x / self.k + self.ox, self.oz - z / self.k)

    # --- 相机正交口径：世界 (X, Z) <-> 渲染图像素 ---
    def world_to_pixel(self, x: float, z: float) -> tuple[float, float]:
        s = self.mm_per_px_render
        return (self.w / 2.0 + (x - self.cx) / s, self.h / 2.0 - (z - self.cz) / s)

    def pixel_to_world(self, u: float, v: float) -> tuple[float, float]:
        s = self.mm_per_px_render
        return ((u - self.w / 2.0) * s + self.cx, (self.h / 2.0 - v) * s + self.cz)

    def src_to_pixel(self, px: float, py: float) -> tuple[float, float]:
        return self.world_to_pixel(*self.src_to_world(px, py))

    def pixel_to_src(self, u: float, v: float) -> tuple[float, float]:
        return self.world_to_src(*self.pixel_to_world(u, v))


def check_anchors(contract: Contract, anchors: list[dict]) -> list[dict]:
    rows = []
    for anchor in anchors:
        point_id = str(anchor.get("id", "?"))
        src = anchor.get("src")
        observed = anchor.get("pixel")
        if not (isinstance(src, (list, tuple)) and len(src) == 2):
            raise SpecError(f"anchor {point_id}: src 必须是 [x, y]")
        if not (isinstance(observed, (list, tuple)) and len(observed) == 2):
            raise SpecError(f"anchor {point_id}: pixel 必须是 [u, v]")
        predicted = contract.src_to_pixel(float(src[0]), float(src[1]))
        err = math.dist(predicted, (float(observed[0]), float(observed[1])))
        rows.append(
            {
                "id": point_id,
                "src": [float(src[0]), float(src[1])],
                "observed_pixel": [float(observed[0]), float(observed[1])],
                "predicted_pixel": [round(predicted[0], 4), round(predicted[1], 4)],
                "residual_px": round(err, 4),
            }
        )
    return rows


def check_self_roundtrip(contract: Contract, points: list[dict]) -> list[dict]:
    rows = []
    for point in points:
        point_id = str(point.get("id", "?"))
        src = point.get("src")
        if not (isinstance(src, (list, tuple)) and len(src) == 2):
            raise SpecError(f"self_check {point_id}: src 必须是 [x, y]")
        px, py = float(src[0]), float(src[1])
        u, v = contract.src_to_pixel(px, py)
        back = contract.pixel_to_src(u, v)
        rows.append(
            {
                "id": point_id,
                "src": [px, py],
                "pixel": [round(u, 4), round(v, 4)],
                "roundtrip_src": [round(back[0], 4), round(back[1], 4)],
                "residual_px": round(math.hypot(back[0] - px, back[1] - py), 6),
            }
        )
    return rows


def render_report(report: dict, stream=None) -> None:
    if stream is None:  # 延迟到调用时取，便于测试里 redirect_stdout
        stream = sys.stdout
    print(f"== 坐标口径预检: {report['name']} ==", file=stream)
    print(
        "几何口径 K = {k} mm/px，原点 src({ox}, {oz})".format(
            k=report["contract"]["mm_per_px"], **report["contract"]
        ),
        file=stream,
    )
    print(
        "相机口径 = {r} mm/px（ortho_scale {o} / 长边 {e}）".format(
            r=round(report["contract"]["mm_per_px_render"], 6),
            o=report["contract"]["ortho_scale"],
            e=report["contract"]["long_side"],
        ),
        file=stream,
    )
    print(f"容差 {report['tol_px']} px\n", file=stream)

    if report["anchors"]:
        print("-- 独立观测锚点（src -> world -> pixel vs 观测） --", file=stream)
        print(f"{'id':<16}{'src':>18}{'观测 pixel':>20}{'推算 pixel':>20}{'残差 px':>10}", file=stream)
        for row in report["anchors"]:
            print(
                f"{row['id']:<16}"
                f"{'({:.1f}, {:.1f})'.format(*row['src']):>18}"
                f"{'({:.1f}, {:.1f})'.format(*row['observed_pixel']):>20}"
                f"{'({:.2f}, {:.2f})'.format(*row['predicted_pixel']):>20}"
                f"{row['residual_px']:>10.3f}",
                file=stream,
            )
        print(
            f"\n锚点 {len(report['anchors'])} 个，最大残差 {report['max_residual_px']} px"
            f" -> 锚点残差判定 {report['anchor_verdict']}（最终判定见下）",
            file=stream,
        )
    else:
        print("!! 未提供 anchors：没有独立观测，本次检查**不能**证明口径正确。", file=stream)
        print("   仅有 self_check（数值往返）时，结论一律为 UNKNOWN。", file=stream)

    if report["self_check"]:
        print("\n-- 数值往返自检（不构成口径证据） --", file=stream)
        for row in report["self_check"]:
            print(
                f"{row['id']:<16}src({row['src'][0]:.1f}, {row['src'][1]:.1f}) "
                f"-> src({row['roundtrip_src'][0]:.1f}, {row['roundtrip_src'][1]:.1f}) "
                f"残差 {row['residual_px']:.6f} px",
                file=stream,
            )

    print(f"\n判定: {report['verdict']}", file=stream)
    for note in report["notes"]:
        print(f"  - {note}", file=stream)


def build_report(spec: dict, tol_override: float | None) -> dict:
    contract = Contract(spec)
    tol = float(tol_override if tol_override is not None else spec["tol_px"])
    anchors = check_anchors(contract, list(spec.get("anchors", [])))
    self_check = check_self_roundtrip(contract, list(spec.get("self_check_points", [])))

    notes = []
    if len(anchors) < MIN_ANCHORS:
        notes.append(
            f"锚点不足 {MIN_ANCHORS} 个（当前 {len(anchors)}）：不足以覆盖画面四角与中心，结论降级为 UNKNOWN。"
        )
    if anchors:
        max_residual = max(row["residual_px"] for row in anchors)
        anchor_verdict = "PASS" if max_residual <= tol else "FAIL"
    else:
        max_residual = None
        anchor_verdict = "UNKNOWN"

    if anchor_verdict == "PASS" and len(anchors) < MIN_ANCHORS:
        verdict = "UNKNOWN"
        notes.append("锚点残差全部达容差，但样本量不足，不允许宣告 PASS。")
    elif anchor_verdict == "FAIL":
        verdict = "FAIL"
        notes.append("停止后续 overlay / IoU / probe / 建模；先修口径或重标定 K。")
    elif anchor_verdict == "UNKNOWN":
        verdict = "UNKNOWN"
        notes.append("至少提供 5 个独立观测锚点后才能宣告 PASS。")
    else:
        verdict = "PASS"
        notes.append("口径可用；把本报告路径写进项目的 UNIT_CONVENTION.md。")

    ratio = contract.mm_per_px_render / contract.k
    notes.append(
        "相机口径 / 几何口径 = {:.6f}（比值不必然为 1；若渲染图与源图同帧，则应接近 1，"
        "明显偏离时先确认这是刻意的帧比例，还是把一套口径当成了另一套）".format(ratio)
    )

    return {
        "name": spec.get("name", "unnamed"),
        "tol_px": tol,
        "contract": {
            "mm_per_px": contract.k,
            "origin_src": [contract.ox, contract.oz],
            "ox": contract.ox,
            "oz": contract.oz,
            "mm_per_px_render": contract.mm_per_px_render,
            "ortho_scale": contract.ortho_scale,
            "long_side": max(contract.w, contract.h),
        },
        "anchors": anchors,
        "self_check": self_check,
        "max_residual_px": max_residual,
        "anchor_verdict": anchor_verdict,
        "verdict": verdict,
        "notes": notes,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="坐标往返预检：验证源图->世界->渲染图的像素口径（需要独立观测锚点）。"
    )
    parser.add_argument("--spec", required=True, help="spec JSON 路径")
    parser.add_argument("--tol", type=float, default=None, help="覆盖 spec 里的 tol_px")
    parser.add_argument("--write-report", default=None, help="把完整报告写成 JSON")
    parser.add_argument(
        "--self-check-only",
        action="store_true",
        help="只做数值往返自检（结论一律 UNKNOWN，仅用于排查参数笔误）",
    )
    args = parser.parse_args(argv)

    try:
        spec = load_spec(Path(args.spec))
        if args.self_check_only:
            if not spec.get("self_check_points"):
                spec["self_check_points"] = [
                    {"id": str(a.get("id", f"C{i + 1}")), "src": a["src"]}
                    for i, a in enumerate(spec.get("anchors", []))
                ]
            if not spec["self_check_points"]:
                raise SpecError(
                    "--self-check-only 需要 self_check_points（或非空 anchors）提供待检点"
                )
            spec["anchors"] = []
        report = build_report(spec, args.tol)
    except SpecError as exc:
        print(f"[spec 错误] {exc}", file=sys.stderr)
        return 2

    render_report(report)
    if args.write_report:
        out = Path(args.write_report)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n报告已写入: {out}")

    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
