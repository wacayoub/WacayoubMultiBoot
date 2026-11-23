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


def t_backups_settings_channels():
    z = make_zip("/media/wmbtest/chan.zip", rootfs=make_rootfs())
    lay = chroot_layout()
    job = FakeJob("i")
    lay.install(job, z, target=target("/media/wmbtest"))
    assert job.new_root and os.path.isdir(job.new_root)
    lay = chroot_layout()
    slot = [s for s in lay.slots if s.root == job.new_root][0]
    # copy channels of the running image into the test slot
    core.copy_channels(FakeJob("c"), slot)
    assert os.path.isfile(job.new_root + "/etc/enigma2/lamedb") or os.path.isfile(job.new_root + "/etc/enigma2/lamedb5")
    assert os.path.isfile(job.new_root + "/etc/enigma2/bouquets.tv")
    # never into the running slot
    expect_error(lambda: core.copy_channels(FakeJob("c"), lay.running_slot()), "en cours")
    # settings backup of the test slot, then restore into it
    core.backup_settings(FakeJob("b"), slot, "/media/wmbtest", lay)
    bk = [b for b in core.list_backups() if b["mount"] == "/media/wmbtest" and b["kind"] == "custom"]
    assert len(bk) == 1, bk
    os.remove(job.new_root + "/etc/enigma2/bouquets.tv")
    core.restore_settings(FakeJob("r"), bk[0]["path"], slot)
    assert os.path.isfile(job.new_root + "/etc/enigma2/bouquets.tv")
    # (restore into the running image restarts the GUI: never in automatic tests)
    # malicious settings archive (path traversal) is refused
    evil = "/media/wmbtest/WMultiBoot/backups/reglages-evil.tar.gz"
    with tarfile.open(evil, "w:gz") as t:
        ti = tarfile.TarInfo("./etc/enigma2/../../../etc/passwd"); ti.size = 1
        t.addfile(ti, io.BytesIO(b"x"))
    expect_error(lambda: core.restore_settings(FakeJob("r"), evil, slot), "ne contient pas")  # traversal skipped
    assert not os.path.exists("/media/wmbtest/etc/passwd")
    # delete backups: only real backup files
    expect_error(lambda: core.delete_backup("/etc/passwd"), "pas une sauvegarde")
    core.delete_backup(evil)
    core.delete_backup(bk[0]["path"])
    assert not [b for b in core.list_backups() if b["mount"] == "/media/wmbtest"]
    caps = dict((st["mount"], n) for st, n in core.install_capacity())
    assert "/media/wmbtest" in caps and caps["/media/wmbtest"] >= 0
    assert core.distro_key("OpenPLi") == "openpli" and core.distro_key("??") == "unknown"
    lay.delete(FakeJob("d"), slot)


