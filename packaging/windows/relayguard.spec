# PyInstaller spec: python-free Windows bundle of the RelayGuard local reviewer.
# Build with: .venv/Scripts/python.exe scripts/build_windows.py
#
# Third-party dependencies are frozen normally. The RelayGuard packages themselves are NOT frozen:
# they are shipped as the exact source files under packages/ (same relative layout, same SHA-256),
# so the code that runs is the code that was tested and hashed, and its resource paths resolve.
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve().parents[1]  # noqa: F821 - SPECPATH is injected by PyInstaller
OWN = ("relayguard", "relayguard_ui")


def tree(src: str, pattern: str) -> list[tuple[str, str]]:
    return [(str(p), str(p.parent.relative_to(ROOT))) for p in sorted((ROOT / src).glob(pattern)) if p.is_file()]


datas = [
    *tree("packages/core/relayguard", "*.py"),
    *tree("packages/core/reference/iso4217", "*"),
    *tree("packages/schemas/v0_5", "*.json"),
    *tree("packages/ui/relayguard_ui", "*.py"),
    *tree("packages/ui/relayguard_ui/templates", "*.html"),
    *tree("packages/ui/relayguard_ui/static", "*"),
    *[(str(p), "samples") for p in sorted((ROOT / "eval/release-set-candidates/inputs").glob("*.input.json"))],
]

a = Analysis(  # noqa: F821
    [str(ROOT / "scripts" / "relayguard_desktop.py")],
    pathex=[str(ROOT / "packages" / "core"), str(ROOT / "packages" / "ui")],
    datas=datas,
    hiddenimports=[*collect_submodules("uvicorn"), "multipart", "python_multipart", "anthropic"],
    excludes=["pytest", "mypy", "ruff", "tkinter", "PyInstaller"],
    noarchive=False,
)
a.pure = [entry for entry in a.pure if entry[0].split(".")[0] not in OWN]
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="RelayGuard",
    console=True,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="RelayGuard", upx=False)  # noqa: F821
