# -*- coding: utf-8 -*-
"""Wacayoub MultiBoot - screens. All handlers are wrapped so that an error shows a
message instead of crashing enigma2. Long work runs in core.Job threads; the GUI
only polls them with an eTimer."""
from __future__ import absolute_import

import os
import traceback

from enigma import eListboxPythonMultiContent, gFont, getDesktop, eTimer, \
    RT_HALIGN_LEFT, RT_HALIGN_RIGHT, RT_HALIGN_CENTER, RT_VALIGN_CENTER
from Screens.Screen import Screen
from Screens.MessageBox import MessageBox
from Screens.ChoiceBox import ChoiceBox
from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.MenuList import MenuList
from Components.ProgressBar import ProgressBar
from Components.MultiContent import MultiContentEntryText

from . import core
from .core import Job, MBError, log, human_mb, fmt_date

# --------------------------------------------------------------------------- look

C_BG, C_PANEL, C_PANEL2, C_LINE = 0x0b1020, 0x131a2e, 0x1e2740, 0x26324f
C_TEXT, C_MUTED, C_ACCENT = 0xe8edf5, 0x8b98b0, 0x22d3ee
C_GREEN, C_RED, C_YELLOW, C_BLUE = 0x22c55e, 0xef4444, 0xeab308, 0x3b82f6
C_SEL = 0x1d4ed8


def hexc(c):
    return "#00%06x" % c


FONT_R = "Regular"
FONT_B = "Regular"
_fonts_done = [False]


def setup_fonts():
    """Register modern fonts when the image ships them, else keep the skin's
    'Regular' alias (always present)."""
    global FONT_R, FONT_B
    if _fonts_done[0]:
        return
    _fonts_done[0] = True
    try:
        from enigma import addFont
    except Exception:
        return
    base = "/usr/share/fonts/"

    def reg(alias, names):
        for n in names:
            p = base + n
            if os.path.isfile(p):
                try:
                    try:
                        addFont(p, alias, 100, False, 0)
                    except TypeError:
                        addFont(p, alias, 100, False)
                    return alias
                except Exception as e:
                    log("addFont %s: %s" % (p, e))
        return None

    FONT_R = reg("WMBRegular", ("Roboto-Regular.ttf", "LiberationSans-Regular.ttf", "OpenSans-Regular.ttf",
                                "DejaVuSans.ttf", "nmsbd.ttf")) or "Regular"
    FONT_B = reg("WMBBold", ("Roboto-Bold.ttf", "LiberationSans-Bold.ttf", "OpenSans-Bold.ttf",
                             "DejaVuSans-Bold.ttf")) or FONT_R


def _scale():
    try:
        w = getDesktop(0).size().width()
    except Exception:
        w = 1280
    return (w or 1280) / 1920.0


F = _scale()


def S(v):
    return int(round(v * F))


def _w(name, x, y, w, h, font=None, size=0, color=C_TEXT, halign="left", valign="center", extra=""):
    f = ' font="%s;%d"' % (font, S(size)) if font else ""
    return ('<widget name="%s" position="%d,%d" size="%d,%d"%s foregroundColor="%s" backgroundColor="%s" '
            'transparent="1" halign="%s" valign="%s" %s/>' % (name, S(x), S(y), S(w), S(h), f, hexc(color),
                                                             hexc(C_BG), halign, valign, extra))


def _box(x, y, w, h, color, z=-2):
    return '<eLabel position="%d,%d" size="%d,%d" backgroundColor="%s" zPosition="%d"/>' % (
        S(x), S(y), S(w), S(h), hexc(color), z)


def _txt(x, y, w, h, text, font, size, color, bg, halign="left"):
    return ('<eLabel position="%d,%d" size="%d,%d" text="%s" font="%s;%d" foregroundColor="%s" '
            'backgroundColor="%s" transparent="1" halign="%s" valign="center" zPosition="1"/>'
            % (S(x), S(y), S(w), S(h), text, font, S(size), hexc(color), hexc(bg), halign))


