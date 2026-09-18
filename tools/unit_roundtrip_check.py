#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

MIN_ANCHORS = 5


class SpecError(Exception):
    pass


def _finite_number(value, field: str, *, positive: bool = False, nonnegative: bool = False) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise SpecError(f"{field} 必须是数值") from exc
    if not math.isfinite(out):
        raise SpecError(f"{field} 必须是有限数")
    if positive and out <= 0:
        raise SpecError(f"{field} 必须为正数")
    if nonnegative and out < 0:
        raise SpecError(f"{field} 不能为负数")
    return out


def _pair(value, field: str, *, positive: bool = False) -> tuple[float, float]:
    if not (isinstance(value, (list, tuple)) and len(value) == 2):
        raise SpecError(f"{field} 必须是长度为 2 的数组")
    a = _finite_number(value[0], f"{field}[0]", positive=positive)
    b = _finite_number(value[1], f"{field}[1]", positive=positive)
    return a, b


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

    geometry["mm_per_px"] = _finite_number(geometry.get("mm_per_px"), "geometry.mm_per_px", positive=True)
    geometry["origin_src"] = list(_pair(geometry.get("origin_src"), "geometry.origin_src"))

    resolution = _pair(camera.get("resolution"), "camera.resolution", positive=True)
    if any(not float(v).is_integer() for v in resolution):
        raise SpecError("camera.resolution 必须是正整数 [W, H]")
    camera["resolution"] = [int(resolution[0]), int(resolution[1])]
    camera["ortho_scale"] = _finite_number(camera.get("ortho_scale"), "camera.ortho_scale", positive=True)

    sensor_fit = str(camera.get("sensor_fit", "AUTO")).upper()
    if sensor_fit != "AUTO":
        raise SpecError("当前 checker 仅支持 camera.sensor_fit=AUTO")
    camera["sensor_fit"] = sensor_fit

    pixel_aspect = _pair(camera.get("pixel_aspect", [1.0, 1.0]), "camera.pixel_aspect", positive=True)
    if not (math.isclose(pixel_aspect[0], 1.0) and math.isclose(pixel_aspect[1], 1.0)):
        raise SpecError("当前 checker 仅支持 square pixels: camera.pixel_aspect=[1, 1]")
    camera["pixel_aspect"] = [1.0, 1.0]

    shift = _pair(camera.get("shift", [0.0, 0.0]), "camera.shift")
    if not (math.isclose(shift[0], 0.0) and math.isclose(shift[1], 0.0)):
        raise SpecError("当前 checker 仅支持 camera.shift=[0, 0]；非零 shift 请先折算进 center_world")
    camera["shift"] = [0.0, 0.0]

    center = _pair(camera.get("center_world", [0.0, 0.0]), "camera.center_world")
    camera["center_world"] = list(center)

    spec["tol_px"] = _finite_number(spec.get("tol_px", 0.5), "tol_px", nonnegative=True)
    for key in ("anchors", "self_check_points"):
        value = spec.get(key, [])
        if not isinstance(value, list):
            raise SpecError(f"{key} 必须是数组")
        spec[key] = value
    return spec


class Contract:
    def __init__(self, spec: dict) -> None:
        geometry = spec["geometry"]
        camera = spec["camera"]
        self.k = geometry["mm_per_px"]
        self.ox, self.oz = geometry["origin_src"]
        self.w, self.h = camera["resolution"]
        self.ortho_scale = camera["ortho_scale"]
        self.cx, self.cz = camera["center_world"]
        # With AUTO sensor fit + square pixels, Blender fits ortho_scale to the longer render side.
        self.mm_per_px_render = self.ortho_scale / max(self.w, self.h)

    def src_to_world(self, px: float, py: float) -> tuple[float, float]:
        return ((px - self.ox) * self.k, (self.oz - py) * self.k)

    def world_to_src(self, x: float, z: float) -> tuple[float, float]:
        return (x / self.k + self.ox, self.oz - z / self.k)

    def world_to_pixel(self, x: float, z: float) -> tuple[float, float]:
        s = self.mm_per_px_render
        return (self.w / 2 + (x - self.cx) / s, self.h / 2 - (z - self.cz) / s)

    def pixel_to_world(self, u: float, v: float) -> tuple[float, float]:
        s = self.mm_per_px_render
        return ((u - self.w / 2) * s + self.cx, (self.h / 2 - v) * s + self.cz)

    def src_to_pixel(self, px: float, py: float) -> tuple[float, float]:
        return self.world_to_pixel(*self.src_to_world(px, py))

    def pixel_to_src(self, u: float, v: float) -> tuple[float, float]:
        return self.world_to_src(*self.pixel_to_world(u, v))


