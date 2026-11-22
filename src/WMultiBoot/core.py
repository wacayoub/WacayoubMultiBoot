# -*- coding: utf-8 -*-
"""Wacayoub MultiBoot - core logic (no GUI imports, runs on Python 2.7 and 3.x).

Everything that touches the receiver goes through this module:
  * box detection
  * multiboot layout detection (Layout subclasses)
  * slot listing, next-boot selection
  * install / backup / delete jobs (run in a worker thread, see Job)

Rules enforced here (not only in the UI):
  * the running slot is never written, wiped or deleted (checked by inode, not by name)
  * every action checks its preconditions first and raises MBError with a clear,
    user-facing French message; anything else is logged and turned into MBError
  * extraction goes to "<name>.partial" first and is renamed only when valid
"""
from __future__ import absolute_import, division, print_function

import os
import re
import shutil
import subprocess
import threading
import time
import zipfile

VERSION = "1.0.0"
LOG_FILE = "/tmp/wmultiboot.log"
DATA_DIR = "WMultiBoot"                     # <device>/WMultiBoot/{downloads,backups,tmp}
CHROOT_BASES = ("OnlineMultiBoot/images", "open-multiboot", "ImageBoot", "WMultiBoot/images")
LINUX_FS = ("ext2", "ext3", "ext4", "xfs", "btrfs", "f2fs", "jfs")
IMAGE_EXT = (".zip", ".tar.bz2", ".tar.xz", ".tar.gz", ".tgz", ".tbz2")
MB = 1024 * 1024


class MBError(Exception):
    """Error with a message that can be shown to the user as is."""


class Cancelled(MBError):
    pass


# --------------------------------------------------------------------------- utils

def log(msg):
    try:
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 512 * 1024:
            os.rename(LOG_FILE, LOG_FILE + ".1")
        with open(LOG_FILE, "a") as fh:
            fh.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


def read_file(path, default=""):
    try:
        with open(path, "rb") as fh:
            return fh.read().decode("utf-8", "ignore")
    except Exception:
        return default


def write_file(path, text):
    """Atomic write (tmp + fsync + rename)."""
    tmp = path + ".wmb-tmp"
    with open(tmp, "w") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.rename(tmp, path)
    sync()


def sync():
    try:
        os.sync()
    except Exception:
        run(["sync"])


def run(args, timeout=None, cwd=None):
    """Run a command (list, no shell). Returns (rc, output). Never raises."""
    try:
        p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             cwd=cwd, close_fds=True)
    except Exception as e:
        return 127, str(e)
    try:
        if timeout is not None:
            try:
                out = p.communicate(timeout=timeout)[0]
            except TypeError:                       # Python 2
                out = p.communicate()[0]
        else:
            out = p.communicate()[0]
    except Exception as e:                          # TimeoutExpired
        try:
            p.kill()
            p.communicate()
        except Exception:
            pass
        return 124, "timeout: %s" % e
    return p.returncode, (out or b"").decode("utf-8", "ignore")


def which(name):
    for d in (os.environ.get("PATH") or "/usr/bin:/bin:/usr/sbin:/sbin").split(":") + ["/usr/sbin", "/sbin"]:
        p = os.path.join(d, name)
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def parse_kv(text):
    out = {}
    for line in text.splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def human_mb(mb):
    if mb is None:
        return "?"
    if mb >= 1024:
        return "%.1f Go" % (mb / 1024.0)
    return "%d Mo" % mb


def fmt_date(d):
    """'20261003' -> '03/10/2026'."""
    if d and len(d) >= 8 and d[:8].isdigit():
        return "%s/%s/%s" % (d[6:8], d[4:6], d[:4])
    return d or ""


def sanitize(name):
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name).strip("._-")
    return name[:64] or "image"


def same_file(a, b):
    try:
        sa, sb = os.stat(a), os.stat(b)
        return sa.st_dev == sb.st_dev and sa.st_ino == sb.st_ino
    except Exception:
        return False


def is_running_root(path):
    return bool(path) and same_file(path, "/")


def fs_usage(path):
    """(free_mb, total_mb) or (0, 0)."""
    try:
        st = os.statvfs(path)
        return st.f_bavail * st.f_frsize // MB, st.f_blocks * st.f_frsize // MB
    except Exception:
        return 0, 0


def dir_size_mb(path):
    rc, out = run(["du", "-smx", path], timeout=600)
    if rc != 0:
        rc, out = run(["du", "-sm", path], timeout=600)
    try:
        return int(out.split()[0])
    except Exception:
        return None


# --------------------------------------------------------------------------- box

def box_info():
    iv = parse_kv(read_file("/etc/image-version"))
    brand, model = "", ""
    vu = read_file("/proc/stb/info/vumodel").strip()
    gb = read_file("/proc/stb/info/gbmodel").strip()
    boxtype = read_file("/proc/stb/info/boxtype").strip()
    stbmodel = read_file("/proc/stb/info/model").strip()
    if vu:
        brand, model = "Vu+", "vu" + vu
    elif gb:
        brand, model = "GigaBlue", gb
    elif boxtype:
        model = boxtype
    elif stbmodel:
        model = stbmodel
    machine = iv.get("box_type") or iv.get("machinebuild") or read_file("/etc/hostname").strip() or model
    brand = iv.get("machine_brand") or brand
    try:                                            # inside enigma2 only
        from Components.SystemInfo import BoxInfo
        machine = BoxInfo.getItem("machinebuild") or machine
        brand = BoxInfo.getItem("displaybrand") or BoxInfo.getItem("brand") or brand
    except Exception:
        pass
    dream = (not vu) and (stbmodel.startswith("dm") or stbmodel in ("one", "two")
                          or os.path.exists("/proc/stb/info/dreambox") or brand.lower().startswith("dream"))
    if dream and not brand:
        brand = "Dreambox"
    if not model:
        model = machine
    info = image_info("/") or {}
    try:
        kernel = os.uname()[2]
        arch = os.uname()[4]
    except Exception:
        kernel = arch = ""
    return {
        "brand": brand or "?", "model": model or "inconnu", "machine": machine or "inconnu",
        "vumodel": vu, "dreambox": dream, "image": info.get("label", "?"),
        "kernel": kernel, "arch": arch,
    }


def image_info(root):
    """Name/version/date of the image installed under root, or None when empty."""
    if not root or not os.path.isdir(root):
        return None
    iv = parse_kv(read_file(os.path.join(root, "etc/image-version")))
    distro = iv.get("distro") or iv.get("creator") or ""
    version = iv.get("imageversion") or iv.get("version") or ""
    date = ""
    for k in ("date", "build", "compile-date", "imagebuild"):
        m = re.search(r"(20\d{6})", iv.get(k, ""))
        if m:
            date = m.group(1)
            break
    if not date:
        m = re.match(r"(20\d{6})", read_file(os.path.join(root, "etc/version")).strip())
        if m:
            date = m.group(1)
    if not distro:
        issue = read_file(os.path.join(root, "etc/issue"))
        for line in issue.splitlines():
            parts = [p for p in line.replace("\\n", "").replace("\\l", "").split() if p]
            if len(parts) >= 2 and not line.lower().startswith(("welcome", "type")):
                distro, version = parts[0], version or parts[1]
                break
    if not distro:
        osr = parse_kv(read_file(os.path.join(root, "etc/os-release")))
        distro = osr.get("ID", "")
        version = version or osr.get("VERSION_ID", "")
    has_init = os.path.exists(os.path.join(root, "sbin/init")) or os.path.islink(os.path.join(root, "sbin/init"))
    if not distro and not has_init:
        return None
    nice = {"openatv": "OpenATV", "openpli": "OpenPLi", "openvix": "OpenViX", "openbh": "OpenBH",
            "egami": "EGAMI", "openspa": "OpenSPA", "pure2": "PurE2", "teamblue": "teamBlue",
            "openhdf": "OpenHDF", "opendroid": "OpenDroid", "openvision": "OpenVision",
            "novaler": "Novaler", "dreamos": "DreamOS", "merlin": "Merlin", "satlodge": "SatLodge"}
    name = nice.get(distro.lower(), distro or "Image")
    modules = []
    try:
        modules = sorted(os.listdir(os.path.join(root, "lib/modules")))
    except Exception:
        pass
    return {
        "distro": name, "version": version, "date": date, "box": iv.get("box_type") or iv.get("machinebuild", ""),
        "label": ("%s %s" % (name, version)).strip(), "has_init": has_init, "modules": modules,
    }


