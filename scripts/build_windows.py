#!/usr/bin/env python3
"""Cross-build a portable Windows x64 application on Linux using official CPython files."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from income_tracker import VERSION


def download_locked(item: dict, cache: Path) -> Path:
    target = cache / Path(item["url"]).name
    cache.mkdir(parents=True, exist_ok=True)
    if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != item["sha256"]:
        partial = target.with_suffix(target.suffix + ".part")
        with urllib.request.urlopen(item["url"], timeout=60) as response, partial.open("wb") as output:
            shutil.copyfileobj(response, output)
        if hashlib.sha256(partial.read_bytes()).hexdigest() != item["sha256"]:
            partial.unlink()
            raise RuntimeError("The upstream download did not match its locked SHA-256: " + target.name)
        os.replace(partial, target)
    return target


def extract_zip(source: Path, destination: Path) -> None:
    with zipfile.ZipFile(source) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("The Python runtime archive is damaged.")
        for item in archive.infolist():
            resolved = (destination / item.filename).resolve()
            if not resolved.is_relative_to(destination.resolve()):
                raise RuntimeError("An archive member escapes the output folder.")
        archive.extractall(destination)


def validate_bundle(folder: Path) -> None:
    required = ("LedgerDesk.exe", "app/start.pyw", "app/income_tracker.py", "runtime/pythonw.exe",
                "runtime/python.exe", "runtime/python314.dll", "runtime/DLLs/_tkinter.pyd",
                "runtime/DLLs/_sqlite3.pyd", "runtime/DLLs/tcl90.dll", "runtime/DLLs/tcl9tk90.dll",
                "runtime/DLLs/libtommath.dll", "runtime/DLLs/zlib1.dll",
                "runtime/Lib/tkinter/__init__.py", "runtime/tcl/libtcl9.0.4.zip", "runtime/tcl/libtk9.0.4.zip")
    for name in required:
        if not (folder / name).is_file():
            raise RuntimeError("Missing application component: " + name)
    for name in ("LedgerDesk.exe", "runtime/pythonw.exe", "runtime/python.exe", "runtime/DLLs/_tkinter.pyd"):
        binary = (folder / name).read_bytes()
        if binary[:2] != b"MZ":
            raise RuntimeError("This is not a Windows executable: " + name)
        offset = struct.unpack_from("<I", binary, 0x3C)[0]
        if binary[offset:offset + 4] != b"PE\0\0" or struct.unpack_from("<H", binary, offset + 4)[0] != 0x8664:
            raise RuntimeError("This binary is not Windows x64: " + name)
    if list(folder.rglob("*.sqlite3")) or list(folder.rglob("*.db")):
        raise RuntimeError("A release must not contain personal financial data.")


def prepare_output(output: Path) -> Path:
    bundle = (Path(output) / "LedgerDesk").resolve()
    if bundle == ROOT or ROOT.is_relative_to(bundle):
        raise RuntimeError("The build output would overwrite the source project. Choose a separate output directory.")
    marker = bundle / ".ledgerdesk-build"
    if bundle.exists():
        owned = marker.is_file() and marker.read_text(encoding="utf-8") == "LedgerDesk Windows build output\n"
        # Accept a completed output from the first packaging revision as well.
        info = bundle / "BUILD_INFO.json"
        if not owned and info.is_file():
            try:
                owned = json.loads(info.read_text())["format"] == "portable folder"
            except (ValueError, KeyError, OSError):
                pass
        if not owned:
            raise RuntimeError("Refusing to replace an existing folder that is not a LedgerDesk build output: " + str(bundle))
        shutil.rmtree(bundle)
    (bundle / "app").mkdir(parents=True)
    marker.write_text("LedgerDesk Windows build output\n", encoding="utf-8")
    return bundle


def build(args) -> Path:
    lock = json.loads((ROOT / "packaging/windows/runtime.lock.json").read_text())
    runtime_zip = download_locked(lock["runtime"], args.cache)
    tkinter_msi = download_locked(lock["tkinter"], args.cache)
    args.output.mkdir(parents=True, exist_ok=True)
    bundle = prepare_output(args.output)
    runtime = bundle / "runtime"
    runtime.mkdir()
    print("Extracting the verified CPython runtime...", flush=True)
    extract_zip(runtime_zip, runtime)
    with tempfile.TemporaryDirectory(prefix="ledgerdesk-build-") as temporary:
        temporary = Path(temporary)
        tkinter = temporary / "tkinter"
        tkinter.mkdir()
        subprocess.run([args.msiextract, "-C", str(tkinter), str(tkinter_msi)], check=True, stdout=subprocess.DEVNULL)
        # The official install-manager ZIP omits Tcl's data ZIPs; the matching MSI supplies them.
        shutil.copytree(tkinter / "tcl", runtime / "tcl", dirs_exist_ok=True)
        shutil.copytree(tkinter / "DLLs", runtime / "DLLs", dirs_exist_ok=True)
        shutil.copytree(tkinter / "Lib/tkinter", runtime / "Lib/tkinter", dirs_exist_ok=True)
        resources = temporary / "launcher.o"
        subprocess.run([args.windres, "-I", str(ROOT / "packaging/windows"),
                        str(ROOT / "packaging/windows/launcher.rc"), str(resources)], check=True)
        print("Compiling LedgerDesk.exe...", flush=True)
        subprocess.run([args.cc, "-Os", "-municode", "-mwindows", "-static", "-static-libgcc", "-s",
                        "-Wall", "-Wextra", "-Werror", "-Wl,--dynamicbase,--nxcompat,--high-entropy-va",
                        str(ROOT / "packaging/windows/launcher.c"), str(resources), "-luser32",
                        "-o", str(bundle / "LedgerDesk.exe")], check=True)
    shutil.copy2(ROOT / "income_tracker.py", bundle / "app/income_tracker.py")
    shutil.copy2(ROOT / "packaging/windows/start.pyw", bundle / "app/start.pyw")
    for document in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(ROOT / document, bundle / document)
    shutil.copy2(ROOT / "docs/USER_GUIDE.md", bundle / "USER_GUIDE.md")
    licenses = runtime / "licenses"
    licenses.mkdir(exist_ok=True)
    for archive_name, target_name in (("libtcl9.0.4.zip", "Tcl-license.terms"),
                                      ("libtk9.0.4.zip", "Tk-license.terms")):
        with zipfile.ZipFile(runtime / "tcl" / archive_name) as archive:
            source_name = next(name for name in archive.namelist() if name.endswith("/license.terms"))
            (licenses / target_name).write_bytes(archive.read(source_name))
    compiler = Path(shutil.which(args.cc) or args.cc).resolve()
    toolchain_license = compiler.parents[1] / "share/doc/mingw-w64-common/copyright"
    if toolchain_license.is_file():
        shutil.copy2(toolchain_license, licenses / "MinGW-w64-COPYING")
    (bundle / "START_HERE.txt").write_text(
        f"LedgerDesk {VERSION} - Windows x64\n\n"
        "1. Extract the entire ZIP to a normal folder.\n"
        "2. Double-click LedgerDesk.exe. No Python installation is required.\n"
        "3. Keep app and runtime beside the EXE when moving or sharing this folder.\n\n"
        "Your financial records are saved separately in %LOCALAPPDATA%\\LedgerDesk.\n"
        "Use Back up data to make a full copy of your records.\n"
        "See USER_GUIDE.md for the complete guide.\n", encoding="utf-8")
    (bundle / "BUILD_INFO.json").write_text(json.dumps({"app_version": VERSION, "runtime": lock,
                                                        "target": "Windows 10/11 x64", "format": "portable folder"}, indent=2) + "\n")
    validate_bundle(bundle)
    archive_path = args.output / f"LedgerDesk-v{VERSION}-Windows-x64.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for file in sorted(bundle.rglob("*")):
            if file.is_file():
                archive.write(file, Path("LedgerDesk") / file.relative_to(bundle))
    with zipfile.ZipFile(archive_path) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("The release archive failed its integrity check.")
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    archive_path.with_suffix(".zip.sha256").write_text(f"{digest}  {archive_path.name}\n", encoding="ascii")
    print(f"Ready: {archive_path} ({archive_path.stat().st_size:,} bytes)", flush=True)
    return archive_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=ROOT / ".build-cache")
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument("--cc", default="x86_64-w64-mingw32-gcc")
    parser.add_argument("--windres", default="x86_64-w64-mingw32-windres")
    parser.add_argument("--msiextract", default="msiextract")
    args = parser.parse_args()
    args.cache = args.cache.expanduser().resolve()
    args.output = args.output.expanduser().resolve()
    build(args)


if __name__ == "__main__":
    main()
