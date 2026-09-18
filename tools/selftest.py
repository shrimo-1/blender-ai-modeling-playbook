#!/usr/bin/env python3
"""tools/ 的自测：用合成数据验证三个工具的真实判定行为（纯标准库）。

运行：
    python tools/selftest.py

覆盖的行为（每条都是断言，失败即抛异常并以非 0 退出）：

unit_roundtrip_check
  - 自洽的口径 + 7 个观测锚点            -> verdict PASS
  - 几何口径被换成相机口径（0.6 倍类事故） -> verdict FAIL
  - 只有 3 个锚点                        -> verdict UNKNOWN（样本量不足，不允许 PASS）

silhouette_diff
  - 完全一致 / 1 px 内偏移               -> PASS
  - 宽行左边界差 5 px                    -> FAIL
  - 窄（≤6 px）区间的边界差              -> UNKNOWN（亚像素归属，不判 FAIL）
  - 单侧缺行                             -> FAIL

stage_guard
  - 目标不存在                           -> 放行
  - 目标已存在且未授权                   -> 阻止，且**不得改动文件**
  - dry-run                              -> 只报告，不改动文件
  - 授权覆盖两次                         -> 依次备份为 _dev1 / _dev2
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
sys.path.insert(0, str(TOOLS))

import silhouette_diff as sd  # noqa: E402
import stage_guard as sg  # noqa: E402
import unit_roundtrip_check as urc  # noqa: E402

CHECKS = 0
# 注意：不直接用 tempfile —— 受限沙箱下系统临时目录可能不可写。
# 临时目录放在仓库内，测试结束即删除（.gitignore 已排除）。
TMP_ROOT = REPO / ".selftest_tmp"


@contextmanager
def scratch_dir():
    if TMP_ROOT.exists():
        shutil.rmtree(TMP_ROOT, ignore_errors=True)
    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    try:
        yield TMP_ROOT
    finally:
        shutil.rmtree(TMP_ROOT, ignore_errors=True)


def expect(label: str, actual, wanted) -> None:
    global CHECKS
    CHECKS += 1
    if actual != wanted:
        raise AssertionError(f"{label}: 期望 {wanted!r}，实得 {actual!r}")
    print(f"  [ok] {label}: {actual!r}")


def load_spec(path: Path) -> dict:
    return urc.load_spec(path)


def test_roundtrip() -> None:
    print("== unit_roundtrip_check ==")
    good = REPO / "examples" / "roundtrip.spec.json"
    bad = REPO / "examples" / "roundtrip_bad.spec.json"

    report = urc.build_report(load_spec(good), None)
    expect("自洽口径 + 7 锚点", report["verdict"], "PASS")
    expect("锚点数量", len(report["anchors"]), 7)
    if not report["max_residual_px"] <= report["tol_px"]:
        raise AssertionError("残差应落在容差内")

    report_bad = urc.build_report(load_spec(bad), None)
    expect("几何口径误用相机口径", report_bad["verdict"], "FAIL")

    spec = load_spec(good)
    spec["anchors"] = spec["anchors"][:3]
    spec["name"] = "only three anchors"
    report_short = urc.build_report(spec, None)
    expect("仅 3 个锚点", report_short["verdict"], "UNKNOWN")
    expect("锚点残差本身达标", report_short["anchor_verdict"], "PASS")


def test_silhouette() -> None:
    print("== silhouette_diff ==")
    base = {"name": "geometry", "width": 296, "rows": [[10, 100], [12, 102], [15, 105], None, [20, 120]]}

    def run(other_rows, tol=1.0, thin=6.0):
        a = {"name": "geometry", "width": 296, "rows": [list(r) if r else None for r in base["rows"]]}
        b = {"name": "other", "width": 296, "rows": [list(r) if r else None for r in other_rows]}
        return sd.diff_rows(a, b, tol, thin, None)

    expect("完全相同", run(base["rows"])["verdict"], "PASS")
    expect(
        "全部 1 px 内偏移",
        run([[10.4, 100.6], [12.2, 102.4], [15.8, 105.9], None, [20.5, 120.5]])["verdict"],
        "PASS",
    )
    expect("宽行左边界差 5 px", run([[10, 100], [12, 102], [15, 105], None, [25, 120]])["verdict"], "FAIL")
    expect("窄区间大差", run([[10, 100], [12, 102], [15, 105], None, [40, 43]])["verdict"], "UNKNOWN")
    expect("单侧缺行", run([[10, 100], [12, 102], [15, 105], None, None])["verdict"], "FAIL")

    thin = run([[10, 100], [12, 102], [15, 105], None, [40, 43]])
    expect("窄区间差异进入 thin 桶（不进 fail 桶）", (len(thin["thin_rows"]), len(thin["fail_rows"])), (1, 0))


def test_stage_guard() -> None:
    print("== stage_guard ==")
    with scratch_dir() as tmp:
        work = Path(tmp)
        expect("目标不存在 -> 放行", sg.guard("stage2_volumes", work)["action"], "write")

        target = work / "stage2_volumes.blend"
        target.write_text("old product", encoding="utf-8")

        blocked = sg.guard("stage2_volumes", work)
        expect("已存在且未授权 -> 阻止", blocked["action"], "blocked")
        expect("阻止时 ok=False", blocked["ok"], False)
        expect("阻止时不得改动文件", target.read_text(encoding="utf-8"), "old product")

        sg.guard("stage2_volumes", work, dry_run=True, allow_overwrite=True)
        expect("dry-run 不产生备份", (work / "stage2_volumes_dev1.blend").exists(), False)
        expect("dry-run 不动主产物", target.exists(), True)

        first = sg.guard("stage2_volumes", work, allow_overwrite=True)
        expect("第一次授权覆盖的备份名", Path(first["backup"]).name, "stage2_volumes_dev1.blend")
        expect("备份内容 = 旧产物", Path(first["backup"]).read_text(encoding="utf-8"), "old product")
        expect("主产物已让位", target.exists(), False)

        target.write_text("v2", encoding="utf-8")
        second = sg.guard("stage2_volumes", work, allow_overwrite=True)
        expect("第二次授权覆盖的备份名", Path(second["backup"]).name, "stage2_volumes_dev2.blend")
        expect("产物链条数（主 + dev1 + dev2）", len(sg.list_chain("stage2_volumes", work)), 3)


def test_cli_contracts() -> None:
    print("== CLI/报告 契约 ==")
    quiet = contextlib.redirect_stdout(io.StringIO())
    mute = contextlib.redirect_stderr(io.StringIO())
    with scratch_dir() as tmp:
        out = Path(tmp) / "nested" / "roundtrip_report.json"
        with quiet:
            code = urc.main(
                [
                    "--spec",
                    str(REPO / "examples" / "roundtrip.spec.json"),
                    "--write-report",
                    str(out),
                ]
            )
        expect("PASS 用例退出码", code, 0)
        expect("报告已落盘", out.is_file(), True)
        payload = json.loads(out.read_text(encoding="utf-8"))
        expect("报告含判定字段", payload["verdict"], "PASS")

        with quiet:
            code_fail = urc.main(["--spec", str(REPO / "examples" / "roundtrip_bad.spec.json")])
        expect("FAIL 用例退出码", code_fail, 1)

        with quiet, mute:
            code_bad_spec = urc.main(["--spec", str(Path(tmp) / "missing.json")])
        expect("spec 缺失退出码", code_bad_spec, 2)

        with quiet:
            code_self = urc.main(
                ["--spec", str(REPO / "examples" / "roundtrip.spec.json"), "--self-check-only"]
            )
        expect("仅自检时不宣告 PASS（退出码 1）", code_self, 1)


def main() -> int:
    test_roundtrip()
    test_silhouette()
    test_stage_guard()
    test_cli_contracts()
    print(f"\n全部 {CHECKS} 项断言通过。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as exc:
        print(f"\n断言失败: {exc}", file=sys.stderr)
        sys.exit(1)