# --------------------------------------------------------------------------- mounts

def mounts():
    out = []
    for line in read_file("/proc/mounts").splitlines():
        p = line.split()
        if len(p) >= 4:
            out.append({"device": p[0], "mount": p[1].replace("\\040", " "), "fstype": p[2], "opts": p[3]})
    return out


def storages():
    """Mounted storage devices usable for images/backups (/media/*)."""
    seen, out = set(), []
    for m in mounts():
        mp = m["mount"]
        if not mp.startswith("/media/") or m["fstype"] in ("tmpfs", "proc", "sysfs", "devtmpfs", "autofs"):
            continue
        if not m["device"].startswith("/dev/") or mp.startswith(("/media/flash", "/media/omb")):
            continue
        if not os.path.isdir(mp) or m["device"] in seen:
            continue
        seen.add(m["device"])
        free, total = fs_usage(mp)
        out.append({"name": os.path.basename(mp), "mount": mp, "device": m["device"], "fstype": m["fstype"],
                    "free": free, "total": total, "linux": m["fstype"] in LINUX_FS,
                    "rw": "rw" in m["opts"].split(",")})
    return out


def storage_for(path):
    best = None
    rp = os.path.realpath(path)
    for s in storages():
        if rp == s["mount"] or rp.startswith(s["mount"] + "/"):
            if best is None or len(s["mount"]) > len(best["mount"]):
                best = s
    return best


_blkid_cache = {"t": 0, "map": {}}


def blkid_map():
    if time.time() - _blkid_cache["t"] < 20:
        return _blkid_cache["map"]
    res = {}
    rc, out = run(["blkid"], timeout=20)
    for line in out.splitlines():
        if ":" not in line:
            continue
        dev, rest = line.split(":", 1)
        res[dev.strip()] = dict(re.findall(r'(\w+)="([^"]*)"', rest))
    _blkid_cache.update(t=time.time(), map=res)
    return res


def uuid_of(dev):
    return blkid_map().get(dev, {}).get("UUID", "")


def resolve_dev(spec):
    """'/dev/x', 'UUID=..', 'PARTUUID=..', 'LABEL=..', 'PARTLABEL=..' -> '/dev/x' or ''."""
    spec = (spec or "").strip()
    if spec.startswith("/dev/"):
        return os.path.realpath(spec) if os.path.exists(spec) else spec
    if "=" in spec:
        key, val = spec.split("=", 1)
        for dev, attrs in blkid_map().items():
            if attrs.get(key) == val:
                return dev
        if key == "PARTLABEL" and os.path.exists("/dev/block/by-name/" + val):
            return os.path.realpath("/dev/block/by-name/" + val)
    return ""


def cmdline():
    return read_file("/proc/cmdline").strip()


def cmdline_arg(name):
    m = re.search(r"(?:^|\s)%s=(\S+)" % re.escape(name), cmdline())
    return m.group(1) if m else ""


def dev_rdev(dev):
    try:
        return os.stat(dev).st_rdev
    except Exception:
        return None


def running_from_dev(dev):
    r = dev_rdev(dev)
    try:
        return r is not None and os.stat("/").st_dev == r
    except Exception:
        return False


_mnt_counter = [0]


class TempMount(object):
    """Mount a block device for the duration of a with-block (reuses an existing
    visible mount point). Read-only unless rw=True."""

    def __init__(self, device, rw=False, fstypes=("ext4", "vfat", "ext3", "ext2", "auto")):
        self.device, self.rw, self.fstypes = device, rw, fstypes
        self.path, self.mine = None, False

    def __enter__(self):
        real = os.path.realpath(self.device)
        for m in mounts():
            if os.path.realpath(m["device"]) == real or (m["device"] == "/dev/root" and running_from_dev(real)):
                mp = m["mount"]
                if os.path.isdir(os.path.join(mp, ".")) and (not self.rw or "rw" in m["opts"].split(",")):
                    try:
                        os.listdir(mp)
                        if mp == "/" or os.stat(mp).st_dev == dev_rdev(real) or m["device"] != "/dev/root":
                            self.path = mp
                            return mp
                    except Exception:
                        pass
        _mnt_counter[0] += 1
        path = "/tmp/wmb-mnt-%d-%d" % (os.getpid(), _mnt_counter[0])
        try:
            os.makedirs(path)
        except OSError:
            pass
        busy = False
        for fs in self.fstypes:
            args = ["mount", "-t", fs] + ([] if self.rw else ["-o", "ro"]) + [self.device, path]
            rc, out = run(args, timeout=30)
            if rc == 0:
                self.path, self.mine = path, True
                return path
            busy = busy or "busy" in out.lower()
        if busy and not self.rw:
            # already mounted read-write elsewhere (hidden mount point): a second
            # mount shares the same superblock, nothing is written.
            rc, out = run(["mount", "-t", "ext4", self.device, path], timeout=30)
            if rc == 0:
                self.path, self.mine = path, True
                return path
        try:
            os.rmdir(path)
        except Exception:
            pass
        raise MBError("Impossible de monter %s" % self.device)

    def __exit__(self, *exc):
        if self.mine and self.path:
            sync()
            rc, out = run(["umount", self.path], timeout=30)
            if rc != 0:
                run(["umount", "-l", self.path], timeout=30)
            try:
                os.rmdir(self.path)
            except Exception:
                pass
        return False


# --------------------------------------------------------------------------- job

class Job(object):
    """State shared between a worker thread and the GUI (the GUI polls it)."""

    def __init__(self, title):
        self.title = title
        self.progress = 0
        self.step = ""
        self.lines = []
        self.done = False
        self.ok = False
        self.result = ""
        self.cancelled = False
        self.cancellable = True
        self.proc = None
        self._lock = threading.Lock()

    def say(self, msg, progress=None):
        with self._lock:
            self.step = msg
            self.lines.append(msg)
            self.lines = self.lines[-40:]
            if progress is not None:
                self.progress = max(0, min(100, int(progress)))
        log("[%s] %s" % (self.title, msg))

    def set_progress(self, p):
        self.progress = max(0, min(100, int(p)))

    def check(self):
        if self.cancelled:
            raise Cancelled("Opération annulée.")

    def cancel(self):
        if self.cancellable:
            self.cancelled = True
            try:
                if self.proc:
                    self.proc.kill()
            except Exception:
                pass

    def start(self, func, *args):
        def runner():
            try:
                res = func(self, *args)
                self.ok, self.result = True, res or "Terminé."
            except MBError as e:
                self.ok, self.result = False, str(e)
                log("job error: %s" % e)
            except Exception as e:
                import traceback
                log("job crash: %s" % traceback.format_exc())
                self.ok, self.result = False, "Erreur inattendue : %s" % e
            self.progress = 100 if self.ok else self.progress
            self.done = True
        t = threading.Thread(target=runner, name="WMultiBootJob")
        t.daemon = True
        t.start()
        return self


# --------------------------------------------------------------------------- slots

class Slot(object):
    def __init__(self, key, number, kind, **kw):
        self.key = key
        self.number = number
        self.kind = kind                    # flash | chroot | emmc | recovery | omb
        self.root = kw.get("root")          # readable path of the rootfs (when mounted/visible)
        self.device = kw.get("device", "")
        self.reldir = kw.get("reldir", "")
        self.info = kw.get("info")
        self.running = kw.get("running", False)
        self.next_boot = kw.get("next_boot", False)
        self.bootable = kw.get("bootable", True)
        self.deletable = kw.get("deletable", False)
        self.installable = kw.get("installable", False)
        self.where = kw.get("where", "")
        self.extra = kw.get("extra", {})
        self.size_mb = None

    @property
    def empty(self):
        return not self.info

    def title(self):
        if self.kind == "recovery":
            return "Recovery"
        if not self.info:
            return "Slot vide"
        return self.info["label"]

    def subtitle(self):
        parts = []
        if self.info:
            if self.info.get("date"):
                parts.append(fmt_date(self.info["date"]))
        parts.append(self.where)
        return "  ·  ".join([p for p in parts if p])

    def status(self):
        if self.running:
            return "EN COURS"
        if self.next_boot:
            return "PROCHAIN DÉMARRAGE"
        if self.kind == "recovery":
            return "RECOVERY"
        if self.empty:
            return "VIDE"
        return ""


