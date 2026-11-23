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

VERSION = "1.6.1"
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


def dir_size_mb(path, job=None):
    if job is not None:                       # cancellable version (EXIT kills du at once)
        try:
            job.proc = subprocess.Popen(["du", "-smx", path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)
            out = job.proc.communicate()[0].decode("utf-8", "ignore")
        finally:
            job.proc = None
        job.check()
        try:
            return int(out.split()[0])
        except Exception:
            return None
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

JOB_STATUS = "/tmp/wmb-job-%d.json"


def _pid_alive(pid):
    return os.path.isdir("/proc/%d" % pid)


def foreign_jobs(max_age=900):
    """Jobs of OTHER processes (SSH, scripts): running ones, and finished ones younger than
    max_age seconds. Stale files of dead processes that never finished are removed."""
    import glob
    import json
    me, now, out = os.getpid(), time.time(), []
    for path in glob.glob(JOB_STATUS.replace("%d", "*")):
        try:
            with open(path) as f:
                d = json.load(f)
            pid = int(d.get("pid", 0))
        except Exception:
            continue
        if pid == me:
            continue
        alive = _pid_alive(pid)
        if not d.get("done") and not alive:
            remove_quiet(path)
            continue
        if d.get("done") and now - float(d.get("ts", 0)) > max_age:
            remove_quiet(path)
            continue
        d["path"] = path
        out.append(d)
    out.sort(key=lambda d: d.get("started", 0))
    return out


class RemoteJob(object):
    """Read-only view of a job running in another process (same interface as Job for the
    progress screen). EXIT only hides the screen: the job keeps running."""

    remote = True

    def __init__(self, data):
        self.path = data["path"]
        self.cancellable = False
        self.cancelled = False
        self.new_root = None
        self._apply(data)

    def _apply(self, d):
        self.title = d.get("title") or "Opération en cours"
        self.progress = int(d.get("progress") or 0)
        self.step = d.get("step") or ""
        self.lines = list(d.get("lines") or [])
        self.done = bool(d.get("done"))
        self.ok = bool(d.get("ok"))
        self.result = d.get("result") or ""
        self.pid = int(d.get("pid") or 0)
        self.started = d.get("started", 0)

    def refresh(self):
        import json
        try:
            with open(self.path) as f:
                self._apply(json.load(f))
        except Exception:
            if not self.done and not _pid_alive(self.pid):
                # process gone without a final state (e.g. the GUI restart of a restore)
                self.done, self.ok = True, True
                self.result = self.result or "Opération terminée (le résultat complet est dans le journal)."
        if not self.done and self.pid and not _pid_alive(self.pid):
            self.done = True
            self.result = self.result or "Le processus s'est arrêté. Voir le journal (MENU > Aide > Journal)."

    def mark_seen(self):
        if self.done:
            remove_quiet(self.path)

    def cancel(self):
        pass

    def check(self):
        pass


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
        self.new_root = None
        self._lock = threading.Lock()

    def say(self, msg, progress=None):
        with self._lock:
            self.step = msg
            self.lines.append(msg)
            self.lines = self.lines[-40:]
            if progress is not None:
                self.progress = max(0, min(100, int(progress)))
        log("[%s] %s" % (self.title, msg))
        self.publish()

    def set_progress(self, p):
        self.progress = max(0, min(100, int(p)))
        self.publish()

    def publish(self, force=False):
        """Write the state to /tmp so a job started outside the GUI (SSH, script, another
        process) can be followed on the TV. Throttled; never raises."""
        import sys
        if "enigma" in sys.modules:          # inside Enigma2 the GUI already shows its own jobs
            return
        now = time.time()
        if not force and now - getattr(self, "_pub_ts", 0) < 1.0:
            return
        self._pub_ts = now
        try:
            import json
            data = {"pid": os.getpid(), "title": self.title, "progress": self.progress, "step": self.step,
                    "lines": self.lines[-12:], "done": self.done, "ok": self.ok, "result": self.result,
                    "cancellable": False, "started": getattr(self, "_started", now), "ts": now}
            path = JOB_STATUS % os.getpid()
            with open(path + ".tmp", "w") as f:
                json.dump(data, f)
            os.rename(path + ".tmp", path)
        except Exception:
            pass

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
            self.publish(force=True)
        self._started = time.time()
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
            previous = read_file(path)
            if slot.root and slot.kind != "flash":
                if once:
                    guard_not_running(slot)
                    install_return_hook(slot.root, previous, self.probe.device)
                else:
                    remove_return_hook(slot.root)
            write_file(path, text)
            if read_file(path) != text:
                raise MBError("Vérification de l'écriture impossible.")
        back = ""
        if once:
            prev_slot = self.running_slot()
            back = " (une seule fois, retour ensuite sur %s)" % (prev_slot.title() if prev_slot else "l'image actuelle")
        job.say("Prochain démarrage : %s%s" % (slot.title(), back), 100)
        return "Prochain démarrage : %s%s." % (slot.title(), back)

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
        job.new_root = dest
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
            job.new_root = dest
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
               ("teamBlue", "https://images.teamblue.tech/json/%s"),
               ("PurE2", "https://www.pur-e2.club/OU/images/json/%s"),
               ("OpenDroid", "https://opendroid.org/json.php?box=%s"),
               ("OpenVision", "https://images.openvision.dedyn.io/json/%s"),
               ("OpenHDF", "https://flash.hdfreaks.cc/openhdf/json/%s"))


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


# Distributions that publish a plain folder listing (Apache autoindex) instead of JSON.
INDEX_FEEDS = (("Neutrino (NI)", "https://neutrino-images.de/neutrino-images/nightly/"),
               ("Neutrino (NI) release", "https://neutrino-images.de/neutrino-images/release/"))


def parse_index(html, base, distro, machine):
    """Multiboot zips for this machine in an autoindex page -> [item]."""
    items = []
    seen = set()
    for m in re.finditer(r'href="([^"?#]+\.zip)"', html):
        name = m.group(1).split("/")[-1]
        low = name.lower()
        if name in seen or not re.search(r"(^|[-_])%s([-_.]|$)" % re.escape(machine.lower()), low):
            continue
        if not ("usb" in low or "multi" in low):
            continue
        seen.add(name)
        tail = html[m.end():m.end() + 400]
        size = 0
        sm = re.search(r">\s*([\d.]+)\s*([KMG])\s*<", tail)
        if sm:
            size = int(float(sm.group(1)) * {"K": 1024, "M": MB, "G": 1024 * MB}[sm.group(2)])
        dm = re.search(r"(20\d{6})", name)
        date = int(time.mktime(time.strptime(dm.group(1), "%Y%m%d"))) if dm else 0
        link = m.group(1) if m.group(1).startswith("http") else base.rstrip("/") + "/" + m.group(1).lstrip("/")
        if not re.match(r"^https?://[^\s'\"<>]+\.zip$", link):
            continue
        items.append({"distro": distro, "group": "nightly" if "nightly" in base else "release", "name": name,
                      "url": link, "size": size, "date": date, "day": fmt_date(dm.group(1)) if dm else "",
                      "eol": False, "beta": "nightly" in base})
    items.sort(key=lambda i: -i["date"])
    return items


