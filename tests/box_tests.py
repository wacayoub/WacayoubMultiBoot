#!/usr/bin/env python3
"""Edge-case tests for Wacayoub MultiBoot core, run ON THE RECEIVER:

    python3 box_tests.py /usr/lib/enigma2/python/Plugins/Extensions/WMultiBoot/core.py

Never touches the real slots, the flash or the boot choice:
  * all writes go to two loop-mounted ext4 test disks (/media/wmbtest 400 MB,
    /media/wmbfull 24 MB) whose image files live in /media/hdd/WMultiBoot-test
  * set_next() is only tested on fake layouts (monkeypatched TempMount)
Everything is unmounted and removed at the end.
"""
import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import traceback
import zipfile

spec = importlib.util.spec_from_file_location("wmbcore", sys.argv[1])
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
MBError = core.MBError

TESTDIR = "/media/hdd/WMultiBoot-test"
DISKS = {"/media/wmbtest": 400, "/media/wmbfull": 24}
RESULTS = []


def sh(*a):
    return subprocess.run(a, stdout=subprocess.PIPE, stderr=subprocess.STDOUT).stdout.decode()


def check(name, fn):
    try:
        fn()
        RESULTS.append((True, name, ""))
        print("PASS", name)
    except Exception as e:
        RESULTS.append((False, name, "%s: %s" % (type(e).__name__, e)))
        print("FAIL", name, "->", type(e).__name__, e)
        traceback.print_exc()


def expect_error(fn, *words):
    try:
        fn()
    except MBError as e:
        msg = str(e)
        for w in words:
            assert w.lower() in msg.lower(), "message %r lacks %r" % (msg, w)
        print("      -> " + " | ".join(msg.splitlines())[:150])
        return msg
    raise AssertionError("no MBError raised")


# ------------------------------------------------------------------ fixtures

def setup_disks():
    os.makedirs(TESTDIR, exist_ok=True)
    for mp, size in DISKS.items():
        img = os.path.join(TESTDIR, os.path.basename(mp) + ".img")
        with open(img, "wb") as fh:
            fh.truncate(size * 1024 * 1024)
        sh("mkfs.ext4", "-q", "-F", "-m", "0", img)
        os.makedirs(mp, exist_ok=True)
        out = sh("mount", "-t", "ext4", "-o", "loop", img, mp)
        assert os.path.ismount(mp), out


def teardown_disks():
    for mp in DISKS:
        sh("umount", mp)
        try:
            os.rmdir(mp)
        except Exception:
            pass
    shutil.rmtree(TESTDIR, ignore_errors=True)


def make_rootfs(box="vuzero4k", payload=0, extra=None, kernel_ver=None):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:bz2") as t:
        def add(name, data, mode=0o644):
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            ti.mode = mode
            t.addfile(ti, io.BytesIO(data))
        add("./sbin/init", b"#!/bin/sh\n", 0o755)
        add("./etc/image-version", ("box_type=%s\ndistro=openatv\nimageversion=9.9.9\ndate=20261122\n" % box).encode())
        add("./etc/fstab", b"rootfs / ext4 defaults 1 1\nproc /proc proc defaults 0 0\n")
        ti = tarfile.TarInfo("./lib/modules/%s" % (kernel_ver or os.uname()[2]))
        ti.type = tarfile.DIRTYPE
        t.addfile(ti)
        if payload:
            add("./usr/share/payload.bin", os.urandom(payload))
        for k, v in (extra or {}).items():
            add(k, v)
    return buf.getvalue()


def make_zip(path, folder="vuplus/zero4k/", rootfs=None, kernel=True, raw_members=None):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as z:
        if rootfs is not None:
            z.writestr(folder + "rootfs.tar.bz2", rootfs)
        if kernel:
            z.writestr(folder + "kernel_auto.bin", b"\0" * 4096)
        for n, d in (raw_members or {}).items():
            z.writestr(n, d)
    return path


BOX = core.box_info()


def chroot_layout():
    lay = core.detect_layout(BOX)
    assert lay.key == "chroot", lay.key
    return lay


def target(mp):
    for st in core.storages():
        if st["mount"] == mp:
            return st
    raise AssertionError("storage %s not found" % mp)


def leftovers(mp):
    bad = []
    for d, dirs, files in os.walk(mp):
        for n in dirs + files:
            if n.endswith((".partial", ".deleting")) or (d.endswith("/tmp") and n.startswith("rootfs.")):
                bad.append(os.path.join(d, n))
    return bad