def guard_not_running(slot):
    if slot.running or (slot.root and is_running_root(slot.root)):
        raise MBError("Ce slot est l'image en cours d'utilisation : action refusée.")


class FlashProbe(object):
    """What is on the internal flash rootfs (seen from flash or from a chroot slot)."""

    def __init__(self):
        self.device = resolve_dev(cmdline_arg("root")) or ""
        self.on_flash = bool(self.device) and running_from_dev(self.device)
        self.init_target = ""
        self.has_omb_init = False
        self.boot_conf = None
        self.info = None
        self.error = ""
        if not self.device:
            return
        try:
            with TempMount(self.device) as root:
                init = os.path.join(root, "sbin/init")
                if os.path.islink(init):
                    self.init_target = os.readlink(init)
                self.has_omb_init = os.path.isfile(os.path.join(root, "sbin/omb-init"))
                conf = os.path.join(root, "etc/omb/boot.conf")
                if os.path.exists(conf):
                    self.boot_conf = parse_kv(read_file(conf))
                self.info = image_info(root)
        except MBError as e:
            self.error = str(e)
        except Exception as e:
            self.error = str(e)
            log("flash probe: %s" % e)


# --------------------------------------------------------------------------- layouts

class Layout(object):
    key = "none"
    name = "Aucun multiboot"
    caps = ()                               # subset of boot, once, install, delete, backup
    new_slots = False                       # install creates a new slot (vs. into a chosen slot)

    def __init__(self, box, probe):
        self.box, self.probe = box, probe
        self.slots = []
        self.notes = []

    def scan(self):
        raise NotImplementedError

    def can(self, cap):
        return cap in self.caps

    def running_slot(self):
        for s in self.slots:
            if s.running:
                return s
        return None

    def next_slot(self):
        for s in self.slots:
            if s.next_boot:
                return s
        return None

    # -- actions (override)
    def set_next(self, job, slot, once=False):
        raise MBError("Le choix du slot de démarrage n'est pas pris en charge ici.")

    def install_targets(self):
        """[(label, device_mount)] where a new slot can be created."""
        return []

    def install(self, job, image, slot=None, target=None, name=None):
        raise MBError("L'installation n'est pas prise en charge sur ce récepteur.")

    def delete(self, job, slot):
        raise MBError("La suppression n'est pas prise en charge sur ce récepteur.")

    # -- common helpers
    def check_bootable(self, slot):
        if not slot.bootable:
            raise MBError("Ce slot ne peut pas être démarré.")
        if slot.kind not in ("flash", "recovery") and slot.empty:
            raise MBError("Ce slot est vide : installez d'abord une image.")
        if slot.root and slot.kind != "flash" and not (os.path.exists(os.path.join(slot.root, "sbin/init"))
                                                     or os.path.islink(os.path.join(slot.root, "sbin/init"))):
            raise MBError("Image incomplète : /sbin/init est absent.")

    def warnings_for(self, slot):
        w = []
        if slot.info and slot.info.get("box") and self.box["machine"] not in ("", "inconnu") \
                and slot.info["box"] != self.box["machine"]:
            w.append("Image prévue pour %s (ce récepteur : %s)." % (slot.info["box"], self.box["machine"]))
        return w

    def backup(self, job, slot, dest_mount):
        return backup_tree(job, slot, dest_mount, self)


class SingleLayout(Layout):
    key = "single"
    name = "Image unique (pas de multiboot)"
    caps = ("backup",)

    def scan(self):
        info = image_info("/")
        self.slots = [Slot("flash", 1, "flash", root="/", info=info, running=True, next_boot=True,
                           where="Flash", device=self.probe.device)]
        self.notes.append("Aucune structure multiboot n'a été trouvée sur ce récepteur.")


class DreamboxLayout(SingleLayout):
    key = "dreambox"
    name = "Dreambox"

    def scan(self):
        SingleLayout.scan(self)
        self.notes = ["Dreambox : le multiboot se gère avec le menu de démarrage Dreambox. "
                      "Ce plugin affiche l'image et permet la sauvegarde."]


class ChrootLayout(Layout):
    """Flash /sbin/init -> omb-init, which chroots into <device>/<SLOT_DIR> read from
    flash:/etc/omb/boot.conf (OnlineMultiBoot format). Used on the Vu+ Zero 4K."""
    key = "chroot"
    name = "Multiboot HDD/USB (omb-init)"
    caps = ("boot", "once", "install", "delete", "backup")
    new_slots = True

    @classmethod
    def detect(cls, box, probe):
        if probe.has_omb_init and "omb-init" in probe.init_target:
            return cls(box, probe)
        return None

    def scan(self):
        p = self.probe
        conf = p.boot_conf or {}
        nxt_dir = conf.get("SLOT_DIR", "")
        nxt_uuid = conf.get("SLOT_UUID", "")
        if conf.get("SLOT_NAME") and not nxt_dir:
            nxt_dir = "OnlineMultiBoot/images/" + conf["SLOT_NAME"]
        flash = Slot("flash", 0, "flash", info=p.info, device=p.device, running=p.on_flash,
                     next_boot=not (nxt_uuid and nxt_dir), where="Flash interne")
        flash.extra["once"] = conf.get("ONCE") == "1"
        slots = [flash]
        n = 0
        for st in storages():
            if not st["linux"]:
                continue
            uuid = uuid_of(st["device"])
            for base in CHROOT_BASES:
                d = os.path.join(st["mount"], base)
                try:
                    names = sorted(os.listdir(d))
                except Exception:
                    continue
                for name in names:
                    path = os.path.join(d, name)
                    if name.startswith(".") or name.endswith(".partial") or name == "flash" or not os.path.isdir(path):
                        continue
                    if os.path.islink(path):
                        continue
                    info = image_info(path)
                    if not info:
                        continue
                    n += 1
                    rel = base + "/" + name
                    slots.append(Slot("%s:%s" % (st["device"], rel), n, "chroot", root=path,
                                      device=st["device"], reldir=rel, info=info,
                                      running=is_running_root(path),
                                      next_boot=bool(nxt_dir) and rel == nxt_dir and (not nxt_uuid or nxt_uuid == uuid),
                                      deletable=True, where="%s/%s" % (st["mount"], rel),
                                      extra={"uuid": uuid, "name": name}))
        if conf.get("ONCE") == "1":
            for s in slots:
                if s.next_boot and s.kind != "flash":
                    s.extra["once"] = True
        self.slots = slots
        if p.error:
            self.notes.append("Flash : %s" % p.error)
        if not any(s.kind == "chroot" for s in slots):
            self.notes.append("Aucune image installée sur HDD/USB.")

    def set_next(self, job, slot, once=False):
        self.check_bootable(slot)
        if slot.kind == "flash":
            text = ""
        else:
            uuid = uuid_of(slot.device) or slot.extra.get("uuid")
            if not uuid:
                raise MBError("UUID introuvable pour %s." % slot.device)
            if ".." in slot.reldir or slot.reldir.startswith("/"):
                raise MBError("Chemin de slot invalide.")
            text = 'SLOT_UUID="%s"\nSLOT_NAME="%s"\nSLOT_DIR="%s"\nONCE=%d\nWAIT=15\n' % (
                uuid, slot.extra.get("name", ""), slot.reldir, 1 if once else 0)
        job.say("Écriture du choix de démarrage dans la flash…", 30)
        with TempMount(self.probe.device, rw=True) as root:
            if not os.path.isfile(os.path.join(root, "sbin/omb-init")):
                raise MBError("Le gestionnaire de démarrage (omb-init) est absent de la flash.")
            conf_dir = os.path.join(root, "etc/omb")
            if not os.path.isdir(conf_dir):
                os.makedirs(conf_dir)
            path = os.path.join(conf_dir, "boot.conf")
            write_file(path, text)
            if read_file(path) != text:
                raise MBError("Vérification de l'écriture impossible.")
        job.say("Prochain démarrage : %s%s" % (slot.title(), " (une seule fois)" if once else ""), 100)
        return "Prochain démarrage : %s%s." % (slot.title(), " (une seule fois)" if once else "")

    def install_targets(self):
        return [st for st in storages() if st["linux"] and st["rw"]]

    def install(self, job, image, slot=None, target=None, name=None):
        if not target:
            raise MBError("Aucun disque cible choisi.")
        base = os.path.join(target["mount"], "OnlineMultiBoot/images")
        name = sanitize(name or image_base_name(image))
        dest = os.path.join(base, name)
        i = 2
        while os.path.exists(dest):
            dest = os.path.join(base, "%s_%d" % (name, i))
            i += 1
        rootfs, kernel, cleanup = prepare_image(job, image, target["mount"], self.box)
        try:
            extract_rootfs(job, rootfs, dest, self.box)
        finally:
            for f in cleanup:
                remove_quiet(f)
        fix_chroot_slot(dest, os.path.basename(dest))
        warn = modules_warning(dest, self.box)
        msg = "Image installée : %s" % os.path.basename(dest)
        if warn:
            msg += "\n" + warn
        job.say(msg, 100)
        return msg

    def delete(self, job, slot):
        guard_not_running(slot)
        if slot.kind != "chroot":
            raise MBError("Seules les images sur HDD/USB peuvent être supprimées.")
        if slot.next_boot:
            raise MBError("Ce slot est choisi pour le prochain démarrage. Choisissez d'abord un autre slot.")
        safe_rmtree(job, slot.root, slot.reldir)
        return "Slot supprimé : %s" % slot.title()