def t_custom_backup_restore():
    z = make_zip("/media/wmbtest/cust.zip", rootfs=make_rootfs())
    lay = chroot_layout()
    job = FakeJob("i")
    lay.install(job, z, target=target("/media/wmbtest"))
    lay = chroot_layout()
    slot = [s for s in lay.slots if s.root == job.new_root][0]
    run = lay.running_slot()
    # classification rules
    assert core.classify("./etc/enigma2/lamedb") == "channels"
    assert core.classify("etc/enigma2/settings") == "settings"
    assert core.classify("etc/tuxbox/satellites.xml") == "satellites"
    assert core.classify("etc/tuxbox/config/oscam.server") == "softcam"
    assert core.classify("etc/enigma2/epg.dat") is None
    assert core.classify("etc/enigma2/x-backups/a") is None
    for bad in ("etc/init.d/x", "etc/rc.local", "etc/passwd", "var/spool/cron/crontabs/root", "usr/bin/x", "../etc/x"):
        assert core.classify(bad) is None, bad
    summ = dict((k, (size, avail)) for k, t, d, w, size, avail in core.backup_summary(run, lay))
    assert summ["channels"][1] and summ["settings"][1], summ
    # backup only channels + satellites of the running image
    res = core.backup_custom(FakeJob("b"), run, ["channels", "satellites"], "/media/wmbtest", lay)
    bk = [b for b in core.list_backups() if b["mount"] == "/media/wmbtest" and b["kind"] == "custom"][0]
    info = core.read_backup(bk["path"])
    assert set(info["categories"]) == {"channels", "satellites"}, info
    assert info["manifest"].get("categories") == "channels,satellites"
    # restore only channels into the test slot
    for f in ("etc/enigma2/bouquets.tv", "etc/tuxbox/satellites.xml"):
        core.remove_quiet(os.path.join(slot.root, f))
    os.makedirs(os.path.join(slot.root, "etc/tuxbox"), exist_ok=True)
    msg = core.restore_custom(FakeJob("r"), bk["path"], ["channels"], slot, lay)
    assert os.path.isfile(os.path.join(slot.root, "etc/enigma2/bouquets.tv")), msg
    assert not os.path.exists(os.path.join(slot.root, "etc/tuxbox/satellites.xml")), "satellites restored but not chosen"
    # an archive with forbidden files: they are skipped, the rest is restored
    evil = "/media/wmbtest/WMultiBoot/backups/sauvegarde-evil.tar.gz"
    with tarfile.open(evil, "w:gz") as t:
        for name, data in (("./etc/init.d/evil", b"x"), ("./etc/enigma2/lamedb", b"ok"),
                           ("./etc/enigma2/../../etc/passwd", b"x")):
            ti = tarfile.TarInfo(name); ti.size = len(data); t.addfile(ti, io.BytesIO(data))
        ti = tarfile.TarInfo("./etc/enigma2/userbouquet.link.tv"); ti.type = tarfile.SYMTYPE; ti.linkname = "/etc/passwd"
        t.addfile(ti)
    core.restore_custom(FakeJob("r"), evil, ["channels"], slot, lay)
    assert core.read_file(os.path.join(slot.root, "etc/enigma2/lamedb")) == "ok"
    assert not os.path.exists(os.path.join(slot.root, "etc/init.d/evil"))
    assert not os.path.lexists(os.path.join(slot.root, "etc/enigma2/userbouquet.link.tv"))
    expect_error(lambda: core.restore_custom(FakeJob("r"), evil, [], slot, lay), "Cochez")
    expect_error(lambda: core.backup_custom(FakeJob("b"), run, [], "/media/wmbtest", lay), "Cochez")
    # instant cancel: nothing kept
    j = FakeJob("c"); j.cancelled = True
    expect_error(lambda: core.backup_custom(j, run, ["channels", "plugins_conf"], "/media/wmbtest", lay), "annul")
    assert not leftovers("/media/wmbtest")
    for b in core.list_backups():
        if b["mount"] == "/media/wmbtest":
            core.delete_backup(b["path"])
    lay.delete(FakeJob("d"), slot)


