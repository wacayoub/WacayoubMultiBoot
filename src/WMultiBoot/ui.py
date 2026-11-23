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
    for i, (name, icon) in enumerate((("key_red", "b_red"), ("key_green", "b_green"), ("key_yellow", "b_yellow"),
                                      ("key_blue", "b_blue"), ("key_menu", "b_menu"))):
        x = 40 + i * 372
        out.append('<widget name="%s_bg" position="%d,%d" size="%d,%d" alphatest="blend" zPosition="1"/>'
                   % (name, S(x), S(1010), S(340), S(60)))
        out.append(_w(name, x + 66, 1010, 262, 60, FONT_B, 25, C_TEXT))
    return "".join(out)


def _footer(y=890):
    """4 slots: chip (OK / EXIT / colour) + label, set at runtime with set_footer()."""
    out = []
    for i in range(4):
        x = 300 + i * 330
        out.append('<widget name="f%d_icon" position="%d,%d" size="%d,%d" alphatest="blend" zPosition="2"/>'
                   % (i, S(x), S(y), S(84), S(40)))
        out.append(_w("f%d_text" % i, x + 96, y - 4, 230, 48, FONT_R, 24, C_TEXT))
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
         _footer()]
    return _screen("WMultiBootPicker", "".join(b))


MENU_COLS, MENU_W, MENU_H, MENU_X, MENU_Y, MENU_DX, MENU_DY = 4, 330, 240, 284, 270, 340, 270