class OmbClassicLayout(Layout):
    """Classic OpenMultiboot: flash /sbin/init -> open_multiboot, data dir
    <device>/open-multiboot, selection in .<box>-selected, kernels in .kernels/."""
    key = "omb"
    name = "OpenMultiboot"
    caps = ("boot", "install", "delete", "backup")
    new_slots = True

    @classmethod
    def detect(cls, box, probe):
        t = os.path.basename(probe.init_target or "")
        if "open_multiboot" in t or "open-multiboot" in t:
            lay = cls(box, probe)
            if lay.data_dir():
                return lay
        return None

    def data_dir(self):
        for st in storages():
            d = os.path.join(st["mount"], "open-multiboot")
            if os.path.isdir(d):
                return d
        return None

    def scan(self):
        d = self.data_dir()
        box = self.box["machine"]
        sel = read_file(os.path.join(d, ".%s-selected" % box)).strip() if d else ""
        flash_id = "%s-flash" % box
        self.slots = [Slot("flash", 0, "flash", info=self.probe.info, device=self.probe.device,
                           running=self.probe.on_flash, next_boot=sel in ("", flash_id),
                           where="Flash interne", extra={"name": flash_id})]
        n = 0
        st = storage_for(d) if d else None
        for name in sorted(os.listdir(d)) if d else []:
            path = os.path.join(d, name)
            if name.startswith(".") or name == "flash" or name.endswith(".partial") or not os.path.isdir(path):
                continue
            info = image_info(path)
            if not info:
                continue
            n += 1
            self.slots.append(Slot("omb:" + name, n, "omb", root=path, info=info, device=st and st["device"],
                                   reldir="open-multiboot/" + name, running=is_running_root(path),
                                   next_boot=(sel == name), deletable=True,
                                   where="%s/open-multiboot/%s" % (st and st["mount"] or "", name),
                                   extra={"name": name}))

    def set_next(self, job, slot, once=False):
        self.check_bootable(slot)
        d = self.data_dir()
        if not d:
            raise MBError("Dossier open-multiboot introuvable.")
        name = slot.extra["name"]
        if slot.kind != "flash" and not os.path.isfile(os.path.join(d, ".kernels", name + ".bin")):
            raise MBError("Noyau absent pour ce slot (.kernels/%s.bin)." % name)
        write_file(os.path.join(d, ".%s-selected" % self.box["machine"]), name)
        job.say("Prochain démarrage : %s" % slot.title(), 100)
        return "Prochain démarrage : %s." % slot.title()

    def install_targets(self):
        d = self.data_dir()
        st = storage_for(d) if d else None
        return [st] if st and st["rw"] else []

    def install(self, job, image, slot=None, target=None, name=None):
        d = self.data_dir()
        if not d:
            raise MBError("Dossier open-multiboot introuvable.")
        name = sanitize(name or image_base_name(image))
        dest = os.path.join(d, name)
        i = 2
        while os.path.exists(dest):
            dest = os.path.join(d, "%s_%d" % (name, i))
            i += 1
        rootfs, kernel, cleanup = prepare_image(job, image, storage_for(d)["mount"], self.box)
        try:
            if not kernel:
                raise MBError("Aucun noyau (kernel) trouvé dans l'image.")
            extract_rootfs(job, rootfs, dest, self.box)
            kd = os.path.join(d, ".kernels")
            if not os.path.isdir(kd):
                os.makedirs(kd)
            shutil.copyfile(kernel, os.path.join(kd, os.path.basename(dest) + ".bin"))
            sync()
        finally:
            for f in cleanup:
                remove_quiet(f)
        return "Image installée : %s" % os.path.basename(dest)

    def delete(self, job, slot):
        guard_not_running(slot)
        if slot.kind != "omb":
            raise MBError("La flash ne peut pas être supprimée.")
        if slot.next_boot:
            raise MBError("Ce slot est choisi pour le prochain démarrage. Choisissez d'abord un autre slot.")
        safe_rmtree(job, slot.root, slot.reldir)
        remove_quiet(os.path.join(self.data_dir(), ".kernels", slot.extra["name"] + ".bin"))
        return "Slot supprimé : %s" % slot.title()


STARTUP_DEV_CANDIDATES = (
    "/dev/block/by-name/bootoptions", "/dev/block/by-name/boot", "/dev/block/by-name/startup",
    "/dev/mmcblk0p1", "/dev/mmcblk1p1", "/dev/mmcblk0p3", "/dev/mmcblk0p4", "/dev/sda1",
)
RAW_LABELS = ("nvram", "macadr", "devtree", "kernel", "initrd", "splash", "rootfs", "userdata",
              "misc", "recovery", "dtb", "logo", "rpmb")


def parse_startup(text):
    t = text.replace("\n", " ")
    d = {"raw": text.strip()}
    for k in ("kernel", "root", "rootsubdir", "rootfstype"):
        m = re.search(r"(?:^|[\s'\"])%s=([^\s'\"]+)" % k, t)
        if m:
            d[k] = m.group(1)
    m = re.search(r"emmcflash0\.(\w+)", t)       # GigaBlue / HiSilicon style
    if m and "kernel" not in d:
        d["kernel"] = "/dev/block/by-name/" + m.group(1)
    return d


