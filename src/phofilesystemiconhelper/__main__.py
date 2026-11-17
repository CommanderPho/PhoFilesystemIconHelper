"""CLI for PhoFilesystemIconHelper."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from phofilesystemiconhelper.apply_volume_icon import apply_matches, is_windows_admin
from phofilesystemiconhelper.disk_probe import list_disks
from phofilesystemiconhelper.icns_to_ico import (
    IcnsConversionError,
    batch_icns_to_ico,
    icns_to_ico,
)
from phofilesystemiconhelper.icon_db import connect, icon_count, index_icons
from phofilesystemiconhelper.match_icons import match_all_disks
from phofilesystemiconhelper.paths import DEFAULT_DB_PATH


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="phofilesystemiconhelper",
        description="Filesystem and volume icon helpers for Windows and macOS",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    convert = sub.add_parser(
        "icns-to-ico",
        help="Convert macOS .icns icon(s) to Windows .ico",
    )
    convert.add_argument(
        "path",
        type=Path,
        help="Path to a .icns file or a directory of .icns files",
    )
    convert.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output .ico path (file) or directory (when converting a folder)",
    )
    convert.add_argument(
        "--recursive",
        action="store_true",
        help="When path is a directory, search recursively for .icns files",
    )

    icons = sub.add_parser("icons", help="Icon library database commands")
    icons_sub = icons.add_subparsers(dest="icons_command", required=True)
    index_cmd = icons_sub.add_parser(
        "index",
        help="Recursively index .icns/.ico files into SQLite",
    )
    index_cmd.add_argument(
        "folder",
        type=Path,
        help="Root folder to scan recursively",
    )
    index_cmd.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"SQLite DB path (default: {DEFAULT_DB_PATH})",
    )

    disks = sub.add_parser("disks", help="Hardware disk probe / match / apply")
    disks_sub = disks.add_subparsers(dest="disks_command", required=True)

    list_cmd = disks_sub.add_parser("list", help="List local physical disks")
    list_cmd.add_argument("--json", action="store_true", help="Emit JSON")

    match_cmd = disks_sub.add_parser(
        "match",
        help="Match local disks to icons in the DB",
    )
    match_cmd.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    match_cmd.add_argument("--json", action="store_true")
    match_cmd.add_argument(
        "--include-system",
        action="store_true",
        help="Include the system/boot volume in matching",
    )

    apply_cmd = disks_sub.add_parser(
        "apply",
        help="Apply matched volume icons (dry-run unless --yes)",
    )
    apply_cmd.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    apply_cmd.add_argument(
        "--yes",
        action="store_true",
        help="Actually apply (default is dry-run)",
    )
    apply_cmd.add_argument(
        "--include-system",
        action="store_true",
        help="Include the system/boot volume",
    )
    return parser


def _cmd_icns_to_ico(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    path: Path = args.path
    try:
        if path.is_dir():
            if args.output is None:
                parser.error("Directory conversion requires -o/--output directory")
            written = batch_icns_to_ico(
                path,
                args.output,
                recursive=args.recursive,
            )
            for out in written:
                print(out)
            print(f"Converted {len(written)} icon(s)", file=sys.stderr)
            return 0 if written else 1

        if not path.is_file():
            print(f"Path not found: {path}", file=sys.stderr)
            return 1

        out = icns_to_ico(path, args.output)
        print(out)
        return 0
    except IcnsConversionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _cmd_icons_index(args: argparse.Namespace) -> int:
    try:
        n = index_icons(args.folder, args.db)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    conn = connect(args.db)
    try:
        total = icon_count(conn)
    finally:
        conn.close()
    print(f"Indexed {n} icon file(s); DB has {total} row(s) at {args.db}")
    return 0


def _cmd_disks_list(args: argparse.Namespace) -> int:
    try:
        disks = list_disks()
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps([d.to_dict() for d in disks], indent=2))
        return 0
    if not disks:
        print("No disks found")
        return 0
    for d in disks:
        mounts = ", ".join(d.mounts) if d.mounts else "(unmounted)"
        sys_flag = " [system]" if d.is_system else ""
        cap = f"{d.capacity_bytes / (1000**3):.0f}GB" if d.capacity_bytes else "?"
        print(
            f"{d.id}: {d.model or d.name} vendor={d.vendor or '-'} "
            f"media={d.media} bus={d.bus} size={cap} mounts={mounts}{sys_flag}"
        )
    return 0


def _format_match_line(m) -> str:
    mounts = ", ".join(m.disk.mounts) or m.disk.id
    if m.icon is None:
        return f"{mounts}: (no match) score={m.score} [{', '.join(m.reasons)}]"
    resolved = m.resolved_path or m.icon.path
    return (
        f"{mounts}: score={m.score} {m.icon.stem} -> {resolved} "
        f"[{', '.join(m.reasons)}]"
    )


def _cmd_disks_match(args: argparse.Namespace) -> int:
    if not Path(args.db).is_file():
        print(
            f"error: icon DB not found at {args.db}; run: "
            f"icons index <folder> --db {args.db}",
            file=sys.stderr,
        )
        return 1
    try:
        matches = match_all_disks(
            db_path=args.db,
            include_system=args.include_system,
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        payload = []
        for m in matches:
            payload.append(
                {
                    "disk": m.disk.to_dict(),
                    "score": m.score,
                    "reasons": m.reasons,
                    "icon": str(m.icon.path) if m.icon else None,
                    "resolved_path": str(m.resolved_path) if m.resolved_path else None,
                }
            )
        print(json.dumps(payload, indent=2))
        return 0
    for m in matches:
        print(_format_match_line(m))
    return 0


def _cmd_disks_apply(args: argparse.Namespace) -> int:
    if not Path(args.db).is_file():
        print(
            f"error: icon DB not found at {args.db}; run icons index first",
            file=sys.stderr,
        )
        return 1

    dry_run = not args.yes
    if args.yes and sys.platform == "win32" and not is_windows_admin():
        print(
            "error: applying Windows DriveIcons requires an elevated shell "
            "(Run as administrator)",
            file=sys.stderr,
        )
        return 1

    try:
        matches, applied = apply_matches(
            db_path=args.db,
            include_system=args.include_system,
            dry_run=dry_run,
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    mode = "DRY-RUN" if dry_run else "APPLY"
    print(f"=== matches ({mode}) ===")
    for m in matches:
        print(_format_match_line(m))
    print(f"=== apply results ({mode}) ===")
    if not applied:
        print("(nothing to apply)")
        return 0
    failures = 0
    for a in applied:
        status = "ok" if a.ok else "FAIL"
        if not a.ok:
            failures += 1
        print(f"{status}: {a.mount}: {a.message}")
    if dry_run:
        print(
            "Dry-run only. Re-run with --yes to apply"
            + (" (elevated on Windows)." if sys.platform == "win32" else "."),
            file=sys.stderr,
        )
    return 1 if failures and not dry_run else 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "icns-to-ico":
        return _cmd_icns_to_ico(args, parser)
    if args.command == "icons":
        if args.icons_command == "index":
            return _cmd_icons_index(args)
    if args.command == "disks":
        if args.disks_command == "list":
            return _cmd_disks_list(args)
        if args.disks_command == "match":
            return _cmd_disks_match(args)
        if args.disks_command == "apply":
            return _cmd_disks_apply(args)

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