class FakeJob(core.Job):
    pass


# ------------------------------------------------------------------ tests

def t_detect_real():
    lay = chroot_layout()
    run = lay.running_slot()
    assert run and run.kind == "chroot" and core.is_running_root(run.root)
    assert lay.slots[0].kind == "flash" and not lay.slots[0].deletable


def t_running_guards():
    lay = chroot_layout()
    run = lay.running_slot()
    expect_error(lambda: lay.delete(FakeJob("t"), run), "en cours")
    expect_error(lambda: lay.delete(FakeJob("t"), lay.slots[0]), "")
    expect_error(lambda: core.safe_rmtree(FakeJob("t"), "/", "x"), "refusé")
    expect_error(lambda: core.safe_rmtree(FakeJob("t"), run.root, run.reldir), "en cours")
    expect_error(lambda: core.extract_rootfs(FakeJob("t"), "/dev/null", "/", BOX), "en cours")


def t_install_backup_restore_delete():
    z = make_zip("/media/wmbtest/good-vuzero4k.zip", rootfs=make_rootfs())
    lay = chroot_layout()
    job = FakeJob("install")
    msg = lay.install(job, z, target=target("/media/wmbtest"))
    dest = "/media/wmbtest/OnlineMultiBoot/images/good-vuzero4k"
    assert os.path.isfile(dest + "/sbin/init"), msg
    assert core.read_file(dest + "/etc/fstab").startswith("#OMB# rootfs"), "fstab not fixed"
    assert core.read_file(dest + "/etc/omb_slot").strip() == "good-vuzero4k"
    assert not leftovers("/media/wmbtest"), leftovers("/media/wmbtest")
    lay = chroot_layout()
    slot = [s for s in lay.slots if s.root == dest]
    assert slot and slot[0].info["version"] == "9.9.9" and not slot[0].running and slot[0].deletable
    # backup
    res = lay.backup(FakeJob("backup"), slot[0], "/media/wmbtest")
    bk = [f for f in os.listdir("/media/wmbtest/WMultiBoot/backups") if f.endswith(".tar.gz")]
    assert len(bk) == 1, res
    # restore the backup as a new slot (name collision -> _2)
    lay.install(FakeJob("restore"), os.path.join("/media/wmbtest/WMultiBoot/backups", bk[0]),
                target=target("/media/wmbtest"), name="good-vuzero4k")
    assert os.path.isfile(dest + "_2/sbin/init")
    # the backup must not contain mounted/virtual dirs content
    # delete both
    lay = chroot_layout()
    for s in [s for s in lay.slots if s.root and s.root.startswith("/media/wmbtest/")]:
        lay.delete(FakeJob("delete"), s)
        assert not os.path.exists(s.root)
    assert not leftovers("/media/wmbtest")


def t_local_image_listing():
    p = "/media/wmbtest/images/listed-image.zip"
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as fh:
        fh.truncate(70 * 1024 * 1024)
    names = [x[1] for x in core.find_local_images()]
    os.remove(p)
    assert p in names, names[:5]


def t_corrupt_zip():
    p = "/media/wmbtest/corrupt.zip"
    with open(p, "wb") as fh:
        fh.write(b"PK\x03\x04" + os.urandom(5000))
    lay = chroot_layout()
    expect_error(lambda: lay.install(FakeJob("t"), p, target=target("/media/wmbtest")), "corrompue")
    assert not leftovers("/media/wmbtest")


