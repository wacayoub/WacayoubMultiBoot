#!/usr/bin/env python3
"""Create/remove the GUI test disk: python3 gui_disk.py core.py up|down"""
import importlib.util, sys, os
spec = importlib.util.spec_from_file_location("wmbtests", "/tmp/wmb_tests.py")
sys.argv = [sys.argv[0], sys.argv[1]] + sys.argv[2:]
t = importlib.util.module_from_spec(spec); spec.loader.exec_module(t)
if sys.argv[2] == "up":
    t.DISKS.pop("/media/wmbfull")
    t.DISKS["/media/wmbtest"] = 800
    t.setup_disks()
    os.makedirs("/media/wmbtest/images", exist_ok=True)
    t.make_zip("/media/wmbtest/images/openatv-9.9.9-vuzero4k-TEST.zip",
               rootfs=t.make_rootfs(payload=62 * 1024 * 1024))
    print(os.listdir("/media/wmbtest/images"))
else:
    t.DISKS.pop("/media/wmbfull")
    t.teardown_disks()
