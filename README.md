# dusky_python

Portable CPython builds for Arch Linux (generic `x86-64`, runs on any 64-bit CPU).

## Install (Arch only)

The installer manages **only** `/usr/local`. System `/usr/bin/python*` is never touched.

```sh
curl -O https://raw.githubusercontent.com/dusklinux/dusky_python/main/python_rc3_install.py
python3 python_rc3_install.py check
sudo python3 python_rc3_install.py install
python --version   # 3.15.0rc3 (via /usr/local/bin shadow)
```

Idempotent: re-running `install` is a no-op when the wanted version is present.
`--reinstall` forces, `uninstall` (or `--undo`) removes only the dusky tree,
`--no-default` skips the `python`/`python3` PATH shadow.

When official 3.15 arrives via pacman: `sudo python3 python_rc3_install.py --undo`
removes every trace, then `sudo pacman -S python` takes over.

## Release assets

Binaries ship as GitHub Release assets (too large for git):

- `dusky-python-3.15.0rc3-x86_64-generic.tar.gz`
- `dusky-python-3.15.0rc3-x86_64-generic.tar.gz.sha256`

Built with stock generic flags (`-march=x86-64 -mtune=generic -O2`,
`--enable-optimizations --with-lto`, `--prefix=/usr/local`).