def t_truncated_zip():
    good = make_zip("/media/wmbtest/full.zip", rootfs=make_rootfs(payload=300000))
    data = open(good, "rb").read()
    p = "/media/wmbtest/truncated.zip"
    with open(p, "wb") as fh:
        fh.write(data[: len(data) // 2])
    lay = chroot_layout()
    expect_error(lambda: lay.install(FakeJob("t"), p, target=target("/media/wmbtest")), "zip")
    assert not leftovers("/media/wmbtest")


def t_crc_damaged_zip():
    good = make_zip("/media/wmbtest/crc.zip", rootfs=make_rootfs(payload=200000))
    data = bytearray(open(good, "rb").read())
    data[len(data) // 2] ^= 0xFF                # flip a byte inside the rootfs member
    open(good, "wb").write(bytes(data))
    lay = chroot_layout()
    expect_error(lambda: lay.install(FakeJob("t"), good, target=target("/media/wmbtest")), "corrompue")
    assert not leftovers("/media/wmbtest")


def t_corrupt_rootfs_in_zip():
    p = make_zip("/media/wmbtest/badroot.zip", rootfs=b"BZh9" + os.urandom(4000))
    lay = chroot_layout()
    expect_error(lambda: lay.install(FakeJob("t"), p, target=target("/media/wmbtest")), "corrompue")
    assert not leftovers("/media/wmbtest")
    assert not os.listdir("/media/wmbtest/OnlineMultiBoot/images") if os.path.isdir(
        "/media/wmbtest/OnlineMultiBoot/images") else True


def t_zip_without_rootfs():
    p = make_zip("/media/wmbtest/norootfs.zip", rootfs=None, raw_members={"readme.txt": b"hello"})
    expect_error(lambda: chroot_layout().install(FakeJob("t"), p, target=target("/media/wmbtest")), "rootfs")
    p = make_zip("/media/wmbtest/ubi.zip", rootfs=None, raw_members={"gb/root_cfe_auto.jffs2.ubi": b"x"})
    expect_error(lambda: chroot_layout().install(FakeJob("t"), p, target=target("/media/wmbtest")), "UBI")


def t_wrong_box_zip():
    p = make_zip("/media/wmbtest/duo.zip", folder="vuplus/duo4k/", rootfs=make_rootfs("vuduo4k"))
    expect_error(lambda: chroot_layout().install(FakeJob("t"), p, target=target("/media/wmbtest")), "duo4k")
    # right folder but image-version says another box
    p = make_zip("/media/wmbtest/liar.zip", rootfs=make_rootfs("gbquad4k"))
    expect_error(lambda: chroot_layout().install(FakeJob("t"), p, target=target("/media/wmbtest")), "gbquad4k")
    assert not leftovers("/media/wmbtest")


def t_full_disk_precheck():
    # 12 MB incompressible payload: zip fits in 24 MB disk but extraction needs ~190 MB
    p = make_zip("/media/wmbfull/big.zip", rootfs=make_rootfs(payload=12 * 1024 * 1024))
    lay = chroot_layout()
    expect_error(lambda: lay.install(FakeJob("t"), p, target=target("/media/wmbfull")), "espace insuffisant")
    assert not leftovers("/media/wmbfull")
    os.remove(p)


def t_full_disk_during_extract():
    p = make_zip("/media/wmbtest/big2.zip", rootfs=make_rootfs(payload=40 * 1024 * 1024))
    rootfs, kernel, cleanup = core.prepare_image(FakeJob("t"), p, "/media/wmbtest", BOX)
    real = core.fs_usage
    core.fs_usage = lambda path: (999999, 999999)      # lie: pass the precheck
    try:
        expect_error(lambda: core.extract_rootfs(FakeJob("t"), rootfs,
                                                 "/media/wmbfull/OnlineMultiBoot/images/x", BOX), "")
    finally:
        core.fs_usage = real
        for f in cleanup:
            core.remove_quiet(f)
    assert not leftovers("/media/wmbfull"), leftovers("/media/wmbfull")
    os.remove(p)


def t_backup_full_disk():
    lay = chroot_layout()
    run = lay.running_slot()
    expect_error(lambda: lay.backup(FakeJob("t"), run, "/media/wmbfull"), "espace insuffisant")
    assert not leftovers("/media/wmbfull")


def t_cancel_install():
    p = make_zip("/media/wmbtest/cancel.zip", rootfs=make_rootfs(payload=8 * 1024 * 1024))
    job = FakeJob("t")
    job.cancelled = True
    expect_error(lambda: chroot_layout().install(job, p, target=target("/media/wmbtest")), "annul")
    assert not leftovers("/media/wmbtest")


def t_bad_urls():
    lay = chroot_layout()
    for u in ("ftp://example.com/x.zip", "https://exa mple.com/x.zip", "http://;rm -rf /"):
        expect_error(lambda: core.download(FakeJob("t"), u, "/media/wmbtest"), "")
    expect_error(lambda: lay.install(FakeJob("t"), "http://127.0.0.1:9/none.zip", target=target("/media/wmbtest")), "")
    assert not leftovers("/media/wmbtest")


def t_unknown_box():
    real = core.read_file

    def fake(path, default=""):
        if path.startswith("/proc/stb/") or path in ("/etc/image-version", "/etc/hostname"):
            return ""
        return real(path, default)
    core.read_file = fake
    try:
        box = core.box_info()
        assert box["model"] and box["machine"], box
        lay = core.detect_layout(box)
        assert lay is not None and isinstance(lay.slots, list)
        # wrong-box check must not reject anything when the box is unknown
        assert not lay.warnings_for(lay.slots[0]) or box["machine"] == "inconnu"
    finally:
        core.read_file = real


def t_no_multiboot_no_slots():
    real_probe, real_st, real_find = core.FlashProbe, core.storages, core.StartupLayout.find_boot_device

    class P(object):
        device, on_flash, init_target, has_omb_init, boot_conf, info, error = "", True, "", False, None, None, ""
    core.FlashProbe = P
    core.storages = lambda: []
    core.StartupLayout.find_boot_device = staticmethod(lambda: None)
    try:
        lay = core.detect_layout(BOX)
        assert lay.key == "single", lay.key
        assert len(lay.slots) == 1 and lay.slots[0].running
        assert not lay.can("boot") and not lay.can("install")
        expect_error(lambda: lay.set_next(FakeJob("t"), lay.slots[0]), "")
        expect_error(lambda: lay.install(FakeJob("t"), "/x.zip"), "")
        # scan that blows up must still give a layout
        real_scan = core.SingleLayout.scan
        core.SingleLayout.scan = lambda self: 1 / 0
        try:
            lay = core.detect_layout(BOX)
            assert lay.slots == [] and lay.notes
        finally:
            core.SingleLayout.scan = real_scan
        # chroot layout with no images on any disk
        class P2(P):
            has_omb_init, init_target, boot_conf = True, "/sbin/omb-init", {}
        core.FlashProbe = P2
        lay = core.detect_layout(BOX)
        assert lay.key == "chroot" and len(lay.slots) == 1 and lay.notes
    finally:
        core.FlashProbe, core.storages = real_probe, real_st
        core.StartupLayout.find_boot_device = real_find


class FakeMount(object):
    """TempMount replacement mapping devices to folders."""
    MAP = {}

    def __init__(self, device, rw=False, fstypes=None):
        self.device = device

    def __enter__(self):
        return self.MAP[self.device]

    def __exit__(self, *a):
        return False


def t_startup_layout():
    tmp = tempfile.mkdtemp(prefix="wmbstartup")
    boot, rootp = os.path.join(tmp, "boot"), os.path.join(tmp, "root")
    os.makedirs(boot)
    for n in (1, 2, 3):
        d = os.path.join(rootp, "linuxrootfs%d" % n)
        os.makedirs(d + "/sbin")
        os.makedirs(d + "/etc")
        if n != 3:
            open(d + "/sbin/init", "w").write("x")
            open(d + "/etc/image-version", "w").write("distro=openpli\nversion=9.%d\ndate=2026010%d\n" % (n, n))
    lines = {1: "kernel=/dev/mmcblk0p4 root=/dev/mmcblk0p7 rootsubdir=linuxrootfs1 kernel=/dev/mmcblk0p4",
             2: "kernel=/dev/mmcblk0p13 root=/dev/mmcblk0p7 rootsubdir=linuxrootfs2",
             3: "kernel=/dev/mmcblk0p15 root=/dev/mmcblk0p7 rootsubdir=linuxrootfs3"}
    for n, t in lines.items():
        open(os.path.join(boot, "STARTUP_%d" % n), "w").write(t)
    open(os.path.join(boot, "STARTUP_RECOVERY"), "w").write("kernel=/dev/mmcblk0p10 recovery")
    open(os.path.join(boot, "STARTUP"), "w").write(lines[2])
    FakeMount.MAP = {"/dev/boot": boot, "/dev/mmcblk0p7": rootp}
    saved = (core.TempMount, core.resolve_dev, core.cmdline_arg)
    core.TempMount = FakeMount
    core.resolve_dev = lambda s: s
    core.cmdline_arg = lambda n: {"root": "/dev/mmcblk0p7", "rootsubdir": "linuxrootfs1"}.get(n, "")
    try:
        lay = core.StartupLayout(BOX, None)
        lay.boot_dev = "/dev/boot"
        lay.scan()
        s = {str(x.number): x for x in lay.slots}
        assert s["1"].running and not s["1"].next_boot, vars(s["1"])
        assert s["2"].next_boot and s["2"].info["version"] == "9.2"
        assert s["3"].empty and s["R"].kind == "recovery"
        expect_error(lambda: lay.delete(FakeJob("t"), s["1"]), "en cours")
        expect_error(lambda: lay.set_next(FakeJob("t"), s["3"]), "vide")
        lay.set_next(FakeJob("t"), s["1"])
        assert open(os.path.join(boot, "STARTUP")).read() == lines[1]
        # GigaBlue / mode12 parsing
        p = core.parse_startup("boot emmcflash0.kernel2 'root=/dev/mmcblk0p5 rootsubdir=linuxrootfs2 rw'")
        assert p["kernel"] == "/dev/block/by-name/kernel2" and p["rootsubdir"] == "linuxrootfs2", p
        p = core.parse_startup("kernel=/dev/mmcblk0p19 root=UUID=1234 rootsubdir=linuxrootfs5 rootfstype=ext4")
        assert p["root"] == "UUID=1234"
    finally:
        core.TempMount, core.resolve_dev, core.cmdline_arg = saved
        shutil.rmtree(tmp, ignore_errors=True)


def t_omb_classic_layout():
    tmp = tempfile.mkdtemp(prefix="wmbomb")
    d = os.path.join(tmp, "open-multiboot")
    os.makedirs(os.path.join(d, ".kernels"))
    os.makedirs(os.path.join(d, "img1/sbin"))
    open(os.path.join(d, "img1/sbin/init"), "w").write("x")
    open(os.path.join(d, ".kernels/img1.bin"), "w").write("k")
    open(os.path.join(d, ".%s-selected" % BOX["machine"]), "w").write("%s-flash" % BOX["machine"])

    class P(object):
        device, on_flash, init_target, has_omb_init, boot_conf, info, error = \
            "/dev/x", True, "/sbin/open_multiboot", False, None, {"label": "Flash"}, ""
    lay = core.OmbClassicLayout.detect(BOX, P())
    saved = core.OmbClassicLayout.data_dir, core.storage_for
    core.OmbClassicLayout.data_dir = lambda self: d
    core.storage_for = lambda p: {"device": "/dev/x", "mount": tmp, "rw": True}
    try:
        lay = core.OmbClassicLayout(BOX, P())
        lay.scan()
        assert lay.slots[0].next_boot and lay.slots[1].info
        lay.set_next(FakeJob("t"), lay.slots[1])
        assert open(os.path.join(d, ".%s-selected" % BOX["machine"])).read() == "img1"
    finally:
        core.OmbClassicLayout.data_dir, core.storage_for = saved
        shutil.rmtree(tmp, ignore_errors=True)


def t_catalog_parse():
    text = u"﻿" + '{"8.0 Release": {"a": {"link": "https://x.org/openatv-8.0.1-vuzero4k-20261003_usb.zip", "name": "openatv-8.0.1-vuzero4k-20261003_usb.zip", "size": 150000000, "date": 1}}, "7.4 EOL": {"b": {"link": "https://x.org/old-20250101.zip", "size": "x"}, "c": {"link": "javascript:alert(1)"}, "d": "junk"}, "x": []}'
    items = core.parse_catalog(text, "OpenATV")
    assert [i["name"] for i in items] == ["openatv-8.0.1-vuzero4k-20261003_usb.zip", "old-20250101.zip"], items
    assert items[0]["day"] == "03/10/2026" and items[1]["eol"] and items[1]["size"] == 0
    assert core.parse_catalog("not json", "X") == [] and core.parse_catalog("[]", "X") == []
    expect_error(lambda: core.fetch_catalog(FakeJob("t"), "inconnu"), "inconnu")


def t_no_temp_mounts_left():
    out = core.read_file("/proc/mounts")
    assert "wmb-mnt" not in out, out


TESTS = [t_detect_real, t_running_guards, t_install_backup_restore_delete, t_local_image_listing,
         t_corrupt_zip, t_truncated_zip, t_crc_damaged_zip, t_corrupt_rootfs_in_zip, t_zip_without_rootfs,
         t_wrong_box_zip, t_full_disk_precheck, t_full_disk_during_extract, t_backup_full_disk,
         t_cancel_install, t_bad_urls, t_unknown_box, t_no_multiboot_no_slots, t_startup_layout,
         t_omb_classic_layout, t_catalog_parse, t_no_temp_mounts_left]

if __name__ == "__main__":
    flash_conf_before = None
    setup_disks()
    try:
        only = sys.argv[2:]
        for t in TESTS:
            if not only or t.__name__ in only:
                check(t.__name__, t)
    finally:
        teardown_disks()
    ok = sum(1 for r in RESULTS if r[0])
    print("\n%d/%d tests passed" % (ok, len(RESULTS)))
    for r in RESULTS:
        if not r[0]:
            print("  FAIL", r[1], r[2])
    sys.exit(0 if ok == len(RESULTS) else 1)
