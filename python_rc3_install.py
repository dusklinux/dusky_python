#!/usr/bin/python3
"""Idempotent installer for dusky-python (CPython 3.15.0rc3, generic x86-64).

Arch Linux only. Manages ONLY the /usr/local dusky build; the system
interpreter at /usr/bin/python3 is never touched, so a working python
always exists. Safe to re-run: exits 0 when the wanted version is
already installed.

Usage:
    python3 python_rc3_install.py [check]
    sudo python3 python_rc3_install.py install [--reinstall] [--no-default]
    sudo python3 python_rc3_install.py uninstall

By default install also shadows /usr/local/bin/python{,3} -> python3.15,
so PATH `python --version` reports the new build (/usr/local/bin precedes
/usr/bin on Arch). /usr/bin/python* itself is never modified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

VERSION = "3.15.0rc3"
ARCH_TAG = "x86_64-generic"  # -march=x86-64 -mtune=generic: any 64-bit CPU
REPO = "dusklinux/dusky_python"
TAG = f"v{VERSION}"
ASSET = f"dusky-python-{VERSION}-{ARCH_TAG}.tar.gz"
PREFIX = Path("/usr/local")
MARKER = PREFIX / "lib" / "dusky-python.json"
SYSTEM_PYTHON = Path("/usr/bin/python3")
WANT_BIN = PREFIX / "bin" / "python3.15"
# PATH-shadow: /usr/local/bin precedes /usr/bin on Arch, so these two
# symlinks make interactive `python`/`python3` resolve to 3.15 while the
# pacman-owned /usr/bin/python* stays 3.14 for system tools.
SHADOW_LINKS = {"python": "python3.15", "python3": "python3.15"}
STAGING_BYTES_NEEDED = 1_500_000_000  # PGO-built tree + tarball headroom

log = logging.getLogger("dusky-python")


def asset_url(tag: str = TAG, repo: str = REPO) -> str:
    return f"https://github.com/{repo}/releases/download/{tag}/{ASSET}"


def die(msg: str, code: int = 1) -> "NoReturn":  # noqa: F821
    log.error(msg)
    raise SystemExit(code)


def is_arch() -> bool:
    try:
        data = Path("/etc/os-release").read_text()
    except OSError:
        return False
    fields = dict(
        line.split("=", 1) for line in data.splitlines() if "=" in line
    )
    ident = fields.get("ID", "").strip('"')
    like = fields.get("ID_LIKE", "").strip('"')
    return ident == "arch" or "arch" in like.split()


def system_python_ok() -> bool:
    """The inviolable guarantee: distro python must exist and run."""
    if not SYSTEM_PYTHON.exists():
        return False
    try:
        r = subprocess.run(
            [str(SYSTEM_PYTHON), "--version"],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0


@dataclass
class State:
    marker: dict | None
    bin_version: str | None

    @property
    def installed(self) -> bool:
        return (
            self.marker is not None
            and self.marker.get("version") == VERSION
            and self.marker.get("arch") == ARCH_TAG
            and self.bin_version == VERSION
        )


def read_marker() -> dict | None:
    try:
        return json.loads(MARKER.read_text())
    except (OSError, ValueError):
        return None


def probe_bin() -> str | None:
    if not WANT_BIN.exists():
        return None
    try:
        r = subprocess.run(
            [str(WANT_BIN), "--version"],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    parts = (r.stdout or r.stderr).strip().split()
    return parts[1] if len(parts) >= 2 else None


def current_state() -> State:
    return State(marker=read_marker(), bin_version=probe_bin())


def ensure_root() -> None:
    if os.geteuid() == 0:
        return
    log.info("Need root for %s; re-executing via sudo...", PREFIX)
    os.execvp("sudo", ["sudo", sys.executable, *sys.argv])


def check_staging_space(path: Path) -> None:
    free = shutil.disk_usage(path).free
    if free < STAGING_BYTES_NEEDED:
        die(
            f"Need {STAGING_BYTES_NEEDED // 1_000_000}MB free under {path} "
            f"(have {free // 1_000_000}MB)."
        )


def download(url: str, dest: Path) -> None:
    log.info("Downloading %s", url)
    req = urllib.request.Request(url, headers={"User-Agent": "dusky-python-installer"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp, dest.open("wb") as fh:
            total = int(resp.headers.get("Content-Length", 0) or 0)
            done = 0
            while chunk := resp.read(1 << 20):
                fh.write(chunk)
                done += len(chunk)
                if total:
                    log.info("  %d/%d MB", done >> 20, total >> 20)
    except OSError as exc:
        die(f"Download failed: {exc}")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify(path: Path, expected: str) -> None:
    log.info("Verifying sha256...")
    actual = sha256_of(path)
    if actual != expected.lower():
        die(f"Checksum mismatch:\n  expected {expected}\n  actual   {actual}")


def fetch_expected_sha256(url: str) -> str:
    log.info("Fetching %s.sha256", url)
    req = urllib.request.Request(
        url + ".sha256", headers={"User-Agent": "dusky-python-installer"}
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read().decode().split()[0].strip()
    except OSError as exc:
        die(f"Could not fetch checksum file: {exc}")


def manifest(staging_usr_local: Path) -> list[str]:
    """All installed paths, relative to PREFIX, longest-first for removal."""
    rels = []
    for root, _dirs, files in os.walk(staging_usr_local):
        for name in files:
            full = Path(root) / name
            rels.append(str(full.relative_to(staging_usr_local)))
        # symlinks to dirs appear in dirs; record them too
        for name in _dirs:
            full = Path(root) / name
            if full.is_symlink():
                rels.append(str(full.relative_to(staging_usr_local)))
    # directories themselves, deepest first, for rmdir cleanup
    dirs = set()
    for rel in rels:
        parent = Path(rel).parent
        while str(parent) != ".":
            dirs.add(str(parent))
            parent = parent.parent
    return sorted(rels, reverse=True) + sorted(dirs, reverse=True)


def cmd_check(_args: argparse.Namespace) -> int:
    state = current_state()
    print(f"system_python_ok: {system_python_ok()} ({SYSTEM_PYTHON})")
    print(f"marker: {state.marker or 'absent'}")
    print(f"python3.15_version: {state.bin_version or 'absent'}")
    which_python = shutil.which("python")
    print(f"PATH python: {which_python or 'not found'}")
    if which_python:
        try:
            r = subprocess.run(
                ["python", "--version"],
                capture_output=True, text=True, timeout=30,
            )
            print(f"PATH python version: {(r.stdout or r.stderr).strip()}")
        except (OSError, subprocess.TimeoutExpired):
            print("PATH python version: failed to run")
    print(f"wanted: {VERSION} ({ARCH_TAG})")
    print(f"installed: {state.installed}")
    return 0


def apply_shadow() -> dict:
    """Point /usr/local/bin/python{,3} at python3.15.

    Returns {"links": [...], "backed_up": {name: old_target}} for the marker.
    Existing real files are never overwritten; foreign symlinks are replaced
    but their old target is recorded so uninstall can restore it.
    """
    state: dict = {"links": [], "backed_up": {}}
    bindir = PREFIX / "bin"
    for name, target in SHADOW_LINKS.items():
        link = bindir / name
        if link.is_symlink():
            if os.readlink(link) == target:
                state["links"].append(name)
                continue
            state["backed_up"][name] = os.readlink(link)
            link.unlink()
        elif link.exists():
            die(f"Refusing: {link} is a real file, not a symlink. Move it aside first.")
        link.symlink_to(target)
        state["links"].append(name)
        log.info("shadow: %s -> %s", link, target)
    return state


def remove_shadow(marker: dict | None) -> None:
    links = list(SHADOW_LINKS)
    backed_up = (marker or {}).get("shadow", {}).get("backed_up", {})
    for name in links:
        link = PREFIX / "bin" / name
        if not link.is_symlink() or os.readlink(link) != SHADOW_LINKS[name]:
            continue  # not ours; leave alone
        link.unlink()
        log.info("removed shadow %s", link)
        if name in backed_up:
            link.symlink_to(backed_up[name])
            log.info("restored %s -> %s", link, backed_up[name])


def cmd_install(args: argparse.Namespace) -> int:
    if not is_arch():
        die("Refusing: this installer is Arch Linux only.")
    if not system_python_ok():
        die(f"Refusing: system python {SYSTEM_PYTHON} is broken or missing.")
    state = current_state()
    if state.installed and not args.reinstall:
        log.info("Already installed: %s (%s). Nothing to do.", VERSION, ARCH_TAG)
        return 0
    if state.marker or state.bin_version:
        log.info("Removing previous /usr/local install before reinstall...")
        cmd_uninstall(args)

    ensure_root()
    if not system_python_ok():  # re-check after elevation
        die(f"Refusing: system python {SYSTEM_PYTHON} is broken or missing.")

    tmp = Path(tempfile.mkdtemp(prefix="dusky-python-"))
    try:
        check_staging_space(tmp)
        url = asset_url(args.tag, args.repo)
        tarball = tmp / ASSET
        download(url, tarball)
        expected = args.checksum or fetch_expected_sha256(url)
        verify(tarball, expected)

        stage = tmp / "stage"
        stage.mkdir()
        log.info("Extracting...")
        with tarfile.open(tarball, "r:gz") as tar:
            tar.extractall(stage, filter="data")  # py3.12+: no tar-slip
        src = stage / "usr" / "local"
        if not (src / "bin" / "python3.15").exists():
            die(f"Bad tarball layout: {src}/bin/python3.15 missing.")

        log.info("Copying into %s...", PREFIX)
        files = manifest(src)
        for rel in files:
            s, d = src / rel, PREFIX / rel
            if s.is_symlink() or s.is_file():
                d.parent.mkdir(parents=True, exist_ok=True)
                if d.is_symlink() or d.exists():
                    d.unlink()
                if s.is_symlink():
                    d.symlink_to(os.readlink(s))
                else:
                    shutil.copy2(s, d)
            elif s.is_dir():
                d.mkdir(parents=True, exist_ok=True)

        if args.no_default:
            shadow_state = {"links": [], "backed_up": {}}
        else:
            shadow_state = apply_shadow()
        MARKER.write_text(json.dumps({
            "version": VERSION, "arch": ARCH_TAG, "repo": args.repo,
            "tag": args.tag, "asset": ASSET, "asset_sha256": sha256_of(tarball),
            "files": files, "shadow": shadow_state,
        }, indent=2))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # Post-install verification; system python must still work.
    if probe_bin() != VERSION:
        die("Install verification failed: /usr/local/bin/python3.15 wrong version.")
    if not args.no_default:
        r = subprocess.run(
            ["python", "--version"],
            capture_output=True, text=True, timeout=30,
        )
        if VERSION not in (r.stdout or r.stderr):
            die("Install verification failed: PATH `python` is not the new build. "
                "Is /usr/local/bin before /usr/bin in PATH?")
    smoke = subprocess.run(
        [str(WANT_BIN), "-c", "import ssl,sqlite3,lzma; print('smoke ok')"],
        capture_output=True, text=True, timeout=60,
    )
    if smoke.returncode != 0:
        die(f"Install verification failed (stdlib smoke): {smoke.stderr[:500]}")
    if not system_python_ok():
        die("Install verification failed: system python broke (should be impossible).")
    log.info("Installed %s (%s). System python untouched.", VERSION, ARCH_TAG)
    return 0


def cmd_uninstall(_args: argparse.Namespace) -> int:
    """Remove ONLY the dusky /usr/local install. /usr/bin is never touched."""
    ensure_root()
    marker = read_marker()
    remove_shadow(marker)  # restores any pre-existing foreign symlinks
    targets: list[Path] = []
    if marker:
        for rel in marker.get("files", []):
            p = PREFIX / rel
            # Hard guard: everything must stay under /usr/local.
            if PREFIX not in p.resolve().parents and p.resolve() != PREFIX:
                die(f"Refusing to remove path escaping {PREFIX}: {p}")
            targets.append(p)
    else:
        log.info("No marker; removing known %s paths only.", VERSION)
        targets = [
            PREFIX / "bin" / "python3.15",
            PREFIX / "bin" / "python3.15-config",
            PREFIX / "bin" / "idle3.15",
            PREFIX / "bin" / "pydoc3.15",
            PREFIX / "lib" / "python3.15",
            PREFIX / "lib" / "libpython3.15.a",
            PREFIX / "lib" / "pkgconfig" / "python-3.15.pc",
            PREFIX / "lib" / "pkgconfig" / "python-3.15-embed.pc",
            PREFIX / "include" / "python3.15",
            PREFIX / "share" / "man" / "man1" / "python3.15.1",
        ]
    for p in targets:
        try:
            if p.is_symlink() or p.is_file():
                p.unlink()
                log.info("removed %s", p)
            elif p.is_dir():
                try:
                    p.rmdir()  # only if already empty
                    log.info("removed %s", p)
                except OSError:
                    # Directory with untracked content: remove the known
                    # 3.15 tree explicitly, never blindly recursive elsewhere.
                    if p == PREFIX / "lib" / "python3.15":
                        shutil.rmtree(p)
                        log.info("removed tree %s", p)
        except OSError as exc:
            log.warning("Could not remove %s: %s", p, exc)
    try:
        MARKER.unlink()
    except OSError:
        pass
    # Prune the one dir we own if now empty; never PREFIX itself.
    for owned in (PREFIX / "lib" / "python3.15", PREFIX / "include" / "python3.15"):
        if owned.is_dir():
            shutil.rmtree(owned, ignore_errors=True)
    if not system_python_ok():
        die("System python broken after uninstall (should be impossible).")
    log.info("Uninstalled dusky-python. System python untouched.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Idempotent dusky-python installer (Arch only, /usr/local only).",
    )
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--tag", default=TAG)
    ap.add_argument("--checksum", default="",
                    help="Expected sha256 of the tarball (else fetched from <url>.sha256).")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="Report state; never modifies anything.")
    ins = sub.add_parser("install", help="Install (no-op if already installed).")
    ins.add_argument("--reinstall", action="store_true",
                     help="Remove and reinstall even if already installed.")
    ins.add_argument("--no-default", action="store_true",
                     help="Don't shadow /usr/local/bin/python{,3}; "
                          "PATH `python` stays on system 3.14.")
    sub.add_parser("uninstall", help="Remove the dusky /usr/local install only.")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )
    if args.cmd == "check":
        return cmd_check(args)
    if args.cmd == "install":
        return cmd_install(args)
    if args.cmd == "uninstall":
        return cmd_uninstall(args)
    raise AssertionError("unreachable")


if __name__ == "__main__":
    sys.exit(main())
