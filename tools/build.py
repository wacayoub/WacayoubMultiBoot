#!/usr/bin/env python3
"""Build packages/enigma2-plugin-extensions-wmultiboot_<ver>_all.ipk from src/WMultiBoot."""
import os
import re
import shutil
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
root = os.path.dirname(here)
sys.path.insert(0, here)
from ipk import build_ipk  # noqa: E402

src = os.path.join(root, "src", "WMultiBoot")
ver = re.search(r'VERSION = "([^"]+)"', open(os.path.join(src, "core.py"), encoding="utf-8").read()).group(1)
pkg = "enigma2-plugin-extensions-wmultiboot"
stage = tempfile.mkdtemp()
dest = os.path.join(stage, "usr/lib/enigma2/python/Plugins/Extensions/WMultiBoot")
shutil.copytree(src, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
control = {
    "Package": pkg,
    "Version": ver,
    "Description": "Wacayoub MultiBoot - gestion multiboot (slots, demarrage, installation, sauvegarde)",
    "Section": "extra",
    "Priority": "optional",
    "Maintainer": "wacayoub",
    "License": "GPL-2.0-only",
    "Architecture": "all",
    "Depends": "enigma2",
    "Source": "https://github.com/wacayoub",
}
scripts = {
    "postinst": "#!/bin/sh\necho 'Wacayoub MultiBoot installe. Redemarrez Enigma2.'\nexit 0\n",
    "postrm": "#!/bin/sh\n# only clean up on real removal (opkg runs the OLD postrm on upgrade)\n"
              "case \"$1\" in remove|purge) rm -rf /usr/lib/enigma2/python/Plugins/Extensions/WMultiBoot ;; esac\nexit 0\n",
}
os.makedirs(os.path.join(root, "packages"), exist_ok=True)
out = os.path.join(root, "packages", "%s_%s_all.ipk" % (pkg, ver))
build_ipk(out, control, stage, scripts)
shutil.rmtree(stage)
print(out, os.path.getsize(out), "bytes")
