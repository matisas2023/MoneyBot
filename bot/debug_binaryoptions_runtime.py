from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path


def _print_module_info() -> tuple[Path | None, Path | None]:
    try:
        from BinaryOptionsToolsV2.pocketoption import asynchronous as po_async  # type: ignore
        from BinaryOptionsToolsV2.pocketoption import synchronous as po_sync  # type: ignore
    except ImportError as exc:
        print(f"ImportError: {exc}")
        return None, None

    print("asynchronous.__file__:", getattr(po_async, "__file__", None))
    print("synchronous.__file__:", getattr(po_sync, "__file__", None))

    async_cls = getattr(po_async, "PocketOptionAsync", None)
    if async_cls is not None:
        print("PocketOptionAsync.__module__:", getattr(async_cls, "__module__", None))
        init_fn = getattr(async_cls, "__init__", None)
        code = getattr(init_fn, "__code__", None)
        print("PocketOptionAsync.__init__.__code__.co_filename:", getattr(code, "co_filename", None))

    return (
        Path(getattr(po_async, "__file__", "")) if getattr(po_async, "__file__", "") else None,
        Path(getattr(po_sync, "__file__", "")) if getattr(po_sync, "__file__", "") else None,
    )


def _scan_warn_usage(package_root: Path) -> None:
    print("\n.warn( usage scan:")
    for file in package_root.rglob("*.py"):
        try:
            text = file.read_text(encoding="utf-8")
        except OSError:
            continue
        for idx, line in enumerate(text.splitlines(), 1):
            if ".warn(" in line:
                print(f"{file}:{idx}: {line.strip()}")


def _patch_warn_to_warning(package_root: Path) -> None:
    for file in package_root.rglob("*.py"):
        try:
            src = file.read_text(encoding="utf-8")
        except OSError:
            continue
        patched = src.replace(".warn(", ".warning(")
        if patched != src:
            file.write_text(patched, encoding="utf-8")
            print("patched:", file)


def _remove_stale_pyc(package_root: Path) -> None:
    for pycache in package_root.rglob("__pycache__"):
        shutil.rmtree(pycache, ignore_errors=True)
        print("removed:", pycache)

    for pyc in package_root.rglob("*.pyc"):
        try:
            pyc.unlink()
            print("removed:", pyc)
        except OSError:
            pass


def _list_all_copies() -> None:
    print("\nPotential BinaryOptionsToolsV2 locations:")
    seen: set[str] = set()

    for base in [Path.cwd(), Path(sys.prefix), Path(sys.base_prefix)]:
        for path in base.rglob("BinaryOptionsToolsV2"):
            candidate = str(path.resolve())
            if candidate not in seen:
                seen.add(candidate)
                print(candidate)


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose BinaryOptionsToolsV2 runtime path and warn mismatch")
    parser.add_argument("--patch", action="store_true", help="Replace .warn( with .warning( in installed package")
    parser.add_argument("--clean-pyc", action="store_true", help="Remove __pycache__ and .pyc in installed package")
    args = parser.parse_args()

    async_file, sync_file = _print_module_info()
    _list_all_copies()

    package_root: Path | None = None
    if async_file is not None:
        package_root = async_file.parents[1]
        _scan_warn_usage(package_root)

    if args.patch and package_root is not None:
        _patch_warn_to_warning(package_root)

    if args.clean_pyc and package_root is not None:
        _remove_stale_pyc(package_root)


if __name__ == "__main__":
    main()