class StartupLayout(Layout):
    """OpenATV/OpenPLi style eMMC multiboot: STARTUP_<n> files on a small boot
    partition, STARTUP is a copy of the selected one. Used by GigaBlue, Zgemma,
    Octagon, Edision, Dinobot, Vu+ 4K (kexec) and others."""
    key = "startup"
    name = "Multiboot eMMC (STARTUP)"
    caps = ("boot", "install", "delete", "backup")

    @classmethod
    def detect(cls, box, probe):
        dev = cls.find_boot_device()
        if dev:
            lay = cls(box, probe)
            lay.boot_dev = dev
            return lay
        return None

    @staticmethod
    def find_boot_device():
        cands = []
        for d in STARTUP_DEV_CANDIDATES:
            if os.path.exists(d):
                r = os.path.realpath(d)
                if r not in cands:
                    cands.append(r)
        bm = blkid_map()
        for dev, attrs in sorted(bm.items()):
            lab = attrs.get("PARTLABEL", attrs.get("LABEL", "")).lower()
            if lab in ("boot", "bootoptions", "startup") and dev not in cands:
                cands.insert(0, dev)
        root_dev = resolve_dev(cmdline_arg("root"))
        for dev in cands:
            attrs = bm.get(dev, {})
            lab = attrs.get("PARTLABEL", "").lower()
            if dev == root_dev or (lab in RAW_LABELS and attrs.get("TYPE") is None):
                continue
            if attrs and attrs.get("TYPE") not in (None, "vfat", "ext4", "ext2", "ext3"):
                continue
            try:
                with TempMount(dev, fstypes=("vfat", "ext4")) as mp:
                    names = os.listdir(mp)
                    if any(re.match(r"STARTUP_(\d+|LINUX_\d+.*|RECOVERY|ANDROID.*)$", n) for n in names):
                        return dev
            except Exception:
                continue
        return None

    def scan(self):
        files, current = {}, ""
        with TempMount(self.boot_dev, fstypes=("vfat", "ext4")) as mp:
            for n in sorted(os.listdir(mp)):
                if n.startswith("STARTUP_"):
                    files[n] = read_file(os.path.join(mp, n))
            current = read_file(os.path.join(mp, "STARTUP"))
        cur_norm = " ".join(current.split())
        run_root = resolve_dev(cmdline_arg("root"))
        run_sub = cmdline_arg("rootsubdir")
        groups = {}
        for fn, text in files.items():
            m = re.match(r"STARTUP_(\d+)$", fn) or re.match(r"STARTUP_LINUX_(\d+)(?:_BOXMODE_(\d+))?$", fn)
            if m:
                num = int(m.group(1))
                mode = m.groups()[1] if len(m.groups()) > 1 else None
                prev = groups.get(num)
                if prev is None or (mode == "1" and prev[2] != "1") or (not mode and prev[2]):
                    groups[num] = (fn, text, mode)
        slots = []
        mounted = {}
        for num in sorted(groups):
            fn, text, mode = groups[num]
            p = parse_startup(text)
            root = resolve_dev(p.get("root", ""))
            sub = p.get("rootsubdir", "")
            same_variant = [f for f, t in files.items()
                            if re.match(r"STARTUP_(LINUX_)?%d(_|$)" % num, f) and " ".join(t.split()) == cur_norm]
            s = Slot(fn, num, "emmc", device=root, reldir=sub, next_boot=bool(same_variant),
                     running=bool(root) and root == run_root and sub == run_sub,
                     deletable=bool(sub), installable=bool(sub),
                     where="%s%s" % (root.replace("/dev/", ""), ("/" + sub) if sub else ""),
                     extra={"file": fn, "startup": p, "mode": mode,
                            "files": [f for f in files if re.match(r"STARTUP_(LINUX_)?%d(_|$)" % num, f)]})
            if root and os.path.exists(root):
                try:
                    if root not in mounted:
                        tm = TempMount(root, fstypes=("ext4", "ext3", "ext2"))
                        mounted[root] = (tm, tm.__enter__())
                    path = os.path.join(mounted[root][1], sub) if sub else mounted[root][1]
                    s.info = image_info(path)
                except Exception as e:
                    log("slot %s: %s" % (fn, e))
            slots.append(s)
        for tm, _ in mounted.values():
            tm.__exit__(None, None, None)
        for fn in ("STARTUP_RECOVERY", "STARTUP_ONCE"):
            if fn in files and fn == "STARTUP_RECOVERY":
                slots.append(Slot(fn, "R", "recovery", next_boot=" ".join(files[fn].split()) == cur_norm,
                                  where="Recovery", extra={"file": fn}))
        if not any(s.running for s in slots):
            self.notes.append("Slot en cours non identifié (cmdline root=%s)." % (run_root or "?"))
        self.slots = slots

    def set_next(self, job, slot, once=False):
        self.check_bootable(slot)
        fn = slot.extra.get("file")
        with TempMount(self.boot_dev, rw=True, fstypes=("vfat", "ext4")) as mp:
            src = os.path.join(mp, fn)
            text = read_file(src)
            if not text.strip():
                raise MBError("Fichier %s vide ou illisible." % fn)
            write_file(os.path.join(mp, "STARTUP"), text)
            if read_file(os.path.join(mp, "STARTUP")) != text:
                raise MBError("Vérification de l'écriture impossible.")
        job.say("Prochain démarrage : slot %s" % slot.number, 100)
        return "Prochain démarrage : slot %s (%s)." % (slot.number, slot.title())

    def _check_slot_target(self, slot):
        guard_not_running(slot)
        if slot.kind != "emmc" or not slot.reldir:
            raise MBError("Ce slot n'utilise pas de sous-dossier (linuxrootfsN) : installation refusée.")
        run_slot = self.running_slot()
        k = slot.extra["startup"].get("kernel", "")
        if run_slot and k and k == run_slot.extra.get("startup", {}).get("kernel"):
            raise MBError("Ce slot partage le noyau de l'image en cours : action refusée.")
        if not slot.device or not os.path.exists(slot.device):
            raise MBError("Partition du slot introuvable.")

    def install(self, job, image, slot=None, target=None, name=None):
        if not slot:
            raise MBError("Choisissez d'abord un slot.")
        self._check_slot_target(slot)
        work = [s for s in storages() if s["linux"] and s["rw"]]
        stage = max(work, key=lambda s: s["free"])["mount"] if work else "/tmp"
        rootfs, kernel, cleanup = prepare_image(job, image, stage, self.box)
        try:
            if not kernel:
                raise MBError("Aucun noyau (kernel) trouvé dans l'image.")
            with TempMount(slot.device, rw=True, fstypes=("ext4",)) as mp:
                dest = os.path.join(mp, slot.reldir)
                if is_running_root(dest):
                    raise MBError("Ce slot est l'image en cours d'utilisation : action refusée.")
                if os.path.exists(dest):
                    job.say("Effacement de l'ancien contenu du slot…", 2)
                    safe_rmtree(job, dest, slot.reldir)
                extract_rootfs(job, rootfs, dest, self.box)
                write_kernel(job, kernel, slot.extra["startup"].get("kernel", ""), mp)
        finally:
            for f in cleanup:
                remove_quiet(f)
        return "Image installée dans le slot %s." % slot.number

    def delete(self, job, slot):
        self._check_slot_target(slot)
        if slot.next_boot:
            raise MBError("Ce slot est choisi pour le prochain démarrage. Choisissez d'abord un autre slot.")
        with TempMount(slot.device, rw=True, fstypes=("ext4",)) as mp:
            dest = os.path.join(mp, slot.reldir)
            if os.path.isdir(dest):
                safe_rmtree(job, dest, slot.reldir)
                os.makedirs(dest)
        return "Slot %s vidé." % slot.number

    def backup(self, job, slot, dest_mount):
        if slot.kind != "emmc":
            raise MBError("Ce slot ne peut pas être sauvegardé.")
        with TempMount(slot.device, fstypes=("ext4", "ext3", "ext2")) as mp:
            s2 = Slot(slot.key, slot.number, slot.kind, root=os.path.join(mp, slot.reldir) if slot.reldir else mp,
                      info=slot.info, running=slot.running)
            return backup_tree(job, s2, dest_mount, self)


def detect_layout(box=None):
    """Return a scanned Layout. Never raises (falls back to SingleLayout)."""
    box = box or box_info()
    probe = FlashProbe()
    order = (StartupLayout, ChrootLayout, OmbClassicLayout)
    if box.get("dreambox"):
        order = ()
    for cls in order:
        try:
            lay = cls.detect(box, probe)
            if lay:
                lay.scan()
                log("layout: %s, %d slots" % (lay.key, len(lay.slots)))
                return lay
        except Exception as e:
            import traceback
            log("detect %s failed: %s" % (cls.__name__, traceback.format_exc()))
    lay = (DreamboxLayout if box.get("dreambox") else SingleLayout)(box, probe)
    try:
        lay.scan()
    except Exception as e:
        log("single scan failed: %s" % e)
        lay.slots = []
        lay.notes.append("Lecture de l'image impossible : %s" % e)
    return lay


# --------------------------------------------------------------------------- images

def image_base_name(path):
    b = os.path.basename(path.split("?")[0].rstrip("/"))
    for ext in IMAGE_EXT:
        if b.lower().endswith(ext):
            return b[:-len(ext)]
    return b