def menu_skin(n):
    b = [_bg("bg_picker"), _pixmap(img("logo"), 300, 136, 64, 64),
         _w("title", 384, 136, 1200, 64, FONT_B, 40, C_TEXT),
         _w("subtitle", 300, 222, 1320, 40, FONT_R, 24, C_MUTED),
         '<widget name="sel" position="%d,%d" size="%d,%d" alphatest="blend" zPosition="1"/>'
         % (S(MENU_X), S(MENU_Y), S(MENU_W), S(MENU_H))]
    for i in range(n):
        x = MENU_X + (i % MENU_COLS) * MENU_DX
        y = MENU_Y + (i // MENU_COLS) * MENU_DY
        b.append(_pixmap(img("tile"), x, y, MENU_W, MENU_H, 0))
        b.append('<widget name="t%d_icon" position="%d,%d" size="%d,%d" alphatest="blend" zPosition="3"/>'
                 % (i, S(x + (MENU_W - 96) // 2), S(y + 28), S(96), S(96)))
        b.append(_w("t%d_title" % i, x + 10, y + 136, MENU_W - 20, 44, FONT_B, 28, C_TEXT, "center"))
        b.append(_w("t%d_sub" % i, x + 14, y + 180, MENU_W - 28, 40, FONT_R, 20, C_MUTED, "center"))
    b.append(_footer())
    return _screen("WMultiBootMenu%d" % n, "".join(b))


def progress_skin():
    b = [_bg("bg_picker"),
         _w("title", 300, 140, 1320, 56, FONT_B, 38, C_TEXT),
         _w("step", 300, 250, 1320, 50, FONT_R, 28, C_ACCENT),
         '<widget name="bar" position="%d,%d" size="%d,%d" borderWidth="0" foregroundColor="%s" '
         'backgroundColor="%s" zPosition="2"/>' % (S(300), S(330), S(1180), S(16), hexc(C_ACCENT), hexc(C_LINE)),
         _w("percent", 1500, 312, 120, 52, FONT_B, 30, C_TEXT, "right"),
         _w("log", 300, 390, 1320, 450, FONT_R, 23, C_MUTED, "left", "top"),
         _w("hint", 300, 840, 1320, 40, FONT_R, 22, C_MUTED), _footer()]
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

    def init_footer(self):
        for i in range(4):
            self["f%d_icon" % i] = Pixmap()
            self["f%d_text" % i] = Label("")

    def footer_init(self):
        self.set_footer(getattr(self, "footer_pairs", None) or [("c_ok", "Choisir"), ("c_exit", "Retour")])

    def set_footer(self, pairs):
        """pairs: [(chip name, text)] e.g. [("c_ok", "Choisir"), ("c_exit", "Retour")]."""
        for i in range(4):
            icon, text = pairs[i] if i < len(pairs) else (None, "")
            self["f%d_text" % i].setText(text)
            w = self["f%d_icon" % i]
            p = pix(icon) if icon else None
            try:
                if w.instance:
                    if p:
                        w.instance.setPixmap(p)
                        w.show()
                    else:
                        w.hide()
            except Exception as e:
                log("footer: %s" % e)


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
        self.init_footer()
        self["list"] = MenuList([], enableWrapAround=True, content=eListboxPythonMultiContent)
        lst = self["list"].l
        lst.setFont(0, gFont(FONT_B, S(30)))
        lst.setFont(1, gFont(FONT_R, S(23)))
        lst.setItemHeight(S(92))
        self["actions"] = ActionMap(["OkCancelActions"], {"ok": self.pick_ok, "cancel": self.pick_cancel}, -1)
        self.onLayoutFinish.append(self.fill_rows)
        self.onLayoutFinish.append(self.footer_init)
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


class WMBChecklist(Base):
    """Tick list: OK = cocher/décocher, VERT = valider, JAUNE = tout, EXIT = retour."""

    def __init__(self, session, title, subtitle, items, action="Valider"):
        setup_fonts()
        self.skin = picker_skin()
        Base.__init__(self, session)
        self.check_items = items
        self["title"] = Label(title)
        self["subtitle"] = Label(subtitle)
        self.init_footer()
        self.footer_pairs = [("c_ok", "Cocher"), ("c_green", action), ("c_yellow", "Tout"), ("c_exit", "Retour")]
        self.onLayoutFinish.append(self.footer_init)
        self["list"] = MenuList([], enableWrapAround=True, content=eListboxPythonMultiContent)
        lst = self["list"].l
        lst.setFont(0, gFont(FONT_B, S(30)))
        lst.setFont(1, gFont(FONT_R, S(23)))
        lst.setItemHeight(S(92))
        self["actions"] = ActionMap(["OkCancelActions", "ColorActions"], {
            "ok": self.toggle, "cancel": self.check_cancel, "green": self.check_done, "yellow": self.toggle_all}, -1)
        self.onLayoutFinish.append(self.fill_rows)
        self.mb_title(title)

    def fill_rows(self):
        w = S(1300)
        rows = []
        for i, it in enumerate(self.check_items):
            row = [i]
            box = pix("cb_on" if it["checked"] else "cb_off")
            if box:
                row.append(PixEntry(pos=(S(26), S(24)), size=(S(44), S(44)), png=box))
            col = C_TEXT if it.get("enabled", True) else C_MUTED
            row.append(MultiContentEntryText(pos=(S(104), S(8)), size=(w - S(120), S(44)), font=0,
                                             flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER, text=it["title"],
                                             color=col, color_sel=0xffffff))
            row.append(MultiContentEntryText(pos=(S(104), S(50)), size=(w - S(120), S(34)), font=1,
                                             flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER, text=it.get("sub", ""),
                                             color=C_MUTED, color_sel=0xdbeafe))
            rows.append(row)
        idx = self["list"].getSelectionIndex() if self["list"].instance else 0
        self["list"].setList(rows)
        if rows:
            self["list"].moveToIndex(min(idx, len(rows) - 1))

    def toggle(self):
        cur = self["list"].getCurrent()
        if cur is None:
            return
        it = self.check_items[cur[0]]
        if it.get("enabled", True):
            it["checked"] = not it["checked"]
            self.fill_rows()

    def toggle_all(self):
        on = not all(it["checked"] for it in self.check_items if it.get("enabled", True))
        for it in self.check_items:
            if it.get("enabled", True):
                it["checked"] = on
        self.fill_rows()

    def check_done(self):
        keys = [it["key"] for it in self.check_items if it["checked"] and it.get("enabled", True)]
        if not keys:
            self.mb_error("Cochez au moins un élément.")
            return
        self.close(keys)

    def check_cancel(self):
        self.close(None)


class WMBMenu(Base):
    """Tile grid: arrows move, OK opens, EXIT closes."""

    def __init__(self, session, tiles, title, subtitle=""):
        setup_fonts()
        self.tiles = tiles[:8]
        self.skin = menu_skin(len(self.tiles))
        Base.__init__(self, session)
        self.idx = 0
        self["title"] = Label(title)
        self["subtitle"] = Label(subtitle)
        self["sel"] = Pixmap()
        for i, (key, icon, t, sub) in enumerate(self.tiles):
            self["t%d_icon" % i] = Pixmap()
            self["t%d_title" % i] = Label(t)
            self["t%d_sub" % i] = Label(sub)
        self.init_footer()
        self["actions"] = ActionMap(["OkCancelActions", "DirectionActions"], {
            "ok": self.menu_ok, "cancel": self.menu_cancel, "left": lambda: self.menu_move(-1),
            "right": lambda: self.menu_move(1), "up": lambda: self.menu_move(-MENU_COLS),
            "down": lambda: self.menu_move(MENU_COLS)}, -1)
        self.onLayoutFinish.append(self.paint)
        self.mb_title(title)

    def paint(self):
        try:
            if pix("tile_sel"):
                self["sel"].instance.setPixmap(pix("tile_sel"))
            for i, (key, icon, t, sub) in enumerate(self.tiles):
                if pix(icon):
                    self["t%d_icon" % i].instance.setPixmap(pix(icon))
        except Exception as e:
            log("menu paint: %s" % e)
        self.set_footer([("c_arrows", "Choisir"), ("c_ok", "Ouvrir"), ("c_exit", "Fermer")])
        self.menu_move(0)

    def menu_move(self, d):
        n = len(self.tiles)
        if not n:
            return
        i = self.idx + d
        if d in (-MENU_COLS, MENU_COLS) and not 0 <= i < n:
            i = self.idx
        self.idx = i % n
        x = MENU_X + (self.idx % MENU_COLS) * MENU_DX
        y = MENU_Y + (self.idx // MENU_COLS) * MENU_DY
        try:
            from enigma import ePoint
            self["sel"].instance.move(ePoint(S(x), S(y)))
        except Exception as e:
            log("menu move: %s" % e)

    def menu_ok(self):
        if self.tiles:
            self.close(self.tiles[self.idx][0])

    def menu_cancel(self):
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
        self["hint"] = Label("")
        self.init_footer()
        self.footer_pairs = [("c_exit", "Annuler")]
        self.onLayoutFinish.append(self.footer_init)
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
            if j.cancelled:
                self["step"].setText("Annulé")
                if self.auto_close:
                    self.close(j)
                    return
            else:
                self["step"].setText("Terminé" if j.ok else "Échec")
            self["log"].setText(j.result)
            self["hint"].setText("")
            self.set_footer([("c_ok", "Continuer"), ("c_exit", "Fermer")])

    def prog_ok(self):
        if self.job.done:
            self.close(self.job)

    def prog_cancel(self):
        if self.job.done:
            self.close(self.job)
            return
        if not self.job.cancellable:
            self["hint"].setText("Étape critique en cours : annulation impossible pour quelques secondes.")
            return
        self.job.cancel()                       # immediate: kills the running tar/wget, cleans up
        self["step"].setText("Annulation en cours…")
        self["hint"].setText("Annulation… les fichiers partiels sont supprimés.")


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
        self["key_blue"] = Label("Sauvegarder")
        self["key_menu"] = Label("Menu")
        for k in ("key_red", "key_green", "key_yellow", "key_blue", "key_menu"):
            self[k + "_bg"] = Pixmap()
        self.onLayoutFinish.append(self.paint_keys)
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

    def paint_keys(self):
        lay = self.mbl
        for name, cap, label, bg in (("key_red", "delete", "Supprimer", "b_red"), ("key_green", "boot", "Démarrer", "b_green"),
                                     ("key_yellow", "install", "Installer", "b_yellow"),
                                     ("key_blue", "backup", "Sauvegarder", "b_blue"), ("key_menu", None, "Menu", "b_menu")):
            ok = cap is None or lay is None or lay.can(cap)
            self[name].setText(label if ok else "")
            w = self[name + "_bg"]
            try:
                if w.instance and pix(bg):
                    w.instance.setPixmap(pix(bg))
                    w.show() if ok else w.hide()
            except Exception as e:
                log("keys: %s" % e)

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
        self.paint_keys()
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
            hint = "Image en cours  ·  BLEU : sauvegarder  ·  MENU : restaurer  ·  JAUNE : installer une autre image"
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
        if self.can_update(s):
            items.append(dict(icon="a_update", title="Mettre à jour cette image (tout garder)", value="update",
                              sub="Nouvelle version installée à côté, avec vos chaînes, réglages et plugins"))
        if lay.can("backup") and not s.empty and s.kind != "recovery":
            items.append(dict(icon="a_settings", title="Sauvegarder… (choisir quoi)", value="settings",
                              sub="Chaînes, satellites, réglages, plugins, softcam, réseau, picons"))
            items.append(dict(icon="a_backup", title="Sauvegarder l'image complète", value="backup",
                              sub="Tout le système, restaurable comme nouvelle image"))
        if s.kind in ("chroot", "omb") and not s.running and not s.empty:
            items.append(dict(icon="a_copy", title="Copier mes chaînes dans cette image", value="copy",
                              sub="Chaînes, favoris et satellites de l'image en cours"))
        if s.running or (s.kind in ("chroot", "omb") and not s.empty):
            if core.list_backups():
                items.append(dict(icon="a_backups", title="Restaurer une sauvegarde dans cette image", value="restore",
                                  sub="Choisir la sauvegarde, puis quoi restaurer"))
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
         "backup": lambda: self.backup_slot(s, False), "settings": lambda: self.backup_choose(s),
         "copy": lambda: self.copy_channels(s), "delete": self.key_red, "size": self.calc_size,
         "restore": lambda: self.restore_start(s), "update": lambda: self.update_start(s)}[what]()

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

    @safe
    def with_target(self, title, cb):
        targets = self.backup_targets()
        if len(targets) == 1:
            cb(targets[0])
            return
        self.mb_pick(title, [dict(icon="a_disk", title=t["mount"], value=t,
                                  sub="%s libres sur %s" % (human_mb(t["free"]), human_mb(t["total"])))
                             for t in targets], cb, "Choisissez le disque")

    @safe
    def backup_slot(self, s, settings_only=False):
        """Full image backup."""
        lay = self.mbl
        if s is None or s.empty:
            raise MBError("Choisissez une image à sauvegarder.")
        if settings_only:
            return self.backup_choose(s)

        def go(st):
            self.mb_ask("Sauvegarder toute l'image « %s » (système, plugins, réglages) vers %s ?\n(%s libres)\n\n"
                        "Cela peut prendre quelques minutes. EXIT pour annuler à tout moment."
                        % (s.title(), st["mount"], human_mb(st["free"])),
                        lambda: self.run_job("Sauvegarde de l'image complète", lambda job: lay.backup(job, s, st["mount"]),
                                             rescan=False), default=True)
        self.with_target("Sauvegarde", go)

    @safe
    def backup_choose(self, s):
        """Let the user tick exactly what to save."""
        lay = self.mbl
        if s is None or s.empty:
            raise MBError("Choisissez une image à sauvegarder.")
        job = Job("Analyse du contenu de l'image").start(
            lambda j: (core.backup_summary(s, lay), core.plugin_report(s, lay)))

        def closed(j=None):
            if not job.ok:
                return
            summary, (details, feed) = job.result
            default = ("channels", "satellites", "settings", "plugins_conf", "plugins")
            items = []
            for key, title, desc, warn, size, avail in summary:
                sub = desc
                if size:
                    sub += "  ·  " + core.human_bytes(size)
                if warn:
                    sub += "  ·  attention : " + warn
                if not avail:
                    sub = "absent de cette image"
                items.append(dict(key=key, title=title, sub=sub, checked=avail and key in default, enabled=avail))

            def save(keys, plugins=None):
                self.with_target("Sauvegarde", lambda st: self.run_job(
                    "Sauvegarde personnalisée", lambda jb: core.backup_custom(jb, s, keys, st["mount"], lay, plugins),
                    rescan=False))

            def chosen(keys):
                if "plugins" in keys and details:
                    self.plugins_checklist("Quels plugins sauvegarder ?", "Image : %s  ·  %d plugins" % (s.title(), len(details)),
                                           details, feed, None, lambda names: save(keys, names), "Sauvegarder")
                else:
                    save(keys)
            self.session.openWithCallback(lambda keys=None: keys and chosen(keys), WMBChecklist,
                                          "Que sauvegarder ?", "Image : %s" % s.title(), items, "Continuer")
        self.session.openWithCallback(closed, WMBProgress, job, True)

    def plugins_checklist(self, title, subtitle, details, feed, have, cb, action="Valider", saved_ipk=None):
        """One line per plugin. details: plugin_details() dicts (or names); have: names already
        installed in the target (shown, unchecked); saved_ipk: names with a saved .ipk."""
        items = []
        for p in details:
            if not isinstance(p, dict):
                p = core.plugin_details_from_name(p)
            notes = [p["kind"]]
            if p.get("version"):
                notes.append(p["version"][:24])
            if p.get("size"):
                notes.append(core.human_bytes(p["size"]))
            if have is not None and p["name"] in have:
                notes.append("déjà installé")
            elif feed and p["name"] not in feed:
                notes.append("hors feed : copié dans la sauvegarde")
            elif saved_ipk is not None and p["name"] in saved_ipk:
                notes.append("copie sauvegardée")
            items.append(dict(key=p["name"], title=p["short"], sub="  ·  ".join(notes),
                              checked=not (have is not None and p["name"] in have)))
        if not items:
            cb([])
            return
        self.session.openWithCallback(lambda names=None: names is not None and cb(names), WMBChecklist,
                                      title, subtitle, items, action)

    # ===== SAUVEGARDER (touche bleue) : création uniquement
    @safe
    def key_blue(self):
        if not self.ready():
            return
        s = self.current()
        if not s or s.empty or s.kind == "recovery":
            raise MBError("Choisissez d'abord une image à sauvegarder.")
        if not self.mbl.can("backup"):
            raise MBError("La sauvegarde n'est pas disponible sur ce récepteur.")
        n = len([b for b in core.list_backups() if s.info and b["image"] == s.info["label"]])
        items = [dict(icon="a_settings", title="Choisir quoi sauvegarder…", value="custom",
                      sub="Chaînes, satellites, réglages, plugins, softcam, réseau, picons"),
                 dict(icon="a_backup", title="Sauvegarder l'image complète", value="full",
                      sub="Tout le système, restaurable comme nouvelle image")]
        self.mb_pick("Sauvegarder « %s »" % s.title(), items,
                     lambda v: self.backup_choose(s) if v == "custom" else self.backup_slot(s),
                     "Cette image a déjà %d sauvegarde%s  ·  pour restaurer : touche MENU" % (n, "s" if n > 1 else ""))

    # ===== RESTAURER (menu) : choisir une sauvegarde, quoi, et où
    def backup_groups_items(self, prefer=None):
        items = []
        groups = core.backups_by_image()
        groups.sort(key=lambda g: 0 if g[0] == prefer else 1)
        for label, bks in groups:
            total = sum(b["size"] for b in bks)
            items.append(dict(icon="d_" + core.distro_key(label), title=label, value=(label, bks),
                              sub="%d sauvegarde%s  ·  dernière : %s  ·  %s" % (
                                  len(bks), "s" if len(bks) > 1 else "", bks[0]["date"], human_mb(max(1, total)))))
        return items

    def backups_items(self, bks):
        return [dict(icon="a_backups" if b["kind"] == "slot" else "a_settings", title=b["date"], value=b,
                     sub="%s  ·  %s  ·  %s" % ("image complète" if b["kind"] == "slot" else "éléments choisis",
                                               human_mb(max(1, b["size"])), b["mount"])) for b in bks]

    @safe
    def restore_start(self, target=None):
        """target: restore into this image (from the image's OK menu), else ask later."""
        if not self.ready():
            return
        items = self.backup_groups_items(target.info["label"] if (target and target.info) else None)
        if not items:
            raise MBError("Aucune sauvegarde trouvée.\nCréez-en une avec la touche BLEUE.")
        self.mb_pick("Restaurer : sauvegardes de quelle image ?", items,
                     lambda v: self.restore_pick_backup(v[0], v[1], target),
                     "Les sauvegardes sont rangées par image d'origine")

    @safe
    def restore_pick_backup(self, label, bks, target):
        self.mb_pick("Restaurer : sauvegarde de %s" % label, self.backups_items(bks),
                     lambda b: self.restore_open(b, target), "Choisissez la date")

    @safe
    def restore_open(self, b, target):
        job = Job("Lecture de la sauvegarde").start(lambda j: core.read_backup(b["path"]))

        def closed(j=None):
            if not job.ok:
                return
            info = job.result
            if info["kind"] == "slot":
                if not self.mbl.can("install"):
                    self.mb_error("Restaurer une image complète n'est pas possible sur ce récepteur.")
                    return
                self.mb_ask("Cette sauvegarde est une image complète (%s).\n\nLa restaurer comme NOUVELLE image ?\n"
                            "L'image en cours ne change pas." % human_mb(max(1, b["size"])),
                            lambda: self.install_from(b["path"], os.path.basename(b["path"])), default=True)
            elif not info["categories"]:
                self.mb_error("Cette sauvegarde est vide.")
            else:
                self.restore_choose(b, info, target)
        self.session.openWithCallback(closed, WMBProgress, job, True)

    @safe
    def restore_choose(self, b, info, target=None):
        man = info["manifest"]
        items = []
        for key, title, desc, warn in core.CATEGORIES:
            n = info["categories"].get(key)
            if n:
                items.append(dict(key=key, title=title, checked=True, enabled=True,
                                  sub="%d %s  ·  %s" % (n, "plugins" if key == "plugins" else "fichiers", desc)))

        def to_slot(keys, s):
            if "plugins" not in keys or not info.get("plugins"):
                self.restore_confirm(b, keys, s)
                return
            try:
                have = set(core.installed_plugins("/" if s.running else s.root)) if (s.running or s.root) else set()
            except Exception:
                have = set()
            if all(n in have for n in info["plugins"]):
                rest = [k for k in keys if k != "plugins"]
                if not rest:
                    self.mb_error("Les %d plugins de cette sauvegarde sont déjà installés dans %s." % (len(info["plugins"]), s.title()))
                    return
                self.restore_confirm(b, rest, s)
                return
            self.plugins_checklist("Quels plugins restaurer ?", "Dans : %s  ·  %d plugins dans la sauvegarde" % (
                s.title(), len(info["plugins"])), info["plugins"], None, have,
                lambda names: self.restore_confirm(b, keys, s, names), "Continuer", set(info.get("ipks") or ()))

        def chosen(keys):
            if target is not None:
                to_slot(keys, target)
                return
            targets = [s for s in self.mbl.slots if s.kind in ("chroot", "omb") and not s.empty]
            run = self.mbl.running_slot()
            if run is None or run not in targets:
                targets.insert(0, run or core.Slot("running", 0, "flash", running=True, info={"label": "Image en cours"}))
            pick = []
            for s in targets:
                pick.append(dict(icon="d_" + core.distro_key((s.info or {}).get("distro", "")), title=s.title(), value=s,
                                 sub=("Image en cours : l'interface redémarre pour appliquer" if s.running
                                      else "Autre image : les fichiers sont écrits directement"),
                                 pill="p_running" if s.running else None))
            self.mb_pick("Restaurer dans quelle image ?", pick, lambda s: to_slot(keys, s),
                         "Éléments : %s" % ", ".join(core.CAT_TITLES[k] for k in keys))
        self.session.openWithCallback(lambda keys=None: keys and chosen(keys), WMBChecklist,
                                      "Que restaurer ?", "Sauvegarde de %s du %s" % (man.get("image", b["image"]), b["date"]),
                                      items, "Continuer")

    @safe
    def restore_confirm(self, b, keys, s, plugins=None):
        if not s.running:
            core.guard_not_running(s)
        if plugins is not None and not plugins:
            keys = [k for k in keys if k != "plugins"]
            if not keys:
                raise MBError("Rien à restaurer : aucun élément ni plugin choisi.")
        what = ", ".join(core.CAT_TITLES[k] for k in keys)
        if plugins:
            what += " (%d plugins)" % len(plugins)
        text = "Restaurer dans « %s » :\n%s\n\n" % (s.title(), what)
        if s.running:
            text += "Une sauvegarde de sécurité des éléments actuels est faite d'abord.\nL'interface redémarrera ensuite."
        else:
            text += "Les fichiers actuels de cette image seront remplacés."

        def go():
            lay = self.mbl

            def work(job):
                if s.running:
                    st = core.storage_for(b["path"]) or (core.storages() or [None])[0]
                    safe_keys = [k for k in keys if k not in ("picons", "plugins")]
                    if st and safe_keys:
                        job.say("Sauvegarde de sécurité avant restauration…", 2)
                        try:
                            core.backup_custom(job, s, safe_keys, st["mount"], lay)
                        except core.Cancelled:
                            raise
                        except MBError as e:
                            log("pre-restore backup: %s" % e)
                        job.progress = 0
                return core.restore_custom(job, b["path"], keys, s, lay, plugins)
            self.run_job("Restauration", work, rescan=not s.running)
        self.mb_ask(text, go, default=True)

    # ===== GÉRER (menu) : voir le contenu, supprimer
    @safe
    def manage_backups(self):
        items = self.backup_groups_items()
        if not items:
            raise MBError("Aucune sauvegarde trouvée.")
        self.mb_pick("Gérer les sauvegardes", items,
                     lambda v: self.mb_pick("Sauvegardes de %s" % v[0], self.backups_items(v[1]), self.manage_one,
                                            "OK : voir le contenu ou supprimer"),
                     "Voir le contenu ou supprimer pour libérer de la place")

    @safe
    def manage_one(self, b):
        job = Job("Lecture de la sauvegarde").start(lambda j: core.read_backup(b["path"]))

        def closed(j=None):
            if not job.ok:
                return
            info = job.result
            items = [dict(icon="a_help", title="Voir le contenu", value="show", sub=self.backup_contents_text(b, info).split("\n")[0]),
                     dict(icon="a_delete", title="Supprimer cette sauvegarde", value="delete",
                          sub="Libère %s  ·  %s" % (human_mb(max(1, b["size"])), b["name"]))]

            def act(what):
                if what == "show":
                    self.mb_info(self.backup_contents_text(b, info))
                else:
                    self.mb_ask("Supprimer définitivement la sauvegarde du %s ?\n%s" % (b["date"], b["name"]),
                                lambda: self.run_job("Suppression de la sauvegarde",
                                                     lambda jb: (core.delete_backup(b["path"]), "Sauvegarde supprimée.")[1],
                                                     rescan=False))
            self.mb_pick("Sauvegarde du %s" % b["date"], items, act, b["image"])
        self.session.openWithCallback(closed, WMBProgress, job, True)

    def backup_contents_text(self, b, info):
        if info["kind"] == "slot":
            return "Image complète de %s (tout le système).\n%s · %s" % (b["image"], b["date"], human_mb(max(1, b["size"])))
        man = info["manifest"]
        lines = ["Sauvegarde de : %s" % man.get("image", b["image"]), "Date : %s" % (man.get("date") or b["date"]), ""]
        for key, title, desc, warn in core.CATEGORIES:
            n = info["categories"].get(key)
            if n:
                lines.append("• %s : %d %s" % (title, n, "plugins" if key == "plugins" else "fichiers"))
        return "\n".join(lines)

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
                      sub="OpenATV, OpenPLi, OpenViX, PurE2, OpenSPA, Neutrino… pour %s" % self.mbl.box["machine"]),
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
    def pick_distro(self, catalog, on_pick=None):
        items = []
        for d, its in catalog:
            if its:
                sub = "%d image%s  ·  dernière : %s" % (len(its), "s" if len(its) > 1 else "", its[0]["day"])
                if core.distro_key(d) == "neutrino":
                    sub += "  ·  pas Enigma2 (menus et plugins différents)"
                items.append(dict(icon="d_" + core.distro_key(d), title=d, value=(d, its), sub=sub))
            else:
                sub = "Aucune image publiée pour %s" % self.mbl.box["machine"]
                if core.distro_key(d) == "egami":
                    sub = "Réservé aux donateurs pour ce récepteur  ·  OK : comment faire"
                items.append(dict(icon="d_" + core.distro_key(d), title=d, value=(d, its), pill="p_empty", sub=sub))
        self.mb_pick("Images en ligne", items, lambda v: self.pick_online(v, on_pick),
                     "Pour %s  ·  choisissez une distribution" % self.mbl.box["machine"])

    @safe
    def pick_online(self, value, on_pick=None):
        distro, its = value
        if not its and core.distro_key(distro) == "egami":
            dirs = ", ".join(st["mount"] + "/images" for st in core.storages()[:2]) or "/media/hdd/images"
            self.mb_info("EGAMI ne publie librement que certaines marques (Zgemma, Dreambox, HD51…).\n"
                         "Pour les Vu+, les images sont réservées aux donateurs.\n\n"
                         "1. Téléchargez le zip « _usb » ou « _multi » pour %s sur egami-image.com (compte donateur).\n"
                         "2. Copiez-le dans %s.\n"
                         "3. Touche JAUNE : il apparaît dans la liste et s'installe comme les autres."
                         % (self.mbl.box["machine"], dirs))
            return
        if not its:
            self.mb_info("%s ne publie pas d'image pour %s.\nChoisissez une autre distribution." % (distro, self.mbl.box["machine"]))
            return
        items = []
        for it in its[:60]:
            pill = "p_eol" if it["eol"] else ("p_beta" if (it["beta"] or "beta" in it["name"].lower()) else "p_release")
            items.append(dict(icon="d_" + core.distro_key(distro), title=it["name"].replace(".zip", ""), value=it,
                              pill=pill, sub="%s  ·  %s  ·  %s" % (it["day"], human_mb(it["size"] // core.MB), it["group"])))
        self.mb_pick(distro, items, lambda it: (on_pick or self.install_from)(it["url"], it["name"]), self.space_text())

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
        if core.distro_key((new.info or {}).get("distro", "")) in ("neutrino", "unknown"):
            offer_boot()
            return
        self.mb_ask("Copier vos chaînes, favoris et satellites dans la nouvelle image ?",
                    lambda: self.run_job("Copie des chaînes", lambda j: core.copy_channels(j, new),
                                         lambda j: offer_boot(), rescan=False),
                    default=True, no_cb=offer_boot)

    # ===== METTRE À JOUR : nouvelle version à côté, tout gardé
    def can_update(self, s):
        lay = self.mbl
        return bool(lay and s and lay.can("install") and lay.new_slots and not s.empty
                    and s.kind != "recovery" and lay.key in ("chroot", "omb"))

    @safe
    def update_start(self, s=None):
        if not self.ready():
            return
        s = s or self.current()
        if not s or s.empty:
            raise MBError("Choisissez d'abord l'image à mettre à jour.")
        if not self.can_update(s):
            raise MBError("La mise à jour « tout garder » demande un multiboot sur disque (HDD/USB).\n"
                          "Sur ce récepteur : sauvegardez (BLEU), installez la nouvelle image (JAUNE), puis restaurez (MENU).")
        if self._catalog and time.time() - self._catalog[0] < 900:
            self.update_pick_source(s, self._catalog[1])
            return
        machine = self.mbl.box["machine"]
        job = Job("Recherche des mises à jour").start(lambda j: core.fetch_catalog(j, machine))

        def closed(j=None):
            if job.ok:
                self._catalog = (time.time(), job.result)
                self.update_pick_source(s, job.result)
        self.session.openWithCallback(closed, WMBProgress, job, True)

    @safe
    def update_pick_source(self, s, catalog):
        info = s.info or {}
        item, newer = core.find_update(catalog, s)
        items = []
        if item:
            items.append(dict(icon="d_" + core.distro_key(info.get("distro", "")), value=("image", item),
                              title="Dernière %s : %s" % (info.get("distro", ""), item["name"].replace(".zip", "")),
                              pill="p_new" if newer else "p_uptodate",
                              sub="%s  ·  %s  ·  %s" % (item["day"], human_mb(item["size"] // core.MB),
                                                       "plus récente que votre image" if newer else "pas plus récente que votre image")))
        items.append(dict(icon="a_online", title="Choisir une autre image en ligne…", value=("other", None),
                          sub="Autre version ou autre distribution"))
        for label, path, size in core.find_local_images()[:20]:
            items.append(dict(icon="a_file", title=os.path.basename(path), value=("file", path),
                              sub="%s  ·  %s" % (human_mb(size), os.path.dirname(path))))
        sub = "Vos chaînes, réglages et plugins sont gardés  ·  l'ancienne image reste disponible"
        if not item:
            sub = "Pas de version en ligne trouvée pour %s  ·  choisissez une image" % (info.get("distro") or "cette image")

        def chosen(v):
            kind, val = v
            if kind == "image":
                self.update_options(s, val["url"], val["name"])
            elif kind == "file":
                self.update_options(s, val, os.path.basename(val))
            else:
                self.pick_distro(catalog, lambda url, name: self.update_options(s, url, name))
        self.mb_pick("Mettre à jour « %s »" % s.title(), items, chosen, sub)

    @safe
    def update_options(self, s, image, label):
        lay = self.mbl
        same = core.distro_key(label) == core.distro_key((s.info or {}).get("distro", ""))
        job = Job("Analyse de l'image actuelle").start(
            lambda j: (core.backup_summary(s, lay), core.plugin_report(s, lay)))

        def closed(j=None):
            if not job.ok:
                return
            summary, (details, feed) = job.result
            risky = ("settings", "plugins_conf", "plugins")
            items = []
            for key, title, desc, warn, size, avail in summary:
                sub = desc + ("  ·  " + core.human_bytes(size) if size else "")
                if not same and key in risky:
                    sub += "  ·  autre distribution : déconseillé"
                if not avail:
                    sub = "absent de cette image"
                items.append(dict(key=key, title=title, sub=sub, enabled=avail,
                                  checked=avail and (same or key not in risky)))
            subtitle = "De %s vers %s" % (s.title(), label.replace(".zip", ""))
            if not same:
                subtitle += "  ·  autre distribution"

            def chosen(keys):
                if "plugins" in keys and details:
                    self.plugins_checklist("Quels plugins garder ?", "%d plugins dans %s" % (len(details), s.title()),
                                           details, feed, None, lambda names: self.update_where(s, image, label, keys, names),
                                           "Continuer")
                else:
                    self.update_where(s, image, label, keys, None)
            self.session.openWithCallback(lambda keys=None: keys and chosen(keys), WMBChecklist,
                                          "Que garder ?", subtitle, items, "Continuer")
        self.session.openWithCallback(closed, WMBProgress, job, True)

    @safe
    def update_where(self, s, image, label, keys, plugins):
        if plugins is not None and not plugins:
            keys = [k for k in keys if k != "plugins"]
        if not keys:
            raise MBError("Cochez au moins un élément à garder.")
        targets = [t for t in self.mbl.install_targets() if t["free"] >= 900]
        if not targets:
            raise MBError("Pas assez de place : il faut environ 900 Mo libres (image + sauvegarde).\n"
                          "Supprimez une ancienne image ou sauvegarde.")
        if len(targets) == 1:
            self.update_confirm(s, image, label, keys, plugins, targets[0])
            return
        self.mb_pick("Où installer la nouvelle version ?", [
            dict(icon="a_disk", title=t["mount"], value=t, sub="%s libres sur %s" % (human_mb(t["free"]), human_mb(t["total"])))
            for t in targets], lambda t: self.update_confirm(s, image, label, keys, plugins, t), "Choisissez le disque")

    @safe
    def update_confirm(self, s, image, label, keys, plugins, target):
        lay = self.mbl
        what = ", ".join(core.CAT_TITLES[k] for k in keys)
        if plugins:
            what += " (%d plugins)" % len(plugins)
        text = ("Mettre à jour « %s » avec\n%s ?\n\n"
                "1. Sauvegarde de : %s\n"
                "2. Installation de la nouvelle version dans un nouveau slot (%s)\n"
                "3. Restauration de tout dans la nouvelle version\n"
                "4. Plugins installés au premier démarrage (Internet nécessaire)\n\n"
                "L'image actuelle n'est pas modifiée. EXIT pour annuler pendant le téléchargement."
                % (s.title(), label.replace(".zip", ""), what, target["mount"]))
        self.mb_ask(text, lambda: self.run_job(
            "Mise à jour d'image", lambda job: core.update_image(job, lay, s, image, target, keys, plugins, target["mount"]),
            self.after_update), default=True)

    def after_update(self, job):
        root = getattr(job, "new_root", None)
        new = None
        for x in self.mbl.slots:
            if root and x.root == root:
                new = x
        if new is None:
            self.mb_info(job.result)
            return
        self["list"].moveToIndex(self.mbl.slots.index(new))
        self.update_details()
        items = []
        if self.mbl.can("once"):
            items.append(dict(icon="a_once", title="Démarrer une fois pour tester (conseillé)", value="once",
                              sub="Au redémarrage suivant, retour sur l'ancienne image"))
        items.append(dict(icon="a_boot", title="Démarrer définitivement sur la nouvelle version", value="boot",
                          sub="L'ancienne image reste dans la liste"))
        items.append(dict(icon="a_help", title="Plus tard", value="later", sub="Touche VERTE quand vous voulez"))

        def go(v):
            if v in ("once", "boot"):
                self.run_job("Choix du démarrage", lambda j: self.mbl.set_next(j, new, v == "once"), self.ask_reboot)
        self.mb_pick("Nouvelle version prête", items, go, (new.info or {}).get("label", new.title()))

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
        tiles = [("update", "m_update", "Mettre à jour", "tout garder"),
                 ("restore", "m_restore", "Restaurer", "une sauvegarde"),
                 ("backups", "m_backup", "Sauvegarder", "choisir quoi"),
                 ("install", "m_install", "Installer", "en ligne · URL · zip"),
                 ("manage", "m_manage", "Sauvegardes", "voir · supprimer"),
                 ("space", "m_space", "Espace disque", self.space_short()),
                 ("rescan", "m_refresh", "Actualiser", "relire les images"),
                 ("help", "m_help", "Aide", "aide · journal")]
        if self.mbl is not None and not self.mbl.can("install"):
            tiles = [t for t in tiles if t[0] not in ("install", "update")]
        self.session.openWithCallback(lambda v=None: v and self.menu_action(v), WMBMenu, tiles,
                                      "Wacayoub MultiBoot %s" % core.VERSION,
                                      "%s %s  ·  %s" % (self.mbl.box["brand"], self.mbl.box["machine"], self.mbl.name)
                                      if self.mbl else "")

    def space_short(self):
        caps = core.install_capacity()
        if not caps:
            return "aucun disque ext4"
        st, n = caps[0]
        return "%s libres · ~%d images" % (human_mb(st["free"]), n)

    @safe
    def key_menu_list(self):
        items = []
        if self.mbl and self.mbl.can("install"):
            items.append(dict(icon="a_online", title="Installer une image", value="install", sub="En ligne, URL ou fichier"))
        items = [dict(icon="a_backups", title="Restaurer une sauvegarde", value="restore",
                      sub="Choisir l'image, la date, quoi restaurer et où")] + items
        items += [dict(icon="a_backup", title="Sauvegarder", value="backups", sub="Même chose que la touche BLEUE"),
                  dict(icon="a_delete", title="Gérer les sauvegardes", value="manage", sub="Voir le contenu, supprimer"),
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
        elif what == "restore":
            self.restore_start()
        elif what == "manage":
            self.manage_backups()
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
            self.mb_pick("Aide", [dict(icon="a_help", title="Aide et compatibilité", value="help_text",
                                       sub="Touches, récepteurs pris en charge, sécurité"),
                                  dict(icon="a_size", title="Journal", value="log", sub=core.LOG_FILE)],
                         self.menu_action, "Wacayoub MultiBoot %s" % core.VERSION)
        elif what == "help_text":
            self.mb_info(HELP)
        elif what == "update":
            self.update_start()
        elif what == "list":
            self.key_menu_list()


HELP = """Wacayoub MultiBoot %s

VERT : démarrer sur l'image choisie.  OK : toutes les options (démarrer une seule fois, copier les chaînes…).
JAUNE : installer une image.  BLEU : sauvegarder.  MENU : mettre à jour, restaurer, gérer les sauvegardes.  ROUGE : supprimer.

Mettre à jour (tout garder) : la nouvelle version est installée à côté de l'ancienne, vos chaînes, réglages, softcam, réseau, picons et plugins choisis y sont remis. Les plugins sont installés à son premier démarrage (Internet nécessaire) ; vos plugins hors feed sont copiés dans la sauvegarde. L'ancienne image reste dans la liste.

Structures reconnues automatiquement :
• HDD/USB (omb-init) : Vu+ 4K et autres.
• eMMC (STARTUP_n) : GigaBlue, Zgemma, Octagon, Edision, AX/Maxytec, Vu+ kexec…
• OpenMultiboot classique.
• Dreambox / sans multiboot : affichage et sauvegarde.

Sécurité : l'image en cours n'est jamais modifiée ni supprimée. Chaque action vérifie l'espace libre, l'archive et le modèle avant de commencer.""" % core.VERSION