def _keys(y):
    out = []
    for i, (name, col) in enumerate((("key_red", C_RED), ("key_green", C_GREEN),
                                     ("key_yellow", C_YELLOW), ("key_blue", C_BLUE))):
        x = 60 + i * 340
        out.append(_box(x, y + 14, 8, 36, col, 1))
        out.append(_w(name, x + 22, y, 300, 64, FONT_R, 26, C_TEXT))
    return "".join(out)


def _screen(name, title, body):
    return ('<screen name="%s" position="0,0" size="%d,%d" flags="wfNoBorder" backgroundColor="%s" title="%s">%s</screen>'
            % (name, S(1920), S(1080), hexc(C_BG), title, body))


def main_skin():
    b = [_box(0, 0, 1920, 1080, C_BG, -3), _box(0, 0, 1920, 120, C_PANEL),
         _box(0, 120, 1920, 3, C_ACCENT, -1),
         _w("title", 60, 14, 900, 56, FONT_B, 40, C_TEXT),
         _w("subtitle", 60, 70, 1300, 38, FONT_R, 24, C_MUTED),
         _w("nextboot", 1100, 14, 760, 56, FONT_B, 26, C_ACCENT, "right"),
         _w("version", 1400, 70, 460, 38, FONT_R, 22, C_MUTED, "right"),
         _box(48, 150, 1124, 790, C_PANEL),
         ('<widget name="list" position="%d,%d" size="%d,%d" scrollbarMode="showOnDemand" '
          'backgroundColor="%s" foregroundColor="%s" backgroundColorSelected="%s" '
          'foregroundColorSelected="#00ffffff" transparent="0" zPosition="1"/>'
          % (S(60), S(162), S(1100), S(768), hexc(C_PANEL), hexc(C_TEXT), hexc(C_SEL))),
         _box(1200, 150, 672, 500, C_PANEL),
         _w("dtitle", 1230, 165, 620, 50, FONT_B, 30, C_ACCENT),
         _w("details", 1230, 222, 620, 420, FONT_R, 24, C_TEXT, "left", "top"),
         _box(1200, 670, 672, 270, C_PANEL),
         _txt(1230, 682, 620, 40, "STOCKAGE", FONT_B, 24, C_MUTED, C_PANEL)]
    for i in range(3):
        y = 728 + i * 70
        b.append(_w("st%d_name" % i, 1230, y, 330, 32, FONT_R, 22, C_TEXT))
        b.append(_w("st%d_text" % i, 1560, y, 290, 32, FONT_R, 22, C_MUTED, "right"))
        b.append('<widget name="st%d_bar" position="%d,%d" size="%d,%d" borderWidth="0" '
                 'foregroundColor="%s" backgroundColor="%s" zPosition="1"/>'
                 % (i, S(1230), S(y + 38), S(620), S(10), hexc(C_ACCENT), hexc(C_LINE)))
    b += [_w("hint", 60, 950, 1810, 40, FONT_R, 22, C_MUTED),
          _box(0, 1000, 1920, 80, C_PANEL), _keys(1008)]
    return _screen("WMultiBootMain", "Wacayoub MultiBoot", "".join(b))


def progress_skin():
    b = [_box(0, 0, 1920, 1080, C_BG, -3), _box(260, 200, 1400, 680, C_PANEL),
         _box(260, 200, 1400, 6, C_ACCENT, -1),
         _w("title", 310, 230, 1300, 60, FONT_B, 38, C_TEXT),
         _w("step", 310, 300, 1300, 50, FONT_R, 28, C_ACCENT),
         '<widget name="bar" position="%d,%d" size="%d,%d" borderWidth="0" foregroundColor="%s" '
         'backgroundColor="%s" zPosition="1"/>' % (S(310), S(370), S(1200), S(18), hexc(C_ACCENT), hexc(C_LINE)),
         _w("percent", 1520, 352, 90, 50, FONT_B, 28, C_TEXT, "right"),
         _w("log", 310, 420, 1300, 380, FONT_R, 22, C_MUTED, "left", "top"),
         _w("hint", 310, 810, 1300, 50, FONT_R, 24, C_TEXT)]
    return _screen("WMultiBootProgress", "Wacayoub MultiBoot", "".join(b))


