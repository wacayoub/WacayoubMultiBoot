# -*- coding: utf-8 -*-
"""Wacayoub MultiBoot - screens.

All key handlers are wrapped (@safe) so an error shows a message instead of crashing
enigma2. Long work runs in core.Job threads; the GUI only polls them with an eTimer.
Never name a method/attribute like enigma2's Screen uses (shown, layout, start…):
tests/check_screen_names.py checks it.
"""
from __future__ import absolute_import

import os
import time
import traceback

from enigma import eListboxPythonMultiContent, gFont, getDesktop, eTimer, \
    RT_HALIGN_LEFT, RT_HALIGN_RIGHT, RT_VALIGN_CENTER
from Screens.Screen import Screen
from Screens.MessageBox import MessageBox
from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.MenuList import MenuList
from Components.Pixmap import Pixmap
from Components.ProgressBar import ProgressBar
from Components.MultiContent import MultiContentEntryText
try:
    from Components.MultiContent import MultiContentEntryPixmapAlphaBlend as PixEntry
except ImportError:                                   # older images
    from Components.MultiContent import MultiContentEntryPixmapAlphaTest as PixEntry
try:
    from Tools.LoadPixmap import LoadPixmap
except ImportError:
    LoadPixmap = None

from . import core
from .core import Job, MBError, log, human_mb, fmt_date

# --------------------------------------------------------------------------- look

C_TEXT, C_MUTED, C_ACCENT, C_BG = 0xe8edf5, 0x8b98b0, 0x22d3ee, 0x080d18
C_GREEN, C_RED, C_YELLOW, C_BLUE, C_LINE = 0x22c55e, 0xef4444, 0xeab308, 0x3b82f6, 0x26324f


def hexc(c):
    return "#00%06x" % c


FONT_R, FONT_B = "Regular", "Regular"
_fonts_done = [False]


def setup_fonts():
    """Use modern fonts when the image ships them, else the skin's 'Regular'."""
    global FONT_R, FONT_B
    if _fonts_done[0]:
        return
    _fonts_done[0] = True
    try:
        from enigma import addFont
    except Exception:
        return

    def reg(alias, names):
        for n in names:
            p = "/usr/share/fonts/" + n
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
IMG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "img", "fhd" if F > 0.8 else "hd")


def S(v):
    return int(round(v * F))


_pix = {}


def pix(name):
    """Cached pixmap from img/<res>/<name>.png (None when missing: never crash)."""
    if name not in _pix:
        p = os.path.join(IMG, name + ".png")
        try:
            _pix[name] = LoadPixmap(cached=True, path=p) if (LoadPixmap and os.path.isfile(p)) else None
        except Exception:
            _pix[name] = None
    return _pix[name]


def img(name, ext="png"):
    return os.path.join(IMG, "%s.%s" % (name, ext))


# --------------------------------------------------------------------------- skin helpers

def _w(name, x, y, w, h, font=None, size=0, color=C_TEXT, halign="left", valign="center", extra=""):
    f = ' font="%s;%d"' % (font, S(size)) if font else ""
    return ('<widget name="%s" position="%d,%d" size="%d,%d"%s foregroundColor="%s" backgroundColor="%s" '
            'transparent="1" halign="%s" valign="%s" zPosition="2" %s/>'
            % (name, S(x), S(y), S(w), S(h), f, hexc(color), hexc(C_BG), halign, valign, extra))


def _pixmap(path, x, y, w, h, z=1):
    return ('<ePixmap pixmap="%s" position="%d,%d" size="%d,%d" alphatest="blend" zPosition="%d"/>'
            % (path, S(x), S(y), S(w), S(h), z))


def _bg(name):
    return ('<ePixmap pixmap="%s" position="0,0" size="%d,%d" zPosition="-5"/>'
            % (img(name, "jpg"), S(1920), S(1080)))


def _list(name, x, y, w, h, sel):
    return ('<widget name="%s" position="%d,%d" size="%d,%d" scrollbarMode="showOnDemand" transparent="1" '
            'selectionPixmap="%s" backgroundColor="%s" foregroundColor="%s" zPosition="2"/>'
            % (name, S(x), S(y), S(w), S(h), img(sel), hexc(C_BG), hexc(C_TEXT)))


def _keys():
    out = []
    for i, (name, icon) in enumerate((("key_red", "k_red"), ("key_green", "k_green"), ("key_yellow", "k_yellow"),
                                      ("key_blue", "k_blue"), ("key_menu", "k_menu"))):
        x = 60 + i * 370
        out.append(_pixmap(img(icon), x, 1020, 40, 40, 2))
        out.append(_w(name, x + 54, 1008, 300, 64, FONT_R, 26, C_TEXT))
    return "".join(out)


def _screen(name, body):
    return ('<screen name="%s" position="0,0" size="%d,%d" flags="wfNoBorder" backgroundColor="%s">%s</screen>'
            % (name, S(1920), S(1080), hexc(C_BG), body))