def plugin_rootfs(version="9.9.9", date="20261122"):
    """Rootfs of a small fake image with two plugins: one in the feed, one only installed."""
    status = ("Package: enigma2-plugin-extensions-infeed\nVersion: 1.0\nStatus: install ok installed\nInstalled-Size: 100\n\n"
              "Package: enigma2-plugin-extensions-mine\nVersion: 2.1\nStatus: install ok installed\nInstalled-Size: 2000\n\n"
              "Package: enigma2-plugin-settings-vhannibal\nVersion: 1\nStatus: install ok installed\n\n"
              "Package: enigma2-plugin-extensions-wmultiboot\nVersion: 1\nStatus: install ok installed\n\n")
    extra = {
        "./etc/inittab": b"id:3:initdefault:\nl3:3:wait:/etc/init.d/rc 3\n",
        "./etc/rc3.d/S01networking": b"#!/bin/sh\n",
        "./etc/rcS.d/S01x": b"#!/bin/sh\n",
        "./usr/lib/enigma2/python/Plugins/Extensions/.keep": b"",
        "./var/lib/opkg/status": status.encode(),
        "./var/lib/opkg/lists/openatv-all": b"Package: enigma2-plugin-extensions-infeed\nVersion: 1.0\n\n",
        "./var/lib/opkg/info/enigma2-plugin-extensions-mine.control":
            b"Package: enigma2-plugin-extensions-mine\nVersion: 2.1\nArchitecture: all\nMaintainer: me\nDescription: mine\n"
            b"Status: install ok installed\nInstalled-Time: 1\n",
        "./var/lib/opkg/info/enigma2-plugin-extensions-mine.list":
            b"/usr/lib/enigma2/python/Plugins/Extensions/Mine/plugin.py\n/usr/lib/enigma2/python/Plugins/Extensions/Mine/plugin.pyc\n"
            b"/etc/init.d/mine-evil\n/usr/bin/mine-bin\n",
        "./usr/lib/enigma2/python/Plugins/Extensions/Mine/plugin.py": b"# mine\n",
        "./usr/lib/enigma2/python/Plugins/Extensions/Mine/plugin.pyc": b"pyc",
        "./etc/init.d/mine-evil": b"#!/bin/sh\n",
        "./usr/bin/mine-bin": b"bin",
        "./etc/enigma2/lamedb": b"eDVB services /4/\nend\n",
        "./etc/enigma2/bouquets.tv": b"#NAME Bouquets (TV)\n",
        "./etc/enigma2/settings": b"config.misc.firstrun=false\n",
        "./etc/image-version": ("box_type=vuzero4k\ndistro=openatv\nimageversion=%s\ndate=%s\n" % (version, date)).encode(),
    }
    return make_rootfs(extra=extra)


def read_ipk(path):
    """{member: bytes} of an ar archive."""
    data = open(path, "rb").read()
    assert data.startswith(b"!<arch>\n"), data[:8]
    i, out = 8, {}
    while i < len(data):
        name = data[i:i + 16].decode().strip().rstrip("/")
        size = int(data[i + 48:i + 58].decode().strip())
        out[name] = data[i + 60:i + 60 + size]
        i += 60 + size + (size % 2)
    return out


def t_plugin_tools():
    det = core.plugin_details("/")
    names = [p["name"] for p in det]
    assert names and core.SELF_PKG not in names and not [n for n in names if "-settings-" in n], names
    assert all(p["kind"] and p["short"] for p in det)
    assert core.plugin_details_from_name("enigma2-plugin-softcams-oscam")["kind"] == "Softcam"
    feed = core.feed_packages("/")
    assert feed, "no opkg lists on the box"
    # a real plugin of the box that is not in the feed is re-packed as a valid .ipk
    own = [n for n in names if n not in feed and n.endswith(("wacayoubpanel", "bop2", "iptvbouquetai"))]
    assert own, "expected own plugins outside the feed"
    out = "/media/wmbtest/test.ipk"
    n = core.repack_ipk("/", own[0], out)
    assert n > 0, own[0]
    parts = read_ipk(out)
    assert set(parts) == {"debian-binary", "control.tar.gz", "data.tar.gz"}, parts.keys()
    with tarfile.open(fileobj=io.BytesIO(parts["data.tar.gz"])) as t:
        files = [m.name for m in t if m.isfile()]
    assert files and all(core.REPACK_OK.match(f[2:]) for f in files), files[:5]
    assert not [f for f in files if f.endswith(".pyc")]
    with tarfile.open(fileobj=io.BytesIO(parts["control.tar.gz"])) as t:
        ctl = t.extractfile("./control").read().decode()
    assert "Package: %s" % own[0] in ctl and "Status:" not in ctl, ctl
    # opkg accepts it: install into an offline test root (nothing touches the running image)
    off = "/media/wmbtest/offroot"
    os.makedirs(off + "/var/lib/opkg", exist_ok=True)
    rc = subprocess.call(["opkg", "-o", off, "--force-depends", "--nodeps", "install", out],
                         stdout=open("/media/wmbtest/opkg.out", "w"), stderr=subprocess.STDOUT)
    log_ = core.read_file("/media/wmbtest/opkg.out")
    assert rc == 0 and os.path.isdir(off + "/usr/lib/enigma2/python/Plugins"), log_[-400:]
    shutil.rmtree(off, ignore_errors=True)
    os.remove(out)