OPENATV_JSON = "https://images.mynonpublic.com/openatv/json/%s"
DISTROS_JSON = "https://raw.githubusercontent.com/OpenATV/FlashImage/gh-pages/%s.json"
CATALOG_DIR = "/tmp/wmb-catalog"
EXTRA_FEEDS = (("OpenPLi", "https://downloads.openpli.org/json/%s"),
               ("OpenViX", "https://www.openvix.co.uk/json/%s"),
               ("OpenBH", "https://images.openbh.net/json/%s"),
               ("OpenSPA", "https://openspa.webhop.info/online/json.php?box=%s"),
               ("EGAMI", "https://image.egami-image.com/json/%s"),
               ("teamBlue", "https://images.teamblue.tech/json/%s"))


def _fetch(url, dest):
    remove_quiet(dest)
    if which("wget"):
        rc, out = run(["wget", "-q", "-T", "20", "-t", "2", "-O", dest, url], timeout=60)
    else:
        rc, out = run(["curl", "-sfL", "--max-time", "40", "-o", dest, url], timeout=60)
    return rc == 0 and os.path.isfile(dest) and os.path.getsize(dest) > 0


def parse_catalog(text, distro):
    """Image list JSON ({group: {key: {link, name, size, date}}}) -> [item]."""
    import json
    try:
        data = json.loads(text.lstrip(u"﻿"))
    except Exception:
        return []
    items = []
    if not isinstance(data, dict):
        return items
    for group, imgs in data.items():
        if not isinstance(imgs, dict):
            continue
        for meta in imgs.values():
            if not isinstance(meta, dict):
                continue
            link = meta.get("link") or ""
            if not re.match(r"^https?://[^\s'\"<>]+\.zip$", link):
                continue
            try:
                size, date = int(meta.get("size") or 0), int(meta.get("date") or 0)
            except (TypeError, ValueError):
                size, date = 0, 0
            name = meta.get("name") or os.path.basename(link)
            m = re.search(r"(20\d{6})", name)
            day = fmt_date(m.group(1)) if m else (time.strftime("%d/%m/%Y", time.localtime(date)) if date else "")
            items.append({"distro": distro, "group": str(group), "name": name, "url": link,
                          "size": size, "date": date, "day": day,
                          "eol": "eol" in str(group).lower(), "beta": "beta" in str(group).lower()})
    items.sort(key=lambda i: (i["eol"], i["beta"] or "beta" in i["name"].lower(), -i["date"]))
    return items


def fetch_catalog(job, machine):
    """Online images for this receiver, like the Octagon / OpenATV flash-online list.
    Returns [(distro, [items])], OpenATV first."""
    if not machine or machine == "inconnu":
        raise MBError("Modèle du récepteur inconnu : liste d'images en ligne indisponible.")
    if not os.path.isdir(CATALOG_DIR):
        os.makedirs(CATALOG_DIR)
    sources = [("OpenATV", OPENATV_JSON % machine)] + [(n, u % machine) for n, u in EXTRA_FEEDS]
    job.say("Recherche des distributions disponibles…", 5)
    dl = os.path.join(CATALOG_DIR, "distros.json")
    if _fetch(DISTROS_JSON % machine, dl):
        import json
        try:
            for entry in json.loads(read_file(dl)):
                name, url = entry[0], entry[1]
                if name.lower() not in [x[0].lower() for x in sources] and re.match(r"^https://[^\s'\"<>]+$", url or ""):
                    sources.append((re.sub(r"[^\w .+-]", "", name)[:30] or "Image", url))
        except Exception as e:
            log("distros.json: %s" % e)
    out = []
    for n, (distro, url) in enumerate(sources):
        job.check()
        job.say("Lecture du catalogue %s…" % distro, 10 + 85 * n // max(1, len(sources)))
        dest = os.path.join(CATALOG_DIR, "%d.json" % n)
        if _fetch(url, dest):
            items = parse_catalog(read_file(dest), distro)
            if items:
                out.append((distro, items))
        remove_quiet(dest)
    if not out:
        raise MBError("Aucune image en ligne trouvée pour %s (pas de connexion Internet ?)." % machine)
    total = sum(len(i) for _, i in out)
    job.say("%d images trouvées dans %d distributions." % (total, len(out)), 100)
    return out


def find_local_images():
    """[(label, path, size_mb)] archives that look like images or slot backups."""
    dirs = ["/tmp"]
    for st in storages():
        for sub in ("", "images", "imagebackups", "downloads", "OnlineMultiBoot/downloads",
                    DATA_DIR + "/downloads", DATA_DIR + "/backups", "backup"):
            dirs.append(os.path.join(st["mount"], sub))
    seen, out = set(), []
    for d in dirs:
        try:
            names = os.listdir(d)
        except Exception:
            continue
        for n in names:
            p = os.path.join(d, n)
            if not n.lower().endswith(IMAGE_EXT) or n.endswith(".partial") or not os.path.isfile(p):
                continue
            rp = os.path.realpath(p)
            if rp in seen:
                continue
            try:
                size = os.path.getsize(p) // MB
                mtime = os.path.getmtime(p)
            except Exception:
                continue
            if size < 60:
                continue
            seen.add(rp)
            out.append((mtime, "%s   (%s, %s)" % (n, human_mb(size), d), p, size))
    out.sort(reverse=True)
    return [(lbl, p, s) for _, lbl, p, s in out]


def remove_quiet(path):
    try:
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path, ignore_errors=True)
        elif os.path.lexists(path):
            os.remove(path)
    except Exception:
        pass


def work_dir(mount, sub):
    d = os.path.join(mount, DATA_DIR, sub)
    if not os.path.isdir(d):
        os.makedirs(d)
    return d