def main_skin():
    b = [_bg("bg"), _pixmap(img("logo"), 48, 28, 64, 64),
         _w("title", 130, 18, 900, 56, FONT_B, 40, C_TEXT),
         _w("subtitle", 130, 70, 1100, 38, FONT_R, 24, C_MUTED),
         _w("nextboot", 1080, 18, 790, 56, FONT_B, 26, C_ACCENT, "right"),
         _w("version", 1400, 70, 470, 38, FONT_R, 22, C_MUTED, "right"),
         _list("list", 64, 162, 1096, 768, "sel"),
         '<widget name="dlogo" position="%d,%d" size="%d,%d" alphatest="blend" zPosition="3"/>'
         % (S(1228), S(176), S(120), S(120)),
         _w("dtitle", 1368, 180, 480, 50, FONT_B, 32, C_TEXT),
         _w("dstatus", 1368, 232, 480, 40, FONT_R, 24, C_ACCENT),
         '<widget name="dlist" position="%d,%d" size="%d,%d" transparent="1" selectionDisabled="1" '
         'scrollbarMode="showNever" zPosition="2"/>' % (S(1222), S(316), S(630), S(324)),
         _w("sttitle", 1228, 684, 620, 36, FONT_B, 22, C_MUTED),
         _w("capacity", 1228, 890, 620, 40, FONT_B, 24, C_ACCENT)]
    for i in range(2):
        y = 728 + i * 78
        b.append(_w("st%d_name" % i, 1228, y, 330, 32, FONT_R, 23, C_TEXT))
        b.append(_w("st%d_text" % i, 1520, y, 330, 32, FONT_R, 22, C_MUTED, "right"))
        b.append('<widget name="st%d_bar" position="%d,%d" size="%d,%d" borderWidth="0" '
                 'foregroundColor="%s" backgroundColor="%s" zPosition="2"/>'
                 % (i, S(1228), S(y + 40), S(620), S(10), hexc(C_ACCENT), hexc(C_LINE)))
    b += [_w("hint", 64, 948, 1800, 40, FONT_R, 24, C_MUTED), _keys()]
    return _screen("WMultiBootMain", "".join(b))


def picker_skin():
    b = [_bg("bg_picker"),
         _w("title", 300, 140, 1320, 56, FONT_B, 38, C_TEXT),
         _w("subtitle", 300, 236, 1320, 40, FONT_R, 24, C_MUTED),
         _list("list", 306, 290, 1308, 552, "sel_picker"),
         _w("hint", 300, 880, 1320, 50, FONT_R, 24, C_MUTED)]
    return _screen("WMultiBootPicker", "".join(b))


def progress_skin():
    b = [_bg("bg_picker"),
         _w("title", 300, 140, 1320, 56, FONT_B, 38, C_TEXT),
         _w("step", 300, 250, 1320, 50, FONT_R, 28, C_ACCENT),
         '<widget name="bar" position="%d,%d" size="%d,%d" borderWidth="0" foregroundColor="%s" '
         'backgroundColor="%s" zPosition="2"/>' % (S(300), S(330), S(1180), S(16), hexc(C_ACCENT), hexc(C_LINE)),
         _w("percent", 1500, 312, 120, 52, FONT_B, 30, C_TEXT, "right"),
         _w("log", 300, 390, 1320, 450, FONT_R, 23, C_MUTED, "left", "top"),
         _w("hint", 300, 880, 1320, 50, FONT_R, 24, C_TEXT)]
    return _screen("WMultiBootProgress", "".join(b))


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
            self.mb_error(str(e))
        except Exception as e:
            log("UI error in %s: %s" % (fn.__name__, traceback.format_exc()))
            self.mb_error("Erreur inattendue : %s\n(détails dans %s)" % (e, core.LOG_FILE))
    wrapper.__name__ = fn.__name__
    return wrapper


def status_pill(s):
    if s.running:
        return "p_running"
    if s.next_boot and s.extra.get("once"):
        return "p_once"
    if s.next_boot:
        return "p_next"
    if s.kind == "recovery":
        return "p_recovery"
    if s.empty:
        return "p_empty"
    return None


def kind_icon(s):
    if s.kind in ("flash", "emmc", "recovery"):
        return "cpu"
    if "/usb" in (s.where or ""):
        return "usb"
    return "drive"


class Base(Screen):
    def mb_error(self, text):
        log("UI message: %s" % text)
        try:
            self.session.open(MessageBox, text, MessageBox.TYPE_ERROR)
        except Exception:
            log("cannot show error: %s" % text)

    def mb_info(self, text, cb=None):
        if cb:
            self.session.openWithCallback(cb, MessageBox, text, MessageBox.TYPE_INFO)
        else:
            self.session.open(MessageBox, text, MessageBox.TYPE_INFO)

    def mb_ask(self, text, cb, default=False, no_cb=None):
        def _cb(answer):
            if answer:
                cb()
            elif no_cb:
                no_cb()
        try:
            self.session.openWithCallback(_cb, MessageBox, text, MessageBox.TYPE_YESNO, default=default)
        except TypeError:
            self.session.openWithCallback(_cb, MessageBox, text, MessageBox.TYPE_YESNO)

    def mb_pick(self, title, items, cb, subtitle=""):
        """items: [dict(icon, title, sub, pill, value)] -> cb(value)."""
        def _cb(value=None):
            if value is not None:
                cb(value)
        self.session.openWithCallback(_cb, WMBPicker, title, items, subtitle)

    def mb_title(self, t):
        try:
            self.setTitle(t)
        except Exception:
            pass