def _point(value, field: str) -> tuple[float, float]:
    return _pair(value, field)


def check_anchors(contract: Contract, anchors: list[dict]) -> list[dict]:
    rows = []
    for i, anchor in enumerate(anchors):
        if not isinstance(anchor, dict):
            raise SpecError(f"anchors[{i}] 必须是对象")
        point_id = str(anchor.get("id", f"A{i+1}"))
        src = _point(anchor.get("src"), f"anchor {point_id}.src")
        observed = _point(anchor.get("pixel"), f"anchor {point_id}.pixel")
        predicted = contract.src_to_pixel(*src)
        err = math.dist(predicted, observed)
        rows.append({
            "id": point_id,
            "src": list(src),
            "observed_pixel": list(observed),
            "predicted_pixel": [round(predicted[0], 4), round(predicted[1], 4)],
            "residual_px": err,
        })
    return rows


def check_self_roundtrip(contract: Contract, points: list[dict]) -> list[dict]:
    rows = []
    for i, point in enumerate(points):
        if not isinstance(point, dict):
            raise SpecError(f"self_check_points[{i}] 必须是对象")
        point_id = str(point.get("id", f"C{i+1}"))
        src = _point(point.get("src"), f"self_check {point_id}.src")
        u, v = contract.src_to_pixel(*src)
        back = contract.pixel_to_src(u, v)
        rows.append({
            "id": point_id,
            "src": list(src),
            "pixel": [round(u, 4), round(v, 4)],
            "roundtrip_src": [round(back[0], 4), round(back[1], 4)],
            "residual_px": math.hypot(back[0] - src[0], back[1] - src[1]),
        })
    return rows


def build_report(spec: dict, tol_override: float | None) -> dict:
    contract = Contract(spec)
    tol = spec["tol_px"] if tol_override is None else _finite_number(tol_override, "--tol", nonnegative=True)
    anchors = check_anchors(contract, spec["anchors"])
    self_check = check_self_roundtrip(contract, spec["self_check_points"])
    notes = []

    if anchors:
        max_raw = max(r["residual_px"] for r in anchors)
        anchor_verdict = "PASS" if max_raw <= tol else "FAIL"
    else:
        max_raw = None
        anchor_verdict = "UNKNOWN"

    if len(anchors) < MIN_ANCHORS:
        notes.append(f"锚点不足 {MIN_ANCHORS} 个（当前 {len(anchors)}）：结论不能为 PASS。")

    if anchor_verdict == "FAIL":
        verdict = "FAIL"
    elif anchor_verdict == "PASS" and len(anchors) >= MIN_ANCHORS:
        verdict = "PASS"
    else:
        verdict = "UNKNOWN"

    ratio = contract.mm_per_px_render / contract.k
    notes.append(f"相机口径 / 几何口径 = {ratio:.6f}")
    notes.append("相机契约限制：orthographic + sensor_fit=AUTO + square pixels + zero shift。")

    return {
        "name": spec.get("name", "unnamed"),
        "tol_px": tol,
        "contract": {
            "mm_per_px": contract.k,
            "origin_src": [contract.ox, contract.oz],
            "mm_per_px_render": contract.mm_per_px_render,
            "ortho_scale": contract.ortho_scale,
            "resolution": [contract.w, contract.h],
        },
        "anchors": [{**r, "residual_px": round(r["residual_px"], 6)} for r in anchors],
        "self_check": [{**r, "residual_px": round(r["residual_px"], 9)} for r in self_check],
        "max_residual_px": None if max_raw is None else round(max_raw, 6),
        "anchor_verdict": anchor_verdict,
        "verdict": verdict,
        "notes": notes,
    }


def render_report(report: dict, stream=None) -> None:
    stream = stream or sys.stdout
    print(f"== 坐标口径预检: {report['name']} ==", file=stream)
    print(f"容差 {report['tol_px']} px；锚点 {len(report['anchors'])} 个", file=stream)
    print(f"最大残差 {report['max_residual_px']} px", file=stream)
    print(f"判定: {report['verdict']}", file=stream)
    for note in report["notes"]:
        print(f"  - {note}", file=stream)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="坐标往返预检")
    parser.add_argument("--spec", required=True)
    parser.add_argument("--tol", type=float, default=None)
    parser.add_argument("--write-report", default=None)
    parser.add_argument("--self-check-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        spec = load_spec(Path(args.spec))
        if args.self_check_only:
            if not spec["self_check_points"]:
                spec["self_check_points"] = [
                    {"id": str(a.get("id", f"C{i+1}")), "src": a["src"]}
                    for i, a in enumerate(spec["anchors"])
                ]
            if not spec["self_check_points"]:
                raise SpecError("--self-check-only 需要待检点")
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
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