def fetch_catalog(job, machine):
    """Online images for this receiver, like the Octagon / OpenATV flash-online list.
    Returns [(distro, [items])], OpenATV first."""
    if not machine or machine == "inconnu":
        raise MBError("Modèle du récepteur inconnu : liste d'images en ligne indisponible.")
    if not os.path.isdir(CATALOG_DIR):
        os.makedirs(CATALOG_DIR)
    sources = [("OpenATV", OPENATV_JSON % machine)] + [(n, u % machine) for n, u in EXTRA_FEEDS] + list(INDEX_FEEDS)
    index_names = set(n for n, _ in INDEX_FEEDS)
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
    results = [None] * len(sources)

    def worker(n, distro, url):
        dest = os.path.join(CATALOG_DIR, "%d.json" % n)
        try:
            if _fetch(url, dest):
                if distro in index_names:
                    results[n] = parse_index(read_file(dest), url, distro.replace(" release", ""), machine)
                else:
                    results[n] = parse_catalog(read_file(dest), distro)
        except Exception as e:
            log("catalog %s: %s" % (distro, e))
        remove_quiet(dest)
    threads = []
    for n, (distro, url) in enumerate(sources):
        t = threading.Thread(target=worker, args=(n, distro, url))
        t.daemon = True
        t.start()
        threads.append(t)
    job.say("Lecture de %d catalogues…" % len(sources), 15)
    deadline = time.time() + 70
    for t in threads:
        while t.is_alive() and time.time() < deadline:
            job.check()
            t.join(0.3)
            job.set_progress(15 + 80 * sum(1 for x in threads if not x.is_alive()) // len(threads))
    merged = []
    for n, items in enumerate(results):
        if items is None:                       # source unreachable: not listed
            continue
        name = sources[n][0].replace(" release", "")
        for d, its in merged:
            if d == name:
                its.extend(items)
                its.sort(key=lambda i: (i["eol"], i["beta"], -i["date"]))
                break
        else:
            merged.append((name, list(items)))
    out = [x for x in merged if x[1]] + [x for x in merged if not x[1]]   # empty ones last
    if not [x for x in out if x[1]]:
        raise MBError("Aucune image en ligne trouvée pour %s (pas de connexion Internet ?)." % machine)
    total = sum(len(i) for _, i in out)
    job.say("%d images trouvées dans %d distributions." % (total, len([x for x in out if x[1]])), 100)
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


RETURN_HOOK = "etc/rcS.d/S99wmbreturn"
RETURN_CONF = "etc/wmb-return.conf"
RETURN_SCRIPT = """#!/bin/sh
# Wacayoub MultiBoot - one-shot boot: put back the previous boot choice, then remove itself.
# (omb-init already emptied boot.conf because ONCE=1, so if this script cannot run the
# receiver simply returns to the flash image.)
DEV="%(dev)s"
M=/var/volatile/wmb-return
mkdir -p $M
if [ -b "$DEV" ] && mount -t ext4 "$DEV" $M 2>/dev/null; then
	if [ -x $M/sbin/omb-init ] && [ -f /%(conf)s ]; then
		cp /%(conf)s $M/etc/omb/boot.conf.wmb && mv $M/etc/omb/boot.conf.wmb $M/etc/omb/boot.conf
		sync
		echo "[WMB] previous boot choice restored" > /dev/kmsg 2>/dev/null
	fi
	umount $M 2>/dev/null || umount -l $M
fi
rmdir $M 2>/dev/null
rm -f /%(conf)s /%(hook)s
exit 0
"""


def install_return_hook(slot_root, previous_conf, flash_dev):
    """Make a 'boot once' come back to the image that was selected before."""
    if not flash_dev or not re.match(r"^/dev/[\w/.-]+$", flash_dev):
        raise MBError("Partition flash inconnue : démarrage unique impossible.")
    rcs = os.path.join(slot_root, "etc/rcS.d")
    if not os.path.isdir(rcs):
        raise MBError("Cette image n'utilise pas /etc/rcS.d : démarrage unique impossible.")
    write_file(os.path.join(slot_root, RETURN_CONF), previous_conf)
    hook = os.path.join(slot_root, RETURN_HOOK)
    write_file(hook, RETURN_SCRIPT % {"dev": flash_dev, "conf": RETURN_CONF, "hook": RETURN_HOOK})
    os.chmod(hook, 0o755)


def remove_return_hook(slot_root):
    for rel in (RETURN_HOOK, RETURN_CONF):
        remove_quiet(os.path.join(slot_root, rel))


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
        used = dir_size_mb(root, job) or 0
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


# --------------------------------------------------------------------------- space, backups, settings

SLOT_ESTIMATE_MB = 800          # a fresh image is 200-500 MB, it grows with plugins/picons/EPG


def install_capacity():
    """[(storage, number of images that still fit)] for disks that can hold new slots."""
    out = []
    for st in storages():
        if st["linux"] and st["rw"]:
            out.append((st, max(0, (st["free"] - 200) // SLOT_ESTIMATE_MB)))
    return out


DISTRO_KEYS = ("neutrino", "openatv", "openpli", "openvix", "openbh", "openspa", "egami", "teamblue", "openhdf",
               "pure2", "openvision", "opendroid", "satlodge", "dreamos")


def distro_key(name):
    n = (name or "").lower().replace(" ", "")
    for k in DISTRO_KEYS:
        if k in n:
            return k
    return "unknown"


def list_backups():
    """[{path, name, size, date, kind}] newest first; kind = 'slot' | 'settings'."""
    out = []
    for st in storages():
        d = os.path.join(st["mount"], DATA_DIR, "backups")
        try:
            names = os.listdir(d)
        except Exception:
            continue
        for n in names:
            p = os.path.join(d, n)
            if not n.endswith(".tar.gz") or not os.path.isfile(p):
                continue
            try:
                size, mtime = os.path.getsize(p), os.path.getmtime(p)
            except Exception:
                continue
            out.append({"path": p, "name": n, "size": size // MB, "mtime": mtime, "mount": st["mount"],
                        "date": time.strftime("%d/%m/%Y %H:%M", time.localtime(mtime)),
                        "kind": "custom" if n.startswith(("reglages-", "sauvegarde-")) else "slot",
                        "image": backup_image_label(n)})
    out.sort(key=lambda b: -b["mtime"])
    return out


def backup_image_label(name):
    """'sauvegarde-OpenATV_8.0.1-2026…' / 'OpenATV_8.0.1-20261003-backup-…' -> 'OpenATV 8.0.1'."""
    n = name[:-7] if name.endswith(".tar.gz") else name
    for p in ("sauvegarde-", "reglages-"):
        if n.startswith(p):
            n = n[len(p):]
    n = n.split("-backup-")[0]
    n = re.split(r"-20\d{6}", n)[0]
    return n.replace("_", " ").strip() or "Image inconnue"


def backups_by_image():
    """[(image label, [backups newest first])], most recent image first."""
    groups = {}
    for b in list_backups():
        groups.setdefault(b["image"], []).append(b)
    return sorted(groups.items(), key=lambda kv: -kv[1][0]["mtime"])


def delete_backup(path):
    rp = os.path.realpath(path)
    if not re.search(r"/%s/backups/[^/]+\.tar\.gz$" % DATA_DIR, rp) or not os.path.isfile(rp):
        raise MBError("Ce fichier n'est pas une sauvegarde Wacayoub MultiBoot.")
    os.remove(rp)
    sync()


SETTINGS_DIRS = ("etc/enigma2", "etc/tuxbox")
CHANNEL_FILES = re.compile(r"^(lamedb5?|bouquets\.(tv|radio)|userbouquet\..+\.(tv|radio)|alternatives\..+|"
                           r"blacklist|whitelist)$")


def _slot_root_ctx(slot, layout, rw=False):
    """Context manager giving a readable (or writable) root for a slot."""
    if slot.root and os.path.isdir(slot.root):
        class _C(object):
            def __enter__(s):
                return slot.root

            def __exit__(s, *a):
                return False
        return _C()
    if slot.kind == "flash" and layout and layout.probe.device:
        return TempMount(layout.probe.device, rw=rw)
    raise MBError("Contenu du slot inaccessible.")


def _writable_slot_root(slot):
    guard_not_running(slot)
    if slot.kind not in ("chroot", "omb") or not slot.root or not os.path.isdir(slot.root):
        raise MBError("Cette action n'est possible que sur une image installée sur HDD/USB.")
    return slot.root


def copy_channels(job, dest_slot, src_root="/"):
    """Copy channel list, bouquets and satellites of the running image into another slot."""
    dest = _writable_slot_root(dest_slot)
    src_e2 = os.path.join(src_root, "etc/enigma2")
    names = [n for n in os.listdir(src_e2) if CHANNEL_FILES.match(n) and os.path.isfile(os.path.join(src_e2, n))]
    if not any(n.startswith("lamedb") for n in names):
        raise MBError("Aucune liste de chaînes trouvée dans l'image en cours.")
    dst_e2 = os.path.join(dest, "etc/enigma2")
    if not os.path.isdir(dst_e2):
        os.makedirs(dst_e2)
    job.say("Copie de %d fichiers de chaînes…" % len(names), 30)
    for n in names:
        shutil.copyfile(os.path.join(src_e2, n), os.path.join(dst_e2, n))
    tux = os.path.join(src_root, "etc/tuxbox")
    copied_xml = 0
    if os.path.isdir(tux) and os.path.isdir(os.path.join(dest, "etc/tuxbox")):
        for n in ("satellites.xml", "cables.xml", "terrestrial.xml"):
            if os.path.isfile(os.path.join(tux, n)):
                shutil.copyfile(os.path.join(tux, n), os.path.join(dest, "etc/tuxbox", n))
                copied_xml += 1
    sync()
    job.say("Chaînes copiées.", 100)
    return "Chaînes, favoris et satellites copiés vers %s (%d fichiers)." % (dest_slot.title(), len(names) + copied_xml)


# ---- categories of a custom backup / restore
# (key, title, description, warning)
CATEGORIES = (
    ("channels", "Chaînes et favoris", "lamedb, bouquets, favoris, listes noires", ""),
    ("satellites", "Satellites et câble", "satellites.xml, cables.xml, terrestrial.xml", ""),
    ("settings", "Réglages Enigma2", "fichier settings, minuteries, autotimer", ""),
    ("plugins_conf", "Réglages des plugins", "configs dans /etc/enigma2 (EPG, IPTV, skins…)", ""),
    ("plugins", "Liste des plugins installés", "pour les réinstaller depuis le feed", ""),
    ("softcam", "Softcam", "configs OSCam/CCcam et clés", "contient vos identifiants"),
    ("network", "Réseau", "interfaces, Wi-Fi, DNS, nom du récepteur", "contient le mot de passe Wi-Fi"),
    ("picons", "Picons", "logos des chaînes du dossier /picon", ""),
    ("addons", "Ajouts installés à la main", "skins et fichiers de plugins copiés sans paquet", ""),
)
CAT_TITLES = dict((c[0], c[1]) for c in CATEGORIES)
E2 = "etc/enigma2/"
SETTINGS_FILES = ("settings", "timers.xml", "autotimer.xml", "profile")
NETWORK_FILES = ("etc/network/interfaces", "etc/wpa_supplicant.conf", "etc/wpa_supplicant.wlan0.conf",
                 "etc/wpa_supplicant.wlan1.conf", "etc/resolv.conf", "etc/hostname", "etc/hosts")
SOFTCAM_PATHS = ("etc/tuxbox/config", "etc/CCcam.cfg", "usr/keys", "etc/oscam", "var/keys")
PICON_DIRS = ("picon", "usr/share/enigma2/picon")
# hand-installed skins/plugins: files there that no opkg package owns
ADDON_DIRS = ("usr/lib/enigma2/python/Plugins", "usr/lib/enigma2/python/Components", "usr/share/enigma2")
ADDON_RE = re.compile(r"^(usr/lib/enigma2/python/(Plugins|Components)/|usr/share/enigma2/)")
ADDON_LIST = "wmb-addons.lst"
MANIFEST = "wmb-manifest.txt"
PLUGIN_LIST = "wmb-plugins.txt"
# never restored, whatever the archive says (boot scripts were the malware vector)
FORBIDDEN = re.compile(r"^(etc/(init\.d|rc\d?\.d|rcS\.d|rc\.local|passwd|shadow|group|dropbear|ssh|cron|profile)"
                       r"|var/spool/cron|home/|root/|sbin/|bin/|usr/(bin|sbin|lib)/|lib/)")


def _skip_name(n):
    low = n.lower()
    return "backup" in low or low.endswith((".bak", ".tar.gz", ".tgz", ".zip")) or n in ("epg.dat", "epg.db")


def classify(rel):
    """Category of a path relative to the image root, or None (never backed up/restored)."""
    rel = rel[2:] if rel.startswith("./") else rel
    rel = rel.rstrip("/")
    if not rel or ".." in rel.split("/") or rel.startswith("/"):
        return None
    for p in PICON_DIRS:
        if rel == p or rel.startswith(p + "/"):
            return "picons"
    if ADDON_RE.match(rel + "/"):
        if "Extensions/WMultiBoot" in rel or any(_skip_name(x) for x in rel.split("/")):
            return None
        return "addons"
    if FORBIDDEN.match(rel):
        return None
    if rel in (MANIFEST, PLUGIN_LIST) or (rel.startswith(IPK_DIR + "/") and rel.count("/") == 1 and rel.endswith(".ipk")):
        return "meta"
    if rel.startswith(E2):
        name = rel[len(E2):]
        top = name.split("/")[0]
        if "/" not in name and CHANNEL_FILES.match(name):
            return "channels"
        if "/" not in name and name in SETTINGS_FILES:
            return "settings"
        if any(_skip_name(p) for p in name.split("/")):
            return None
        return "plugins_conf" if top else None
    if rel.startswith("etc/tuxbox/") and rel.count("/") == 2 and rel.endswith(".xml"):
        return "satellites"
    for p in SOFTCAM_PATHS:
        if rel == p or rel.startswith(p + "/"):
            return "softcam"
    if rel.startswith("etc/oscam"):
        return "softcam"
    if rel in NETWORK_FILES:
        return "network"
    for p in PICON_DIRS:
        if rel == p or rel.startswith(p + "/"):
            return "picons"
    return None


def _owned_files(root):
    """Paths (relative) that an installed opkg package owns in this image."""
    owned = set()
    for info in ("var/lib/opkg/info", "usr/lib/opkg/info"):
        d = os.path.join(root, info)
        try:
            names = os.listdir(d)
        except Exception:
            continue
        for n in names:
            if n.endswith(".list"):
                for line in read_file(os.path.join(d, n)).splitlines():
                    line = line.split("\t")[0].strip().lstrip("/")
                    if line:
                        owned.add(line)
    return owned


def _is_elf(path):
    try:
        with open(path, "rb") as f:
            return f.read(4) == b"\x7fELF"
    except Exception:
        return False


def addon_paths(root, job=None):
    """Hand-installed files (skins, plugin files copied without a package): files under
    ADDON_DIRS that no package owns. Programs (ELF) are left out on purpose.
    Returns (files, size, skipped_programs)."""
    owned = _owned_files(root)
    if not owned:
        return [], 0, []                    # no package database: cannot tell, keep nothing
    files, size, elf = [], 0, []
    for top in ADDON_DIRS:
        base = os.path.join(root, top)
        for dp, dn, fn in os.walk(base):
            if job:
                job.check()
            reld = os.path.relpath(dp, root)
            dn[:] = sorted(d for d in dn if classify(reld + "/" + d) == "addons"
                           and not os.path.islink(os.path.join(dp, d)))
            for f in sorted(fn):
                rel = reld + "/" + f
                if rel in owned or classify(rel) != "addons":
                    continue
                full = os.path.join(dp, f)
                if not os.path.islink(full):
                    if _is_elf(full):
                        elf.append(rel)
                        continue
                    try:
                        size += os.path.getsize(full)
                    except Exception:
                        continue
                files.append(rel)
    return files, size, elf


def category_paths(root, key):
    """Existing paths (relative to root) for one category."""
    out = []
    e2 = os.path.join(root, E2)
    if key in ("channels", "settings", "plugins_conf"):
        try:
            names = sorted(os.listdir(e2))
        except Exception:
            names = []
        for n in names:
            rel = E2 + n
            if classify(rel) == key and os.path.exists(os.path.join(root, rel)):
                out.append(rel)
    elif key == "satellites":
        try:
            out = [ "etc/tuxbox/" + n for n in sorted(os.listdir(os.path.join(root, "etc/tuxbox"))) if n.endswith(".xml")]
        except Exception:
            pass
    elif key == "softcam":
        out = [p for p in SOFTCAM_PATHS if os.path.exists(os.path.join(root, p))]
        try:
            out += ["etc/" + n for n in os.listdir(os.path.join(root, "etc")) if n.startswith("oscam") and n != "oscam"]
        except Exception:
            pass
    elif key == "network":
        out = [p for p in NETWORK_FILES if os.path.isfile(os.path.join(root, p))]
    elif key == "picons":
        out = [p for p in PICON_DIRS if os.path.isdir(os.path.join(root, p)) and not os.path.islink(os.path.join(root, p))]
    return out


def _tree_size(path):
    total = 0
    if os.path.isfile(path) or os.path.islink(path):
        try:
            return os.lstat(path).st_size
        except Exception:
            return 0
    for dp, dn, fn in os.walk(path):
        dn[:] = [d for d in dn if not _skip_name(d)]
        for f in fn:
            if not _skip_name(f):
                try:
                    total += os.lstat(os.path.join(dp, f)).st_size
                except Exception:
                    pass
    return total


SELF_PKG = "enigma2-plugin-extensions-wmultiboot"
PLUGIN_KINDS = (("extensions", "Extension"), ("systemplugins", "Système"), ("skins", "Skin"),
                ("skincomponents", "Skin"), ("softcams", "Softcam"), ("picons", "Picons"),
                ("drivers", "Pilote"), ("font", "Police"))
IPK_DIR = "wmb-ipk"
# files a re-packed plugin may contain (never boot scripts, binaries or system libraries)
REPACK_OK = re.compile(r"^(usr/lib/enigma2/|usr/share/enigma2/|usr/share/fonts/|etc/enigma2/|picon/|"
                       r"usr/lib/python[\d.]+/site-packages/)")


def _opkg_status(root):
    for st in ("var/lib/opkg/status", "usr/lib/opkg/status"):
        text = read_file(os.path.join(root, st))
        if text:
            return text
    return ""


def plugin_details(root):
    """[{name, short, kind, version, size, auto}] of the Enigma2 plugins installed in an image.
    Channel-list packages (enigma2-plugin-settings-*) and this plugin are left out."""
    out = []
    for block in _opkg_status(root).split("\n\n"):
        m = re.search(r"^Package:\s*(\S+)", block, re.M)
        if not m or not re.search(r"^Status:.*\binstalled\b", block, re.M):
            continue
        n = m.group(1)
        if not n.startswith("enigma2-plugin-") or n.startswith("enigma2-plugin-settings-") or n == SELF_PKG:
            continue
        rest = n[len("enigma2-plugin-"):]
        kind, short = "Plugin", rest
        for k, label in PLUGIN_KINDS:
            if rest.startswith(k + "-"):
                kind, short = label, rest[len(k) + 1:]
                break
        v = re.search(r"^Version:\s*(\S+)", block, re.M)
        sz = re.search(r"^Installed-Size:\s*(\d+)", block, re.M)
        out.append({"name": n, "short": short, "kind": kind, "version": v.group(1) if v else "",
                    "size": int(sz.group(1)) if sz else 0,
                    "auto": bool(re.search(r"^Auto-Installed:\s*yes", block, re.M))})
    out.sort(key=lambda p: (p["kind"] != "Extension", p["kind"], p["short"]))
    return out


def plugin_report(slot, layout=None):
    """(plugin details, feed package names) of a slot, for the plugin checklists."""
    with _slot_root_ctx(slot, layout) as root:
        return plugin_details(root), feed_packages(root)


def plugin_details_from_name(n):
    """Same dict as plugin_details() for a bare package name (from a backup list)."""
    rest = n[len("enigma2-plugin-"):] if n.startswith("enigma2-plugin-") else n
    kind, short = "Plugin", rest
    for k, label in PLUGIN_KINDS:
        if rest.startswith(k + "-"):
            kind, short = label, rest[len(k) + 1:]
            break
    return {"name": n, "short": short, "kind": kind, "version": "", "size": 0, "auto": False}


def installed_plugins(root):
    """Package names of the Enigma2 plugins installed in an image (from opkg status)."""
    return sorted(set(p["name"] for p in plugin_details(root)))


def feed_packages(root):
    """Package names known by the image's opkg feed lists (empty set when never updated)."""
    names = set()
    for d in ("var/lib/opkg/lists", "var/lib/opkg"):
        base = os.path.join(root, d)
        try:
            files = os.listdir(base)
        except Exception:
            continue
        for f in files:
            p = os.path.join(base, f)
            if f in ("status", "info") or not os.path.isfile(p):
                continue
            try:
                with open(p, "rb") as fh:
                    head = fh.read(2)
                    fh.seek(0)
                    if head == b"\x1f\x8b":
                        import gzip
                        data = gzip.GzipFile(fileobj=fh).read()
                    else:
                        data = fh.read()
                names.update(re.findall(r"^Package:\s*(\S+)", data.decode("utf-8", "ignore"), re.M))
            except Exception:
                pass
        if names:
            break
    return names


def _ar_member(name, data):
    hdr = "%-16s%-12d%-6d%-6d%-8s%-10d`\n" % (name, int(time.time()), 0, 0, "100644", len(data))
    return hdr.encode("ascii") + data + (b"\n" if len(data) % 2 else b"")


def repack_ipk(root, name, out_path, max_bytes=60 * MB):
    """Rebuild an installable .ipk of a plugin from its installed files (for plugins that
    are not in any feed). Only plugin files are taken, no maintainer scripts.
    Returns the number of files, 0 when not possible."""
    import io
    import tarfile
    info = os.path.join(root, "var/lib/opkg/info")
    control = read_file(os.path.join(info, name + ".control"))
    listing = read_file(os.path.join(info, name + ".list"))
    if not control or not listing:
        return 0
    files = []
    total = 0
    for line in listing.splitlines():
        rel = line.split("\t")[0].strip().lstrip("/")
        p = os.path.join(root, rel)
        if not rel or ".." in rel.split("/") or not REPACK_OK.match(rel):
            continue
        if os.path.islink(p) or not os.path.isfile(p) or rel.endswith((".pyc", ".pyo")):
            continue
        files.append(rel)
        total += os.path.getsize(p)
        if total > max_bytes:
            return 0
    if not files:
        return 0
    keep = [l for l in control.splitlines() if l.strip() and not l.startswith(
        ("Status:", "Installed-Time:", "Auto-Installed:", "Conffiles:", " /"))]
    ctl = ("\n".join(keep) + "\n").encode("utf-8")

    def tgz(add):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as t:
            add(t)
        return buf.getvalue()

    def add_control(t):
        ti = tarfile.TarInfo("./control")
        ti.size, ti.mode, ti.mtime = len(ctl), 0o644, int(time.time())
        t.addfile(ti, io.BytesIO(ctl))

    def add_data(t):
        for rel in files:
            t.add(os.path.join(root, rel), "./" + rel, recursive=False)

    blob = b"!<arch>\n" + _ar_member("debian-binary", b"2.0\n") + _ar_member("control.tar.gz", tgz(add_control)) \
        + _ar_member("data.tar.gz", tgz(add_data))
    with open(out_path, "wb") as f:
        f.write(blob)
    return len(files)


def backup_summary(slot, layout=None):
    """[(key, title, description, warning, size_bytes, available)] for the backup checklist."""
    out = []
    with _slot_root_ctx(slot, layout) as root:
        for key, title, desc, warn in CATEGORIES:
            if key == "plugins":
                n = len(installed_plugins(root))
                out.append((key, title, "%d plugins : %s" % (n, desc), warn, 0, n > 0))
                continue
            paths = category_paths(root, key)
            size = sum(_tree_size(os.path.join(root, p)) for p in paths)
            out.append((key, title, desc, warn, size, bool(paths)))
    return out


def human_bytes(b):
    if b < 1024 * 1024:
        return "%d Ko" % max(1, b // 1024) if b else "0 Ko"
    return human_mb(b // MB)


def _run_tar(job, args, cwd, out_path, est_bytes, p0, p1):
    """Run tar with progress (size of the archive being written) and instant cancel."""
    job.proc = subprocess.Popen(args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, close_fds=True)
    try:
        while job.proc.poll() is None:
            if job.cancelled:
                job.proc.kill()
                break
            try:
                job.set_progress(p0 + (p1 - p0) * min(1.0, os.path.getsize(out_path) / float(max(1, est_bytes))))
            except Exception:
                pass
            time.sleep(0.3)
        out = job.proc.stdout.read().decode("utf-8", "ignore")
        rc = job.proc.wait()
    finally:
        job.proc = None
    return rc, out


def backup_custom(job, slot, keys, dest_mount, layout=None, plugins=None):
    """Archive exactly the chosen categories of a slot into <dest>/WMultiBoot/backups.
    plugins: the package names to keep (None = all installed). Plugins missing from the
    feed (your own plugins, GitHub installs) are re-packed as .ipk inside the archive."""
    keys = [k for k in keys if k in CAT_TITLES]
    if not keys:
        raise MBError("Cochez au moins un élément à sauvegarder.")
    if not dest_mount:
        raise MBError("Aucun disque de sauvegarde disponible.")
    d = work_dir(dest_mount, "backups")
    tmpd = work_dir(dest_mount, "tmp")
    label = sanitize((slot.info or {}).get("label", "image"))
    final = os.path.join(d, "sauvegarde-%s-%s.tar.gz" % (label, time.strftime("%Y%m%d-%H%M%S")))
    part = final + ".partial"
    meta_dir = os.path.join(tmpd, "meta-%d" % os.getpid())
    remove_quiet(meta_dir)
    os.makedirs(meta_dir)
    addons, addon_elf = [], []
    lst = os.path.join(tmpd, "addons-%d.lst" % os.getpid())
    try:
        with _slot_root_ctx(slot, layout) as root:
            job.say("Préparation : %s" % ", ".join(CAT_TITLES[k] for k in keys), 3)
            paths, size = [], 0
            if "addons" in keys:
                job.say("Recherche des ajouts installés à la main…", 3)
                addons, asize, addon_elf = addon_paths(root, job)
                size += asize
            for k in keys:
                if k in ("plugins", "addons"):
                    continue
                for p in category_paths(root, k):
                    paths.append(p)
                    size += _tree_size(os.path.join(root, p))
                job.check()
            have = installed_plugins(root) if "plugins" in keys else []
            plugins = [n for n in have if plugins is None or n in plugins]
            if not paths and not plugins and not addons:
                raise MBError("Rien à sauvegarder : ces éléments n'existent pas dans cette image.")
            need = size // MB + 50
            free, _ = fs_usage(dest_mount)
            if free < need:
                raise MBError("Espace insuffisant sur %s : %s libres, %s nécessaires." % (dest_mount, human_mb(free), human_mb(need)))
            manifest = "image=%s\nbox=%s\ndate=%s\ncategories=%s\nsource=%s\n" % (
                (slot.info or {}).get("label", "?"), (slot.info or {}).get("box", ""), time.strftime("%Y-%m-%d %H:%M"),
                ",".join(keys), slot.where or slot.kind)
            write_file(os.path.join(meta_dir, MANIFEST), manifest)
            members = [MANIFEST]
            if plugins:
                write_file(os.path.join(meta_dir, PLUGIN_LIST), "\n".join(plugins) + "\n")
                members.append(PLUGIN_LIST)
                feed = feed_packages(root)
                extra = [n for n in plugins if n not in feed] if feed else []
                if extra:
                    os.makedirs(os.path.join(meta_dir, IPK_DIR))
                    for n in extra:
                        job.check()
                        job.say("Copie du plugin hors feed : %s" % n.replace("enigma2-plugin-", ""), 4)
                        out_ipk = os.path.join(meta_dir, IPK_DIR, n + ".ipk")
                        try:
                            if not repack_ipk(root, n, out_ipk):
                                remove_quiet(out_ipk)
                        except Exception as e:
                            log("repack %s: %s" % (n, e))
                            remove_quiet(out_ipk)
                    if os.listdir(os.path.join(meta_dir, IPK_DIR)):
                        members.append(IPK_DIR)
            # manifest first (read back quickly), then the files of the image
            args = ["tar", "-czf", part, "-C", meta_dir] + members
            if paths:
                args += ["-C", root, "--exclude=*backup*", "--exclude=*.bak", "--exclude=epg.dat",
                         "--exclude=*.tar.gz"] + ["./" + p for p in paths]
            if addons:
                write_file(lst, "".join("./%s\n" % a for a in addons))
                args += ["-C", root, "-T", lst]
            job.say("Sauvegarde de %s…" % human_bytes(size), 8)
            rc, out = _run_tar(job, args, None, part, size * 0.5 + 1, 8, 97)
            if job.cancelled:
                remove_quiet(part)
                raise Cancelled("Sauvegarde annulée : rien n'a été gardé.")
            if rc not in (0, 1) or not os.path.isfile(part):
                remove_quiet(part)
                if "no space" in out.lower():
                    raise MBError("Disque plein pendant la sauvegarde.")
                raise MBError("Échec de la sauvegarde (tar %s) : %s" % (rc, out.strip()[-160:]))
            os.rename(part, final)
            sync()
    finally:
        remove_quiet(meta_dir)
        remove_quiet(lst)
    job.last_backup = final
    job.say("Sauvegarde terminée.", 100)
    what = ", ".join(CAT_TITLES[k] for k in keys)
    if plugins:
        what += " (%d plugins)" % len(plugins)
    if addons:
        what += " (%d fichiers ajoutés à la main)" % len(addons)
    if addon_elf:
        what += "\n%d programmes non sauvegardés par sécurité (à réinstaller avec leur plugin)." % len(addon_elf)
    return "Sauvegarde créée (%s) :\n%s\n\nContenu : %s" % (human_bytes(os.path.getsize(final)), final, what)


def backup_settings(job, slot, dest_mount, layout=None):
    """Compatibility: channels + satellites + Enigma2 settings + plugin settings."""
    return backup_custom(job, slot, ["channels", "satellites", "settings", "plugins_conf"], dest_mount, layout)


def read_backup(path):
    """{'kind': 'slot'|'custom', 'categories': {key: n_files}, 'manifest': {...}} without full extraction."""
    import tarfile
    name = os.path.basename(path)
    if "-backup-" in name and not name.startswith(("sauvegarde-", "reglages-")):
        return {"kind": "slot", "categories": {}, "manifest": {}}
    cats, manifest, plugins, ipks = {}, {}, [], []
    try:
        with tarfile.open(path, "r:gz") as t:
            for m in t:
                c = classify(m.name)
                rel = m.name[2:] if m.name.startswith("./") else m.name
                if c == "meta" and m.isfile() and rel == MANIFEST:
                    manifest = parse_kv(t.extractfile(m).read().decode("utf-8", "ignore"))
                elif c == "meta" and m.isfile() and rel == PLUGIN_LIST:
                    plugins = [n for n in t.extractfile(m).read().decode("utf-8", "ignore").split()
                               if re.match(r"^[a-z0-9.+-]+$", n)]
                    cats["plugins"] = len(plugins)
                elif c == "meta" and m.isfile() and rel.startswith(IPK_DIR + "/"):
                    ipks.append(os.path.basename(rel)[:-4])
                elif c and c != "meta" and not m.isdir():
                    cats[c] = cats.get(c, 0) + 1
    except Exception:
        raise MBError("Sauvegarde corrompue ou illisible : %s" % name)
    return {"kind": "custom", "categories": cats, "manifest": manifest, "plugins": plugins, "ipks": ipks}


def _safe_member(m):
    if m.issym() or m.islnk():
        ln = m.linkname or ""
        if ln.startswith("/") or ".." in ln.split("/"):
            return False
    if m.isdev() or m.isfifo():
        return False
    return True


def restore_custom(job, archive, keys, slot, layout=None, plugins=None):
    """Restore the chosen categories of a backup into a slot.
    plugins: package names to reinstall (None = all listed in the backup).
    Another image: files written directly; plugins are installed at its first start
    (first-boot hook). The running image: files are staged, then the GUI is restarted
    by a detached script that copies them (Enigma2 must be stopped)."""
    import tarfile
    keys = [k for k in keys if k in CAT_TITLES]
    if not keys:
        raise MBError("Cochez au moins un élément à restaurer.")
    running = slot.running or (slot.root and is_running_root(slot.root))
    if not running:
        dest = _writable_slot_root(slot)
    else:
        dest = "/"
    st = storage_for(archive)
    tmpd = work_dir(st["mount"], "tmp") if st else "/tmp"
    stamp = int(time.time())
    stage = os.path.join(tmpd, "restore-%d" % stamp) if running else None
    ipk_tmp = None
    out_root = stage or dest
    if stage:
        os.makedirs(stage)
    done, skipped, kept, wanted_plugins, ipk_members = 0, 0, 0, [], {}
    try:
        job.say("Lecture de la sauvegarde…", 5)
        with tarfile.open(archive, "r:gz") as t:
            members = []
            for m in t:
                job.check()
                c = classify(m.name)
                rel = m.name[2:] if m.name.startswith("./") else m.name
                if c == "meta":
                    if rel == PLUGIN_LIST and "plugins" in keys and m.isfile():
                        listed = [n for n in t.extractfile(m).read().decode("utf-8", "ignore").split()
                                  if re.match(r"^[a-z0-9.+-]+$", n)]
                        wanted_plugins = [n for n in listed if plugins is None or n in plugins]
                    elif rel.startswith(IPK_DIR + "/") and m.isfile():
                        ipk_members[os.path.basename(rel)[:-4]] = m.name
                    continue
                if c in keys and _safe_member(m):
                    if c == "addons" and os.path.lexists(os.path.join(dest, rel)):
                        kept += 1                   # the target image already has it: keep its own
                        continue
                    members.append(m)
                elif c is None or not _safe_member(m):
                    skipped += 1
        if not members and not wanted_plugins:
            raise MBError("Cette sauvegarde ne contient pas les éléments choisis.")
        job.say("Restauration de %d fichiers…" % len(members), 15)
        ipk_out = None
        if wanted_plugins:
            if running:
                ipk_tmp = os.path.join(tmpd, "ipk-%d" % stamp)
                ipk_out = ipk_tmp
            else:
                ipk_out = os.path.join(dest, FIRSTBOOT_DIR, "ipk")
        need_ipk = dict((ipk_members[n], n) for n in wanted_plugins if n in ipk_members)
        with tarfile.open(archive, "r:gz") as t:
            wanted = set(m.name for m in members)
            total = max(1, len(members))
            for m in t:
                if m.name in need_ipk:
                    if not os.path.isdir(ipk_out):
                        os.makedirs(ipk_out)
                    with open(os.path.join(ipk_out, need_ipk[m.name] + ".ipk"), "wb") as f:
                        shutil.copyfileobj(t.extractfile(m), f)
                    continue
                if m.name not in wanted:
                    continue
                job.check()
                try:
                    try:
                        t.extract(m, out_root, filter="tar")       # Python 3.12+: refuses unsafe paths
                    except TypeError:
                        t.extract(m, out_root)
                    done += 1
                except Exception as e:
                    log("restore skip %s: %s" % (m.name, e))
                    skipped += 1
                job.set_progress(15 + 60 * done / float(total))
        sync()
        msg = ["%d fichiers restaurés dans %s." % (done, "l'image en cours" if running else slot.title())]
        if skipped:
            msg.append("%d fichiers ignorés (non autorisés ou pas cochés)." % skipped)
        if kept:
            msg.append("%d ajouts déjà présents dans l'image : gardés tels quels." % kept)
        if wanted_plugins:
            if running:
                job.cancellable = True
                msg.append(reinstall_plugins(job, wanted_plugins, ipk_tmp))
            else:
                have = set(installed_plugins(dest))
                todo = [n for n in wanted_plugins if n not in have]
                if todo:
                    install_firstboot_hook(dest, todo)
                    msg.append("%d plugins seront installés automatiquement au premier démarrage de cette image "
                               "(il faut Internet ; le démarrage est un peu plus long)." % len(todo))
                else:
                    msg.append("Plugins : tous déjà présents dans cette image.")
        if running and done:
            job.cancellable = False
            script = os.path.join(tmpd, "wmb-apply.sh")
            write_file(script, "#!/bin/sh\nsleep 2\ninit 4\nsleep 4\ncp -a '%s'/. /\nsync\nrm -rf '%s'\ninit 3\nrm -f '%s'\n"
                       % (stage, stage, script))
            os.chmod(script, 0o755)
            subprocess.Popen(["setsid", "sh", script] if which("setsid") else ["sh", script],
                             stdout=open("/dev/null", "w"), stderr=subprocess.STDOUT, close_fds=True)
            stage = None                    # the script owns it now
            msg.append("L'interface va redémarrer dans quelques secondes pour appliquer les réglages.")
            if "network" in keys:
                msg.append("Le réseau sera appliqué au prochain redémarrage de la box.")
        job.say("Terminé.", 100)
        return "\n".join(msg)
    finally:
        if stage:
            remove_quiet(stage)
        if ipk_tmp:
            remove_quiet(ipk_tmp)


def reinstall_plugins(job, names, ipk_dir=None):
    """opkg install (running image) of the listed plugins that are missing: from the feed,
    else from the .ipk saved in the backup."""
    have = set(installed_plugins("/"))
    missing = [n for n in names if n not in have and re.match(r"^[a-z0-9.+-]+$", n)]
    if not missing:
        return "Plugins : tous déjà installés."
    job.say("Mise à jour de la liste des paquets…", 78)
    run(["opkg", "update"], timeout=300)
    ok, fail = [], []
    for i, n in enumerate(missing):
        job.check()
        job.say("Installation de %s (%d/%d)…" % (n.replace("enigma2-plugin-", ""), i + 1, len(missing)),
                80 + 18 * i // len(missing))
        rc, out = run(["opkg", "install", n], timeout=600)
        local = os.path.join(ipk_dir, n + ".ipk") if ipk_dir else ""
        if rc != 0 and local and os.path.isfile(local):
            rc, out = run(["opkg", "install", local], timeout=600)
        (ok if rc == 0 else fail).append(n)
    text = "Plugins réinstallés : %d." % len(ok)
    if fail:
        text += " Introuvables : %s" % ", ".join(f.replace("enigma2-plugin-", "") for f in fail[:8]) + ("…" if len(fail) > 8 else "")
    return text


FIRSTBOOT_DIR = "etc/wmb-firstboot"
FIRSTBOOT_SCRIPT = """#!/bin/sh
# Wacayoub MultiBoot - first start of an updated/restored image: install the chosen
# plugins once (from the feed, else from the saved .ipk), then remove itself.
# Runs before Enigma2 starts; every step has a time limit so the boot can never hang.
D=/%(dir)s
rm -f /%(hook)s
[ -f $D/plugins.txt ] || exit 0
LOG=$D/opkg.log
KEEP=/tmp/wmb-keep-$$.tgz
( cd %(root)s && find etc/enigma2 etc/tuxbox/config -type f -size -2048k > $KEEP.lst 2>/dev/null
  tar -czf $KEEP -T $KEEP.lst 2>/dev/null ) || rm -f $KEEP
rm -f $KEEP.lst
NET=0
i=0
while [ $i -lt 6 ]; do
	if timeout 120 opkg update >>$LOG 2>&1; then NET=1; break; fi
	i=$((i+1)); sleep 10
done
INST=0; FAIL=""
for p in $(cat $D/plugins.txt); do
	case "$p" in *[!a-z0-9.+-]*|"") continue;; esac
	if opkg status "$p" 2>/dev/null | grep -q "install ok installed"; then continue; fi
	if [ $NET = 1 ] && timeout 600 opkg install "$p" >>$LOG 2>&1; then INST=$((INST+1)); continue; fi
	if [ -f "$D/ipk/$p.ipk" ] && timeout 300 opkg install "$D/ipk/$p.ipk" >>$LOG 2>&1; then INST=$((INST+1)); continue; fi
	FAIL="$FAIL $p"
done
[ -f $KEEP ] && tar -xzf $KEEP -C %(root)s 2>/dev/null
rm -f $KEEP
printf 'installed=%%s\\nfailed=%%s\\nnetwork=%%s\\n' "$INST" "$FAIL" "$NET" > $D/result.txt
rm -rf $D/ipk $D/plugins.txt
sync
exit 0
"""


def _default_runlevel(root):
    m = re.search(r"^[^#:]*:(\d):initdefault:", read_file(os.path.join(root, "etc/inittab")), re.M)
    return m.group(1) if m else "3"


def install_firstboot_hook(root, names):
    """Install the plugins of `names` at the first start of the image in root (not running)."""
    if is_running_root(root):
        raise MBError("Image en cours : les plugins sont installés tout de suite.")
    names = [n for n in names if re.match(r"^[a-z0-9.+-]+$", n)]
    rc = os.path.join(root, "etc/rc%s.d" % _default_runlevel(root))
    if not os.path.isdir(rc):
        raise MBError("Cette image n'a pas de dossier %s : plugins non programmés." % rc[len(root):])
    hook_rel = "etc/rc%s.d/S98wmbfirstboot" % _default_runlevel(root)
    d = os.path.join(root, FIRSTBOOT_DIR)
    if not os.path.isdir(d):
        os.makedirs(d)
    prev = read_file(os.path.join(d, "plugins.txt")).split()
    write_file(os.path.join(d, "plugins.txt"), "\n".join(sorted(set(prev + names))) + "\n")
    remove_quiet(os.path.join(d, "result.txt"))
    hook = os.path.join(root, hook_rel)
    write_file(hook, FIRSTBOOT_SCRIPT % {"dir": FIRSTBOOT_DIR, "hook": hook_rel, "root": "/"})
    os.chmod(hook, 0o755)
    return hook_rel


def firstboot_result(root="/"):
    """Result of the first-boot plugin install of this image, read once (then removed)."""
    p = os.path.join(root, FIRSTBOOT_DIR, "result.txt")
    kv = parse_kv(read_file(p))
    if not kv:
        return None
    remove_quiet(p)
    fail = [f.replace("enigma2-plugin-", "") for f in kv.get("failed", "").split()]
    text = "Wacayoub MultiBoot : %s plugins installés après la mise à jour." % kv.get("installed", "0")
    if fail:
        text += "\nNon trouvés : %s" % ", ".join(fail[:10])
    if kv.get("network") != "1":
        text += "\nPas d'Internet au démarrage : seuls les plugins sauvegardés en .ipk ont pu être installés."
    return text


def copy_self(root):
    """Put this plugin into another image (so the updated image keeps it). No .pyc."""
    src = os.path.dirname(os.path.abspath(__file__))
    ext = os.path.join(root, "usr/lib/enigma2/python/Plugins/Extensions")
    if not os.path.isdir(ext) or same_file(root, "/"):
        return False
    dst = os.path.join(ext, os.path.basename(src))
    remove_quiet(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("*.pyc", "*.pyo", "__pycache__"))
    return True


def find_update(catalog, slot):
    """Newest stable catalog image of the slot's distribution: (item, is_newer) or (None, False)."""
    info = slot.info or {}
    key = distro_key(info.get("distro", ""))
    if key == "unknown":
        return None, False
    best = None
    for distro, its in catalog:
        if distro_key(distro) != key:
            continue
        for it in its:
            if it["eol"] or it["beta"] or "beta" in it["name"].lower():
                continue
            m = re.search(r"(20\d{6})", it["name"])
            day = m.group(1) if m else time.strftime("%Y%m%d", time.localtime(it["date"] or 0))
            if best is None or day > best[1]:
                best = (it, day)
    if not best:
        return None, False
    return best[0], best[1] > (info.get("date") or "0")


def update_image(job, layout, src, image, target, keys, plugins, backup_mount, name=None):
    """Smart update: back up the chosen elements of `src`, install `image` as a NEW slot,
    restore everything into it and schedule the plugins for its first start.
    The old image is never modified."""
    job.say("Étape 1/4 : sauvegarde de « %s »…" % src.title(), 1)
    backup_custom(job, src, keys, backup_mount, layout, plugins)
    archive = job.last_backup
    job.check()
    job.say("Étape 2/4 : installation de la nouvelle image…", 0)
    layout.install(job, image, target=target, name=name)
    new_root = getattr(job, "new_root", None)
    if not new_root or not os.path.isdir(new_root):
        raise MBError("La nouvelle image est introuvable après l'installation.")
    job.cancellable = False                         # the slot exists: finish the job
    new = Slot("new", 0, layout.key if layout.key in ("chroot", "omb") else "chroot", root=new_root,
               info=image_info(new_root), where=new_root)
    job.say("Étape 3/4 : restauration de vos réglages dans la nouvelle image…", 0)
    try:
        res = restore_custom(job, archive, keys, new, layout, plugins)
    except MBError as e:
        raise MBError("La nouvelle image est installée mais la restauration a échoué : %s\n"
                      "Votre sauvegarde est gardée : %s" % (e, archive))
    job.say("Étape 4/4 : ajout de Wacayoub MultiBoot dans la nouvelle image…", 98)
    try:
        copy_self(new_root)
    except Exception as e:
        log("copy_self: %s" % e)
    job.new_root = new_root
    job.say("Mise à jour prête.", 100)
    return ("Nouvelle image prête : %s\n%s\n\nL'ancienne image « %s » est gardée telle quelle.\nSauvegarde : %s"
            % ((new.info or {}).get("label", os.path.basename(new_root)), res, src.title(), archive))


def restore_settings(job, archive, dest_slot):
    """Compatibility: restore every category present."""
    info = read_backup(archive)
    return restore_custom(job, archive, list(info["categories"].keys()) or ["channels"], dest_slot)


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
