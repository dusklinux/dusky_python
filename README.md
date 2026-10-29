# Dusky temporary Python runtime

This repository hosts a generic x86-64 CPython 3.15.2 runtime for Dusky while Arch's system Python is older than 3.15. It does not replace `/usr/bin/python3`.

The `v3.15.2` release contains `dusky-python-3.15.2-x86_64-generic-desktop.tar.gz` and its SHA-256 checksum. The runtime includes PyGObject 3.58.0, pycairo 1.29.2, Rich 15.0.0, Textual 8.2.8, Pillow 12.3.0, and pyudev 0.24.4. Native GTK bindings and CPython were built with `-march=x86-64 -mtune=generic`; Pillow is the upstream manylinux x86-64 wheel. GTK, GLib, Cairo, and other native libraries must already be installed.

The interpreter was built from the official Python 3.15.2 source archive, SHA-256 `8b5536d280142ecf6cdfe15d12a21ba1c65e300bbf7b28a8d0cdb849575797de`, with PGO and LTO. Python's standard test suite is omitted from the binary archive. The installer also accepts a managed 3.15.0rc3 installation from the previous release and upgrades it without discarding unrecorded files.

Run `python_rc3_install.py check` to inspect the installation; run `sudo /usr/bin/python3 python_rc3_install.py install` to install or verify it. `--tarball PATH` accepts the archive offline; place its `.sha256` file alongside it. Run `sudo /usr/bin/python3 python_rc3_install.py --undo` after migrating to the distribution Python. A normal install retains an already selected, unmanaged compatible Python 3.15 or newer.

The payload was tested on an Arch x86-64 VM with its Python 3.14 interpreter using an isolated installation prefix, including standard-library and desktop dependency probes, updater startup, upgrade from RC3, and undo. The final ISO package versions still need their own verification.