def t_backup_restore_plugin_choice():
    z = make_zip("/media/wmbtest/plug.zip", rootfs=plugin_rootfs())
    lay = chroot_layout()
    job = FakeJob("i")
    lay.install(job, z, target=target("/media/wmbtest"))
    lay = chroot_layout()
    src = [s for s in lay.slots if s.root == job.new_root][0]
    det, feed = core.plugin_report(src, lay)
    assert [p["name"] for p in det] == ["enigma2-plugin-extensions-infeed", "enigma2-plugin-extensions-mine"], det
    assert feed == {"enigma2-plugin-extensions-infeed"}, feed
    # back up only the chosen plugins
    jb = FakeJob("b")
    core.backup_custom(jb, src, ["channels", "plugins"], "/media/wmbtest", lay,
                       ["enigma2-plugin-extensions-mine", "enigma2-plugin-extensions-infeed", "not-installed"])
    info = core.read_backup(jb.last_backup)
    assert info["plugins"] == ["enigma2-plugin-extensions-infeed", "enigma2-plugin-extensions-mine"], info
    assert info["ipks"] == ["enigma2-plugin-extensions-mine"], info      # only the one outside the feed
    jb2 = FakeJob("b2")
    core.backup_custom(jb2, src, ["plugins"], "/media/wmbtest", lay, ["enigma2-plugin-extensions-infeed"])
    assert core.read_backup(jb2.last_backup)["plugins"] == ["enigma2-plugin-extensions-infeed"]
    # restore into a second (not running) image with only one plugin chosen
    z2 = make_zip("/media/wmbtest/plug2.zip", rootfs=make_rootfs(extra={
        "./etc/inittab": b"id:3:initdefault:\n", "./etc/rc3.d/S01networking": b"#!/bin/sh\n"}))
    j2 = FakeJob("i2")
    lay.install(j2, z2, target=target("/media/wmbtest"))
    lay = chroot_layout()
    dst = [s for s in lay.slots if s.root == j2.new_root][0]
    msg = core.restore_custom(FakeJob("r"), jb.last_backup, ["channels", "plugins"], dst, lay,
                              ["enigma2-plugin-extensions-mine"])
    fb = os.path.join(dst.root, core.FIRSTBOOT_DIR)
    assert core.read_file(fb + "/plugins.txt").split() == ["enigma2-plugin-extensions-mine"], msg
    assert os.path.isfile(fb + "/ipk/enigma2-plugin-extensions-mine.ipk")
    hook = os.path.join(dst.root, "etc/rc3.d/S98wmbfirstboot")
    assert os.access(hook, os.X_OK) and subprocess.call(["sh", "-n", hook]) == 0
    assert os.path.isfile(os.path.join(dst.root, "etc/enigma2/lamedb"))
    assert "premier démarrage" in msg, msg
    # never on the running image
    expect_error(lambda: core.install_firstboot_hook("/", ["x"]), "en cours")
    for s in (src, dst):
        lay.delete(FakeJob("d"), s)
    for b in core.list_backups():
        if b["mount"] == "/media/wmbtest":
            core.delete_backup(b["path"])
    assert not leftovers("/media/wmbtest")