# --------------------------------------------------------------------------- picker

class WMBPicker(Base):
    """Full-screen list with icon, title, subtitle and a status pill."""

    def __init__(self, session, title, items, subtitle=""):
        setup_fonts()
        self.skin = picker_skin()
        Base.__init__(self, session)
        self.pick_items = items
        self["title"] = Label(title)
        self["subtitle"] = Label(subtitle)
        self["hint"] = Label("OK : choisir    ·    EXIT : retour")
        self["list"] = MenuList([], enableWrapAround=True, content=eListboxPythonMultiContent)
        lst = self["list"].l
        lst.setFont(0, gFont(FONT_B, S(30)))
        lst.setFont(1, gFont(FONT_R, S(23)))
        lst.setItemHeight(S(92))
        self["actions"] = ActionMap(["OkCancelActions"], {"ok": self.pick_ok, "cancel": self.pick_cancel}, -1)
        self.onLayoutFinish.append(self.fill_rows)
        self.mb_title(title)

    def fill_rows(self):
        w = S(1300)
        rows = []
        for it in self.pick_items:
            row = [it.get("value")]
            icon = pix(it.get("icon") or "d_unknown")
            x = S(14)
            if icon:
                row.append(PixEntry(pos=(x, S(12)), size=(S(68), S(68)), png=icon))
            pl = pix(it["pill"]) if it.get("pill") else None
            pw = pl.size().width() if pl else 0
            if pl:
                row.append(PixEntry(pos=(w - pw - S(16), S(27)), size=(pw, S(38)), png=pl))
            tw = w - S(110) - pw - S(30)
            row.append(MultiContentEntryText(pos=(S(104), S(8)), size=(tw, S(44)), font=0,
                                             flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER, text=it.get("title", ""),
                                             color=C_TEXT, color_sel=0xffffff))
            row.append(MultiContentEntryText(pos=(S(104), S(50)), size=(w - S(120), S(34)), font=1,
                                             flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER, text=it.get("sub", ""),
                                             color=C_MUTED, color_sel=0xdbeafe))
            rows.append(row)
        self["list"].setList(rows)

    def pick_ok(self):
        cur = self["list"].getCurrent()
        if cur:
            self.close(cur[0])

    def pick_cancel(self):
        self.close(None)


# --------------------------------------------------------------------------- progress

class WMBProgress(Base):
    def __init__(self, session, job, auto_close=False):
        setup_fonts()
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
        self["actions"] = ActionMap(["OkCancelActions"], {"ok": self.prog_ok, "cancel": self.prog_cancel}, -1)
        self.timer = eTimer()
        self._conn = connect_timer(self.timer, self.poll)
        self.onLayoutFinish.append(self.begin)
        self.onClose.append(self.timer.stop)
        self.mb_title(job.title)

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
            self["hint"].setText("OK : continuer")

    def prog_ok(self):
        if self.job.done:
            self.close(self.job)

    def prog_cancel(self):
        if self.job.done:
            self.close(self.job)
            return
        if not self.job.cancellable:
            self["hint"].setText("Opération critique en cours : impossible d'annuler maintenant.")
            return
        self.mb_ask("Annuler l'opération en cours ?", self.job.cancel)


# --------------------------------------------------------------------------- main