def download(job, url, dest_mount):
    if not re.match(r"^https?://[^\s'\"<>]+$", url or ""):
        raise MBError("Adresse invalide : seules les URL http:// ou https:// sont acceptées.")
    d = work_dir(dest_mount, "downloads")
    name = sanitize(image_base_name(url)) + ".zip"
    for ext in IMAGE_EXT:
        if url.split("?")[0].lower().endswith(ext):
            name = sanitize(image_base_name(url)) + ext
    final = os.path.join(d, name)
    part = final + ".partial"
    job.say("Vérification de l'adresse…", 1)
    size = 0
    rc, out = run(["curl", "-sIL", "--max-time", "20", url], timeout=30) if which("curl") else \
        run(["wget", "-q", "-S", "--spider", "-T", "20", url], timeout=30)
    for m in re.finditer(r"(?im)^\s*content-length:\s*(\d+)", out):
        size = int(m.group(1))
    if re.search(r"(?im)^\s*HTTP/\S+\s+(4|5)\d\d", out) and not re.search(r"(?im)^\s*HTTP/\S+\s+200", out):
        raise MBError("Le serveur refuse le téléchargement (erreur HTTP).")
    need = (size // MB if size else 1024) + 200
    free, _ = fs_usage(dest_mount)
    if free < need:
        raise MBError("Espace insuffisant sur %s : %s libres, %s nécessaires." % (dest_mount, human_mb(free), human_mb(need)))
    job.say("Téléchargement de %s…" % name, 2)
    remove_quiet(part)
    if which("wget"):
        args = ["wget", "-q", "-T", "30", "-t", "3", "-O", part, url]
    else:
        args = ["curl", "-sfL", "--retry", "3", "--connect-timeout", "30", "-o", part, url]
    job.proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, close_fds=True)
    try:
        while job.proc.poll() is None:
            if job.cancelled:
                job.proc.kill()
                break
            if size:
                try:
                    job.set_progress(2 + 38 * os.path.getsize(part) / float(size))
                except Exception:
                    pass
            time.sleep(0.5)
        rc = job.proc.wait()
    finally:
        job.proc = None
    if job.cancelled:
        remove_quiet(part)
        raise Cancelled("Téléchargement annulé.")
    if rc != 0 or not os.path.isfile(part) or os.path.getsize(part) == 0:
        remove_quiet(part)
        raise MBError("Échec du téléchargement (code %s)." % rc)
    if size and os.path.getsize(part) != size:
        remove_quiet(part)
        raise MBError("Téléchargement incomplet.")
    os.rename(part, final)
    job.say("Téléchargé : %s (%s)" % (name, human_mb(os.path.getsize(final) // MB)), 40)
    return final


def _box_tokens(box):
    toks = set([box.get("machine", ""), box.get("model", "")])
    if box.get("vumodel"):
        toks.update([box["vumodel"], "vu" + box["vumodel"]])
    return set([t.lower() for t in toks if t])


def prepare_image(job, image, stage_mount, box):
    """Return (rootfs_tarball, kernel_file_or_None, files_to_cleanup).
    image: local path or http(s) URL. Checks the archive before anything else."""
    cleanup = []
    if re.match(r"^https?://", image or ""):
        image = download(job, image, stage_mount)
        cleanup.append(image)           # a downloaded zip is removed once used (like Octagon)
    if not image or not os.path.isfile(image):
        raise MBError("Fichier image introuvable.")
    low = image.lower()
    if low.endswith(".zip"):
        try:
            zf = zipfile.ZipFile(image)
            names = zf.namelist()
        except Exception:
            raise MBError("Archive zip corrompue ou illisible : %s" % os.path.basename(image))
        roots = [n for n in names if re.search(r"(^|/)rootfs\.tar\.(bz2|xz|gz)$", n)]
        if not roots:
            if any(n.lower().endswith((".ubi", ".ubifs")) for n in names):
                raise MBError("Image UBI (mémoire NAND) : non prise en charge par le multiboot.")
            if any(n.lower().endswith(".nfi") for n in names):
                raise MBError("Image Dreambox (.nfi) : non prise en charge.")
            raise MBError("Aucun rootfs.tar.* trouvé dans l'archive : ce n'est pas une image multiboot.")
        toks = _box_tokens(box)
        if box.get("vumodel"):
            good = [r for r in roots if "/%s/" % box["vumodel"] in "/" + r or "/vu%s/" % box["vumodel"] in "/" + r]
            if not good and all(r.startswith("vuplus/") for r in roots):
                other = roots[0].split("/")[1] if "/" in roots[0] else "?"
                raise MBError("Cette image est pour le Vu+ %s, ce récepteur est un Vu+ %s." % (other, box["vumodel"]))
            roots = good or roots
        rootname = roots[0]
        folder = rootname.rsplit("/", 1)[0] + "/" if "/" in rootname else ""
        kernels = [n for n in names if n.startswith(folder) and "/" not in n[len(folder):]
                   and re.search(r"(kernel.*\.bin|uImage|zImage|kernel_auto\.bin|oe_kernel\.bin)$", n, re.I)]
        kernels.sort(key=lambda n: (0 if "kernel_auto" in n else 1 if n.lower().endswith("kernel.bin") else 2))
        info = zf.getinfo(rootname)
        need = (info.file_size + (zf.getinfo(kernels[0]).file_size if kernels else 0)) // MB + 50
        free, _ = fs_usage(stage_mount)
        if free < need:
            raise MBError("Espace insuffisant sur %s pour préparer l'image (%s nécessaires)." % (stage_mount, human_mb(need)))
        tmpd = work_dir(stage_mount, "tmp")
        out_root = os.path.join(tmpd, "rootfs." + rootname.rsplit(".", 1)[1])
        cleanup.append(out_root)
        job.say("Lecture de l'archive (contrôle CRC)…", 41)
        try:
            _zip_extract(job, zf, rootname, out_root, 41, 55)
            kernel = None
            if kernels:
                kernel = os.path.join(tmpd, "kernel.bin")
                cleanup.append(kernel)
                _zip_extract(job, zf, kernels[0], kernel, 55, 56)
        except Cancelled:
            for f in cleanup:
                remove_quiet(f)
            raise
        except MBError:
            for f in cleanup:
                remove_quiet(f)
            raise
        except Exception as e:
            for f in cleanup:
                remove_quiet(f)
            raise MBError("Archive zip corrompue (%s)." % e)
        _ = toks
        return out_root, kernel, cleanup
    if low.endswith((".tar.bz2", ".tbz2", ".tar.xz", ".tar.gz", ".tgz")):
        return image, None, cleanup
    raise MBError("Format non pris en charge (zip, tar.bz2, tar.xz, tar.gz).")


def _zip_extract(job, zf, member, out, p0, p1):
    info = zf.getinfo(member)
    total = max(1, info.file_size)
    done = 0
    src = zf.open(member)
    try:
        with open(out, "wb") as dst:
            while True:
                job.check()
                buf = src.read(1024 * 1024)
                if not buf:
                    break
                dst.write(buf)
                done += len(buf)
                job.set_progress(p0 + (p1 - p0) * done / float(total))
    except zipfile.BadZipfile as e:
        raise MBError("Archive zip corrompue : %s" % e)
    finally:
        src.close()
    if done != info.file_size:
        raise MBError("Archive zip tronquée.")


def _tar_flag(path):
    low = path.lower()
    if low.endswith((".bz2", ".tbz2")):
        return "j"
    if low.endswith(".xz"):
        return "J"
    if low.endswith((".gz", ".tgz")):
        return "z"
    return ""


def extract_rootfs(job, tarball, dest, box):
    """Extract tarball into dest via dest.partial (renamed only when valid)."""
    if is_running_root(dest):
        raise MBError("Destination = image en cours : action refusée.")
    parent = os.path.dirname(dest)
    if not os.path.isdir(parent):
        os.makedirs(parent)
    size = os.path.getsize(tarball) // MB
    factor = {"j": 3.4, "J": 3.6, "z": 2.6}.get(_tar_flag(tarball), 1.1)
    need = int(size * factor) + 150
    free, _ = fs_usage(parent)
    if free < need:
        raise MBError("Espace insuffisant sur le disque : %s libres, environ %s nécessaires."
                      % (human_mb(free), human_mb(need)))
    part = dest + ".partial"
    remove_quiet(part)
    os.makedirs(part)
    job.say("Extraction de l'image (%s)…" % human_mb(size), 57)
    flag = _tar_flag(tarball)
    args = ["tar", "-x%sf" % flag, "-", "-C", part]
    total = max(1, os.path.getsize(tarball))
    ok = False
    try:
        job.proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, close_fds=True)
        sent = 0
        err = None
        with open(tarball, "rb") as fh:
            while True:
                if job.cancelled:
                    break
                buf = fh.read(512 * 1024)
                if not buf:
                    break
                try:
                    job.proc.stdin.write(buf)
                except Exception as e:      # tar died (corrupt archive, disk full)
                    err = e
                    break
                sent += len(buf)
                job.set_progress(57 + 38 * sent / float(total))
        try:
            job.proc.stdin.close()
        except Exception:
            pass
        out = job.proc.stdout.read().decode("utf-8", "ignore")
        rc = job.proc.wait()
        job.check()
        if rc != 0 or err:
            low = out.lower()
            if "no space" in low:
                raise MBError("Disque plein pendant l'extraction.")
            raise MBError("Archive rootfs corrompue ou illisible (tar code %s). %s" % (rc, out.strip()[-160:]))
        if not (os.path.exists(os.path.join(part, "sbin/init")) or os.path.islink(os.path.join(part, "sbin/init"))):
            # some tarballs contain a single top folder
            subs = [x for x in os.listdir(part) if os.path.isdir(os.path.join(part, x))]
            if len(subs) == 1 and os.path.lexists(os.path.join(part, subs[0], "sbin/init")):
                inner = os.path.join(part, subs[0])
                for x in os.listdir(inner):
                    os.rename(os.path.join(inner, x), os.path.join(part, x))
                os.rmdir(inner)
            else:
                raise MBError("L'archive ne contient pas de système Enigma2 valide (/sbin/init absent).")
        info = image_info(part)
        if info and info.get("box") and box.get("machine") not in ("", "inconnu") and info["box"] != box["machine"]:
            # vuzero4k vs zero4k etc. are the same box
            a, b = info["box"].lower(), box["machine"].lower()
            if not (a.endswith(b) or b.endswith(a)):
                raise MBError("Image prévue pour %s, ce récepteur est %s." % (info["box"], box["machine"]))
        if os.path.exists(dest):
            raise MBError("Le dossier de destination existe déjà.")
        os.rename(part, dest)
        sync()
        ok = True
        job.say("Extraction terminée.", 96)
    finally:
        job.proc = None
        if not ok:
            job.cancellable = False
            job.say("Nettoyage…")
            remove_quiet(part)
            job.cancellable = True
    return dest


def fix_chroot_slot(dest, name):
    """Make a freshly extracted image bootable by chroot (omb-init)."""
    fstab = os.path.join(dest, "etc/fstab")
    text = read_file(fstab)
    if text:
        lines = []
        for line in text.splitlines():
            p = line.split()
            if len(p) >= 2 and p[1] == "/" and not line.startswith("#"):
                line = "#OMB# " + line
            lines.append(line)
        write_file(fstab, "\n".join(lines) + "\n")
    try:
        write_file(os.path.join(dest, "etc/omb_slot"), name + "\n")
    except Exception:
        pass


def modules_warning(dest, box):
    kernel = box.get("kernel", "")
    mods = []
    try:
        mods = os.listdir(os.path.join(dest, "lib/modules"))
    except Exception:
        pass
    if kernel and mods and kernel not in mods:
        return ("Attention : l'image utilise le noyau %s mais la flash démarre le noyau %s. "
                "Certains pilotes peuvent manquer." % (", ".join(mods), kernel))
    return ""


def write_kernel(job, kernel, spec, root_mount):
    if not spec:
        raise MBError("Partition noyau inconnue pour ce slot.")
    job.say("Écriture du noyau…", 97)
    size = os.path.getsize(kernel)
    if spec.startswith("/dev/"):
        dev = os.path.realpath(spec)
        part = os.path.basename(dev)
        try:
            cap = int(read_file("/sys/class/block/%s/size" % part).strip()) * 512
        except Exception:
            cap = 0
        if not cap or size > cap:
            raise MBError("Noyau trop grand pour la partition %s." % dev)
        rc, out = run(["dd", "if=%s" % kernel, "of=%s" % dev, "bs=1M", "conv=fsync"], timeout=120)
        if rc != 0:
            rc, out = run(["dd", "if=%s" % kernel, "of=%s" % dev, "bs=1M"], timeout=120)
        if rc != 0:
            raise MBError("Échec de l'écriture du noyau : %s" % out.strip()[-120:])
    else:
        target = os.path.join(root_mount, spec.lstrip("/"))
        if os.path.dirname(target) and not os.path.isdir(os.path.dirname(target)):
            os.makedirs(os.path.dirname(target))
        shutil.copyfile(kernel, target)
    sync()


def safe_rmtree(job, path, reldir):
    """rm -rf with paranoid guards."""
    rp = os.path.realpath(path)
    if not path or rp in ("/", "/media", "/media/hdd", "/media/usb") or rp.count("/") < 3:
        raise MBError("Chemin refusé : %s" % path)
    if not reldir or ".." in reldir:
        raise MBError("Chemin de slot invalide.")
    if is_running_root(rp):
        raise MBError("Ce slot est l'image en cours d'utilisation : action refusée.")
    for sub in ("", "media/hdd", "media/flash"):
        if is_running_root(os.path.join(rp, sub)) and sub == "":
            raise MBError("Ce slot est l'image en cours d'utilisation : action refusée.")
    # never follow mounts inside the slot
    for m in mounts():
        if m["mount"].startswith(rp + "/"):
            raise MBError("Un périphérique est monté dans ce slot (%s) : suppression refusée." % m["mount"])
    job.cancellable = False
    job.say("Suppression de %s…" % os.path.basename(rp), 10)
    trash = rp + ".deleting"
    os.rename(rp, trash)
    rc, out = run(["rm", "-rf", trash], timeout=1800)
    if os.path.exists(trash):
        shutil.rmtree(trash, ignore_errors=True)
    sync()
    job.cancellable = True
    if os.path.exists(trash):
        raise MBError("Suppression incomplète : %s" % trash)
    job.say("Supprimé.", 100)


def backup_tree(job, slot, dest_mount, layout=None):
    """tar.gz of a slot into <dest>/WMultiBoot/backups/."""
    if not dest_mount:
        raise MBError("Aucun disque de sauvegarde disponible.")
    root = slot.root
    mount_ctx = None
    if slot.kind == "flash" and not root:
        if layout is None or not layout.probe.device:
            raise MBError("Flash introuvable.")
        mount_ctx = TempMount(layout.probe.device)
        root = mount_ctx.__enter__()
    try:
        if not root or not os.path.isdir(root):
            raise MBError("Slot illisible.")
        job.say("Calcul de la taille du slot…", 2)
        used = dir_size_mb(root) or 0
        need = int(used * 0.6) + 100
        free, _ = fs_usage(dest_mount)
        if free < need:
            raise MBError("Espace insuffisant sur %s : %s libres, environ %s nécessaires."
                          % (dest_mount, human_mb(free), human_mb(need)))
        d = work_dir(dest_mount, "backups")
        label = sanitize("%s-%s" % (slot.info["label"] if slot.info else "slot", (slot.info or {}).get("date", "")))
        name = "%s-backup-%s.tar.gz" % (label, time.strftime("%Y%m%d-%H%M"))
        final = os.path.join(d, name)
        part = final + ".partial"
        excl = ["./proc/*", "./sys/*", "./dev/*", "./media/*", "./mnt/*", "./tmp/*", "./run/*",
                "./var/volatile/*", "./omb/*", "./hdd", "./%s" % DATA_DIR]
        rc, helptext = run(["tar", "--help"], timeout=10)
        gnu = "--one-file-system" in helptext
        args = ["tar", "-czf", part]
        exfile = None
        if gnu:
            args.append("--one-file-system")
            args += ["--exclude=%s" % e for e in excl]
        else:
            exfile = os.path.join(work_dir(dest_mount, "tmp"), "exclude.txt")
            with open(exfile, "w") as fh:
                fh.write("\n".join(excl) + "\n")
            args += ["-X", exfile]
        args.append(".")
        job.say("Sauvegarde vers %s…" % final, 5)
        job.proc = subprocess.Popen(args, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, close_fds=True)
        est = max(1, used * 0.45) * MB
        while job.proc.poll() is None:
            if job.cancelled:
                job.proc.kill()
                break
            try:
                job.set_progress(5 + 90 * min(1.0, os.path.getsize(part) / est))
            except Exception:
                pass
            time.sleep(0.5)
        out = job.proc.stdout.read().decode("utf-8", "ignore")
        rc = job.proc.wait()
        job.proc = None
        if exfile:
            remove_quiet(exfile)
        if job.cancelled:
            remove_quiet(part)
            raise Cancelled("Sauvegarde annulée.")
        # GNU tar returns 1 when files changed while reading (running slot): still valid
        if rc not in (0, 1) or not os.path.isfile(part):
            remove_quiet(part)
            if "no space" in out.lower():
                raise MBError("Disque plein pendant la sauvegarde.")
            raise MBError("Échec de la sauvegarde (tar code %s). %s" % (rc, out.strip()[-160:]))
        os.rename(part, final)
        sync()
        size = os.path.getsize(final) // MB
        job.say("Sauvegarde terminée : %s (%s)" % (name, human_mb(size)), 100)
        return "Sauvegarde créée :\n%s\n(%s)" % (final, human_mb(size))
    finally:
        if mount_ctx:
            mount_ctx.__exit__(None, None, None)


# --------------------------------------------------------------------------- CLI (read-only)

def _cli():
    import json
    import sys
    lay = detect_layout()
    out = {"version": VERSION, "box": lay.box, "layout": lay.key, "layout_name": lay.name,
           "caps": list(lay.caps), "notes": lay.notes,
           "storages": storages(),
           "slots": [{"n": s.number, "kind": s.kind, "title": s.title(), "sub": s.subtitle(),
                      "status": s.status(), "running": s.running, "next": s.next_boot,
                      "root": s.root, "reldir": s.reldir, "device": s.device} for s in lay.slots]}
    if "--images" in sys.argv:
        out["images"] = find_local_images()
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    _cli()
