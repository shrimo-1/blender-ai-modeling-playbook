#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path


def _dev_pattern(stage: str, ext: str) -> re.Pattern:
    return re.compile(rf"^{re.escape(stage)}_dev(\d+){re.escape(ext)}$")


def existing_devs(stage: str, directory: Path, ext: str) -> list[tuple[int, Path]]:
    pattern = _dev_pattern(stage, ext)
    found = []
    if directory.is_dir():
        for item in directory.iterdir():
            m = pattern.match(item.name)
            if m:
                found.append((int(m.group(1)), item))
    return sorted(found)


def guard(stage: str, directory: str | Path, allow_overwrite=False, dry_run=False, ext=".blend") -> dict:
    if not stage or "/" in stage or "\\" in stage:
        raise ValueError("stage 名不能为空，也不能包含路径分隔符")
    if not ext.startswith(".") or "/" in ext or "\\" in ext:
        raise ValueError("ext 必须是形如 .blend 的扩展名")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{stage}{ext}"
    if target.exists() and not target.is_file():
        raise ValueError(f"目标存在但不是普通文件: {target}")

    if not target.exists():
        return {"ok": True, "action": "write", "target": str(target), "backup": None, "message": f"OK: 可安全写入 {target}"}
    if not allow_overwrite:
        return {"ok": False, "action": "blocked", "target": str(target), "backup": None, "message": f"STOP: {target} 已存在。"}

    devs = existing_devs(stage, directory, ext)
    next_index = devs[-1][0] + 1 if devs else 1
    backup = directory / f"{stage}_dev{next_index}{ext}"
    if dry_run:
        return {"ok": True, "action": "backup_then_write", "target": str(target), "backup": str(backup), "message": f"DRY-RUN: 会复制旧产物到 {backup}"}

    # Copy, don't rename: if the subsequent Blender save fails, the current main artifact still exists.
    shutil.copy2(target, backup)
    return {"ok": True, "action": "backup_then_write", "target": str(target), "backup": str(backup), "message": f"OK: 旧产物已备份为 {backup.name}；主产物仍保留，随后可覆盖写入"}


def list_chain(stage: str, directory: str | Path, ext=".blend") -> list[str]:
    directory = Path(directory)
    target = directory / f"{stage}{ext}"
    lines = [f"{'[主产物]' if target.exists() else '[缺失]  '} {target.name}"]
    for index, path in existing_devs(stage, directory, ext):
        lines.append(f"[dev{index}]   {path.name}")
    return lines


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="阶段产物防覆写守卫")
    p.add_argument("--stage", required=True); p.add_argument("--dir", required=True)
    p.add_argument("--ext", default=".blend"); p.add_argument("--allow-overwrite", action="store_true")
    p.add_argument("--dry-run", action="store_true"); p.add_argument("--list", action="store_true")
    args = p.parse_args(argv)
    try:
        if args.list:
            print("\n".join(list_chain(args.stage, args.dir, args.ext))); return 0
        result = guard(args.stage, args.dir, args.allow_overwrite, args.dry_run, args.ext)
    except (ValueError, OSError) as exc:
        print(f"[错误] {exc}", file=sys.stderr); return 1
    print(result["message"])
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
