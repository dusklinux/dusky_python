# Dusky temporary Python runtime

This repository hosts the temporary generic x86-64 CPython 3.15.0rc3 runtime for Dusky while Arch's system Python is older than 3.15. It does not replace `/usr/bin/python3`.

The `v3.15.0rc3` release contains `dusky-python-3.15.0rc3-x86_64-generic-desktop.tar.gz` and its SHA-256 checksum. The runtime includes PyGObject 3.58.0, pycairo 1.29.2, Rich 15.0.0, Textual 8.2.8, Pillow 12.3.0, and pyudev 0.24.4. Native GTK bindings were rebuilt with `-march=x86-64 -mtune=generic`; the CPython build uses those generic flags too. GTK, GLib, Cairo, and the other native libraries must already be installed.

Run `python_rc3_install.py check` to inspect the installation; run `sudo /usr/bin/python3 python_rc3_install.py install` to install or verify it. `--tarball PATH` accepts the archive offline; place its `.sha256` file alongside it. Run `sudo /usr/bin/python3 python_rc3_install.py --undo` after migrating to the distribution Python. The installer preserves an already selected compatible Python 3.15 or newer rather than replacing it with this prerelease.

The payload was tested on an Arch x86-64 VM with its Python 3.14 interpreter using an isolated installation prefix, including standard-library and desktop dependency probes, updater startup, and undo. The final ISO package versions still need their own verification.