# --------------------------------------------------------------------------- helpers

def connect_timer(timer, fn):
    try:
        timer.callback.append(fn)
        return None
    except AttributeError:
        return timer.timeout.connect(fn)


def safe(fn):
    def wrapper(self, *a, **kw):
        try:
            return fn(self, *a, **kw)
        except MBError as e:
            self.error(str(e))
        except Exception as e:
            log("UI error in %s: %s" % (fn.__name__, traceback.format_exc()))
            self.error("Erreur inattendue : %s\n(détails dans %s)" % (e, core.LOG_FILE))
    wrapper.__name__ = fn.__name__
    return wrapper


class Base(Screen):
    def error(self, text):
        log("UI message: %s" % text)
        try:
            self.session.open(MessageBox, text, MessageBox.TYPE_ERROR)
        except Exception:
            log("cannot show error: %s" % text)

    def info(self, text, cb=None):
        if cb:
            self.session.openWithCallback(cb, MessageBox, text, MessageBox.TYPE_INFO)
        else:
            self.session.open(MessageBox, text, MessageBox.TYPE_INFO)

    def ask(self, text, cb, default=False):
        def _cb(answer):
            if answer:
                cb()
        try:
            self.session.openWithCallback(_cb, MessageBox, text, MessageBox.TYPE_YESNO, default=default)
        except TypeError:
            self.session.openWithCallback(_cb, MessageBox, text, MessageBox.TYPE_YESNO)

    def choose(self, title, items, cb):
        def _cb(choice):
            if choice:
                cb(choice[1])
        self.session.openWithCallback(_cb, ChoiceBox, title=title, list=items)

    def set_title(self, t):
        try:
            self.setTitle(t)
        except Exception:
            pass


# --------------------------------------------------------------------------- progress

class WMBProgress(Base):
    def __init__(self, session, job, auto_close=False):
        self.skin = progress_skin()
        Base.__init__(self, session)
        self.job = job
        self.auto_close = auto_close
        self["title"] = Label(job.title)
        self["step"] = Label("")
        self["bar"] = ProgressBar()
        self["percent"] = Label("")
        self["log"] = Label("")
        self["hint"] = Label("EXIT : annuler")
        self["actions"] = ActionMap(["OkCancelActions"], {"ok": self.ok, "cancel": self.cancel}, -1)
        self.timer = eTimer()
        self._conn = connect_timer(self.timer, self.poll)
        self.onLayoutFinish.append(self.begin)
        self.onClose.append(self.timer.stop)
        self.set_title(job.title)

    def begin(self):
        self.timer.start(400, False)
        self.poll()

    @safe
    def poll(self):
        j = self.job
        self["step"].setText(j.step)
        self["bar"].setValue(j.progress)
        self["percent"].setText("%d %%" % j.progress)
        self["log"].setText("\n".join(j.lines[-9:]))
        if j.done:
            self.timer.stop()
            if j.ok and self.auto_close:
                self.close(j)
                return
            self["step"].setText("Terminé" if j.ok else "Échec")
            self["log"].setText(j.result)
            self["hint"].setText("OK : fermer")

    def ok(self):
        if self.job.done:
            self.close(self.job)

    def cancel(self):
        if self.job.done:
            self.close(self.job)
            return
        if not self.job.cancellable:
            self["hint"].setText("Opération critique en cours : impossible d'annuler maintenant.")
            return
        self.ask("Annuler l'opération en cours ?", self.job.cancel)


# --------------------------------------------------------------------------- main