def t_firstboot_script():
    """Run the real first-boot script in a sandbox with a fake opkg (no change to the box)."""
    sb = "/media/wmbtest/fb"
    shutil.rmtree(sb, ignore_errors=True)
    os.makedirs(sb + "/bin")
    os.makedirs(sb + "/root/etc/enigma2")
    os.makedirs(sb + "/root/etc/wmb-firstboot/ipk")
    core.write_file(sb + "/root/etc/enigma2/settings", "mine\n")
    core.write_file(sb + "/bin/opkg", "#!/bin/sh\necho \"$@\" >> %s/calls\n"
                    "case \"$1\" in update) exit 0;; status) [ \"$2\" = have-it ] && echo 'Status: install ok installed'; exit 0;;\n"
                    " install) case \"$2\" in *good*) echo overwrite > %s/root/etc/enigma2/settings; exit 0;; *.ipk) exit 0;; esac; exit 1;; esac\n"
                    % (sb, sb))
    os.chmod(sb + "/bin/opkg", 0o755)
    core.write_file(sb + "/root/etc/wmb-firstboot/plugins.txt", "good-one\nhave-it\nlocal-one\nmissing-one\nbad;name\n")
    core.write_file(sb + "/root/etc/wmb-firstboot/ipk/local-one.ipk", "x")
    script = core.FIRSTBOOT_SCRIPT % {"dir": sb[1:] + "/root/etc/wmb-firstboot", "hook": sb[1:] + "/hook", "root": sb + "/root"}
    core.write_file(sb + "/hook", script)
    env = dict(os.environ, PATH=sb + "/bin:" + os.environ.get("PATH", ""))
    rc = subprocess.call(["sh", sb + "/hook"], env=env, timeout=120)
    res = core.parse_kv(core.read_file(sb + "/root/etc/wmb-firstboot/result.txt"))
    calls = core.read_file(sb + "/calls")
    assert rc == 0 and not os.path.exists(sb + "/hook"), "hook must remove itself"
    assert res.get("installed") == "2" and res.get("failed", "").split() == ["missing-one"] and res.get("network") == "1", res
    assert "install have-it" not in calls and "bad;name" not in calls, calls
    assert core.read_file(sb + "/root/etc/enigma2/settings") == "mine\n", "restored settings must win over the package"
    assert not os.path.exists(sb + "/root/etc/wmb-firstboot/plugins.txt")
    # the notice is shown once
    text = core.firstboot_result(sb + "/root")
    assert "2 plugins" in text and "missing-one" in text, text
    assert core.firstboot_result(sb + "/root") is None
    shutil.rmtree(sb, ignore_errors=True)


def t_find_update():
    slot = core.Slot("x", 1, "chroot", info={"distro": "OpenATV", "date": "20261002", "label": "OpenATV 8.0.1"})
    cat = [("OpenATV", [
        {"name": "openatv-8.0.2-vuzero4k-20261120_usb.zip", "eol": False, "beta": False, "date": 0, "url": "u1"},
        {"name": "openatv-8.1-beta-vuzero4k-20261122_usb.zip", "eol": False, "beta": True, "date": 0, "url": "u2"},
        {"name": "openatv-7.6-vuzero4k-20261121_usb.zip", "eol": True, "beta": False, "date": 0, "url": "u3"}]),
           ("OpenPLi", [{"name": "openpli-9.2-vuzero4k-20261130.zip", "eol": False, "beta": False, "date": 0, "url": "u4"}])]
    it, newer = core.find_update(cat, slot)
    assert it["url"] == "u1" and newer, it
    slot.info["date"] = "20261125"
    it, newer = core.find_update(cat, slot)
    assert it["url"] == "u1" and not newer
    slot.info["distro"] = "Bidule"
    assert core.find_update(cat, slot) == (None, False)


