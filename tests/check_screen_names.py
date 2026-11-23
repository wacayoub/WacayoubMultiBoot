#!/usr/bin/env python3
"""Run on the receiver: fails if ui.py defines a method/attribute whose name enigma2's
Screen class already uses (e.g. 'shown' -> crash 'bool object is not callable')."""
import marshal, re, sys
ui = open(sys.argv[1], encoding="utf-8").read()
co = marshal.loads(open("/usr/lib/enigma2/python/Screens/Screen.pyc", "rb").read()[16:])
names = set()
def walk(c):
    names.update(c.co_names)
    for k in c.co_consts:
        if hasattr(k, "co_code"):
            names.add(k.co_name); walk(k)
walk(co)
mine = set(re.findall(r"^    def (\w+)\(self", ui, re.M)) | set(re.findall(r"self\.(\w+)\s*=", ui))
allowed = {"skin", "__init__", "close", "session", "setTitle"}
bad = sorted(n for n in mine if n in names and n not in allowed and not n.startswith("__"))
print("clashes:", bad)
# OpenATV runs non-method entries of onLayoutFinish/onShown… as skin applet code (exec) -> crash
lam = re.findall(r"on(?:LayoutFinish|Shown|Show|ExecBegin|FirstExecBegin)\.append\(lambda", ui)
print("lambda hooks:", len(lam))
sys.exit(1 if (bad or lam) else 0)
