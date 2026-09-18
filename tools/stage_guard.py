#!/usr/bin/env python3
"""阶段产物防覆写守卫（纯标准库）。

背景
----
真实事故：阶段脚本里写死了保存路径，把**上一阶段**的 `.blend` 覆盖掉了，前一轮的事实基础消失。
规则是：脚本显式声明 `STAGE_NAME`，保存路径由它生成；`<STAGE_NAME>.blend` 已存在则停止并报告；
同轮内确实要重跑时，先把旧产物改名保留（`*_devN.blend`），不得直接覆盖。

用法（命令行）
--------------
    python tools/stage_guard.py --stage stage2_volumes --dir builder
        目标不存在      -> 打印 OK，退出码 0
        目标已存在      -> 打印 STOP 与保留建议，退出码 2（拒绝写入）
    python tools/stage_guard.py --stage stage2_volumes --dir builder --allow-overwrite
        目标已存在      -> 先把旧产物改名为 stage2_volumes_devN.blend 再放行，退出码 0
    python tools/stage_guard.py --list --stage stage2_volumes --dir builder
        列出该阶段现有产物链（主产物 + devN）

用法（在 Blender 阶段脚本里）
-----------------------------
    import os, sys
    sys.path.insert(0, r"<repo>/tools")
    from stage_guard import guard

    STAGE_NAME = "stage2_volumes"
    result = guard(STAGE_NAME, r"<project>/builder",
                   allow_overwrite=os.environ.get("STAGE_ALLOW_OVERWRITE") == "1")
    if not result["ok"]:
        raise SystemExit(result["message"])
    bpy.ops.wm.save_as_mainfile(filepath=result["target"])

退出码：0 = 可写（必要时已备份）；2 = 已阻止写入；1 = 参数/环境错误
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def _dev_pattern(stage: str, ext: str) -> re.Pattern:
    return re.compile(rf"^{re.escape(stage)}_dev(\d+){re.escape(ext)}$")


def existing_devs(stage: str, directory: Path, ext: str) -> list[tuple[int, Path]]:
    pattern = _dev_pattern(stage, ext)
    found = []
    if directory.is_dir():
        for item in directory.iterdir():
            match = pattern.match(item.name)
            if match:
                found.append((int(match.group(1)), item))
    return sorted(found)


def guard(
    stage: str,
    directory: str | Path,
    allow_overwrite: bool = False,
    dry_run: bool = False,
    ext: str = ".blend",
) -> dict:
    """检查目标阶段文件能否写入；必要时把旧产物备份成 <stage>_devN<ext>。

    返回 {"ok", "action", "target", "backup", "message"}；
    action 取值 "write"（直接写）/ "backup_then_write" / "blocked"。
    """
    if not stage or "/" in stage or "\\" in stage:
        raise ValueError("stage 名不能为空，也不能包含路径分隔符")
    directory = Path(directory)
    target = directory / f"{stage}{ext}"

    if not target.exists():
        return {
            "ok": True,
            "action": "write",
            "target": str(target),
            "backup": None,
            "message": f"OK: 目标不存在，可安全写入 {target}",
        }

    if not allow_overwrite:
        return {
            "ok": False,
            "action": "blocked",
            "target": str(target),
            "backup": None,
            "message": (
                f"STOP: {target} 已存在。默认不覆盖上一阶段产物。\n"
                f"      若确认要在同一轮内重跑：加 --allow-overwrite "
                f"(或设置 STAGE_ALLOW_OVERWRITE=1)，旧产物会先改名为 "
                f"{stage}_devN{ext} 保留。"
            ),
        }

    devs = existing_devs(stage, directory, ext)
    next_index = (devs[-1][0] + 1) if devs else 1
    backup = directory / f"{stage}_dev{next_index}{ext}"

    if dry_run:
        return {
            "ok": True,
            "action": "backup_then_write",
            "target": str(target),
            "backup": str(backup),
            "message": f"DRY-RUN: 会把 {target} 改名为 {backup}，然后写入新产物",
        }

    target.rename(backup)
    return {
        "ok": True,
        "action": "backup_then_write",
        "target": str(target),
        "backup": str(backup),
        "message": f"OK: 旧产物已保留为 {backup.name}，可写入 {target}",
    }


def list_chain(stage: str, directory: str | Path, ext: str = ".blend") -> list[str]:
    directory = Path(directory)
    lines = []
    target = directory / f"{stage}{ext}"
    lines.append(f"{'[主产物]' if target.exists() else '[缺失]  '} {target.name}")
    for index, path in existing_devs(stage, directory, ext):
        lines.append(f"[dev{index}]   {path.name}")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="阶段产物防覆写守卫：目标已存在则停止，除非显式允许覆盖（先备份为 devN）"
    )
    parser.add_argument("--stage", required=True, help="阶段名，例如 stage2_volumes")
    parser.add_argument("--dir", required=True, help="阶段产物所在目录")
    parser.add_argument("--ext", default=".blend", help="产物扩展名（默认 .blend）")
    parser.add_argument("--allow-overwrite", action="store_true", help="允许覆盖；旧产物先改名为 devN")
    parser.add_argument("--dry-run", action="store_true", help="只报告将要做什么，不改动文件")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    parser.add_argument("--list", action="store_true", help="只列出该阶段的产物链")
    args = parser.parse_args(argv)

    try:
        if args.list:
            for line in list_chain(args.stage, args.dir, args.ext):
                print(line)
            return 0
        result = guard(
            args.stage,
            args.dir,
            allow_overwrite=args.allow_overwrite,
            dry_run=args.dry_run,
            ext=args.ext,
        )
    except (ValueError, OSError) as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 1

    if args.json:
        import json

        print(json.dumps(result, ensure_ascii=False))
    else:
        print(result["message"])

    if not result["ok"]:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