def t_update_image():
    lay = chroot_layout()
    j0 = FakeJob("i")
    lay.install(j0, make_zip("/media/wmbtest/old.zip", rootfs=plugin_rootfs("8.0.1", "20261002")), target=target("/media/wmbtest"))
    lay = chroot_layout()
    old = [s for s in lay.slots if s.root == j0.new_root][0]
    before = core.read_file(os.path.join(old.root, "etc/enigma2/settings"))
    newzip = make_zip("/media/wmbtest/new.zip", rootfs=make_rootfs(extra={
        "./etc/inittab": b"id:3:initdefault:\n", "./etc/rc3.d/S01networking": b"#!/bin/sh\n",
        "./usr/lib/enigma2/python/Plugins/Extensions/.keep": b"",
        "./etc/enigma2/settings": b"config.misc.firstrun=true\n"}))
    job = FakeJob("u")
    msg = core.update_image(job, lay, old, newzip, target("/media/wmbtest"), ["channels", "settings", "plugins"], None,
                            "/media/wmbtest")
    new = job.new_root
    assert new and new != old.root and os.path.isdir(new), msg
    assert core.read_file(os.path.join(new, "etc/enigma2/settings")) == "config.misc.firstrun=false\n", "settings kept"
    assert os.path.isfile(os.path.join(new, "etc/enigma2/lamedb"))
    assert sorted(core.read_file(os.path.join(new, core.FIRSTBOOT_DIR, "plugins.txt")).split()) == [
        "enigma2-plugin-extensions-infeed", "enigma2-plugin-extensions-mine"]
    assert os.path.isfile(os.path.join(new, core.FIRSTBOOT_DIR, "ipk/enigma2-plugin-extensions-mine.ipk"))
    me = os.path.join(new, "usr/lib/enigma2/python/Plugins/Extensions/WMultiBoot")
    assert os.path.isfile(me + "/core.py") and not [f for f in os.listdir(me) if f.endswith(".pyc")]
    assert core.read_file(os.path.join(old.root, "etc/enigma2/settings")) == before, "old image untouched"
    assert "gardée" in msg, msg
    # cancel during the backup step: nothing installed, nothing left
    jc = FakeJob("c"); jc.cancelled = True
    expect_error(lambda: core.update_image(jc, chroot_layout(), old, newzip, target("/media/wmbtest"), ["channels"], None,
                                           "/media/wmbtest"), "annul")
    lay = chroot_layout()
    for s in [s for s in lay.slots if s.root and s.root.startswith("/media/wmbtest/")]:
        lay.delete(FakeJob("d"), s)
    for b in core.list_backups():
        if b["mount"] == "/media/wmbtest":
            core.delete_backup(b["path"])
    assert not leftovers("/media/wmbtest")


def t_addons_backup_restore():
    """Hand-installed skins/plugin files (owned by no package) are backed up, programs are not,
    and a restore never overwrites a file the target image already has."""
    z = make_zip("/media/wmbtest/addons.zip", rootfs=make_rootfs())
    lay = chroot_layout()
    job = FakeJob("i")
    lay.install(job, z, target=target("/media/wmbtest"))
    lay = chroot_layout()
    slot = [s for s in lay.slots if s.root == job.new_root][0]
    R = slot.root
    def put(rel, data):
        p = os.path.join(R, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)
    info = os.path.join(R, "var/lib/opkg/info")
    os.makedirs(info, exist_ok=True)
    with open(os.path.join(info, "enigma2-plugin-skins-x.list"), "w") as f:
        f.write("/usr/share/enigma2/SkinX/skin.xml\n/usr/lib/enigma2/python/Components/Renderer/XR.py\t0644\n")
    put("usr/share/enigma2/SkinX/skin.xml", b"<skin/>")                      # owned -> not an addon
    put("usr/lib/enigma2/python/Components/Renderer/XR.py", b"# owned")      # owned
    put("usr/share/enigma2/MySkin/skin.xml", b"<skin>mine</skin>")           # hand-installed
    put("usr/lib/enigma2/python/Components/MySkin/extra.py", b"x = 1\n")     # hand-installed
    put("usr/lib/enigma2/python/Components/MySkin/only.pyc", b"\x00pyc")     # sourceless file
    put("usr/lib/enigma2/python/Plugins/Extensions/Hand/plugin.py", b"# hand")
    put("usr/lib/enigma2/python/Plugins/Extensions/Hand/tool.so", b"\x7fELF....")  # program -> left out
    put("usr/share/enigma2/MySkin/old-backup/a.png", b"x")                   # backup folder -> left out
    files, size, elf = core.addon_paths(R)
    assert "usr/share/enigma2/MySkin/skin.xml" in files, files
    assert "usr/lib/enigma2/python/Components/MySkin/only.pyc" in files
    assert "usr/lib/enigma2/python/Plugins/Extensions/Hand/plugin.py" in files
    assert "usr/share/enigma2/SkinX/skin.xml" not in files and "usr/lib/enigma2/python/Components/Renderer/XR.py" not in files
    assert elf == ["usr/lib/enigma2/python/Plugins/Extensions/Hand/tool.so"], elf
    assert not any("backup" in f for f in files), files
    assert core.classify("usr/bin/evil") is None and core.classify("usr/lib/libx.so") is None
    msg = core.backup_custom(FakeJob("b"), slot, ["addons"], "/media/wmbtest", lay)
    assert "ajoutés à la main" in msg and "programmes non sauvegardés" in msg, msg
    bk = sorted(b["path"] for b in core.list_backups() if b["mount"] == "/media/wmbtest" and b["kind"] == "custom")[-1]
    with tarfile.open(bk) as t:
        names = [n[2:] if n.startswith("./") else n for n in t.getnames()]
    assert "usr/share/enigma2/MySkin/skin.xml" in names and not any(n.endswith("tool.so") for n in names), names
    assert core.read_backup(bk)["categories"].get("addons") == len(files), core.read_backup(bk)["categories"]
    # restore: a missing addon comes back, an existing file is kept as it is
    core.remove_quiet(os.path.join(R, "usr/lib/enigma2/python/Components/MySkin/extra.py"))
    put("usr/share/enigma2/MySkin/skin.xml", b"<skin>newer</skin>")
    msg = core.restore_custom(FakeJob("r"), bk, ["addons"], slot, lay)
    assert core.read_file(os.path.join(R, "usr/lib/enigma2/python/Components/MySkin/extra.py")) == "x = 1\n", msg
    assert core.read_file(os.path.join(R, "usr/share/enigma2/MySkin/skin.xml")) == "<skin>newer</skin>", msg
    assert "gardés tels quels" in msg, msg
    core.remove_quiet(bk)


