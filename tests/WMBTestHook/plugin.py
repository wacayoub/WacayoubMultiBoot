# Test-only helper (installed during tests, removed afterwards).
# /tmp/wmb_cmd: "open" | "open_noslots" | "open_unknown"
import os
from Plugins.Plugin import PluginDescriptor
from enigma import eTimer

_s = {}


def _open(mode):
    from Plugins.Extensions.WMultiBoot import core
    from Plugins.Extensions.WMultiBoot.ui import WMBMain
    saved = {}
    if mode == "open_noslots":
        class P(object):
            device, on_flash, init_target, has_omb_init, boot_conf, info, error = "", True, "", False, None, None, ""
        saved = {"FlashProbe": core.FlashProbe, "storages": core.storages}
        core.FlashProbe = P
        core.storages = lambda: []
        _orig_scan = core.SingleLayout.scan
        saved["scan"] = _orig_scan

        def scan(self):
            self.slots = []
            self.notes.append("Aucune structure multiboot n'a été trouvée sur ce récepteur.")
        core.SingleLayout.scan = scan
    elif mode == "open_unknown":
        real = core.read_file
        saved = {"read_file": real}

        def fake(path, default=""):
            if path.startswith("/proc/stb/") or path in ("/etc/image-version", "/etc/hostname"):
                return ""
            return real(path, default)
        core.read_file = fake
    scr = _s["session"].open(WMBMain)

    def restore():
        for k, v in saved.items():
            if k == "scan":
                core.SingleLayout.scan = v
            else:
                setattr(core, k, v)
    scr.onClose.append(restore)


def _tick():
    try:
        if os.path.exists("/tmp/wmb_cmd"):
            cmd = open("/tmp/wmb_cmd").read().strip()
            os.remove("/tmp/wmb_cmd")
            if cmd.startswith("open"):
                _open(cmd)
    except Exception:
        import traceback
        open("/tmp/wmb_hook.log", "a").write(traceback.format_exc())


def sessionstart(reason, session=None, **kw):
    if session:
        _s["session"] = session
        _s["t"] = eTimer()
        _s["t"].callback.append(_tick)
        _s["t"].start(1000, False)


def Plugins(**kw):
    return [PluginDescriptor(where=PluginDescriptor.WHERE_SESSIONSTART, fnc=sessionstart)]