class WMBMain(Base):
    def __init__(self, session):
        setup_fonts()
        self.skin = main_skin()
        Base.__init__(self, session)
        self.mbl = None
        self.scan_job = None
        self._keep = None
        self._catalog = None
        self._after_scan = None
        self["title"] = Label("Wacayoub MultiBoot")
        self["subtitle"] = Label("Analyse du récepteur…")
        self["nextboot"] = Label("")
        self["version"] = Label("v%s" % core.VERSION)
        self["list"] = MenuList([], enableWrapAround=True, content=eListboxPythonMultiContent)
        self["dlogo"] = Pixmap()
        self["dtitle"] = Label("")
        self["dstatus"] = Label("")
        self["dlist"] = MenuList([], content=eListboxPythonMultiContent)
        self["sttitle"] = Label("ESPACE DISQUE")
        self["capacity"] = Label("")
        self["hint"] = Label("")
        for i in range(2):
            self["st%d_name" % i] = Label("")
            self["st%d_text" % i] = Label("")
            self["st%d_bar" % i] = ProgressBar()
        self["key_red"] = Label("Supprimer")
        self["key_green"] = Label("Démarrer")
        self["key_yellow"] = Label("Installer")
        self["key_blue"] = Label("Sauvegardes")
        self["key_menu"] = Label("Menu")
        lst = self["list"].l
        lst.setFont(0, gFont(FONT_B, S(30)))
        lst.setFont(1, gFont(FONT_R, S(22)))
        lst.setItemHeight(S(92))
        dl = self["dlist"].l
        dl.setFont(0, gFont(FONT_R, S(22)))
        dl.setFont(1, gFont(FONT_R, S(24)))
        dl.setItemHeight(S(46))
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
        self.mb_title("Wacayoub MultiBoot")
        log("UI: main created")

    @safe
    def mb_on_shown(self):
        log("UI: main shown")
        if self.mbl is not None:
            self.fill_storage()

    # ---- scanning
    @safe
    def rescan(self, keep=None, after=None):
        self._keep = keep
        self._after_scan = after
        self["hint"].setText("Détection des images…")
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
        after, self._after_scan = self._after_scan, None
        if after:
            after()

    def fill(self, keep_key=None):
        lay = self.mbl
        box = lay.box
        run = lay.running_slot()
        nxt = lay.next_slot()
        self["subtitle"].setText("%s %s   ·   %s" % (box["brand"], box["machine"], lay.name))
        self["nextboot"].setText("Prochain démarrage : %s" % (nxt.title() if nxt else "?"))
        rows = [self.row(s, S(1092)) for s in lay.slots]
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
                                 ("key_yellow", "install", "Installer"), ("key_blue", "backup", "Sauvegardes")):
            self[name].setText(label if lay.can(cap) else "—")
        self.fill_storage()
        self.update_details()

    def row(self, s, w):
        r = [s]
        logo = pix("d_" + core.distro_key((s.info or {}).get("distro", "")))
        if logo:
            r.append(PixEntry(pos=(S(12), S(12)), size=(S(68), S(68)), png=logo))
        pk = status_pill(s)
        pl = pix(pk) if pk else None
        pw = pl.size().width() if pl else 0
        if pl:
            r.append(PixEntry(pos=(w - pw - S(16), S(27)), size=(pw, S(38)), png=pl))
        r.append(MultiContentEntryText(pos=(S(98), S(8)), size=(w - S(110) - pw - S(30), S(44)), font=0,
                                       flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER, text=s.title(),
                                       color=C_TEXT if not s.empty else C_MUTED, color_sel=0xffffff))
        ti = pix("t_" + kind_icon(s))
        if ti:
            r.append(PixEntry(pos=(S(98), S(58)), size=(S(22), S(22)), png=ti))
        if s.kind == "flash":
            num, place = "Flash interne", ""
        else:
            num = "Slot %s" % s.number
            parts = (s.where or "").split("/")
            place = "/".join(parts[:3]) if (s.where or "").startswith("/media/") else (s.where or "")
        sub = "  ·  ".join([x for x in (num, fmt_date((s.info or {}).get("date", "")), place) if x])
        r.append(MultiContentEntryText(pos=(S(128), S(52)), size=(w - S(140) - pw - S(30), S(34)), font=1,
                                       flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER, text=sub,
                                       color=C_MUTED, color_sel=0xdbeafe))
        return r

    def fill_storage(self):
        caps = dict((st["mount"], n) for st, n in core.install_capacity())
        sts = core.storages()[:2]
        for i in range(2):
            if i < len(sts):
                st = sts[i]
                used = 100 - (100 * st["free"] // st["total"] if st["total"] else 0)
                self["st%d_name" % i].setText("%s  (%s)" % (st["mount"], st["fstype"]))
                self["st%d_text" % i].setText("%s libres sur %s" % (human_mb(st["free"]), human_mb(st["total"])))
                self["st%d_bar" % i].setValue(used)
                self["st%d_bar" % i].show()
            else:
                self["st%d_name" % i].setText("" if i else "Aucun disque monté")
                self["st%d_text" % i].setText("")
                self["st%d_bar" % i].hide()
        if self.mbl is not None and not self.mbl.new_slots:
            self["capacity"].setText("Installation dans les slots existants")
        elif caps:
            n = sum(caps.values())
            self["capacity"].setText("Place pour environ %d nouvelle%s image%s" % (n, "s" if n > 1 else "", "s" if n > 1 else ""))
        else:
            self["capacity"].setText("Pas de disque ext4 pour installer des images")

    def current(self):
        cur = self["list"].getCurrent()
        return cur[0] if cur else None

    def detail_row(self, icon, label, value):
        w = S(630)
        r = [None]
        p = pix("i_" + icon)
        if p:
            r.append(PixEntry(pos=(S(8), S(10)), size=(S(26), S(26)), png=p))
        r.append(MultiContentEntryText(pos=(S(48), 0), size=(S(170), S(46)), font=0,
                                       flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER, text=label, color=C_MUTED))
        r.append(MultiContentEntryText(pos=(S(220), 0), size=(w - S(225), S(46)), font=1,
                                       flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER, text=value, color=C_TEXT))
        return r

    def update_details(self):
        s = self.current()
        lay = self.mbl
        if not s:
            self["dtitle"].setText("Aucun slot")
            self["dstatus"].setText("")
            self["dlist"].setList([])
            self.set_logo("dl_unknown")
            self["hint"].setText(" · ".join(lay.notes) if lay else "")
            return
        self["dtitle"].setText(s.title())
        st = []
        if s.running:
            st.append("En cours d'utilisation")
        if s.next_boot:
            st.append("prochain démarrage" + (" (une fois)" if s.extra.get("once") else ""))
        self["dstatus"].setText(", ".join(st).capitalize() if st else ("Slot vide" if s.empty else "Prête à démarrer"))
        self.set_logo("dl_" + core.distro_key((s.info or {}).get("distro", "")))
        rows = []
        if s.info:
            rows.append(self.detail_row("tag", "Version", s.info.get("version") or "?"))
            if s.info.get("date"):
                rows.append(self.detail_row("calendar", "Date", fmt_date(s.info["date"])))
            if s.info.get("box"):
                rows.append(self.detail_row("box", "Récepteur", s.info["box"]))
            if s.info.get("modules"):
                rows.append(self.detail_row("cpu", "Noyau", ", ".join(s.info["modules"])))
        kinds = {"flash": "Flash interne", "chroot": "Disque dur / USB", "emmc": "Slot eMMC",
                 "omb": "OpenMultiboot", "recovery": "Recovery"}
        rows.append(self.detail_row(kind_icon(s), "Type", kinds.get(s.kind, s.kind)))
        if s.where and s.kind != "flash":
            rows.append(self.detail_row("folder", "Dossier", os.path.basename(s.where) or s.where))
        if s.size_mb is not None:
            rows.append(self.detail_row("layers", "Taille", human_mb(s.size_mb)))
        for w in lay.warnings_for(s):
            rows.append(self.detail_row("shield", "Attention", w))
        self["dlist"].setList(rows)
        if lay.notes and not s.running:
            hint = " · ".join(lay.notes)
        elif s.running:
            hint = "Image en cours  ·  OK : options  ·  BLEU : sauvegarder  ·  JAUNE : installer une autre image"
        elif s.empty:
            hint = "Slot vide  ·  JAUNE : installer une image ici"
        else:
            hint = "VERT : démarrer sur cette image  ·  OK : toutes les options"
        self["hint"].setText(hint)

    def set_logo(self, name):
        p = pix(name) or pix("dl_unknown")
        try:
            if p and self["dlogo"].instance:
                self["dlogo"].instance.setPixmap(p)
        except Exception as e:
            log("logo: %s" % e)

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
    def run_job(self, title, func, done_cb=None, rescan=True):
        job = Job(title).start(func)

        def closed(j=None):
            key = self.current().key if self.current() else None
            after = (lambda: done_cb(job)) if (done_cb and job.ok) else None
            if rescan:
                self.rescan(key, after)
            elif after:
                after()
        self.session.openWithCallback(closed, WMBProgress, job)

    def ready(self):
        if self.mbl is None:
            self.mb_error("La détection n'est pas terminée.")
            return False
        return True

    # ---- keys
    @safe
    def key_ok(self):
        if not self.ready():
            return
        s, lay = self.current(), self.mbl
        if not s:
            return self.key_menu()
        items = []
        if lay.can("boot") and not s.running and not s.empty:
            items.append(dict(icon="a_boot", title="Démarrer sur cette image", value="boot",
                              sub="La box redémarre sur %s" % s.title()))
        if lay.can("once") and not s.running and s.kind != "flash" and not s.empty:
            items.append(dict(icon="a_once", title="Démarrer une seule fois", value="once",
                              sub="Pour essayer : retour automatique sur l'image actuelle ensuite"))
        if lay.can("install") and (lay.new_slots or (s.installable and not s.running)):
            items.append(dict(icon="a_install", title="Installer une image…", value="install",
                              sub="Images en ligne, adresse internet ou fichier zip"))
        if lay.can("backup") and not s.empty and s.kind != "recovery":
            items.append(dict(icon="a_backup", title="Sauvegarder cette image", value="backup",
                              sub="Copie complète en .tar.gz, restaurable plus tard"))
            items.append(dict(icon="a_settings", title="Sauvegarder les réglages et chaînes", value="settings",
                              sub="Petite sauvegarde : chaînes, favoris, réglages"))
        if s.kind in ("chroot", "omb") and not s.running and not s.empty:
            items.append(dict(icon="a_copy", title="Copier mes chaînes dans cette image", value="copy",
                              sub="Chaînes, favoris et satellites de l'image en cours"))
        if s.root and os.path.isdir(s.root):
            items.append(dict(icon="a_size", title="Calculer la taille", value="size", sub=s.where))
        if lay.can("delete") and s.deletable and not s.running:
            items.append(dict(icon="a_delete", title="Supprimer cette image", value="delete",
                              sub="Libère de la place sur le disque (irréversible)"))
        if not items:
            self.mb_info("Aucune action possible sur ce slot.")
            return
        self.mb_pick(s.title(), items, self.do_action, "Que voulez-vous faire ?")

    @safe
    def do_action(self, what):
        s = self.current()
        {"boot": lambda: self.boot(False), "once": lambda: self.boot(True), "install": self.key_yellow,
         "backup": lambda: self.backup_slot(s, False), "settings": lambda: self.backup_slot(s, True),
         "copy": lambda: self.copy_channels(s), "delete": self.key_red, "size": self.calc_size}[what]()

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
            raise MBError("Le choix de l'image de démarrage n'est pas pris en charge sur ce récepteur (%s)." % lay.name)
        if s.running:
            raise MBError("Cette image est déjà celle en cours.")
        lay.check_bootable(s)
        warn = lay.warnings_for(s)
        if once:
            text = "Démarrer une seule fois sur « %s » ?\n\nAu redémarrage suivant, la box revient toute seule sur l'image actuelle." % s.title()
        else:
            text = "Démarrer sur « %s » ?\n\nCette image restera l'image de démarrage." % s.title()
        if warn:
            text += "\n\n" + "\n".join(warn)
        self.mb_ask(text, lambda: self.run_job("Choix du démarrage", lambda job: lay.set_next(job, s, once),
                                               self.ask_reboot), default=not warn)

    def ask_reboot(self, job):
        def reboot():
            try:
                from Screens.Standby import TryQuitMainloop
                self.session.open(TryQuitMainloop, 2)
            except Exception as e:
                log("TryQuitMainloop: %s" % e)
                core.run(["reboot"])
        self.mb_ask("%s\n\nRedémarrer maintenant ?" % job.result, reboot, default=True)

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
            raise MBError("Cette image ne peut pas être supprimée (flash ou recovery).")
        if s.next_boot:
            raise MBError("Cette image est choisie pour le prochain démarrage. Choisissez d'abord une autre image.")
        self.mb_ask("Supprimer définitivement « %s » ?\n%s\n\nCette action est irréversible. Pensez à la sauvegarder avant (touche BLEUE)."
                    % (s.title(), s.where),
                    lambda: self.run_job("Suppression", lambda job: lay.delete(job, s)))

    # ---- backups
    def backup_targets(self):
        t = [st for st in core.storages() if st["rw"]]
        if not t:
            raise MBError("Aucun disque (HDD/USB) monté pour recevoir la sauvegarde.")
        return t

    def with_target(self, title, cb):
        targets = self.backup_targets()
        if len(targets) == 1:
            cb(targets[0])
            return
        self.mb_pick(title, [dict(icon="a_disk", title=t["mount"], value=t,
                                  sub="%s libres sur %s" % (human_mb(t["free"]), human_mb(t["total"])))
                             for t in targets], cb, "Choisissez le disque")

    @safe
    def backup_slot(self, s, settings_only):
        lay = self.mbl
        if s is None or s.empty:
            raise MBError("Choisissez une image à sauvegarder.")

        def go(st):
            if settings_only:
                self.run_job("Sauvegarde des réglages",
                             lambda job: core.backup_settings(job, s, st["mount"], lay), rescan=False)
            else:
                self.mb_ask("Sauvegarder toute l'image « %s » vers %s ?\n(%s libres)\n\nCela peut prendre quelques minutes."
                            % (s.title(), st["mount"], human_mb(st["free"])),
                            lambda: self.run_job("Sauvegarde complète", lambda job: lay.backup(job, s, st["mount"]),
                                                 rescan=False), default=True)
        self.with_target("Sauvegarde", go)

    @safe
    def key_blue(self):
        if not self.ready():
            return
        s = self.current()
        items = []
        if s and not s.empty and self.mbl.can("backup") and s.kind != "recovery":
            items.append(dict(icon="a_backup", title="Sauvegarder « %s »" % s.title(), value=("full", None),
                              sub="Copie complète de l'image sélectionnée"))
            items.append(dict(icon="a_settings", title="Sauvegarder seulement les réglages et chaînes",
                              value=("settings", None), sub="Rapide et petit : chaînes, favoris, réglages"))
        for b in core.list_backups()[:40]:
            items.append(dict(icon="a_settings" if b["kind"] == "settings" else "a_backups", title=b["name"],
                              value=("open", b), sub="%s  ·  %s  ·  %s" % (b["date"], human_mb(max(1, b["size"])), b["mount"])))
        if len(items) <= 2:
            items.append(dict(icon="a_help", title="Aucune sauvegarde pour le moment", value=("none", None),
                              sub="Les sauvegardes sont rangées dans <disque>/WMultiBoot/backups"))
        self.mb_pick("Sauvegardes", items, self.backup_action, "Créer, restaurer ou supprimer une sauvegarde")

    @safe
    def backup_action(self, value):
        what, b = value
        if what == "full":
            self.backup_slot(self.current(), False)
        elif what == "settings":
            self.backup_slot(self.current(), True)
        elif what == "open":
            self.open_backup(b)

    @safe
    def open_backup(self, b):
        items = []
        if b["kind"] == "slot" and self.mbl.can("install"):
            items.append(dict(icon="a_install", title="Restaurer comme nouvelle image", value="restore",
                              sub="Installe la sauvegarde dans un nouveau slot (l'image en cours ne change pas)"))
        if b["kind"] == "settings":
            items.append(dict(icon="a_settings", title="Restaurer ces réglages dans une image…", value="settings",
                              sub="Dans une autre image que celle en cours"))
        items.append(dict(icon="a_delete", title="Supprimer cette sauvegarde", value="delete",
                          sub="Libère %s" % human_mb(max(1, b["size"]))))

        def act(what):
            if what == "restore":
                self.install_from(b["path"], os.path.basename(b["path"]))
            elif what == "settings":
                self.restore_settings_to(b)
            elif what == "delete":
                self.mb_ask("Supprimer la sauvegarde\n%s ?" % b["name"],
                            lambda: self.run_job("Suppression de la sauvegarde",
                                                 lambda job: (core.delete_backup(b["path"]), "Sauvegarde supprimée.")[1],
                                                 rescan=False))
        self.mb_pick(b["name"], items, act, "%s  ·  %s" % (b["date"], human_mb(max(1, b["size"]))))

    @safe
    def restore_settings_to(self, b):
        targets = [s for s in self.mbl.slots if s.kind in ("chroot", "omb") and not s.running and not s.empty]
        if not targets:
            raise MBError("Aucune autre image sur HDD/USB pour recevoir ces réglages.")
        self.mb_pick("Restaurer les réglages dans…",
                     [dict(icon="d_" + core.distro_key((s.info or {}).get("distro", "")), title=s.title(),
                           sub=s.where, value=s) for s in targets],
                     lambda s: self.mb_ask("Restaurer les réglages dans « %s » ?\nSes réglages actuels seront remplacés." % s.title(),
                                           lambda: self.run_job("Restauration des réglages",
                                                                lambda job: core.restore_settings(job, b["path"], s))))

    @safe
    def copy_channels(self, s):
        self.mb_ask("Copier les chaînes, favoris et satellites de l'image en cours dans « %s » ?" % s.title(),
                    lambda: self.run_job("Copie des chaînes", lambda job: core.copy_channels(job, s)), default=True)

    # ---- install
    @safe
    def key_yellow(self):
        if not self.ready():
            return
        lay, s = self.mbl, self.current()
        if not lay.can("install"):
            raise MBError("L'installation d'images n'est pas prise en charge sur ce récepteur (%s)." % lay.name)
        self.pick_source()

    @safe
    def pick_source(self):
        items = [dict(icon="a_online", title="Images en ligne", value=("online", None),
                      sub="OpenATV, OpenPLi, OpenViX, PurE2, OpenBH, OpenSPA… pour %s" % self.mbl.box["machine"]),
                 dict(icon="a_url", title="Adresse internet (URL)", value=("url", None),
                      sub="Lien direct vers un fichier .zip")]
        for label, path, size in core.find_local_images()[:30]:
            items.append(dict(icon="a_file", title=os.path.basename(path), value=("file", path),
                              sub="%s  ·  %s" % (human_mb(size), os.path.dirname(path))))
        self.mb_pick("Installer une image", items, self.source_chosen, self.space_text())

    def space_text(self):
        caps = core.install_capacity()
        if not self.mbl.new_slots:
            return "L'image sera installée dans le slot sélectionné"
        if not caps:
            return "Aucun disque ext4 : branchez un disque dur ou une clé USB formatée"
        return "   ·   ".join("%s : %s libres, place pour ~%d image%s" % (st["mount"], human_mb(st["free"]), n, "s" if n > 1 else "")
                              for st, n in caps)

    @safe
    def source_chosen(self, value):
        kind, path = value
        if kind == "online":
            self.online_images()
        elif kind == "url":
            from Screens.VirtualKeyBoard import VirtualKeyBoard

            def got(url):
                if url:
                    self.install_from(url.strip())
            self.session.openWithCallback(got, VirtualKeyBoard, title="Adresse de l'image (.zip)", text="https://")
        elif kind == "file":
            self.install_from(path)

    @safe
    def online_images(self):
        if self._catalog and time.time() - self._catalog[0] < 900:
            self.pick_distro(self._catalog[1])
            return
        machine = self.mbl.box["machine"]
        job = Job("Recherche des images en ligne").start(lambda j: core.fetch_catalog(j, machine))

        def closed(j=None):
            if job.ok:
                self._catalog = (time.time(), job.result)
                self.pick_distro(job.result)
        self.session.openWithCallback(closed, WMBProgress, job, True)

    @safe
    def pick_distro(self, catalog):
        items = []
        for d, its in catalog:
            last = its[0]
            items.append(dict(icon="d_" + core.distro_key(d), title=d, value=(d, its),
                              sub="%d images  ·  dernière : %s" % (len(its), last["day"])))
        self.mb_pick("Images en ligne", items, self.pick_online, "Pour %s  ·  choisissez une distribution" % self.mbl.box["machine"])

    @safe
    def pick_online(self, value):
        distro, its = value
        items = []
        for it in its[:60]:
            pill = "p_eol" if it["eol"] else ("p_beta" if (it["beta"] or "beta" in it["name"].lower()) else "p_release")
            items.append(dict(icon="d_" + core.distro_key(distro), title=it["name"].replace(".zip", ""), value=it,
                              pill=pill, sub="%s  ·  %s  ·  %s" % (it["day"], human_mb(it["size"] // core.MB), it["group"])))
        self.mb_pick(distro, items, lambda it: self.install_from(it["url"], it["name"]), self.space_text())

    @safe
    def install_from(self, image, label=None):
        lay, s = self.mbl, self.current()
        if lay.new_slots:
            targets = lay.install_targets()
            if not targets:
                raise MBError("Aucun disque Linux (ext4) monté en écriture pour recevoir l'image.")
            ok = [t for t in targets if t["free"] >= 700]
            if not ok:
                raise MBError("Pas assez de place : il faut environ 700 Mo libres.\n%s\n\nSupprimez une image ou une sauvegarde."
                              % "\n".join("%s : %s libres" % (t["mount"], human_mb(t["free"])) for t in targets))
            if len(ok) == 1:
                self.confirm_install(None, ok[0], image, label)
            else:
                self.mb_pick("Où installer ?", [dict(icon="a_disk", title=t["mount"], value=t,
                                                    sub="%s libres sur %s" % (human_mb(t["free"]), human_mb(t["total"])))
                                               for t in ok],
                             lambda t: self.confirm_install(None, t, image, label), "Choisissez le disque")
        else:
            if not s:
                return
            core.guard_not_running(s)
            if not s.installable:
                raise MBError("Choisissez d'abord un slot libre (pas l'image en cours).")
            self.confirm_install(s, None, image, label)

    @safe
    def confirm_install(self, slot, target, image, label=None):
        lay = self.mbl
        where = ("le slot %s" % slot.number) if slot else ("un nouveau slot sur %s (%s libres)" % (target["mount"], human_mb(target["free"])))
        name = label or (os.path.basename(image) if "://" not in image else image)
        text = "Installer\n%s\ndans %s ?" % (name, where)
        if "://" in image:
            text += "\n\nL'image sera téléchargée puis installée (le zip est supprimé ensuite)."
        if slot and not slot.empty:
            text += "\n\nLe contenu actuel du slot (%s) sera effacé." % slot.title()
        text += "\n\nL'image en cours n'est pas modifiée."
        self.mb_ask(text, lambda: self.run_job("Installation d'image",
                                               lambda job: lay.install(job, image, slot=slot, target=target),
                                               self.after_install))

    def after_install(self, job):
        root = getattr(job, "new_root", None)
        new = None
        for s in self.mbl.slots:
            if root and s.root == root:
                new = s
        if new is None:
            return
        idx = self.mbl.slots.index(new)
        self["list"].moveToIndex(idx)
        self.update_details()

        def offer_boot():
            if self.mbl.can("once"):
                self.mb_ask("Image installée.\n\nDémarrer une fois dessus maintenant pour l'essayer ?\n"
                            "(retour automatique sur l'image actuelle ensuite)",
                            lambda: self.run_job("Choix du démarrage", lambda j: self.mbl.set_next(j, new, True),
                                                 self.ask_reboot))
        self.mb_ask("Copier vos chaînes, favoris et satellites dans la nouvelle image ?",
                    lambda: self.run_job("Copie des chaînes", lambda j: core.copy_channels(j, new),
                                         lambda j: offer_boot(), rescan=False),
                    default=True, no_cb=offer_boot)

    @safe
    def calc_size(self):
        s = self.current()
        if not s or not s.root:
            return

        def work(job):
            job.say("Calcul de la taille…", 10)
            s.size_mb = core.dir_size_mb(s.root)
            return "Taille de %s : %s" % (s.title(), human_mb(s.size_mb))
        self.run_job("Taille de l'image", work, rescan=False, done_cb=lambda j: self.update_details())

    # ---- menu
    @safe
    def key_menu(self):
        items = []
        if self.mbl and self.mbl.can("install"):
            items.append(dict(icon="a_online", title="Installer une image", value="install", sub="En ligne, URL ou fichier"))
        items += [dict(icon="a_backups", title="Sauvegardes", value="backups", sub="Créer, restaurer, supprimer"),
                  dict(icon="a_disk", title="Espace disque", value="space", sub=self.space_text() if self.mbl else ""),
                  dict(icon="a_once", title="Actualiser", value="rescan", sub="Relire les images et les disques"),
                  dict(icon="a_help", title="Aide et compatibilité", value="help", sub="Récepteurs pris en charge, sécurité"),
                  dict(icon="a_size", title="Journal", value="log", sub=core.LOG_FILE)]
        self.mb_pick("Menu", items, self.menu_action, "Wacayoub MultiBoot %s" % core.VERSION)

    @safe
    def menu_action(self, what):
        if what == "rescan":
            self.rescan(self.current().key if self.current() else None)
        elif what == "install":
            self.key_yellow()
        elif what == "backups":
            self.key_blue()
        elif what == "space":
            lines = ["%s (%s) : %s libres sur %s" % (st["mount"], st["fstype"], human_mb(st["free"]), human_mb(st["total"]))
                     for st in core.storages()]
            free, total = core.fs_usage("/")
            lines.insert(0, "Image en cours (/) : %s libres sur %s" % (human_mb(free), human_mb(total)))
            lines.append("")
            lines.append(self.space_text())
            self.mb_info("\n".join(lines))
        elif what == "log":
            self.mb_info(core.read_file(core.LOG_FILE)[-2500:] or "Journal vide.")
        elif what == "help":
            self.mb_info(HELP)


HELP = """Wacayoub MultiBoot %s

VERT : démarrer sur l'image choisie.  OK : toutes les options (démarrer une seule fois pour essayer, copier les chaînes…).
JAUNE : installer une image (en ligne, URL, fichier).  BLEU : sauvegardes.  ROUGE : supprimer.

Structures reconnues automatiquement :
• HDD/USB (omb-init) : Vu+ 4K et autres.
• eMMC (STARTUP_n) : GigaBlue, Zgemma, Octagon, Edision, AX/Maxytec, Vu+ kexec…
• OpenMultiboot classique.
• Dreambox / sans multiboot : affichage et sauvegarde.

Sécurité : l'image en cours n'est jamais modifiée ni supprimée. Chaque action vérifie l'espace libre, l'archive et le modèle avant de commencer.""" % core.VERSION