class WMBMain(Base):
    def __init__(self, session):
        setup_fonts()
        self.skin = main_skin()
        Base.__init__(self, session)
        self.mbl = None
        self.scan_job = None
        self._keep = None
        self["title"] = Label("Wacayoub MultiBoot")
        self["subtitle"] = Label("Analyse du récepteur…")
        self["nextboot"] = Label("")
        self["version"] = Label("v%s" % core.VERSION)
        self["list"] = MenuList([], enableWrapAround=True, content=eListboxPythonMultiContent)
        self["dtitle"] = Label("")
        self["details"] = Label("")
        self["hint"] = Label("")
        for i in range(3):
            self["st%d_name" % i] = Label("")
            self["st%d_text" % i] = Label("")
            self["st%d_bar" % i] = ProgressBar()
        self["key_red"] = Label("Supprimer")
        self["key_green"] = Label("Démarrer")
        self["key_yellow"] = Label("Installer")
        self["key_blue"] = Label("Sauvegarder")
        lst = self["list"].l
        lst.setFont(0, gFont(FONT_B, S(30)))
        lst.setFont(1, gFont(FONT_R, S(22)))
        lst.setFont(2, gFont(FONT_B, S(20)))
        lst.setItemHeight(S(96))
        self["actions"] = ActionMap(["OkCancelActions", "ColorActions", "DirectionActions", "MenuActions"], {
            "ok": self.key_ok, "cancel": self.close, "menu": self.key_menu,
            "red": self.key_red, "green": self.key_green, "yellow": self.key_yellow, "blue": self.key_blue,
            "up": self.key_up, "down": self.key_down, "left": self.key_left, "right": self.key_right,
        }, -1)
        self.timer = eTimer()
        self._conn = connect_timer(self.timer, self.poll_scan)
        self.onLayoutFinish.append(self.rescan)
        self.onClose.append(self.timer.stop)
        self.onClose.append(lambda: log("UI: main closed"))
        self.onShown.append(self.mb_on_shown)
        self._catalog = None
        self.set_title("Wacayoub MultiBoot")
        log("UI: main created")

    @safe
    def mb_on_shown(self):
        log("UI: main shown")
        if self.mbl is not None:
            self.fill_storage()

    # ---- scanning
    @safe
    def rescan(self):
        self["subtitle"].setText("Analyse du récepteur…")
        self["hint"].setText("Détection des slots en cours…")
        self.scan_job = Job("scan").start(lambda job: core.detect_layout())
        self.timer.start(200, False)

    @safe
    def poll_scan(self):
        j = self.scan_job
        if not j or not j.done:
            return
        self.timer.stop()
        self.scan_job = None
        log("UI: scan done ok=%s" % j.ok)
        if not j.ok:
            self.mbl = None
            self["subtitle"].setText("Détection impossible")
            self["hint"].setText(j.result)
            return
        self.mbl = j.result
        keep, self._keep = self._keep, None
        self.fill(keep)

    def fill(self, keep_key=None):
        lay = self.mbl
        box = lay.box
        run = lay.running_slot()
        nxt = lay.next_slot()
        self["subtitle"].setText("%s %s   ·   %s   ·   en cours : %s" % (
            box["brand"], box["machine"], lay.name, run.title() if run else box["image"]))
        self["nextboot"].setText("Prochain démarrage : %s" % (nxt.title() if nxt else "?"))
        width = S(1100)
        rows = [self.row(s, width) for s in lay.slots]
        self["list"].setList(rows)
        idx = 0
        for i, s in enumerate(lay.slots):
            if s.running:
                idx = i
        for i, s in enumerate(lay.slots):
            if keep_key and s.key == keep_key:
                idx = i
        if rows:
            self["list"].moveToIndex(idx)
            log("UI: list %d rows, select %d" % (len(rows), idx))
        for name, cap, label in (("key_red", "delete", "Supprimer"), ("key_green", "boot", "Démarrer"),
                                 ("key_yellow", "install", "Installer"), ("key_blue", "backup", "Sauvegarder")):
            self[name].setText(label if lay.can(cap) else "—")
        self.fill_storage()
        hint = "OK : actions du slot   ·   MENU : options   ·   EXIT : quitter"
        if lay.notes:
            hint = " · ".join(lay.notes)
        self["hint"].setText(hint)
        self.update_details()

    def row(self, s, w):
        if s.running:
            badge, stc = C_GREEN, C_GREEN
        elif s.next_boot:
            badge, stc = C_ACCENT, C_ACCENT
        else:
            badge, stc = C_LINE, C_MUTED
        num = "F" if s.kind == "flash" else str(s.number)
        status = s.status()
        if s.extra.get("once") and s.next_boot and not s.running:
            status = "UNE FOIS"
        tw = w - S(96) - S(330)
        return [s,
                MultiContentEntryText(pos=(S(10), S(16)), size=(S(64), S(64)), font=0,
                                      flags=RT_HALIGN_CENTER | RT_VALIGN_CENTER, text=num,
                                      color=0xffffff, color_sel=0xffffff, backcolor=badge, backcolor_sel=badge),
                MultiContentEntryText(pos=(S(96), S(8)), size=(tw, S(46)), font=0,
                                      flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER, text=s.title(),
                                      color=C_TEXT if not s.empty else C_MUTED, color_sel=0xffffff),
                MultiContentEntryText(pos=(S(96), S(54)), size=(w - S(110), S(34)), font=1,
                                      flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER, text=s.subtitle(),
                                      color=C_MUTED, color_sel=0xdbeafe),
                MultiContentEntryText(pos=(w - S(330), S(8)), size=(S(310), S(46)), font=2,
                                      flags=RT_HALIGN_RIGHT | RT_VALIGN_CENTER, text=status,
                                      color=stc, color_sel=0xffffff)]

    def fill_storage(self):
        sts = core.storages()[:3]
        for i in range(3):
            if i < len(sts):
                st = sts[i]
                used = 100 - (100 * st["free"] // st["total"] if st["total"] else 0)
                self["st%d_name" % i].setText("%s  (%s)" % (st["mount"], st["fstype"]))
                self["st%d_text" % i].setText("%s libres / %s" % (human_mb(st["free"]), human_mb(st["total"])))
                self["st%d_bar" % i].setValue(used)
                self["st%d_bar" % i].show()
            else:
                self["st%d_name" % i].setText("" if i else "Aucun disque monté")
                self["st%d_text" % i].setText("")
                self["st%d_bar" % i].hide()

    def current(self):
        cur = self["list"].getCurrent()
        if cur:
            return cur[0]
        return None

    def update_details(self):
        s = self.current()
        if not s:
            self["dtitle"].setText("Aucun slot")
            self["details"].setText("\n".join(self.mbl.notes) if self.mbl else "")
            return
        self["dtitle"].setText(s.title())
        lines = []
        if s.info:
            lines.append("Version : %s" % (s.info.get("version") or "?"))
            if s.info.get("date"):
                lines.append("Date : %s" % fmt_date(s.info["date"]))
            if s.info.get("box"):
                lines.append("Prévue pour : %s" % s.info["box"])
            if s.info.get("modules"):
                lines.append("Noyau image : %s" % ", ".join(s.info["modules"]))
        kinds = {"flash": "Flash interne", "chroot": "Image sur disque (HDD/USB)", "emmc": "Slot eMMC",
                 "omb": "OpenMultiboot", "recovery": "Recovery"}
        lines.append("Type : %s" % kinds.get(s.kind, s.kind))
        if s.where:
            lines.append("Emplacement : %s" % s.where)
        if s.device:
            lines.append("Partition : %s" % s.device)
        st = []
        if s.running:
            st.append("en cours")
        if s.next_boot:
            st.append("prochain démarrage" + (" (une fois)" if s.extra.get("once") else ""))
        if st:
            lines.append("Statut : %s" % ", ".join(st))
        if s.size_mb is not None:
            lines.append("Taille : %s" % human_mb(s.size_mb))
        for w in self.mbl.warnings_for(s):
            lines.append("Attention : " + w)
        self["details"].setText("\n".join(lines))

    # ---- navigation
    def _move(self, attr):
        inst = self["list"].instance
        if inst:
            inst.moveSelection(getattr(inst, attr))
        self.update_details()

    def key_up(self):
        self._move("moveUp")

    def key_down(self):
        self._move("moveDown")

    def key_left(self):
        self._move("pageUp")

    def key_right(self):
        self._move("pageDown")

    # ---- jobs
    def run_job(self, title, func, done_cb=None, *args):
        job = Job(title).start(func, *args)

        def closed(j=None):
            key = self.current().key if self.current() else None
            if done_cb and job.ok:
                done_cb(job)
            self.rescan_keep(key)
        self.session.openWithCallback(closed, WMBProgress, job)

    def rescan_keep(self, key):
        self._keep = key
        self["hint"].setText("Actualisation…")
        self.scan_job = Job("scan").start(lambda job: core.detect_layout())
        self.timer.start(200, False)

    def ready(self):
        if self.mbl is None:
            self.error("La détection n'est pas terminée.")
            return False
        return True

    # ---- keys
    @safe
    def key_ok(self):
        if not self.ready():
            return
        s = self.current()
        if not s:
            return self.key_menu()
        lay = self.mbl
        items = []
        if lay.can("boot") and not s.running:
            items.append(("Démarrer sur ce slot", "boot"))
        if lay.can("once") and not s.running and s.kind != "flash":
            items.append(("Démarrer une seule fois (retour auto)", "once"))
        if lay.can("install") and (lay.new_slots or (s.installable and not s.running)):
            items.append(("Installer une image…", "install"))
        if lay.can("backup") and s.kind in ("flash", "chroot", "omb", "emmc") and not s.empty:
            items.append(("Sauvegarder ce slot", "backup"))
        if s.root and os.path.isdir(s.root):
            items.append(("Calculer la taille", "size"))
        if lay.can("delete") and s.deletable and not s.running:
            items.append(("Supprimer ce slot", "delete"))
        if not items:
            self.info("Aucune action possible sur ce slot.")
            return
        self.choose(s.title(), items, self.do_action)

    @safe
    def do_action(self, what):
        {"boot": self.key_green, "once": lambda: self.boot(True), "install": self.key_yellow,
         "backup": self.key_blue, "delete": self.key_red, "size": self.calc_size}[what]()

    @safe
    def key_green(self):
        self.boot(False)

    @safe
    def boot(self, once):
        if not self.ready():
            return
        lay, s = self.mbl, self.current()
        if not s:
            return
        if not lay.can("boot"):
            raise MBError("Le choix du slot de démarrage n'est pas pris en charge sur ce récepteur (%s)." % lay.name)
        if s.running and not once:
            raise MBError("Ce slot est déjà celui en cours.")
        lay.check_bootable(s)
        warn = lay.warnings_for(s)
        text = "Démarrer sur « %s » %s ?" % (s.title(), "une seule fois" if once else "au prochain redémarrage")
        if warn:
            text += "\n\n" + "\n".join(warn)

        def go():
            self.run_job("Choix du démarrage", lambda job: lay.set_next(job, s, once), self.ask_reboot)
        self.ask(text, go, default=not warn)

    def ask_reboot(self, job):
        def reboot():
            try:
                from Screens.Standby import TryQuitMainloop
                self.session.open(TryQuitMainloop, 2)
            except Exception as e:
                log("TryQuitMainloop: %s" % e)
                core.run(["reboot"])
        self.ask("%s\n\nRedémarrer maintenant ?" % job.result, reboot, default=True)

    @safe
    def key_red(self):
        if not self.ready():
            return
        lay, s = self.mbl, self.current()
        if not s:
            return
        if not lay.can("delete"):
            raise MBError("La suppression n'est pas prise en charge ici.")
        core.guard_not_running(s)
        if not s.deletable:
            raise MBError("Ce slot ne peut pas être supprimé.")
        if s.next_boot:
            raise MBError("Ce slot est choisi pour le prochain démarrage. Choisissez d'abord un autre slot.")
        self.ask("Supprimer définitivement « %s » ?\n%s\n\nCette action est irréversible." % (s.title(), s.where),
                 lambda: self.run_job("Suppression du slot", lambda job: lay.delete(job, s)))

    @safe
    def key_blue(self):
        if not self.ready():
            return
        lay, s = self.mbl, self.current()
        if not s:
            return
        if not lay.can("backup"):
            raise MBError("La sauvegarde n'est pas disponible ici.")
        if s.empty:
            raise MBError("Ce slot est vide.")
        targets = [st for st in core.storages() if st["rw"]]
        if not targets:
            raise MBError("Aucun disque (HDD/USB) monté pour recevoir la sauvegarde.")

        def go(st):
            self.ask("Sauvegarder « %s » vers %s/%s/backups ?\n(%s libres)" % (
                s.title(), st["mount"], core.DATA_DIR, human_mb(st["free"])),
                lambda: self.run_job("Sauvegarde du slot", lambda job: lay.backup(job, s, st["mount"])),
                default=True)
        if len(targets) == 1:
            go(targets[0])
        else:
            self.choose("Disque de destination", [("%s  (%s libres)" % (t["mount"], human_mb(t["free"])), t)
                                                  for t in targets], go)

    @safe
    def key_yellow(self):
        if not self.ready():
            return
        lay, s = self.mbl, self.current()
        if not lay.can("install"):
            raise MBError("L'installation d'images n'est pas prise en charge sur ce récepteur (%s)." % lay.name)
        if lay.new_slots:
            targets = lay.install_targets()
            if not targets:
                raise MBError("Aucun disque Linux (ext4) monté en écriture pour recevoir l'image.")
            if len(targets) == 1:
                self.pick_source(None, targets[0])
            else:
                self.choose("Disque de destination",
                            [("%s  (%s libres)" % (t["mount"], human_mb(t["free"])), t) for t in targets],
                            lambda t: self.pick_source(None, t))
        else:
            if not s:
                return
            core.guard_not_running(s)
            if not s.installable:
                raise MBError("Impossible d'installer dans ce slot.")
            self.pick_source(s, None)

    @safe
    def pick_source(self, slot, target):
        items = [("Images en ligne (OpenATV, OpenPLi, OpenViX…)", ("online", None)),
                 ("Saisir une adresse (URL)…", ("url", None))]
        for label, path, size in core.find_local_images()[:30]:
            items.append((label, ("file", path)))
        if len(items) == 2:
            items.append(("(aucune image .zip trouvée sur les disques)", ("none", None)))
        self.choose("Image à installer", items, lambda v: self.source_chosen(slot, target, v))

    @safe
    def source_chosen(self, slot, target, value):
        kind, path = value
        if kind == "none":
            return
        if kind == "online":
            self.online_images(slot, target)
            return
        if kind == "url":
            from Screens.VirtualKeyBoard import VirtualKeyBoard

            def got(url):
                if url:
                    self.confirm_install(slot, target, url.strip())
            self.session.openWithCallback(got, VirtualKeyBoard, title="Adresse de l'image (.zip)", text="https://")
        else:
            self.confirm_install(slot, target, path)

    @safe
    def online_images(self, slot, target):
        import time as _t
        if self._catalog and _t.time() - self._catalog[0] < 900:
            self.pick_distro(slot, target, self._catalog[1])
            return
        machine = self.mbl.box["machine"]
        job = Job("Images en ligne").start(lambda j: core.fetch_catalog(j, machine))

        def closed(j=None):
            if job.ok:
                self._catalog = (_t.time(), job.result)
                self.pick_distro(slot, target, job.result)
        self.session.openWithCallback(closed, WMBProgress, job, True)

    @safe
    def pick_distro(self, slot, target, catalog):
        if len(catalog) == 1:
            self.pick_online(slot, target, catalog[0])
            return
        self.choose("Images en ligne pour %s" % self.mbl.box["machine"],
                    [("%s   (%d images)" % (d, len(items)), (d, items)) for d, items in catalog],
                    lambda v: self.pick_online(slot, target, v))

    @safe
    def pick_online(self, slot, target, value):
        distro, items = value
        rows = []
        for it in items[:60]:
            tag = " · fin de support" if it["eol"] else (" · bêta" if it["beta"] else "")
            rows.append(("%s  ·  %s  ·  %s%s" % (it["name"], it["day"], human_mb(it["size"] // core.MB), tag), it))
        self.choose("%s : choisissez l'image" % distro, rows,
                    lambda it: self.confirm_install(slot, target, it["url"], it["name"]))

    @safe
    def confirm_install(self, slot, target, image, label=None):
        lay = self.mbl
        where = ("le slot %s" % slot.number) if slot else ("un nouveau slot sur %s" % target["mount"])
        text = "Installer\n%s\ndans %s ?" % (label or (os.path.basename(image) if "://" not in image else image), where)
        if "://" in image:
            text += "\n\nL'image sera téléchargée puis installée (le zip est supprimé ensuite)."
        if slot and not slot.empty:
            text += "\n\nLe contenu actuel du slot (%s) sera effacé." % slot.title()
        text += "\n\nL'image en cours n'est pas modifiée."
        self.ask(text, lambda: self.run_job("Installation d'image",
                                            lambda job: lay.install(job, image, slot=slot, target=target)))

    @safe
    def calc_size(self):
        s = self.current()
        if not s or not s.root:
            return

        def work(job):
            job.say("Calcul de la taille…", 10)
            s.size_mb = core.dir_size_mb(s.root)
            return "Taille de %s : %s" % (s.title(), human_mb(s.size_mb))
        self.run_job("Taille du slot", work)

    @safe
    def key_menu(self):
        items = [("Actualiser", "rescan"), ("Espace disque", "space"), ("Journal (log)", "log"),
                 ("Compatibilité et aide", "help")]
        if self.mbl and self.mbl.can("install"):
            items.insert(0, ("Installer une image…", "install"))
        self.choose("Wacayoub MultiBoot", items, self.menu_action)

    @safe
    def menu_action(self, what):
        if what == "rescan":
            self.rescan_keep(self.current().key if self.current() else None)
        elif what == "install":
            self.key_yellow()
        elif what == "space":
            lines = ["%s (%s, %s) : %s libres sur %s" % (st["mount"], st["device"], st["fstype"],
                                                         human_mb(st["free"]), human_mb(st["total"]))
                     for st in core.storages()]
            free, total = core.fs_usage("/")
            lines.insert(0, "Système (/) : %s libres sur %s" % (human_mb(free), human_mb(total)))
            self.info("\n".join(lines) or "Aucun disque.")
        elif what == "log":
            text = core.read_file(core.LOG_FILE)[-2500:] or "Journal vide."
            self.info(text)
        elif what == "help":
            self.info(HELP)


HELP = """Wacayoub MultiBoot %s

Structures reconnues automatiquement :
• Multiboot HDD/USB (omb-init) : Vu+ 4K et autres, images dans /media/*/OnlineMultiBoot/images ou /open-multiboot.
• Multiboot eMMC (fichiers STARTUP_n) : GigaBlue, Zgemma, Octagon, Edision, Dinobot, AX/Maxytec, Vu+ 4K kexec…
• OpenMultiboot classique (open_multiboot).
• Dreambox / récepteur sans multiboot : affichage et sauvegarde.

Sécurité : l'image en cours n'est jamais modifiée ni supprimée. Chaque action vérifie l'espace libre, l'archive et le modèle du récepteur avant de commencer.

Journal : %s""" % (core.VERSION, core.LOG_FILE)
