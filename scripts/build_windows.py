#!/usr/bin/env python3
"""Build the python-free Windows bundle: dist/RelayGuard/ and dist/RelayGuard-<version>-win64.zip.

Steps (fail closed - any mismatch aborts without producing the zip):
1. PyInstaller with packaging/windows/relayguard.spec.
2. Every shipped RelayGuard source/schema/template file must be byte-identical to the checkout.
3. Smoke test: start RelayGuard.exe on a spare port, log in, open a synthetic sample, stop it.
4. Write SHA256SUMS.txt and the zip (bundle + README-ja.txt).

Usage: .venv/Scripts/python.exe scripts/build_windows.py [--version 0.1.2] [--skip-smoke]
"""

from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "packaging" / "windows" / "relayguard.spec"
README = ROOT / "packaging" / "windows" / "README-ja.txt"
DIST = ROOT / "dist"
WORK = ROOT / "build" / "pyinstaller"
BUNDLE = DIST / "RelayGuard"
SMOKE_PORT = 8791
SMOKE_TOKEN = "smoke-test-token-000000"  # noqa: S105 - throwaway token for a local smoke run
SHIPPED = (
    ("packages/core/relayguard", "*.py"),
    ("packages/core/reference/iso4217", "*"),
    ("packages/schemas/v0_5", "*.json"),
    ("packages/ui/relayguard_ui", "*.py"),
    ("packages/ui/relayguard_ui/templates", "*.html"),
    ("packages/ui/relayguard_ui/static", "*"),
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def discard(directory: Path) -> None:
    """Remove a previous build tree. A virus scanner briefly holds files open on Windows, so the
    directory is renamed out of the way first - a rename succeeds where rmdir returns WinError 5."""
    # Sweep what earlier builds left behind. An emptied tree can survive the rmtree below, and
    # without this every build that hit a held file adds one more dead directory next to dist/.
    for stale in sorted(directory.parent.glob(f"{directory.name}.old-*")):
        shutil.rmtree(stale, ignore_errors=True)
    if not directory.exists():
        return
    doomed = directory.with_name(f"{directory.name}.old-{os.getpid()}")
    try:
        directory.rename(doomed)
    except OSError:
        doomed = directory
    for _ in range(3):
        shutil.rmtree(doomed, ignore_errors=True)
        if not any(path.is_file() for path in doomed.rglob("*")):
            shutil.rmtree(doomed, ignore_errors=True)  # the files are gone; take the empty tree too if Windows lets go
            return
        time.sleep(0.5)
    raise SystemExit(f"前回のビルド結果を削除できません: {doomed}（エクスプローラやウイルス対策が掴んでいる可能性があります）")


def internal_dir() -> Path:
    return BUNDLE / "_internal"


def verify_shipped_sources() -> int:
    count = 0
    for directory, pattern in SHIPPED:
        for source in sorted((ROOT / directory).glob(pattern)):
            if not source.is_file():
                continue
            shipped = internal_dir() / source.relative_to(ROOT)
            if not shipped.is_file() or sha256(shipped) != sha256(source):
                raise SystemExit(f"bundle mismatch: {source.relative_to(ROOT)}")
            count += 1
    toc = (WORK / "relayguard" / "PYZ-00.toc").read_text(encoding="utf-8")
    if re.search(r"'relayguard(_ui)?[.']", toc):
        raise SystemExit("RelayGuard modules must not be frozen into the PYZ (shipped source would not be what runs)")
    return count


def smoke_test() -> None:
    env = dict(os.environ, RELAYGUARD_NO_BROWSER="1", ANTHROPIC_API_KEY="")
    command = [str(BUNDLE / "RelayGuard.exe"), "--port", str(SMOKE_PORT), "--token", SMOKE_TOKEN, "--operator", "smoke"]
    process = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    base = f"http://127.0.0.1:{SMOKE_PORT}"
    try:
        for _ in range(60):
            try:
                with opener.open(f"{base}/login?token={SMOKE_TOKEN}", timeout=2) as response:
                    index = response.read().decode("utf-8")
                break
            except urllib.error.URLError, ConnectionError:
                if process.poll() is not None:
                    raise SystemExit("RelayGuard.exe exited during start:\n" + process.stdout.read().decode(errors="replace")) from None  # type: ignore[union-attr]
                time.sleep(0.5)
        else:
            raise SystemExit("RelayGuard.exe did not answer within 30 s")
        if "RG-EVAL-011.input.json" not in index:
            raise SystemExit("smoke: bundled samples are not listed")
        print("smoke: login + sample list OK")
    finally:
        process.terminate()
        process.wait(timeout=10)


def write_zip(version: str) -> Path:
    sums = BUNDLE / "SHA256SUMS.txt"
    lines = [f"{sha256(p)}  {p.relative_to(BUNDLE).as_posix()}" for p in sorted(BUNDLE.rglob("*")) if p.is_file() and p != sums]
    sums.write_text("\n".join(lines) + "\n", encoding="utf-8")
    shutil.copyfile(README, BUNDLE / README.name)
    target = DIST / f"RelayGuard-{version}-win64.zip"
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(BUNDLE.rglob("*")):
            if path.is_file():
                archive.write(path, Path("RelayGuard") / path.relative_to(BUNDLE))
    return target


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="0.1.2")
    parser.add_argument("--skip-smoke", action="store_true")
    args = parser.parse_args(argv)
    for stale in (DIST, WORK):
        discard(stale)
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--distpath", str(DIST), "--workpath", str(WORK), str(SPEC)],
        check=True,
    )
    print(f"verified {verify_shipped_sources()} shipped RelayGuard files are byte-identical to the checkout")
    if not args.skip_smoke:
        smoke_test()
    target = write_zip(args.version)
    print(f"{target} ({target.stat().st_size / 1_048_576:.1f} MiB) sha256={sha256(target)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