def t_remote_job_status():
    """A job run outside Enigma2 publishes its state; RemoteJob follows it to the end."""
    import json, time
    code = ("import sys,time,importlib.util\n"
            "sp=importlib.util.spec_from_file_location('c', %r); c=importlib.util.module_from_spec(sp); sp.loader.exec_module(c)\n"
            "j=c.Job('Test SSH')\n"
            "j.start(lambda j:(j.say('etape 1',10),time.sleep(3),j.say('etape 2',60),time.sleep(3),'fini')[-1])\n"
            "while not j.done: time.sleep(0.2)\n") % sys.argv[1]
    p = subprocess.Popen([sys.executable, "-c", code])
    time.sleep(1.5)
    mine = [d for d in core.foreign_jobs() if d["pid"] == p.pid]
    assert len(mine) == 1, mine
    r = core.RemoteJob(mine[0])
    assert not r.done and r.progress == 10 and r.title == "Test SSH", (r.progress, r.step)
    time.sleep(3.5); r.refresh()
    assert r.progress == 60 and r.step == "etape 2", (r.progress, r.step)
    p.wait(); r.refresh()
    assert r.done and r.ok and r.result == "fini", (r.done, r.result)
    r.mark_seen()
    assert not os.path.exists(r.path)
    fake = core.JOB_STATUS % 999999
    json.dump({"pid": 999999, "done": False, "title": "x"}, open(fake, "w"))
    core.foreign_jobs()
    assert not os.path.exists(fake), "stale status of a dead process must be removed"


def t_no_temp_mounts_left():
    out = core.read_file("/proc/mounts")
    assert "wmb-mnt" not in out, out


TESTS = [t_detect_real, t_running_guards, t_install_backup_restore_delete, t_local_image_listing,
         t_corrupt_zip, t_truncated_zip, t_crc_damaged_zip, t_corrupt_rootfs_in_zip, t_zip_without_rootfs,
         t_wrong_box_zip, t_full_disk_precheck, t_full_disk_during_extract, t_backup_full_disk,
         t_cancel_install, t_bad_urls, t_unknown_box, t_no_multiboot_no_slots, t_startup_layout,
         t_omb_classic_layout, t_catalog_parse, t_backups_settings_channels, t_custom_backup_restore,
         t_plugin_tools, t_backup_restore_plugin_choice, t_firstboot_script, t_find_update, t_update_image,
         t_addons_backup_restore, t_remote_job_status, t_no_temp_mounts_left]

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
