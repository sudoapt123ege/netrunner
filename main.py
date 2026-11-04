import array
import json
import math
import os
import queue
import random
import socket
import sys
import threading
import time
import traceback
import uuid
import asyncio
from functools import lru_cache

import pygame

# ── Native 2x design space. Everything authored directly in these units. ──
W, H = 768, 432
FPS = 60
HERE = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.getcwd()
PROFILE_NAME = ""
if "--profile" in sys.argv:
    try:
        PROFILE_NAME = sys.argv[sys.argv.index("--profile") + 1]
    except IndexError:
        pass
_sfx = ("_" + "".join(c for c in PROFILE_NAME if c.isalnum())) if PROFILE_NAME else ""
PROFILE_FILE = os.path.join(HERE, "netrunner_profile%s.json" % _sfx)
CFG_FILE = os.path.join(HERE, "netrunner_cfg%s.json" % _sfx)
WORLD_FILE = os.path.join(HERE, "netrunner_world.json")
TCP_PORT, UDP_PORT = 47077, 47078
TITLE = "NETRUNNER: BLACKOUT"

# ───────────────────────── colours ─────────────────────────
BG = (6, 10, 14)
PANEL = (10, 18, 24)
BORDER = (30, 120, 96)
GREEN, DGREEN = (80, 255, 140), (24, 90, 56)
CYAN, MAG = (80, 230, 255), (255, 70, 200)
AMBER, RED = (255, 190, 60), (255, 72, 84)
WHITE, DIM, MID = (226, 240, 236), (84, 118, 112), (140, 180, 170)
BLACK = (0, 0, 0)
CORP = (176, 70, 84)
VIOLET = (170, 120, 255)
PCOLORS = [(80, 255, 140), (80, 230, 255), (255, 70, 200), (255, 190, 60),
           (170, 120, 255), (255, 120, 80), (120, 160, 255), (230, 255, 90),
           (255, 150, 40), (255, 150, 40)]
PNAMES = ["GREEN", "CYAN", "MAGENTA", "AMBER", "VIOLET", "CORAL", "AZURE", "LIME"]


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def lerp(a, b, t):
    return a + (b - a) * t


def lerpc(a, b, t):
    return (int(a[0] + (b[0] - a[0]) * t), int(a[1] + (b[1] - a[1]) * t), int(a[2] + (b[2] - a[2]) * t))


def dimc(c, f):
    return (int(c[0] * f), int(c[1] * f), int(c[2] * f))


def money(n):
    return "$" + format(int(n), ",")


def clean(s, n=14):
    return "".join(ch for ch in str(s) if 32 <= ord(ch) < 127).strip()[:n]


# ───────────────────────── storage ─────────────────────────
_STORAGE_BACKEND = "fs"
try:
    import js  # pyodide / pygbag
    _STORAGE_BACKEND = "web"
except Exception:
    pass


def _key(path):
    return os.path.basename(str(path))


def _web_get(key):
    from js import localStorage
    v = localStorage.getItem(key)
    return json.loads(v) if v else None


def _web_set(key, obj):
    from js import localStorage
    localStorage.setItem(key, json.dumps(obj))
    return True


def jload(path, default):
    if _STORAGE_BACKEND == "web":
        try:
            v = _web_get(_key(path))
            return v if v is not None else default
        except Exception:
            return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def jsave(path, obj):
    if _STORAGE_BACKEND == "web":
        try:
            return _web_set(_key(path), obj)
        except Exception:
            return False
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f)
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def export_save(obj):
    blob = json.dumps(obj, indent=2)
    if _STORAGE_BACKEND == "web":
        try:
            from js import Blob, URL, document
            b = Blob.new([blob], {"type": "application/json"})
            a = document.createElement("a")
            a.href = URL.createObjectURL(b)
            a.download = "netrunner_save.json"
            a.click()
            return blob
        except Exception:
            return blob
    path = os.path.join(HERE, "netrunner_export.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(blob)
    except Exception:
        pass
    return path


def local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# ───────────────────────── fonts & drawing helpers ─────────────────────────
FONTS = {}


def font(sz):
    f = FONTS.get(sz)
    if f is None:
        f = FONTS[sz] = pygame.font.Font(None, sz)
    return f


@lru_cache(maxsize=4096)
def _render(msg, sz, col):
    return font(sz).render(msg, False, col)


def text(s, msg, x, y, col=WHITE, sz=14, al="l", sh=True):
    msg = str(msg)
    if not msg:
        return 0
    img = _render(msg, sz, col)
    x, y = int(x), int(y)
    w = img.get_width()
    if al == "r":
        x -= w
    elif al == "c":
        x -= w // 2
    if sh:
        s.blit(_render(msg, sz, BLACK), (x + 1, y + 1))
    s.blit(img, (x, y))
    return w


def tw(msg, sz=14):
    return font(sz).size(str(msg))[0]


def fh(sz=14):
    return font(sz).get_height()


def ctext(s, msg, rect, col=WHITE, sz=14):
    r = pygame.Rect(rect)
    text(s, msg, r.centerx, r.centery - fh(sz) // 2, col, sz, "c")


def fit(msg, w, sz=14):
    msg = str(msg)
    if tw(msg, sz) <= w:
        return msg
    while msg and tw(msg + "..", sz) > w:
        msg = msg[:-1]
    return msg + ".."


def wrap(msg, width, sz=14):
    out = []
    for para in str(msg).split("\n"):
        line = ""
        for word in para.split(" "):
            t = (line + " " + word) if line else word
            if tw(t, sz) <= width:
                line = t
            else:
                if line:
                    out.append(line)
                line = word
        out.append(line)
    return out


@lru_cache(maxsize=64)
def _panel_bg(w, h, alpha, bg):
    sf = pygame.Surface((w, h), pygame.SRCALPHA)
    sf.fill((bg[0], bg[1], bg[2], alpha))
    return sf


def panel(s, rect, col=BORDER, bg=PANEL, title=None, alpha=236, dither=True):
    r = pygame.Rect(rect)
    s.blit(_panel_bg(r.w, r.h, alpha, bg), r.topleft)
    if dither and r.w > 16 and r.h > 16:
        for yy in range(r.top + 2, r.bottom - 2, 4):
            for xx in range(r.left + 2 + ((yy // 4) % 2) * 2, r.right - 2, 4):
                s.set_at((xx, yy), (bg[0] + 6, bg[1] + 10, bg[2] + 14) if bg[2] > bg[0] else (bg[0] + 4, bg[1] + 4, bg[2] + 6))
    pygame.draw.rect(s, col, r, 1)
    L = 6
    for cx, cy, dx, dy in ((r.left, r.top, 1, 1), (r.right - 1, r.top, -1, 1),
                           (r.left, r.bottom - 1, 1, -1), (r.right - 1, r.bottom - 1, -1, -1)):
        pygame.draw.line(s, lerpc(col, WHITE, .5), (cx, cy), (cx + L * dx, cy))
        pygame.draw.line(s, lerpc(col, WHITE, .5), (cx, cy), (cx, cy + L * dy))
    if title:
        w = tw(title, 12) + 8
        pygame.draw.rect(s, col, (r.left + 6, r.top - 3, w, 9))
        text(s, title, r.left + 10, r.top - 2, BLACK, 12, sh=False)


def bar(s, x, y, w, h, v, mx, col, bg=(12, 22, 26)):
    x, y, w, h = int(x), int(y), int(w), int(h)
    pygame.draw.rect(s, bg, (x, y, w, h))
    fw = int((w - 2) * clamp(v / mx if mx else 0, 0, 1))
    if fw > 0:
        pygame.draw.rect(s, col, (x + 1, y + 1, fw, h - 2))
    pygame.draw.rect(s, BORDER, (x, y, w, h), 1)


def heatcol(v):
    v = clamp(v, 0, 100)
    return lerpc(GREEN, AMBER, v / 50) if v < 50 else lerpc(AMBER, RED, (v - 50) / 50)


# ───────────────────────── icons ─────────────────────────
def node_icon(s, cx, cy, typ, col):
    d = pygame.draw
    if typ == "BANK":
        d.polygon(s, col, [(cx - 7, cy - 1), (cx, cy - 7), (cx + 7, cy - 1)])
        for i in (-4, 0, 4):
            d.line(s, col, (cx + i, cy), (cx + i, cy + 5))
        d.line(s, col, (cx - 7, cy + 7), (cx + 7, cy + 7))
    elif typ == "CRYPTO":
        d.polygon(s, col, [(cx, cy - 7), (cx + 6, cy), (cx, cy + 7), (cx - 6, cy)], 1)
        d.line(s, col, (cx - 2, cy), (cx + 2, cy))
        d.line(s, col, (cx, cy - 4), (cx, cy + 4))
    elif typ == "TELECOM":
        d.line(s, col, (cx, cy + 7), (cx, cy - 1))
        d.circle(s, col, (cx, cy - 3), 1)
        d.arc(s, col, (cx - 6, cy - 8, 12, 12), 0.6, 2.5, 1)
        d.arc(s, col, (cx - 8, cy - 10, 16, 16), 0.7, 2.4, 1)
    elif typ == "MEDIA":
        d.rect(s, col, (cx - 7, cy - 4, 14, 8), 1)
        d.polygon(s, col, [(cx - 1, cy - 1), (cx + 3, cy), (cx - 1, cy + 2)])
    elif typ == "LAB":
        d.polygon(s, col, [(cx - 1, cy - 7), (cx + 1, cy - 7), (cx + 1, cy - 1),
                           (cx + 7, cy + 7), (cx - 7, cy + 7), (cx - 1, cy - 1)], 1)
    elif typ == "MILITARY":
        d.polygon(s, col, [(cx - 7, cy - 4), (cx + 7, cy - 4), (cx + 6, cy + 2),
                           (cx, cy + 8), (cx - 6, cy + 2)], 1)
        d.line(s, col, (cx, cy - 3), (cx, cy + 4))
        d.line(s, col, (cx - 2, cy - 1), (cx + 2, cy - 1))
    elif typ == "AI_CORE":
        d.rect(s, col, (cx - 6, cy - 6, 12, 12), 1)
        d.rect(s, col, (cx - 2, cy - 2, 4, 4))
        for a in range(4):
            ang = a * math.pi / 2 + 0.4
            d.line(s, col, (cx + int(math.cos(ang) * 5), cy + int(math.sin(ang) * 5)),
                   (cx + int(math.cos(ang) * 8), cy + int(math.sin(ang) * 8)))
    elif typ == "VOID":
        d.circle(s, col, (cx, cy), 7, 1)
        d.circle(s, dimc(col, .3), (cx, cy), 4)
        d.line(s, col, (cx - 3, cy - 3), (cx + 3, cy + 3), 1)
        d.line(s, col, (cx + 3, cy - 3), (cx - 3, cy + 3), 1)
    else:
        d.polygon(s, col, [(cx - 7, cy - 4), (cx + 7, cy - 4), (cx + 6, cy + 2),
                           (cx, cy + 8), (cx - 6, cy + 2)], 1)
        d.line(s, col, (cx, cy - 3), (cx, cy + 4))


def dock_icon(s, kind, cx, cy, col):
    d = pygame.draw
    if kind == "net":
        pts = [(cx - 7, cy + 3), (cx + 7, cy + 3), (cx, cy - 6)]
        d.polygon(s, col, pts, 1)
        for p in pts:
            d.circle(s, col, p, 2)
    elif kind == "shop":
        d.circle(s, col, (cx, cy), 7, 1)
        ctext(s, "$", (cx - 7, cy - 7, 14, 14), col, 16)
    elif kind == "rig":
        d.rect(s, col, (cx - 6, cy - 6, 12, 12), 1)
        d.rect(s, col, (cx - 2, cy - 2, 4, 4))
        for i in (-3, 0, 3):
            d.line(s, col, (cx + i, cy - 9), (cx + i, cy - 6))
            d.line(s, col, (cx + i, cy + 6), (cx + i, cy + 9))
    elif kind == "ranks":
        for i, hh in enumerate((5, 9, 7)):
            d.rect(s, col, (cx - 7 + i * 5, cy + 6 - hh, 4, hh))
    elif kind == "chat":
        d.rect(s, col, (cx - 7, cy - 6, 14, 9), 1)
        d.polygon(s, col, [(cx - 3, cy + 3), (cx - 3, cy + 7), (cx + 1, cy + 3)])
        for i in (-3, 0, 3):
            d.rect(s, col, (cx + i - 1, cy - 2, 2, 2))
    elif kind == "forge":
        d.rect(s, col, (cx - 6, cy - 5, 12, 11), 1)
        d.rect(s, col, (cx - 3, cy - 2, 3, 3))
        d.rect(s, col, (cx + 1, cy - 2, 3, 3))
        d.line(s, col, (cx - 6, cy + 1), (cx + 6, cy + 1))
        d.circle(s, col, (cx - 4, cy + 4), 1)
        d.circle(s, col, (cx + 4, cy + 4), 1)
    elif kind == "botnet":
        for dx, dy in ((-5, 3), (5, 3), (0, -4)):
            d.circle(s, col, (cx + dx, cy + dy), 2)
        d.line(s, col, (cx - 4, cy + 2), (cx, cy - 3))
        d.line(s, col, (cx + 4, cy + 2), (cx, cy - 3))
        d.line(s, col, (cx - 5, cy + 4), (cx + 5, cy + 4))
    elif kind == "jobs":
        d.rect(s, col, (cx - 5, cy - 5, 10, 12), 1)
        d.rect(s, col, (cx - 2, cy - 6, 4, 3))
        for i in range(3):
            d.line(s, col, (cx - 3, cy - 1 + i * 3), (cx + 3, cy - 1 + i * 3))
    elif kind == "data":
        d.rect(s, col, (cx - 6, cy - 5, 12, 11), 1)
        d.rect(s, col, (cx - 4, cy - 3, 4, 3))
        d.rect(s, col, (cx + 1, cy - 3, 3, 3))
        d.rect(s, col, (cx - 4, cy + 2, 8, 2))
    elif kind == "market":
        d.rect(s, col, (cx - 6, cy - 3, 12, 8), 1)
        d.rect(s, col, (cx - 2, cy - 5, 4, 2))
        d.line(s, col, (cx, cy - 3), (cx, cy + 5))
    elif kind == "study":
        d.rect(s, col, (cx - 6, cy - 5, 12, 11), 1)
        d.line(s, col, (cx, cy - 5), (cx, cy + 6))
    elif kind == "sys":
        d.circle(s, col, (cx, cy), 6, 1)
        for i in range(8):
            a = i * math.pi / 4
            d.line(s, col, (cx + math.cos(a) * 8, cy + math.sin(a) * 8),
                   (cx + math.cos(a) * 10, cy + math.sin(a) * 10), 1)
    else:
        d.circle(s, col, (cx, cy), 4, 1)
        for i in range(8):
            a = i * math.pi / 4
            d.line(s, col, (cx + math.cos(a) * 5, cy + math.sin(a) * 5),
                   (cx + math.cos(a) * 8, cy + math.sin(a) * 8), 2)


def device_icon(s, kind, cx, cy, col):
    d = pygame.draw
    if kind == "phone":
        d.rect(s, col, (cx - 3, cy - 6, 6, 12), 1)
        d.rect(s, col, (cx - 2, cy - 4, 4, 8))
        d.circle(s, col, (cx, cy + 4), 1)
    elif kind == "tablet":
        d.rect(s, col, (cx - 5, cy - 6, 10, 12), 1)
        d.rect(s, col, (cx - 4, cy - 5, 8, 9))
        d.circle(s, col, (cx, cy + 5), 1)
    elif kind == "drone":
        d.circle(s, col, (cx, cy), 2)
        for dx in (-5, 5):
            for dy in (-5, 5):
                d.line(s, col, (cx, cy), (cx + dx, cy + dy))
                d.circle(s, col, (cx + dx, cy + dy), 2, 1)
    elif kind == "server":
        for i in range(3):
            d.rect(s, col, (cx - 6, cy - 6 + i * 4, 12, 3), 1)
            d.circle(s, col, (cx + 4, cy - 4 + i * 4), 1)
    elif kind == "quantum":
        d.circle(s, col, (cx, cy), 6, 1)
        d.circle(s, col, (cx, cy), 3, 1)
        for i in range(4):
            a = i * math.pi / 2 + 0.4
            d.line(s, col, (cx + math.cos(a) * 3, cy + math.sin(a) * 3),
                   (cx + math.cos(a) * 8, cy + math.sin(a) * 8))
    elif kind == "pcb_scanner":
        d.rect(s, col, (cx - 6, cy - 4, 12, 9), 1)
        for i in range(3):
            d.line(s, col, (cx - 4, cy - 2 + i * 3), (cx + 4, cy - 2 + i * 3))
        d.circle(s, col, (cx, cy - 6), 2, 1)
    elif kind == "relay_pylon":
        d.polygon(s, col, [(cx, cy - 7), (cx - 5, cy + 6), (cx + 5, cy + 6)], 1)
        for i in (-2, 0, 2):
            d.line(s, col, (cx - 4, cy + i), (cx + 4, cy + i))
    elif kind == "brute_rig":
        d.rect(s, col, (cx - 6, cy - 4, 12, 9), 1)
        for i in range(3):
            d.rect(s, col, (cx - 4 + i * 3, cy - 2, 2, 5))
        d.line(s, col, (cx - 6, cy - 6), (cx + 6, cy - 6))
    elif kind == "ghost_node":
        d.circle(s, col, (cx, cy), 6, 1)
        d.circle(s, dimc(col, .4), (cx, cy), 4)
        d.circle(s, dimc(col, .4), (cx, cy), 2)
    elif kind == "void_core":
        d.circle(s, col, (cx, cy), 7, 1)
        d.circle(s, dimc(col, .5), (cx, cy), 4)
        d.line(s, col, (cx - 4, cy - 4), (cx + 4, cy + 4))
        d.line(s, col, (cx + 4, cy - 4), (cx - 4, cy + 4))
    else:
        d.circle(s, col, (cx, cy), 4, 1)


# ───────────────────────── sound ─────────────────────────
SR = 22050


def tone(freq, dur, vol=.5, wave="sq", slide=0.0):
    n = max(1, int(SR * dur))
    out, ph = [], 0.0
    for i in range(n):
        t = i / n
        if freq <= 0:
            out.append(0)
            continue
        ph += (freq + slide * t) / SR
        x = ph % 1.0
        if wave == "sq":
            v = 1.0 if x < .5 else -1.0
        elif wave == "tri":
            v = 4 * abs(x - .5) - 1
        elif wave == "noise":
            v = random.uniform(-1, 1)
        else:
            v = math.sin(6.2832 * x)
        env = min(1.0, i / 100) * (1 - t) ** .7
        out.append(int(v * vol * env * 26000))
    return out


def arp(notes, dur=.08, vol=.4, wave="sq"):
    r = []
    for f in notes:
        r += tone(f, dur, vol, wave)
    return r


SFX = {
    "click": lambda: tone(1500, .02, .2),
    "key": lambda: tone(1900, .012, .14),
    "ok": lambda: arp([660, 990], .05, .28),
    "deny": lambda: tone(140, .16, .35),
    "coin": lambda: arp([988, 1319, 1760], .05, .3),
    "win": lambda: arp([523, 659, 784, 1047, 1319], .07, .3),
    "lose": lambda: arp([330, 262, 196, 147], .14, .35, "tri"),
    "alarm": lambda: arp([880, 660, 880, 660], .09, .35),
    "scan": lambda: tone(300, .35, .25, "sine", 1500),
    "connect": lambda: arp([392, 523, 659, 784], .08, .3),
    "chat": lambda: tone(1200, .04, .2, "tri") + tone(1600, .05, .2, "tri"),
    "raid": lambda: tone(200, .35, .4, "noise") + arp([220, 180, 140], .1, .4),
    "tick": lambda: tone(2200, .01, .1),
    "buy": lambda: arp([784, 1047], .06, .3),
    "lvup": lambda: arp([523, 659, 784, 1047, 1319, 1568], .07, .3),
    "zero": lambda: tone(100, .45, .4, "sine", 2000) + arp([1047, 1568, 2093], .06, .3),
    "glitch": lambda: tone(80, .14, .4, "noise"),
    "step": lambda: tone(520, .02, .14, "tri"),
    "pipe": lambda: tone(900, .02, .18) + tone(620, .02, .14),
    "lock": lambda: tone(1200, .05, .3) + tone(1800, .09, .3),
    "bump": lambda: tone(90, .06, .3, "tri", -30),
    "hit": lambda: tone(200, .12, .45, "noise") + tone(110, .1, .4, "tri", -60),
    "forge": lambda: arp([220, 330, 440, 550], .05, .35, "tri") + tone(150, .1, .3, "noise"),
    "botnet": lambda: sum(tone(60 + i * 15, .12, .15, "sine") for i in range(4)),
    "job": lambda: arp([660, 880, 1100], .09, .3) + arp([1320, 1760], .12, .25),
    "rank": lambda: arp([523, 659, 784, 1047, 1319, 1568, 2093], .09, .3),
    "build": lambda: tone(400, .03, .15, "tri") + tone(500, .03, .15, "tri") + tone(600, .05, .2, "tri"),
    "ice": lambda: tone(50, .6, .25, "sine", 600) + tone(800, .3, .15, "noise"),
    "daily": lambda: arp([784, 1047, 1319, 1568, 2093, 2637], .05, .28),
    "wire": lambda: tone(1800, .015, .18, "sq") + tone(1400, .02, .12, "tri"),
    "snip": lambda: tone(900, .04, .2, "noise") + tone(200, .05, .15, "sq", -300),
    "zap": lambda: tone(2200, .03, .2, "noise") + tone(400, .1, .3, "sq", -200),
    "snap": lambda: tone(300, .05, .3, "sq") + tone(180, .08, .25, "sq", -50),
}
NOTE = lambda n: 440.0 * 2 ** ((n - 69) / 12.0)
PROG = [(33, (57, 60, 64)), (29, (53, 57, 60)), (31, (55, 59, 62)), (28, (52, 56, 59))]
TRACKS = {
    "menu":   (76, PROG, "slow"),
    "grid":   (104, PROG, "pulse"),
    "breach": (136, PROG, "drive"),
    "forge":  (88, PROG, "clank"),
    "raid":   (120, PROG, "tense"),
}


def render_track(name):
    bpm, prog, style = TRACKS[name]
    beat = 60.0 / bpm
    rnd = random.Random(sum(map(ord, name)))
    bars = 4
    total = int(SR * beat * 4 * bars)
    buf = [0] * (total + SR)

    def put(start, samples):
        for i, v in enumerate(samples):
            if start + i < len(buf):
                buf[start + i] += v

    for bi in range(bars):
        bass, chord = prog[bi % 4]
        b0 = int(SR * beat * 4 * bi)
        pool = list(chord) + [c + 12 for c in chord]
        steps = {"slow": 8, "pulse": 8, "drive": 16, "clank": 8, "tense": 12}.get(style, 8)
        for k in range(steps):
            at = b0 + int(SR * beat * k * 4 / steps)
            if style == "slow":
                if k % 4 == 0:
                    put(at, tone(NOTE(bass), beat * 1.9, .13, "tri"))
                if rnd.random() < .3:
                    put(at, tone(NOTE(rnd.choice(pool)), beat * 1.2, .05, "sine"))
            elif style == "pulse":
                put(at, tone(NOTE(bass + (12 if k % 4 == 3 else 0)), beat * .42, .11, "sq"))
                if k % 2 == 1:
                    put(at, tone(1, beat * .08, .035, "noise"))
                if rnd.random() < .5:
                    put(at, tone(NOTE(rnd.choice(pool)), beat * .4, .05, "tri"))
            elif style == "drive":
                put(at, tone(NOTE(bass), beat * .22, .12, "sq"))
                if k % 2 == 1:
                    put(at, tone(1, beat * .05, .045, "noise"))
                if k % 4 == 0:
                    put(at, tone(NOTE(chord[(k // 4) % 3] + 12), beat * .5, .05, "tri"))
                if rnd.random() < .4:
                    put(at, tone(NOTE(rnd.choice(pool) + 12), beat * .2, .04, "sq"))
            elif style == "clank":
                if k % 2 == 0:
                    put(at, tone(180, beat * .15, .18, "noise"))
                    put(at, tone(880, beat * .12, .08, "tri"))
                if k % 4 == 0:
                    put(at, tone(NOTE(bass - 12), beat * 1.2, .10, "tri"))
                if rnd.random() < .35:
                    put(at, tone(NOTE(rnd.choice(pool) + 24), beat * .18, .04, "sine"))
            elif style == "tense":
                put(at, tone(NOTE(bass), beat * .3, .14, "sq"))
                if k % 3 == 0:
                    put(at, tone(60, beat * .35, .20, "sine", -20))
                if k == 0 or k == steps // 2:
                    put(at, tone(NOTE(chord[0] + 6), beat * .6, .06, "noise"))
        if style == "slow":
            for ct in chord:
                put(b0, tone(NOTE(ct - 12), beat * 3.7, .03, "sine"))
    return array.array("h", [max(-32000, min(32000, v)) for v in buf[:total]])


class Audio:
    def __init__(self, g):
        self.g, self.ok, self.sounds, self.tracks, self.cur, self.want = g, False, {}, {}, None, None
        self.muted = False
        try:
            pygame.mixer.pre_init(SR, -16, 1, 512)
            pygame.mixer.init(SR, -16, 1, 512)
            self.chan = pygame.mixer.Channel(0)
            self.ok = True
        except Exception:
            return
        for k, fn in SFX.items():
            try:
                self.sounds[k] = pygame.mixer.Sound(buffer=array.array("h", fn()).tobytes())
            except Exception:
                pass
        threading.Thread(target=self._build, daemon=True).start()

    def _build(self):
        for name in TRACKS:
            try:
                self.tracks[name] = pygame.mixer.Sound(buffer=render_track(name).tobytes())
            except Exception:
                pass

    def vol(self, kind):
        return 0.0 if self.muted else self.g.cfg.get(kind, 6) / 10.0

    def sfx(self, name, v=1.0):
        s = self.sounds.get(name)
        if self.ok and s is not None and not self.muted:
            s.set_volume(clamp(self.vol("sfx") * v, 0, 1))
            s.play()

    def poll(self):
        if not self.ok:
            return
        if self.want != self.cur and self.want in self.tracks:
            self.cur = self.want
            self.chan.play(self.tracks[self.cur], loops=-1, fade_ms=400)
        self.chan.set_volume(self.vol("music") * .5)


# ───────────────────────── world ─────────────────────────
NTYPES = ["BANK", "CRYPTO", "TELECOM", "MEDIA", "LAB", "DEFENSE", "MILITARY", "AI_CORE", "VOID"]
CORPS = ["Arasaka", "Zetatech", "Omnicorp", "Kiroshi", "Militech", "Synthex", "Nexora", "Voidline",
         "Tyrell", "Cybrix", "Helix", "Ironvault", "Quanta", "Blacknet", "Aurum", "Stratos",
         "Kagemitsu", "Erebus", "Solace", "Zenith", "Noctis", "Cinder", "Lucent", "Mirai",
         "Sable", "Rhex", "Vesper", "Onyx"]
NPCS = ["GLITCH", "VANTA", "ROOK", "SPECTRE", "MIRAGE"]
CANNED = ["gl hf", "who raided my node?!", "nice firewall", "heat's rising...", "ghost in the wire",
          "feds are sniffing", "anyone got spare scrap?", "forging drones all day", "botnet's humming",
          "new PCB layout is clean", "void nodes are sketchy", "AI_CORE go brrr"]
NPC_COL = 8
NODE_MODS = [None, None, None, "TURRETED", "VAULTED", "HAUNTED", "RIFT"]
GRID_W, GRID_H = 7, 4
NODE_EDGES = [
    (0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 6),
    (0, 7), (7, 14), (14, 21), (21, 27),
    (6, 13), (13, 20), (20, 27),
    (3, 10), (10, 17), (17, 24),
    (1, 8), (8, 15), (15, 22),
    (4, 11), (11, 18), (18, 25),
    (2, 9), (9, 16), (16, 23),
    (5, 12), (12, 19), (19, 26),
    (7, 8), (8, 9), (9, 10), (10, 11), (11, 12), (12, 13),
    (14, 15), (15, 16), (16, 17), (17, 18), (18, 19), (19, 20),
    (21, 22), (22, 23), (23, 24), (24, 25), (25, 26), (26, 27),
]
NODE_COUNT = 28


class World:
    def __init__(self):
        d = jload(WORLD_FILE, None)
        ok = isinstance(d, dict) and isinstance(d.get("nodes"), list) and len(d["nodes"]) == NODE_COUNT
        self.nodes = d["nodes"] if ok else self.gen()
        for n in self.nodes:
            n.setdefault("mod", None)
        self.players, self.chat, self.log = {}, [], []
        self.seq, self.npct, self.saved = 0, 6.0, time.time()
        for i, n in enumerate(NPCS):
            self.players["npc%d" % i] = {"n": n, "c": NPC_COL, "cash": 800.0, "fw": i % 3, "t": 0}

    def gen(self):
        r = random.Random(11)
        types = (["BANK", "CRYPTO", "TELECOM", "MEDIA", "LAB", "DEFENSE"] * 4) + \
                ["MILITARY", "AI_CORE", "MILITARY", "VOID"]
        names = CORPS[:NODE_COUNT]
        r.shuffle(types)
        r.shuffle(names)
        out = []
        for i in range(NODE_COUNT):
            is_hq = i == NODE_COUNT - 1
            typ = "AI_CORE" if is_hq else types[i]
            d = r.choice([1, 1, 2, 2, 3, 3, 4, 5])
            mod = None if is_hq else r.choice(NODE_MODS)
            p = d * 3 + r.randint(0, 3)
            if mod == "VAULTED":
                p *= 2
            if typ == "VOID":
                p *= 3
            if is_hq:
                p *= 3
            gx, gy = i % GRID_W, i // GRID_W
            out.append({
                "i": i, "n": names[i], "t": typ, "d": d, "p": p, "o": None, "mod": mod,
                "x": 28 + gx * 68 + r.randint(-4, 4),
                "y": 24 + gy * 84 + r.randint(-4, 4),
            })
        return out

    def pname(self, pid):
        return self.players.get(pid, {}).get("n", "?") if pid else "CORP"

    def addlog(self, txt, victim=None, loss=0):
        self.seq += 1
        self.log = (self.log + [[self.seq, txt, victim, loss]])[-14:]

    def apply(self, pid, m):
        t = m.get("t")
        if t == "stat":
            p = self.players.setdefault(pid, {})
            p.update(n=clean(m.get("n", "?"), 12) or "?", c=int(m.get("c", 0)) % 8,
                     cash=int(m.get("cash", 0)), fw=clamp(int(m.get("fw", 0)), 0, 5), t=time.time())
        elif t == "own" and pid in self.players:
            i = m.get("node")
            if isinstance(i, int) and 0 <= i < len(self.nodes) and self.nodes[i]["o"] != pid:
                nd = self.nodes[i]
                prev, nd["o"] = nd["o"], pid
                self.addlog("%s %s %s" % (self.pname(pid), "raided" if prev else "hacked", nd["n"]),
                            prev, nd["p"] * 20)
        elif t == "chat" and pid in self.players:
            self.chat = (self.chat + [[self.pname(pid), clean(m.get("m", ""), 60)]])[-30:]
        elif t == "bye":
            self.players.pop(pid, None)

    def tick(self, dt):
        for k, p in self.players.items():
            if k.startswith("npc"):
                p["cash"] += sum(n["p"] for n in self.nodes if n["o"] == k) * dt
        if time.time() - self.saved > 15:
            self.saved = time.time()
            jsave(WORLD_FILE, {"nodes": self.nodes})
        for nd in self.nodes:
            if nd.get("mod") == "RIFT" and random.random() < dt * 0.08:
                if nd["o"] is not None:
                    nd["o"] = None
                    self.addlog("RIFT destabilized: %s" % nd["n"])
        self.npct -= dt
        if self.npct > 0:
            return
        self.npct = random.uniform(8, 20)
        k = random.choice([p for p in self.players if p.startswith("npc")])
        r, free = random.random(), [n for n in self.nodes if n["o"] is None]
        if free and r < .45:
            nd = random.choice(free)
            nd["o"] = k
            self.addlog("%s hacked %s" % (self.pname(k), nd["n"]))
        elif r < .88:
            tg = [n for n in self.nodes if n["o"] and n["o"] != k]
            if tg:
                nd = random.choice(tg)
                v = nd["o"]
                fw = self.players.get(v, {}).get("fw", 0)
                if nd.get("mod") == "TURRETED":
                    fw += 2
                if random.random() < .55 - .1 * fw:
                    nd["o"] = k
                    self.addlog("%s raided %s" % (self.pname(k), nd["n"]), v, nd["p"] * 20)
                else:
                    self.addlog("%s's raid on %s blocked" % (self.pname(k), nd["n"]))
        else:
            self.chat = (self.chat + [[self.pname(k), random.choice(CANNED)]])[-30:]

    def snapshot(self):
        now, pl = time.time(), {}
        for k, p in self.players.items():
            if k.startswith("npc") or now - p.get("t", 0) < 15:
                pl[k] = {"n": p.get("n", "?"), "c": p.get("c", 0), "cash": int(p.get("cash", 0)),
                         "fw": p.get("fw", 0),
                         "nn": sum(1 for n in self.nodes if n["o"] == k)}
        return {"nodes": self.nodes, "players": pl, "chat": self.chat, "log": self.log, "seq": self.seq}


# ───────────────────────── networking ─────────────────────────
class Net:
    def __init__(self, pid, mode, host=None, name="RUNNER"):
        self.pid, self.mode, self.host, self.name = pid, mode, host, name
        self.q, self.clients, self.alive, self.world = queue.Queue(), {}, True, None
        self.sock = self.srv = None
        self.t, self.ip = 0.0, local_ip()
        self.state = {"nodes": [], "players": {}, "chat": [], "log": [], "seq": 0}
        if mode in ("solo", "host"):
            self.world = World()
            self.state = self.world.snapshot()
        if mode == "host":
            self.srv = socket.socket()
            self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.srv.bind(("", TCP_PORT))
            self.srv.listen(8)
            threading.Thread(target=self._accept, daemon=True).start()
            threading.Thread(target=self._beacon, daemon=True).start()
        elif mode == "client":
            h, _, p = host.partition(":")
            self.sock = socket.create_connection((h, int(p) if p else TCP_PORT), timeout=4)
            self.sock.settimeout(2.0)
            self.sock.sendall((json.dumps({"t": "hello", "id": self.pid}) + "\n").encode())
            threading.Thread(target=self._client_read, daemon=True).start()

    def _read(self, c, cb):
        buf = b""
        while self.alive:
            try:
                d = c.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                return
            if not d:
                return
            buf += d
            if len(buf) > 1 << 20:
                return
            while b"\n" in buf:
                ln, buf = buf.split(b"\n", 1)
                try:
                    cb(json.loads(ln))
                except Exception:
                    pass

    def _client_read(self):
        self._read(self.sock, self.q.put)
        self.alive = False

    def _accept(self):
        while self.alive:
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            c.settimeout(2.0)
            threading.Thread(target=self._serve, args=(c,), daemon=True).start()

    def _serve(self, c):
        box = [None]

        def got(m):
            if box[0] is None:
                if m.get("t") == "hello":
                    box[0] = clean(m.get("id", ""), 16) or uuid.uuid4().hex[:8]
                    self.clients[box[0]] = c
            else:
                self.q.put((box[0], m))

        self._read(c, got)
        if box[0]:
            self.clients.pop(box[0], None)
            self.q.put((box[0], {"t": "bye"}))
        try:
            c.close()
        except OSError:
            pass

    def _beacon(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        while self.alive:
            try:
                s.sendto(("NRB1|%s|%d" % (self.name, len(self.state["players"]))).encode(),
                         ("255.255.255.255", UDP_PORT))
            except OSError:
                pass
            time.sleep(1.5)

    def send(self, m):
        if self.world:
            self.q.put((self.pid, m))
        else:
            try:
                self.sock.sendall((json.dumps(m) + "\n").encode())
            except OSError:
                self.alive = False

    def update(self, dt):
        self.t += dt
        if self.world:
            while True:
                try:
                    pid, m = self.q.get_nowait()
                except queue.Empty:
                    break
                try:
                    self.world.apply(pid, m)
                except Exception:
                    pass
            self.world.tick(dt)
            self.state = self.world.snapshot()
            if self.mode == "host" and self.t >= .5:
                self.t = 0
                data = (json.dumps(self.state) + "\n").encode()
                for pid, c in list(self.clients.items()):
                    try:
                        c.sendall(data)
                    except OSError:
                        self.clients.pop(pid, None)
        else:
            while True:
                try:
                    self.state = self.q.get_nowait()
                except queue.Empty:
                    break

    def close(self):
        self.alive = False
        if self.world:
            jsave(WORLD_FILE, {"nodes": self.world.nodes})
        for s in [self.sock, self.srv] + list(self.clients.values()):
            try:
                s.close()
            except Exception:
                pass


class Discover:
    def __init__(self):
        self.hosts = {}
        try:
            self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.s.bind(("", UDP_PORT))
            self.s.setblocking(False)
        except OSError:
            self.s = None

    def poll(self):
        if not self.s:
            return
        for _ in range(20):
            try:
                d, a = self.s.recvfrom(256)
            except OSError:
                break
            p = d.decode("ascii", "ignore").split("|")
            if len(p) == 3 and p[0] == "NRB1":
                self.hosts[a[0]] = (clean(p[1], 12), clean(p[2], 3), time.time())
        for k in [k for k, v in self.hosts.items() if time.time() - v[2] > 5]:
            del self.hosts[k]

    def close(self):
        if self.s:
            self.s.close()


# ───────────────────────── mini-games ─────────────────────────
class Mini:
    title = hint = ""

    def __init__(self, d, g):
        self.d, self.g, self.t, self.done = d, g, 0.0, None

    def update(self, dt):
        self.t += dt

    def key(self, e):
        pass

    def click(self, p):
        pass

    def release(self, p):
        pass

    def rclick(self, p):
        pass

    def draw(self, sc):
        pass


CPAL = [RED, AMBER, GREEN, CYAN, MAG, WHITE]


class Cipher(Mini):
    title = "CIPHER"
    hint = "Crack the 4-peg code (click colours). GREEN = right spot, AMBER = wrong spot."

    def __init__(self, d, g):
        super().__init__(d, g)
        self.k = 5 if d < 4 else 6
        self.code = [random.randrange(self.k) for _ in range(4)]
        self.tries, self.rows, self.cur = 10 - d // 2, [], []
        self.pal = [pygame.Rect(460 + (j % 3) * 56, 112 + (j // 3) * 56, 44, 44) for j in range(self.k)]
        self.rdel, self.rok = pygame.Rect(460, 236, 80, 32), pygame.Rect(552, 236, 80, 32)

    def add(self, c):
        if len(self.cur) < 4:
            self.cur.append(c)
            self.g.audio.sfx("key")

    def submit(self):
        if len(self.cur) < 4:
            return
        ex = sum(a == b for a, b in zip(self.cur, self.code))
        cc = sum(min(self.cur.count(c), self.code.count(c)) for c in range(self.k))
        self.rows.append((self.cur, ex, cc - ex))
        self.cur = []
        if ex == 4:
            self.done = True
        elif len(self.rows) >= self.tries:
            self.done = False
        else:
            self.g.audio.sfx("ok")

    def key(self, e):
        if pygame.K_1 <= e.key < pygame.K_1 + self.k:
            self.add(e.key - pygame.K_1)
        elif e.key == pygame.K_BACKSPACE:
            self.cur = self.cur[:-1]
        elif e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self.submit()

    def click(self, p):
        for j, r in enumerate(self.pal):
            if r.collidepoint(p):
                self.add(j)
        if self.rdel.collidepoint(p):
            self.cur = self.cur[:-1]
        if self.rok.collidepoint(p):
            self.submit()

    def draw(self, sc):
        for i in range(self.tries):
            y = 60 + i * 32
            act = i == len(self.rows)
            pygame.draw.rect(sc, (14, 26, 30), (80, y, 200, 28))
            pygame.draw.rect(sc, CYAN if act else DGREEN, (80, y, 200, 28), 1)
            row = self.rows[i] if i < len(self.rows) else (self.cur if act else [], 0, 0)
            for j, c in enumerate(row[0]):
                pygame.draw.circle(sc, CPAL[c], (100 + j * 32, y + 14), 10)
                pygame.draw.circle(sc, dimc(CPAL[c], .5), (100 + j * 32, y + 14), 4)
            if i < len(self.rows):
                for k in range(4):
                    col = GREEN if k < row[1] else AMBER if k < row[1] + row[2] else DIM
                    pygame.draw.rect(sc, col, (220 + k * 14, y + 10, 8, 8))
        for j, r in enumerate(self.pal):
            pygame.draw.rect(sc, CPAL[j], r)
            pygame.draw.rect(sc, WHITE, r, 1)
            text(sc, str(j + 1), r.centerx, r.y + 12, BLACK, 16, "c", False)
        for r, lb in ((self.rdel, "DEL"), (self.rok, "TRY")):
            pygame.draw.rect(sc, BORDER, r, 1)
            ctext(sc, lb, r, GREEN, 14)
        text(sc, "TRIES LEFT %d" % (self.tries - len(self.rows)), 460, 80, MID, 14)


D4 = [(-1, 0), (0, 1), (1, 0), (0, -1)]


class Pipes(Mini):
    title = "PIPES"
    hint = "Click tiles to rotate. Connect SRC to ROOT before trace finishes."

    def __init__(self, d, g):
        super().__init__(d, g)
        n = self.n = 4 + (d >= 3) + (d >= 5)
        self.time, self.cs, self.ox, self.oy = 44 - d * 3, 48, (W - n * 48) // 2, 76
        self.r0 = r = random.randrange(n)
        path = []
        for c in range(n):
            path.append((r, c))
            r2 = random.randrange(n)
            while r != r2:
                r += 1 if r2 > r else -1
                path.append((r, c))
        self.rend = r
        self.m = [[random.choice((7, 14, 13, 11, 5, 10, 3, 6, 12, 9)) for _ in range(n)] for _ in range(n)]
        for i, (r, c) in enumerate(path):
            a = path[i - 1] if i else (r, c - 1)
            b = path[i + 1] if i + 1 < len(path) else (r, c + 1)
            self.m[r][c] = sum(1 << D4.index((q[0] - r, q[1] - c)) for q in (a, b))
        for r in range(n):
            for c in range(n):
                for _ in range(random.randrange(4)):
                    self.rot(r, c)
        while self.solved():
            self.rot(self.r0, 0)

    def rot(self, r, c):
        m = self.m[r][c]
        self.m[r][c] = ((m << 1) | (m >> 3)) & 15

    def flow(self):
        seen = set()
        if self.m[self.r0][0] & 8:
            st = [(self.r0, 0)]
            seen.add(st[0])
            while st:
                r, c = st.pop()
                for i, (dr, dc) in enumerate(D4):
                    if self.m[r][c] >> i & 1:
                        nr, nc = r + dr, c + dc
                        if 0 <= nr < self.n and 0 <= nc < self.n and (nr, nc) not in seen \
                                and self.m[nr][nc] >> ((i + 2) % 4) & 1:
                            seen.add((nr, nc))
                            st.append((nr, nc))
        return seen

    def solved(self):
        return (self.rend, self.n - 1) in self.flow() and self.m[self.rend][self.n - 1] & 2

    def update(self, dt):
        super().update(dt)
        if self.t > self.time:
            self.done = False

    def click(self, p):
        c, r = (p[0] - self.ox) // self.cs, (p[1] - self.oy) // self.cs
        if 0 <= r < self.n and 0 <= c < self.n:
            self.rot(r, c)
            self.g.audio.sfx("pipe")
            if self.solved():
                self.done = True

    def draw(self, sc):
        fl, cs = self.flow(), self.cs
        for r in range(self.n):
            for c in range(self.n):
                x, y = self.ox + c * cs, self.oy + r * cs
                rr = pygame.Rect(x + 1, y + 1, cs - 2, cs - 2)
                pygame.draw.rect(sc, (12, 24, 28), rr)
                pygame.draw.rect(sc, DGREEN, rr, 1)
                col, cx, cy = (GREEN if (r, c) in fl else MID), x + cs // 2, y + cs // 2
                for i, (dr, dc) in enumerate(D4):
                    if self.m[r][c] >> i & 1:
                        pygame.draw.line(sc, col, (cx, cy),
                                         (cx + dc * cs // 2, cy + dr * cs // 2), 3)
                pygame.draw.circle(sc, col, (cx, cy), 2)
        text(sc, "SRC>", self.ox - 6, self.oy + self.r0 * cs + 16, CYAN, 12, "r")
        text(sc, ">ROOT", self.ox + self.n * cs + 6, self.oy + self.rend * cs + 16, MAG, 12)


class Lock(Mini):
    title = "LOCK"
    hint = "Tap or SPACE when needle is inside window. 3 hits to crack."

    def __init__(self, d, g):
        super().__init__(d, g)
        self.x0, self.w, self.ww = 88, 592, max(32, 128 - d * 14)
        self.nx, self.nd, self.sp = 0.0, 1, 220 + d * 56
        self.hits, self.lives, self.ph, self.flash, self.fc = 0, 3, random.random() * 6, 0.0, GREEN

    def wc(self):
        return self.x0 + self.w / 2 + (self.w / 2 - self.ww / 2 - 8) * math.sin(self.t * (1.1 + self.d * .12) + self.ph)

    def update(self, dt):
        super().update(dt)
        self.nx += self.nd * self.sp * dt
        if self.nx > self.w:
            self.nx, self.nd = self.w, -1
        if self.nx < 0:
            self.nx, self.nd = 0, 1
        self.flash = max(0, self.flash - dt)

    def lock(self):
        self.flash = .25
        if abs(self.x0 + self.nx - self.wc()) <= self.ww / 2:
            self.hits += 1
            self.sp *= 1.12
            self.fc = GREEN
            self.g.audio.sfx("lock")
            if self.hits >= 3:
                self.done = True
        else:
            self.lives -= 1
            self.fc = RED
            self.g.audio.sfx("deny")
            if self.lives <= 0:
                self.done = False

    def key(self, e):
        if e.key == pygame.K_SPACE:
            self.lock()

    def click(self, p):
        self.lock()

    def draw(self, sc):
        pygame.draw.rect(sc, (12, 24, 28), (self.x0, 196, self.w, 44))
        pygame.draw.rect(sc, self.fc if self.flash else BORDER, (self.x0, 196, self.w, 44), 1)
        pygame.draw.rect(sc, DGREEN, (int(self.wc() - self.ww / 2), 200, self.ww, 36))
        pygame.draw.rect(sc, GREEN, (int(self.wc() - self.ww / 2), 200, self.ww, 36), 1)
        nx = int(self.x0 + self.nx)
        pygame.draw.line(sc, WHITE, (nx, 184), (nx, 252), 4)
        text(sc, "DECRYPT (TAP TO LOCK)", W // 2, 120, CYAN, 16, "c")
        for i in range(3):
            pygame.draw.rect(sc, GREEN if i < self.hits else DGREEN, (300 + i * 60, 280, 44, 16))
            pygame.draw.circle(sc, RED if i < self.lives else DGREEN, (310 + i * 60, 320), 10)


class Ice(Mini):
    title = "ICE"
    hint = "Use on-screen D-Pad or Arrow keys to reach ROOT. Avoid ICE."

    def __init__(self, d, g):
        super().__init__(d, g)
        C, R = self.C, self.R = 21, 11
        self.ox, self.oy, self.time = 48, 56, 55
        self.m = [[1] * C for _ in range(R)]
        self.m[1][1] = 0
        st = [(1, 1)]
        while st:
            x, y = st[-1]
            nb = [(x + dx * 2, y + dy * 2, dx, dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                  if 0 < x + dx * 2 < C - 1 and 0 < y + dy * 2 < R - 1 and self.m[y + dy * 2][x + dx * 2]]
            if nb:
                nx, ny, dx, dy = random.choice(nb)
                self.m[y + dy][x + dx] = self.m[ny][nx] = 0
                st.append((nx, ny))
            else:
                st.pop()
        for _ in range(20):
            x, y = random.randrange(1, C - 1), random.randrange(1, R - 1)
            if self.m[y][x] and ((x % 2 == 0) != (y % 2 == 0)):
                self.m[y][x] = 0
        self.p, self.goal, self.cd = [1, 1], (19, 9), 0.0
        floor = [(x, y) for y in range(R) for x in range(C) if not self.m[y][x] and x + y > 12]
        self.ice = [[*random.choice(floor), 1, 0, 1.0] for _ in range(min(5, 2 + d // 2))]
        self.btn_up = pygame.Rect(620, 280, 60, 40)
        self.btn_down = pygame.Rect(620, 360, 60, 40)
        self.btn_left = pygame.Rect(556, 320, 60, 40)
        self.btn_right = pygame.Rect(684, 320, 60, 40)

    def move_player(self, dx, dy):
        if self.cd <= 0:
            nx, ny = self.p[0] + dx, self.p[1] + dy
            if not self.m[ny][nx]:
                self.p, self.cd = [nx, ny], .09
                self.g.audio.sfx("step", .6)
            else:
                self.cd = .15
                self.g.audio.sfx("bump", .6)

    def move_ice(self, e):
        e[4] = max(.16, .36 - self.d * .03)
        opts = [o for o in ((1, 0), (-1, 0), (0, 1), (0, -1)) if not self.m[e[1] + o[1]][e[0] + o[0]]]
        if len(opts) > 1:
            opts = [o for o in opts if o != (-e[2], -e[3])] or opts
        if abs(e[0] - self.p[0]) + abs(e[1] - self.p[1]) < 7 and random.random() < .5:
            o = min(opts, key=lambda o: abs(e[0] + o[0] - self.p[0]) + abs(e[1] + o[1] - self.p[1]))
        else:
            o = random.choice(opts)
        e[0] += o[0]
        e[1] += o[1]
        e[2], e[3] = o

    def update(self, dt):
        super().update(dt)
        if self.t > self.time:
            self.done = False
            return
        self.cd -= dt
        k = pygame.key.get_pressed()
        dx = (k[pygame.K_RIGHT] or k[pygame.K_d]) - (k[pygame.K_LEFT] or k[pygame.K_a])
        dy = (k[pygame.K_DOWN] or k[pygame.K_s]) - (k[pygame.K_UP] or k[pygame.K_w])
        if dx or dy:
            if dx:
                dy = 0
            self.move_player(dx, dy)
        for e in self.ice:
            e[4] -= dt
            if e[4] <= 0:
                self.move_ice(e)
        if any((e[0], e[1]) == tuple(self.p) for e in self.ice):
            self.g.audio.sfx("hit")
            self.done = False
        elif tuple(self.p) == self.goal:
            self.done = True

    def click(self, p):
        if self.btn_up.collidepoint(p):
            self.move_player(0, -1)
        elif self.btn_down.collidepoint(p):
            self.move_player(0, 1)
        elif self.btn_left.collidepoint(p):
            self.move_player(-1, 0)
        elif self.btn_right.collidepoint(p):
            self.move_player(1, 0)

    def draw(self, sc):
        T, ox, oy = 32, self.ox, self.oy
        for y in range(self.R):
            for x in range(self.C):
                if self.m[y][x]:
                    rr = pygame.Rect(ox + x * T, oy + y * T, T, T)
                    pygame.draw.rect(sc, (16, 48, 44), rr)
                    pygame.draw.rect(sc, DGREEN, rr, 1)
        gx, gy = ox + self.goal[0] * T, oy + self.goal[1] * T
        pygame.draw.rect(sc, lerpc(DGREEN, GREEN, .5 + .5 * math.sin(self.t * 6)),
                         (gx + 4, gy + 4, T - 8, T - 8))
        for e in self.ice:
            cx, cy = ox + e[0] * T + T // 2, oy + e[1] * T + T // 2
            r = 12 + int(math.sin(self.t * 8) * 2)
            pygame.draw.polygon(sc, RED, [(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)])
            pygame.draw.circle(sc, dimc(RED, .5), (cx, cy), 2)
        pygame.draw.rect(sc, CYAN, (ox + self.p[0] * T + 6, oy + self.p[1] * T + 6, T - 12, T - 12))
        for r, lbl in ((self.btn_up, "U"), (self.btn_down, "D"), (self.btn_left, "L"), (self.btn_right, "R")):
            pygame.draw.rect(sc, PANEL, r)
            pygame.draw.rect(sc, BORDER, r, 1)
            ctext(sc, lbl, r, GREEN, 16)


class Trace(Mini):
    title = "TRACE"
    hint = "Collect yellow packets. Avoid red trace lines. Survive 18s."

    def __init__(self, d, g):
        super().__init__(d, g)
        self.time = 18.0
        self.p = [W // 2, H // 2 + 20]
        self.packets = []
        self.trails = []
        self.cd = 0.0
        self.spawn_t = 0.0
        self.got = 0
        self.need = 4 + d
        self.joy = pygame.Rect(48, 300, 160, 100)
        self.joy_knob = [self.joy.centerx, self.joy.centery]
        self.joy_active = False
        self.speed = 180

    def update(self, dt):
        super().update(dt)
        self.cd -= dt
        self.spawn_t -= dt
        if self.t > self.time:
            self.done = self.got >= self.need
            return
        k = pygame.key.get_pressed()
        dx = (k[pygame.K_RIGHT] or k[pygame.K_d]) - (k[pygame.K_LEFT] or k[pygame.K_a])
        dy = (k[pygame.K_DOWN] or k[pygame.K_s]) - (k[pygame.K_UP] or k[pygame.K_w])
        if self.joy_active:
            cx, cy = self.joy.center
            vx = clamp((self.joy_knob[0] - cx) / 60.0, -1, 1)
            vy = clamp((self.joy_knob[1] - cy) / 40.0, -1, 1)
            if abs(vx) > .15:
                dx = vx
            if abs(vy) > .15:
                dy = vy
        n = math.hypot(dx, dy) or 1
        self.p[0] += dx / n * self.speed * dt
        self.p[1] += dy / n * self.speed * dt
        self.p[0] = clamp(self.p[0], 20, W - 20)
        self.p[1] = clamp(self.p[1], 60, H - 60)
        if self.spawn_t <= 0:
            self.spawn_t = 0.9
            self.packets.append([random.uniform(40, W - 40), random.uniform(72, H - 80), random.uniform(0, 6.28)])
        for pk in list(self.packets):
            pk[2] += dt * 6
            if math.hypot(pk[0] - self.p[0], pk[1] - self.p[1]) < 18:
                self.packets.remove(pk)
                self.got += 1
                self.g.audio.sfx("coin", .5)
                if self.got >= self.need:
                    self.done = True
                    return
        if self.cd <= 0:
            self.cd = 0.9 - self.d * .06
            side = random.randrange(4)
            if side == 0:
                x, y, vx, vy = 0, random.uniform(60, H - 60), 1, 0
            elif side == 1:
                x, y, vx, vy = W, random.uniform(60, H - 60), -1, 0
            elif side == 2:
                x, y, vx, vy = random.uniform(40, W - 40), 52, 0, 1
            else:
                x, y, vx, vy = random.uniform(40, W - 40), H, 0, -1
            self.trails.append([x, y, vx, vy, 0])
        for tr in list(self.trails):
            tr[0] += tr[2] * (160 + self.d * 24) * dt
            tr[1] += tr[3] * (160 + self.d * 24) * dt
            tr[4] += dt
            if tr[4] > 8 or tr[0] < -40 or tr[0] > W + 40 or tr[1] < 20 or tr[1] > H + 40:
                self.trails.remove(tr)
            elif math.hypot(tr[0] - self.p[0], tr[1] - self.p[1]) < 16:
                self.g.audio.sfx("hit")
                self.done = False
                return

    def click(self, p):
        if self.joy.collidepoint(p):
            self.joy_active = True
            self.joy_knob = [p[0], p[1]]
        if self.joy_active:
            self.joy_knob = [clamp(p[0], self.joy.left, self.joy.right),
                             clamp(p[1], self.joy.top, self.joy.bottom)]

    def release(self, p):
        self.joy_active = False

    def draw(self, sc):
        for gx in range(0, W, 48):
            pygame.draw.line(sc, (12, 28, 26), (gx, 52), (gx, H), 1)
        for gy in range(56, H, 48):
            pygame.draw.line(sc, (12, 28, 26), (0, gy), (W, gy), 1)
        for pk in self.packets:
            r = 8 + math.sin(pk[2]) * 4
            pygame.draw.circle(sc, AMBER, (int(pk[0]), int(pk[1])), int(r))
            pygame.draw.circle(sc, WHITE, (int(pk[0]), int(pk[1])), int(r), 1)
            pygame.draw.circle(sc, dimc(AMBER, .5), (int(pk[0]), int(pk[1])), int(r * .4))
        for tr in self.trails:
            cx, cy = int(tr[0]), int(tr[1])
            pygame.draw.circle(sc, RED, (cx, cy), 12)
            pygame.draw.line(sc, RED, (int(tr[0] - tr[2] * 20), int(tr[1] - tr[3] * 20)),
                             (cx, cy), 4)
        px, py = int(self.p[0]), int(self.p[1])
        pygame.draw.circle(sc, CYAN, (px, py), 12)
        pygame.draw.circle(sc, WHITE, (px, py), 12, 1)
        pygame.draw.circle(sc, dimc(CYAN, .4), (px, py), 5)
        text(sc, "PACKETS %d/%d" % (self.got, self.need), 80, 60, AMBER, 12)
        text(sc, "TIME %.1f" % max(0, self.time - self.t), W - 160, 60, CYAN, 12)
        pygame.draw.rect(sc, (16, 30, 30), self.joy)
        pygame.draw.rect(sc, BORDER, self.joy, 1)
        pygame.draw.circle(sc, DGREEN, (int(self.joy_knob[0]), int(self.joy_knob[1])), 16)
        pygame.draw.circle(sc, GREEN, (int(self.joy_knob[0]), int(self.joy_knob[1])), 16, 1)


class Sequence(Mini):
    title = "SEQUENCE"
    hint = "Watch the pattern, then repeat it. 3 rounds."

    def __init__(self, d, g):
        super().__init__(d, g)
        self.pads = [pygame.Rect(240 + (i % 2) * 160, 120 + (i // 2) * 120, 120, 100) for i in range(4)]
        self.pad_c = [GREEN, CYAN, MAG, AMBER]
        self.rounds = 0
        self.max_rounds = 3
        self.seq = []
        self.idx = 0
        self.phase = "show"
        self.show_t = 0.0
        self.show_i = 0
        self.wait_t = 0.7

    def update(self, dt):
        super().update(dt)
        if self.phase == "show":
            self.show_t -= dt
            if self.show_t <= 0:
                if self.show_i < len(self.seq):
                    self.g.audio.sfx("tick")
                    self.show_i += 1
                    self.show_t = 0.55
                else:
                    self.phase = "input"
                    self.idx = 0
        elif self.phase == "wait":
            self.wait_t -= dt
            if self.wait_t <= 0:
                self.rounds += 1
                if self.rounds >= self.max_rounds:
                    self.done = True
                    return
                self.seq = [random.randrange(4) for _ in range(3 + self.rounds)]
                self.phase = "show"
                self.show_t = 0.4
                self.show_i = 0

    def start(self):
        self.seq = [random.randrange(4) for _ in range(3 + self.rounds)]
        self.phase = "show"
        self.show_t = 0.5
        self.show_i = 0

    def press(self, i):
        if self.phase != "input":
            return
        if i == self.seq[self.idx]:
            self.g.audio.sfx("ok", .7)
            self.idx += 1
            if self.idx >= len(self.seq):
                self.phase = "wait"
                self.wait_t = 0.7
        else:
            self.g.audio.sfx("deny")
            self.done = False

    def click(self, p):
        for i, r in enumerate(self.pads):
            if r.collidepoint(p):
                self.press(i)

    def draw(self, sc):
        if not self.seq and self.phase != "wait":
            if self.phase == "show":
                self.start()
        text(sc, "ROUND %d/%d" % (min(self.rounds + 1, self.max_rounds), self.max_rounds),
             W // 2, 72, CYAN, 16, "c")
        for i, r in enumerate(self.pads):
            on = False
            if self.phase == "show" and self.show_i > 0 and self.seq[self.show_i - 1] == i:
                on = int(self.t * 10) % 2 == 0
            col = self.pad_c[i] if on else dimc(self.pad_c[i], .35)
            pygame.draw.rect(sc, col, r)
            pygame.draw.rect(sc, self.pad_c[i], r, 1)
        if self.phase == "input":
            text(sc, "REPEAT (%d/%d)" % (self.idx, len(self.seq)), W // 2, 348, GREEN, 12, "c")


VECTORS = [("CIPHER", Cipher), ("PIPES", Pipes), ("LOCK", Lock), ("ICE", Ice),
           ("TRACE", Trace), ("SEQUENCE", Sequence)]

TABS = ["net", "shop", "rig", "forge", "botnet", "jobs", "ranks", "chat", "sys",
        "data", "market", "study"]
TABN = ["NET", "SHOP", "RIG", "FORGE", "BOT", "JOBS", "RANK", "CHAT", "SYS",
        "DATA", "MKT", "STUDY"]

# ───────────────────────── hardware & PCB forge ─────────────────────────
PART_DEFS = {
    "BAT":  {"label": "BATTERY",  "col": RED,   "role": "power",  "pins": 2},
    "CPU":  {"label": "CPU",      "col": CYAN,  "role": "data",   "pins": 4},
    "MEM":  {"label": "MEM",      "col": CYAN,  "role": "data",   "pins": 2},
    "WIFI": {"label": "WIFI",     "col": AMBER, "role": "signal", "pins": 2},
    "CELL": {"label": "CELL",     "col": AMBER, "role": "signal", "pins": 2},
    "CAM":  {"label": "CAM",      "col": AMBER, "role": "signal", "pins": 1},
    "FLY":  {"label": "ROTOR",    "col": MAG,   "role": "output", "pins": 2},
    "DISP": {"label": "DISPLAY",  "col": GREEN, "role": "output", "pins": 2},
    "DISK": {"label": "DISK",     "col": CYAN,  "role": "data",   "pins": 2},
    "PWR":  {"label": "PWR-AMP",  "col": RED,   "role": "power",  "pins": 3},
    "QBT":  {"label": "QUBIT",    "col": VIOLET,"role": "data",   "pins": 2},
}

BOARD_W, BOARD_H = 40, 24
CELL = 18

HARDWARE = {
    "phone": {
        "label": "PHONE", "cost": 120, "scrap": 4, "time": 6, "tech": 0,
        "desc": "+0.3 income. Cheap bot.",
        "parts": [("BAT", 4, 10), ("CPU", 14, 10), ("MEM", 14, 16), ("DISP", 24, 10), ("CELL", 24, 16)],
        "wires": [((4, 10), (14, 10)), ((14, 10), (24, 10)), ((14, 10), (14, 16)), ((14, 10), (24, 16))],
    },
    "tablet": {
        "label": "TABLET", "cost": 340, "scrap": 10, "time": 10, "tech": 1,
        "desc": "+0.8 income, +1 scan speed.",
        "parts": [("BAT", 4, 6), ("CPU", 14, 6), ("MEM", 14, 12), ("DISK", 14, 18),
                  ("DISP", 24, 6), ("WIFI", 24, 12)],
        "wires": [((4, 6), (14, 6)), ((14, 6), (14, 12)), ((14, 12), (14, 18)),
                  ((14, 6), (24, 6)), ((14, 12), (24, 12))],
    },
    "pcb_scanner": {
        "label": "SCANNER", "cost": 220, "scrap": 6, "time": 8, "tech": 1,
        "desc": "+0.5 income, reveals 1 node's owner passively.",
        "parts": [("BAT", 4, 12), ("CPU", 14, 12), ("WIFI", 24, 8), ("CAM", 30, 8),
                  ("MEM", 24, 18), ("DISP", 30, 18)],
        "wires": [((4, 12), (14, 12)), ((14, 12), (24, 8)), ((14, 12), (24, 18)), ((24, 8), (30, 8)),
                  ((24, 18), (30, 18)), ((24, 8), (24, 18))],
    },
    "drone": {
        "label": "DRONE", "cost": 780, "scrap": 20, "time": 16, "tech": 2,
        "desc": "+2 income, raid bonus.",
        "parts": [("BAT", 4, 10), ("PWR", 10, 10), ("CPU", 18, 10), ("WIFI", 28, 6),
                  ("CAM", 28, 14), ("FLY", 18, 18)],
        "wires": [((4, 10), (10, 10)), ((10, 10), (18, 10)), ((18, 10), (28, 6)),
                  ((18, 10), (28, 14)), ((18, 10), (18, 18))],
    },
    "relay_pylon": {
        "label": "RELAY", "cost": 520, "scrap": 14, "time": 12, "tech": 2,
        "desc": "+1.2 income. Reduces heat gain by 10%.",
        "parts": [("BAT", 4, 18), ("PWR", 10, 18), ("CPU", 18, 12), ("WIFI", 28, 6),
                  ("CELL", 28, 14), ("FLY", 18, 18), ("DISP", 34, 14)],
        "wires": [((4, 18), (10, 18)), ((10, 18), (18, 12)), ((18, 12), (28, 6)), ((18, 12), (28, 14)),
                  ((18, 12), (18, 18)), ((28, 14), (34, 14)), ((10, 18), (18, 18))],
    },
    "server": {
        "label": "SERVER", "cost": 1600, "scrap": 40, "time": 26, "tech": 3,
        "desc": "+6 income, +1 firewall.",
        "parts": [("BAT", 4, 6), ("PWR", 10, 6), ("CPU", 18, 6), ("MEM", 18, 12),
                  ("DISK", 18, 18), ("WIFI", 28, 6), ("DISP", 28, 12)],
        "wires": [((4, 6), (10, 6)), ((10, 6), (18, 6)), ((18, 6), (18, 12)), ((18, 12), (18, 18)),
                  ((18, 6), (28, 6)), ((18, 12), (28, 12))],
    },
    "brute_rig": {
        "label": "BRUTE RIG", "cost": 1400, "scrap": 30, "time": 20, "tech": 3,
        "desc": "+4 income. +1 permanent raid success chance.",
        "parts": [("BAT", 4, 6), ("BAT", 4, 18), ("PWR", 10, 12), ("CPU", 18, 8),
                  ("MEM", 18, 16), ("QBT", 26, 12), ("DISK", 32, 8), ("WIFI", 34, 18),
                  ("FLY", 32, 18)],
        "wires": [((4, 6), (10, 12)), ((4, 18), (10, 12)), ((10, 12), (18, 8)), ((10, 12), (18, 16)),
                  ((18, 8), (26, 12)), ((18, 16), (26, 12)), ((26, 12), (32, 8)), ((26, 12), (34, 18)),
                  ((26, 12), (32, 18)), ((18, 8), (32, 8)), ((18, 16), (32, 18))],
    },
    "ghost_node": {
        "label": "GHOST NODE", "cost": 2600, "scrap": 55, "time": 32, "tech": 4,
        "desc": "+8 income. Nodes you own are 50% harder to raid.",
        "parts": [("BAT", 4, 12), ("PWR", 10, 12), ("CPU", 18, 6), ("CPU", 18, 18),
                  ("QBT", 26, 12), ("MEM", 32, 6), ("DISK", 32, 18), ("WIFI", 36, 12),
                  ("CAM", 10, 18)],
        "wires": [((4, 12), (10, 12)), ((10, 12), (18, 6)), ((10, 12), (18, 18)), ((18, 6), (26, 12)),
                  ((18, 18), (26, 12)), ((26, 12), (32, 6)), ((26, 12), (32, 18)), ((26, 12), (36, 12)),
                  ((10, 12), (10, 18)), ((26, 12), (36, 12))],
    },
    "quantum": {
        "label": "QUANTUM", "cost": 3600, "scrap": 80, "time": 40, "tech": 5,
        "desc": "+18 income, chance of free zero-day.",
        "parts": [("BAT", 4, 12), ("PWR", 10, 12), ("QBT", 18, 12), ("CPU", 26, 12),
                  ("MEM", 26, 18), ("WIFI", 34, 6), ("DISP", 34, 12), ("FLY", 34, 18)],
        "wires": [((4, 12), (10, 12)), ((10, 12), (18, 12)), ((18, 12), (26, 12)),
                  ((26, 12), (26, 18)), ((26, 12), (34, 6)), ((26, 12), (34, 12)), ((26, 12), (34, 18))],
    },
    "void_core": {
        "label": "VOID CORE", "cost": 4800, "scrap": 100, "time": 50, "tech": 6,
        "desc": "+30 income. 25% chance a zero-day is generated hourly.",
        "parts": [("BAT", 4, 6), ("BAT", 4, 18), ("PWR", 10, 12), ("QBT", 18, 6),
                  ("QBT", 18, 18), ("CPU", 26, 12), ("MEM", 34, 6), ("DISK", 34, 18),
                  ("WIFI", 36, 12)],
        "wires": [((4, 6), (10, 12)), ((4, 18), (10, 12)), ((10, 12), (18, 6)), ((10, 12), (18, 18)),
                  ((18, 6), (26, 12)), ((18, 18), (26, 12)), ((26, 12), (34, 6)), ((26, 12), (34, 18)),
                  ((34, 6), (36, 12)), ((34, 18), (36, 12)), ((26, 12), (36, 12))],
    },
}

XP_PER_RANK = [0, 50, 160, 400, 900, 1800, 3600, 7000]
RANKS = ["SCRIPT KIDDIE", "RUNNER", "NETRUNNER", "GHOST", "PHANTOM", "LEGEND", "MYTH", "ASCENDED"]

CONTRACTS_POOL = [
    {"id": "own3", "desc": "Own 3 nodes", "cash": 600, "scrap": 15, "zd": 0, "prog": "nodes"},
    {"id": "earn2k", "desc": "Earn $2,000", "cash": 400, "scrap": 10, "zd": 0, "prog": "cash", "goal": 2000},
    {"id": "breach5", "desc": "Win 5 breaches", "cash": 500, "scrap": 20, "zd": 1, "prog": "wins", "goal": 5},
    {"id": "heat0", "desc": "Cool down to 10 heat", "cash": 350, "scrap": 8, "zd": 0, "prog": "heat", "goal": 10},
    {"id": "device3", "desc": "Craft 3 devices", "cash": 550, "scrap": 18, "zd": 0, "prog": "crafted", "goal": 3},
    {"id": "bot10", "desc": "Grow botnet to 10", "cash": 700, "scrap": 22, "zd": 1, "prog": "botnet", "goal": 10},
    {"id": "raid2", "desc": "Raid 2 nodes", "cash": 800, "scrap": 25, "zd": 1, "prog": "raids", "goal": 2},
]

OSES = ["WIN10", "LINUX", "ANDROID", "IOS", "RTOS", "BSD"]
PORTS = [21, 22, 23, 80, 443, 445, 3389, 8080, 31337, 9001]


class Game:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption(TITLE + (" [%s]" % PROFILE_NAME if PROFILE_NAME else ""))
        self.cfg = {"music": 5, "sfx": 6}
        self.cfg.update(jload(CFG_FILE, {}))
        self.win = pygame.display.set_mode((W, H), pygame.RESIZABLE)
        self.scr = pygame.Surface((W, H))
        self.clock = pygame.time.Clock()
        self.audio = Audio(self)
        self.audio.want = "menu"
        self.prof = {
            "id": uuid.uuid4().hex[:8], "name": clean(PROFILE_NAME, 12) or "RUNNER", "color": 0,
            "cash": 500.0, "heat": 0.0, "fw": 0, "rig": 0, "zd": 1, "hacks": 0, "wins": 0,
            "xp": 0, "rank": 0, "scrap": 5.0,
            "devices": {},
            "bots": [],
            "buildq": [],
            "botnet_deployed": 0,
            "contracts": [],
            "contracts_done": [],
            "daily_node": -1,
            "daily_used": False,
            "session_raids": 0, "session_crafted": 0,
            "cash_hist": [],
            "offers": [],
            "offer_t": 0.0,
        }
        self.prof.update(jload(PROFILE_FILE, {}))
        for k, v in [("devices", {}), ("bots", []), ("buildq", []), ("contracts", []),
                     ("contracts_done", []), ("xp", 0), ("rank", 0), ("scrap", 5.0),
                     ("botnet_deployed", 0), ("daily_node", -1), ("daily_used", False),
                     ("session_raids", 0), ("session_crafted", 0),
                     ("cash_hist", []), ("offers", []), ("offer_t", 0.0)]:
            self.prof.setdefault(k, v)
        self.scene, self.net, self.disc, self.breach = "menu", None, None, None
        self.hits, self.toasts, self.t, self.inc = [], [], 0.0, 0.0
        self.tab, self.sel, self.scanned, self.scan_t, self.scan_id = 0, None, set(), 0.0, None
        self.field, self.bufs = None, {"name": self.prof["name"], "ip": "", "chat": ""}
        self.seen, self.lastchat, self.mouse, self.stat_t, self.save_t = None, None, (0, 0), 0.0, 8.0
        self.rain = [[x, random.uniform(0, H), random.uniform(40, 120)] for x in range(0, W, 16)]
        self.contract_timer = 0.0
        self.pending_ice = False
        self.pcb = {
            "sel": "phone",
            "parts": [],
            "wires": [],
            "carry": None,
            "wire_mode": "power",
            "dragging": None,
            "err": 0.0,
            "msg": "",
            "tray_sel": None,
        }
        self.forge_hits = []
        self.forge_load_blueprint("phone")

    def view(self):
        ww, wh = self.win.get_size()
        k = min(ww / W, wh / H)
        vw, vh = int(W * k), int(H * k)
        return k, (ww - vw) // 2, (wh - vh) // 2, vw, vh

    def mpos(self, p):
        k, ox, oy, _, _ = self.view()
        if k <= 0:
            return (0, 0)
        return int((p[0] - ox) / k), int((p[1] - oy) / k)

    def toast(self, msg, col=GREEN):
        self.toasts.append([msg, col, 3.0])

    def save(self):
        jsave(PROFILE_FILE, self.prof)
        jsave(CFG_FILE, self.cfg)

    def quit(self):
        self.save()
        if self.net:
            self.net.close()
        pygame.quit()
        sys.exit()

    def leave(self):
        self.save()
        for o in (self.net, self.disc):
            if o:
                o.close()
        self.net = self.disc = self.breach = self.field = None
        self.scene = "menu"
        self.audio.want = "menu"

    def start(self, mode, host=None):
        self.prof["name"] = clean(self.bufs["name"], 12) or "RUNNER"
        try:
            self.net = Net(self.prof["id"], mode, host, self.prof["name"])
        except Exception as ex:
            self.net = None
            self.audio.sfx("deny")
            self.toast("NET ERROR: " + clean(ex, 34), RED)
            return
        if self.disc:
            self.disc.close()
            self.disc = None
        self.scene, self.seen, self.tab, self.sel = "game", None, 0, None
        self.audio.want = "grid"
        self.audio.sfx("connect")
        self.send_stat()
        if self.prof.get("daily_node", -1) < 0 or self.prof.get("daily_node", -1) >= NODE_COUNT:
            self.prof["daily_node"] = random.randrange(NODE_COUNT)
            self.prof["daily_used"] = False
        if not self.prof.get("contracts"):
            self.roll_contracts()
        self.toast({"solo": "SOLO WORLD ONLINE", "host": "HOSTING %s:%d" % (self.net.ip, TCP_PORT),
                    "client": "CONNECTED"}[mode], CYAN)
        if not self.prof.get("daily_used", True):
            self.audio.sfx("daily")
            self.toast("DAILY GLITCH NODE ACTIVE — 5x LOOT", MAG)

    def send_stat(self):
        p = self.prof
        if self.net:
            self.net.send({"t": "stat", "n": p["name"], "c": p["color"], "cash": int(p["cash"]), "fw": p["fw"]})

    def ocol(self, o):
        if o is None:
            return CORP
        if o == self.prof["id"]:
            return PCOLORS[self.prof["color"] % 8]
        pl = self.net.state["players"].get(o)
        return PCOLORS[pl["c"] % 10] if pl else MID

    def oname(self, o):
        if o is None:
            return "CORP"
        pl = self.net.state["players"].get(o)
        return pl["n"] if pl else "?"

    def event(self, e):
        if e.type == pygame.QUIT:
            self.quit()
        elif e.type in (pygame.MOUSEBUTTONDOWN, pygame.FINGERDOWN):
            pos = e.pos if hasattr(e, "pos") else (e.x * self.win.get_width(), e.y * self.win.get_height())
            p = self.mpos(pos)
            btn = getattr(e, "button", 1) if hasattr(e, "button") else 1
            if self.scene == "breach":
                g = self.breach["game"]
                if btn == 3:
                    g.rclick(p)
                else:
                    g.click(p)
            elif self.scene == "game" and self.tab == TABS.index("forge"):
                if not self.forge_click(p, btn):
                    self.field = None
                    for r, fn in reversed(self.hits):
                        if r.collidepoint(p):
                            self.audio.sfx("click")
                            fn()
                            break
            else:
                self.field = None
                for r, fn in reversed(self.hits):
                    if r.collidepoint(p):
                        self.audio.sfx("click")
                        fn()
                        break
        elif e.type in (pygame.MOUSEBUTTONUP, pygame.FINGERUP):
            pos = e.pos if hasattr(e, "pos") else (e.x * self.win.get_width(), e.y * self.win.get_height())
            p = self.mpos(pos)
            if self.scene == "breach":
                self.breach["game"].release(p)
        elif e.type == pygame.MOUSEMOTION:
            p = self.mpos(e.pos)
            if self.scene == "game" and self.tab == TABS.index("forge"):
                self.forge_motion(p)
        elif e.type == pygame.KEYDOWN:
            self.keydown(e)

    def keydown(self, e):
        k = e.key
        if k == pygame.K_F11:
            pygame.display.toggle_fullscreen()
        elif self.field:
            buf, lim = self.bufs[self.field], {"name": 12, "ip": 21, "chat": 60}[self.field]
            if k in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.submit_field()
            elif k == pygame.K_ESCAPE:
                self.field = None
            elif k == pygame.K_BACKSPACE:
                self.bufs[self.field] = buf[:-1]
            elif e.unicode and 32 <= ord(e.unicode[0]) < 127 and len(buf) < lim:
                self.bufs[self.field] += e.unicode[0]
                self.audio.sfx("key", .6)
        elif k == pygame.K_n:
            self.audio.muted = not self.audio.muted
        elif self.scene == "breach":
            if k == pygame.K_ESCAPE:
                self.end_breach(None)
            elif k == pygame.K_z:
                self.zero()
            else:
                self.breach["game"].key(e)
        elif self.scene == "game":
            if pygame.K_1 <= k <= pygame.K_9:
                idx = k - pygame.K_1
                if idx < len(TABS):
                    self.tab = idx
            elif k == pygame.K_TAB:
                self.tab = (self.tab + (-1 if e.mod & pygame.KMOD_SHIFT else 1)) % len(TABS)
            elif k in (pygame.K_RETURN, pygame.K_t):
                self.tab, self.field = TABS.index("chat"), "chat"
            elif k == pygame.K_ESCAPE:
                self.tab, self.sel = 0, None
        elif self.scene == "join" and k == pygame.K_ESCAPE:
            self.leave()

    def submit_field(self):
        f, v = self.field, self.bufs[self.field].strip()
        self.field = None
        if f == "name":
            self.bufs["name"] = self.prof["name"] = clean(v, 12) or "RUNNER"
        elif f == "chat" and v and self.net:
            self.net.send({"t": "chat", "m": v})
            self.bufs["chat"] = ""
        elif f == "ip" and v:
            self.start("client", v)

    def begin(self, nd, cls):
        fw = self.net.state["players"].get(nd["o"], {}).get("fw", 0) if nd["o"] else 0
        self.pending_ice = nd.get("mod") == "HAUNTED"
        d = clamp(nd["d"] + fw // 2, 1, 7)
        if nd.get("mod") == "TURRETED":
            d = clamp(d + 1, 1, 7)
        if nd["i"] == self.prof.get("daily_node", -1):
            d = clamp(d + 1, 1, 7)
        self.breach = {"node": nd["i"], "game": cls(d, self), "raid": bool(nd["o"])}
        self.scene = "breach"
        self.audio.want = "breach"
        self.prof["hacks"] += 1

    def end_breach(self, ok):
        b, p = self.breach, self.prof
        self.breach, self.scene = None, "game"
        self.audio.want = "grid"
        nd = self.net.state["nodes"][b["node"]]
        if ok is None:
            self.toast("BREACH ABORTED", MID)
        elif ok:
            loot = nd["p"] * 25 * (1.6 if b["raid"] else 1)
            scrap_gain = 2 + nd["d"] * 2
            daily_bonus = nd["i"] == p.get("daily_node", -1) and not p.get("daily_used", False)
            if daily_bonus:
                loot *= 5
                scrap_gain *= 3
                p["daily_used"] = True
            p["cash"] += loot
            p["scrap"] = p.get("scrap", 0) + scrap_gain
            p["heat"] += (6 + nd["d"] * 3) * (1 - .2 * p.get("sk_stealth", 0))
            p["wins"] += 1
            if b["raid"]:
                p["session_raids"] = p.get("session_raids", 0) + 1
            nd["o"] = p["id"]
            self.net.send({"t": "own", "node": nd["i"]})
            self.audio.sfx("win")
            self.add_xp(10 + nd["d"] * 5)
            self.toast("%s OWNED  +%s  +%d scrap%s" %
                       (nd["n"].upper(), money(loot), scrap_gain, " [DAILY!]" if daily_bonus else ""), GREEN)
            if self.pending_ice and random.random() < .7:
                self.pending_ice = False
                self.breach = {"node": nd["i"], "game": Ice(clamp(nd["d"] + 1, 1, 7), self), "raid": False}
                self.scene = "breach"
                self.audio.want = "raid"
                self.toast("ICE STORM! BONUS BREACH", MAG)
        else:
            p["heat"] += 4
            p["scrap"] = p.get("scrap", 0) + 1
            self.audio.sfx("lose")
            self.toast("BREACH FAILED  +4 HEAT  +1 scrap", RED)

    def zero(self):
        g = self.breach["game"]
        if self.prof["zd"] > 0 and g.done is None:
            self.prof["zd"] -= 1
            self.audio.sfx("zero")
            g.done = True
        else:
            self.audio.sfx("deny")

    def buy(self, key, cost):
        p = self.prof
        if p["cash"] < cost:
            return self.audio.sfx("deny")
        p["cash"] -= cost
        if key:
            p[key] += 1
        else:
            p["heat"] = max(0, p["heat"] - 35)
        self.audio.sfx("buy")
        self.send_stat()

    def vol(self, k, d):
        self.cfg[k] = clamp(self.cfg[k] + d, 0, 10)
        self.audio.sfx("click")

    def set_color(self, i):
        self.prof["color"] = i
        self.send_stat()

    def add_xp(self, n):
        p = self.prof
        p["xp"] = p.get("xp", 0) + n
        rank = p.get("rank", 0)
        while rank + 1 < len(XP_PER_RANK) and p["xp"] >= XP_PER_RANK[rank + 1]:
            rank += 1
            p["rank"] = rank
            p["cash"] += 300 * rank
            p["scrap"] = p.get("scrap", 0) + 10 * rank
            self.audio.sfx("rank")
            self.toast("RANK UP! %s" % RANKS[rank], MAG)
        p["rank"] = rank

    def botnet_size(self):
        return sum(self.prof.get("devices", {}).values()) + len(self.prof.get("bots", []))

    def device_count_total(self):
        return sum(self.prof.get("devices", {}).values())

    def botnet_income(self):
        mults = {"phone": .3, "tablet": .8, "drone": 2, "server": 6, "quantum": 18,
                 "pcb_scanner": .5, "relay_pylon": 1.2, "brute_rig": 4,
                 "ghost_node": 8, "void_core": 30}
        base = sum(mults.get(k, 0) * c for k, c in self.prof.get("devices", {}).items())
        for b in self.prof.get("bots", []):
            if b["state"] in ("idle", "spreading"):
                base += .4 * b["lvl"] * (1 + 0.1 * b["threads"])
            elif b["state"] == "scanning":
                base += .15 * b["lvl"]
        return base * (1 + .15 * self.prof.get("rig", 0))

    def device_count(self, kind):
        return self.prof.get("devices", {}).get(kind, 0)

    def _new_bot(self, lvl=None):
        lvl = lvl or random.choice([1, 1, 2, 2, 3])
        return {
            "ip": "%d.%d.%d.%d" % (random.randrange(11, 223), random.randrange(0, 256),
                                    random.randrange(0, 256), random.randrange(1, 255)),
            "os": random.choice(OSES),
            "port": random.choice(PORTS),
            "state": "idle",
            "heat": 0.0,
            "lvl": lvl,
            "threads": random.randint(1, lvl * 2),
        }

    def botnet_tick(self, dt):
        p = self.prof
        bots = p.setdefault("bots", [])
        income = self.botnet_income()
        for b in bots:
            b["heat"] = max(0, b["heat"] - dt * .5)
            if b["state"] == "idle":
                if random.random() < dt * 0.02 * b["lvl"]:
                    b["state"] = "scanning"
            elif b["state"] == "scanning":
                b["heat"] += dt * 1.2
                if random.random() < dt * 0.05 * b["lvl"]:
                    b["state"] = "spreading"
                    self.toast("BOT %s spreading" % b["ip"], GREEN)
            elif b["state"] == "spreading":
                b["heat"] += dt * 2.0
                if random.random() < dt * 0.04 * b["lvl"]:
                    b["state"] = "idle"
                    b["lvl"] += 1
                    b["heat"] = max(0, b["heat"] - 5)
                    self.toast("BOT %s leveled to %d" % (b["ip"], b["lvl"]), GREEN)
            if b["heat"] > 60 and random.random() < dt * 0.01:
                b["state"] = "traced"
                self.audio.sfx("alarm")
                self.toast("BOT %s TRACED — purged" % b["ip"], RED)
        p["bots"] = [b for b in bots if b["state"] != "traced"]
        p["cash"] += income * dt

    def roll_contracts(self):
        pool = CONTRACTS_POOL[:]
        random.shuffle(pool)
        active = []
        for c in pool[:3]:
            active.append({"id": c["id"], "goal": c.get("goal", 0), "start": self._contract_start(c["id"])})
        self.prof["contracts"] = active

    def _contract_start(self, cid):
        p = self.prof
        mapping = {
            "own3": lambda: sum(1 for n in self.net.state["nodes"] if n["o"] == p["id"]) if self.net else 0,
            "earn2k": lambda: int(p["cash"]),
            "breach5": lambda: p.get("wins", 0),
            "heat0": lambda: int(p["heat"]),
            "device3": lambda: p.get("session_crafted", 0),
            "bot10": lambda: self.botnet_size(),
            "raid2": lambda: p.get("session_raids", 0),
        }
        try:
            return mapping[cid]() if self.net else 0
        except Exception:
            return 0

    def contract_progress(self, c):
        p = self.prof
        cid = c["id"]
        if cid == "own3":
            return sum(1 for n in self.net.state["nodes"] if n["o"] == p["id"]) if self.net else 0
        if cid == "earn2k":
            return int(p["cash"]) - c["start"]
        if cid == "breach5":
            return p.get("wins", 0) - c["start"]
        if cid == "heat0":
            return c["start"] - int(p["heat"]) if p["heat"] < c["start"] else 0
        if cid == "device3":
            return p.get("session_crafted", 0) - c["start"]
        if cid == "bot10":
            return self.botnet_size()
        if cid == "raid2":
            return p.get("session_raids", 0) - c["start"]
        return 0

    def contract_goal(self, c):
        cid = c["id"]
        for cc in CONTRACTS_POOL:
            if cc["id"] == cid:
                return cc.get("goal", 1) if cid != "bot10" else 10
        return 1

    def contract_def(self, cid):
        for cc in CONTRACTS_POOL:
            if cc["id"] == cid:
                return cc
        return {"desc": "?", "cash": 0, "scrap": 0, "zd": 0}

    def claim_contract(self, c):
        prog = self.contract_progress(c)
        goal = self.contract_goal(c)
        if prog < goal:
            return self.audio.sfx("deny")
        d = self.contract_def(c["id"])
        self.prof["cash"] += d["cash"]
        self.prof["scrap"] = self.prof.get("scrap", 0) + d["scrap"]
        self.prof["zd"] = self.prof.get("zd", 0) + d["zd"]
        self.prof["contracts"] = [cc for cc in self.prof["contracts"] if cc["id"] != c["id"]]
        self.prof["contracts_done"] = (self.prof.get("contracts_done", []) + [c["id"]])[-10:]
        self.audio.sfx("job")
        self.add_xp(20)
        self.toast("CONTRACT CLAIMED: %s" % d["desc"], GREEN)
        if len(self.prof["contracts"]) < 3:
            active_ids = {cc["id"] for cc in self.prof["contracts"]}
            for cc in CONTRACTS_POOL:
                if cc["id"] not in active_ids:
                    self.prof["contracts"].append({"id": cc["id"], "goal": cc.get("goal", 0),
                                                   "start": self._contract_start(cc["id"])})
                    if len(self.prof["contracts"]) >= 3:
                        break

    def salvage(self, kind):
        n = self.device_count(kind)
        if n <= 0:
            return self.audio.sfx("deny")
        h = HARDWARE[kind]
        self.prof["devices"][kind] -= 1
        refund_cash = int(h["cost"] * .5)
        refund_scrap = max(1, h["scrap"] // 2)
        self.prof["cash"] += refund_cash
        self.prof["scrap"] = self.prof.get("scrap", 0) + refund_scrap
        self.audio.sfx("buy")
        self.toast("SALVAGED %s +%s +%d scrap" % (h["label"], money(refund_cash), refund_scrap), AMBER)

    def deploy_botnet(self):
        p = self.prof
        cost = 150 + 40 * len(p.get("bots", []))
        if p["cash"] < cost:
            self.audio.sfx("deny")
            return self.toast("NEED %s TO ACQUIRE BOT" % money(cost), RED)
        p["cash"] -= cost
        b = self._new_bot()
        b["state"] = "scanning"
        p.setdefault("bots", []).append(b)
        self.audio.sfx("botnet")
        self.toast("BOT ACQUIRED  %s  %s" % (b["ip"], b["os"]), CYAN)

    def _purge_bot(self, b):
        if b in self.prof.get("bots", []):
            self.prof["bots"].remove(b)
        self.audio.sfx("snip")
        self.toast("BOT %s purged" % b["ip"], AMBER)

    def _botnet_raid(self):
        p = self.prof
        bots = p.get("bots", [])
        if len(bots) < 3 or not self.net:
            return self.audio.sfx("deny")
        enemies = [n for n in self.net.state["nodes"] if n["o"] and n["o"] != p["id"]]
        if not enemies:
            return self.toast("NO ENEMY NODES", MID)
        tgt = random.choice(enemies)
        strength = sum(b["lvl"] * (1 + b["threads"] * 0.1) for b in bots) / 10.0
        chance = clamp(0.25 + 0.05 * p.get("sk_intrusion", 0) + strength * 0.05, 0, 0.9)
        for _ in range(2):
            if bots:
                b = bots.pop(random.randrange(len(bots)))
                if random.random() < .2:
                    p.setdefault("bots", []).append(b)
        if random.random() < chance:
            tgt["o"] = p["id"]
            self.net.send({"t": "own", "node": tgt["i"]})
            p["cash"] += tgt["p"] * 20
            p["session_raids"] = p.get("session_raids", 0) + 1
            self.audio.sfx("win")
            self.toast("BOTNET RAID OK: %s" % tgt["n"], GREEN)
        else:
            self.audio.sfx("lose")
            self.toast("BOTNET RAID FAILED: %s" % tgt["n"], RED)

    def _market_buy(self, nm, price, key):
        p = self.prof
        if p.get("scrap", 0) < price:
            return self.audio.sfx("deny")
        p["scrap"] -= price
        if key == "zd":
            p["zd"] += 1
        elif key == "fw":
            p["fw"] = min(5, p["fw"] + 1)
            self.send_stat()
        elif key == "rig":
            p["rig"] = min(8, p["rig"] + 1)
        elif key == "heat":
            p["heat"] = max(0, p["heat"] - 40)
        elif key == "cash":
            p["cash"] += 300
        p["offers"] = [o for o in p.get("offers", []) if o[0] != nm]
        self.audio.sfx("buy")
        self.toast("MARKET: %s" % nm, GREEN)

    def _buy_skill(self, key, cost):
        p = self.prof
        if p["cash"] < cost or p.get(key, 0) >= 5:
            return self.audio.sfx("deny")
        p["cash"] -= cost
        p[key] = p.get(key, 0) + 1
        self.audio.sfx("lvup")
        self.toast("SKILL UP: %s" % key, GREEN)

    def forge_board_rect(self):
        return pygame.Rect(16, 40, BOARD_W * CELL, BOARD_H * CELL)

    def forge_cell(self, p):
        b = self.forge_board_rect()
        cx, cy = (p[0] - b.x) // CELL, (p[1] - b.y) // CELL
        if 0 <= cx < BOARD_W and 0 <= cy < BOARD_H:
            return (cx, cy)
        return None

    def forge_part_at(self, x, y):
        for part in self.pcb["parts"]:
            if part["x"] == x and part["y"] == y:
                return part
        return None

    def forge_load_blueprint(self, kind):
        bp = HARDWARE[kind]
        self.pcb["sel"] = kind
        self.pcb["parts"] = [{"kind": k, "x": x, "y": y} for (k, x, y) in bp["parts"]]
        self.pcb["wires"] = [(a[0], a[1], b[0], b[1]) for (a, b) in bp["wires"]]
        self.pcb["msg"] = "Blueprint loaded. Click to place, drag to wire."

    def forge_clear(self):
        self.pcb["parts"] = []
        self.pcb["wires"] = []
        self.pcb["dragging"] = None
        self.pcb["msg"] = "Board cleared. Place a part from the tray."

    def forge_click(self, p, btn):
        for r, fn in reversed(self.hits):
            if r.collidepoint(p):
                self.audio.sfx("click")
                fn()
                return True
        for i, (kind, d) in enumerate(PART_DEFS.items()):
            tr = pygame.Rect(W - 156, 44 + i * 26, 140, 24)
            if tr.collidepoint(p):
                if btn == 3:
                    self.pcb["tray_sel"] = None
                else:
                    self.pcb["tray_sel"] = kind
                    self.pcb["wire_mode"] = d["role"]
                    self.audio.sfx("wire")
                return True
        for i, kind in enumerate(HARDWARE.keys()):
            br = pygame.Rect(16 + (i % 6) * 120, 8 + (i // 6) * 26, 112, 22)
            if br.collidepoint(p):
                self.forge_load_blueprint(kind)
                self.audio.sfx("click")
                return True
        bm = pygame.Rect(W - 312, 52, 68, 24)
        if bm.collidepoint(p):
            self.forge_clear()
            self.audio.sfx("snip")
            return True
        build_rect = pygame.Rect(W - 312, 84, 68, 24)
        if build_rect.collidepoint(p):
            self.forge_build()
            return True
        for i, mode in enumerate(("power", "data", "signal", "output")):
            wr = pygame.Rect(W - 312, 116 + i * 24, 68, 22)
            if wr.collidepoint(p):
                self.pcb["wire_mode"] = mode
                self.audio.sfx("wire")
                return True
        cell = self.forge_cell(p)
        if cell is None:
            return False
        x, y = cell
        if btn == 3:
            part = self.forge_part_at(x, y)
            if part:
                self.pcb["parts"].remove(part)
                self.pcb["wires"] = [w for w in self.pcb["wires"]
                                     if (w[0], w[1]) != (x, y) and (w[2], w[3]) != (x, y)]
                self.audio.sfx("snip")
                return True
            new = [w for w in self.pcb["wires"] if (w[0], w[1]) != (x, y)]
            if len(new) != len(self.pcb["wires"]):
                self.pcb["wires"] = new
                self.audio.sfx("snip")
                return True
            return True
        if self.pcb.get("tray_sel"):
            kind = self.pcb["tray_sel"]
            if not self.forge_part_at(x, y):
                self.pcb["parts"].append({"kind": kind, "x": x, "y": y})
                self.audio.sfx("zap")
            self.pcb["tray_sel"] = None
            return True
        if self.pcb["dragging"] is None:
            self.pcb["dragging"] = (x, y)
            self.pcb["msg"] = "Drag to a target cell to wire."
        else:
            sx, sy = self.pcb["dragging"]
            if (sx, sy) != (x, y):
                self.pcb["wires"].append((sx, sy, x, y))
                self.audio.sfx("wire")
                self.pcb["msg"] = "%s wire: (%d,%d)->(%d,%d)" % (self.pcb["wire_mode"], sx, sy, x, y)
            self.pcb["dragging"] = None
        return True

    def forge_motion(self, p):
        pass

    def forge_build(self):
        kind = self.pcb["sel"]
        bp = HARDWARE[kind]
        if self.prof["cash"] < bp["cost"] or self.prof.get("scrap", 0) < bp["scrap"]:
            self.pcb["err"] = 1.2
            self.pcb["msg"] = "NOT ENOUGH CASH / SCRAP"
            self.audio.sfx("deny")
            return
        if self.prof.get("rank", 0) < bp["tech"]:
            self.pcb["err"] = 1.2
            self.pcb["msg"] = "RANK %d REQUIRED" % bp["tech"]
            self.audio.sfx("deny")
            return
        want = set((k, x, y) for (k, x, y) in bp["parts"])
        have = set((pt["kind"], pt["x"], pt["y"]) for pt in self.pcb["parts"])
        if want != have:
            self.pcb["err"] = 1.2
            self.pcb["msg"] = "PARTS MISMATCH — need %d parts" % len(want)
            self.audio.sfx("deny")
            return
        want_w = set((min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))
                     for (a, b) in bp["wires"])
        have_w = set((min(w[0], w[2]), min(w[1], w[3]), max(w[0], w[2]), max(w[1], w[3]))
                     for w in self.pcb["wires"])
        if want_w != have_w:
            self.pcb["err"] = 1.2
            self.pcb["msg"] = "WIRES MISMATCH — check power/data/signal"
            self.audio.sfx("deny")
            return
        self.prof["cash"] -= bp["cost"]
        self.prof["scrap"] = self.prof.get("scrap", 0) - bp["scrap"]
        dur = bp["time"] * (0.8 ** self.prof.get("sk_coding", 0))
        self.prof.setdefault("buildq", []).append({"kind": kind, "t": 0.0, "dur": dur})
        self.prof["session_crafted"] = self.prof.get("session_crafted", 0) + 1
        self.audio.sfx("forge")
        self.toast("FORGING %s..." % bp["label"], CYAN)
        self.pcb["msg"] = "CIRCUIT VERIFIED. FORGING %s" % bp["label"]
        self.pcb["err"] = 0.0

    def finish_builds(self, dt):
        q = self.prof.setdefault("buildq", [])
        done = []
        for b in q:
            b["t"] += dt
            if b["t"] >= b["dur"]:
                done.append(b)
        for b in done:
            q.remove(b)
            kind = b["kind"]
            self.prof.setdefault("devices", {})[kind] = self.prof["devices"].get(kind, 0) + 1
            self.audio.sfx("build")
            self.toast("%s COMPLETE (botnet +1)" % HARDWARE[kind]["label"], GREEN)
            self.add_xp(8)
            if kind == "server":
                self.prof["fw"] = min(5, self.prof.get("fw", 0) + 1)
                self.send_stat()
            if kind == "quantum" and random.random() < .5:
                self.prof["zd"] = self.prof.get("zd", 0) + 1
                self.toast("QUANTUM BONUS: +1 ZERO-DAY", MAG)
            if kind == "void_core" and random.random() < .25:
                self.prof["zd"] = self.prof.get("zd", 0) + 1
                self.toast("VOID CORE: +1 ZERO-DAY", MAG)

    def update(self, dt):
        self.audio.poll()
        for t in self.toasts:
            t[2] -= dt
        self.toasts = [t for t in self.toasts if t[2] > 0]
        for r in self.rain:
            r[1] = (r[1] + r[2] * dt) % (H + 80)
        if self.pcb["err"] > 0:
            self.pcb["err"] = max(0, self.pcb["err"] - dt)
        if self.scene == "join" and self.disc:
            self.disc.poll()
        if self.scene not in ("game", "breach") or not self.net:
            self.finish_builds(dt)
            return
        n, p = self.net, self.prof
        n.update(dt)
        if not n.alive:
            self.toast("DISCONNECTED FROM HOST", RED)
            return self.leave()
        st = n.state
        if not st["nodes"]:
            return
        if self.seen is None:
            self.seen = st["seq"]
        for lg in st["log"]:
            if lg[0] > self.seen:
                self.seen = lg[0]
                if lg[2] == p["id"]:
                    loss = min(lg[3], p["cash"] * .15)
                    p["cash"] -= loss
                    self.toast("RAIDED! %s  -%s" % (lg[1], money(loss)), RED)
                    self.audio.sfx("raid")
        ch = st["chat"][-1] if st["chat"] else None
        if ch != self.lastchat:
            self.lastchat = ch
            if ch and ch[0] != p["name"]:
                self.audio.sfx("chat")
        node_inc = sum(x["p"] for x in st["nodes"] if x["o"] == p["id"]) * (1 + .15 * p["rig"])
        self.inc = node_inc + self.botnet_income()
        p["cash"] += self.inc * dt
        p["heat"] = max(0, p["heat"] - .35 * (1 + .2 * p.get("sk_stealth", 0)) * dt)
        if p["heat"] >= 100:
            p["cash"] *= .5
            p["heat"] = 45
            self.audio.sfx("alarm")
            self.toast("FEDS SEIZED HALF YOUR CASH!", RED)
        self.finish_builds(dt)
        self.botnet_tick(dt)
        self.stat_t -= dt
        if self.stat_t <= 0:
            self.stat_t = 1
            self.send_stat()
        self.save_t -= dt
        if self.save_t <= 0:
            self.save_t = 8
            self.save()
        if self.scan_t > 0:
            self.scan_t -= dt
            if self.scan_t <= 0:
                self.scanned.add(self.scan_id)
                if p.get("sk_network", 0) > 0:
                    self.scanned.update(random.sample(range(len(st["nodes"])),
                                                       min(p["sk_network"], len(st["nodes"]))))
                self.audio.sfx("ok")
        if not self.prof.get("contracts"):
            self.roll_contracts()
        if self.scene == "breach":
            g = self.breach["game"]
            g.update(dt)
            if g.done is not None:
                self.end_breach(g.done)

    def button(self, rect, label, fn, col=GREEN, en=True, sz=12):
        r = pygame.Rect(rect)
        hov = en and r.collidepoint(self.mouse)
        c = col if en else DIM
        pygame.draw.rect(self.scr, lerpc((10, 22, 24), c, .35) if hov else (10, 22, 24), r)
        pygame.draw.rect(self.scr, c, r, 1)
        ctext(self.scr, label, r, WHITE if hov else c, sz)
        if en:
            self.hits.append((r, fn))

    def inp(self, rect, key):
        r, on = pygame.Rect(rect), self.field == key
        pygame.draw.rect(self.scr, (14, 28, 30) if on else (10, 20, 22), r)
        pygame.draw.rect(self.scr, CYAN if on else BORDER, r, 1)
        s = self.bufs[key] + ("_" if on and int(self.t * 2) % 2 == 0 else "")
        while len(s) > 1 and tw(s, 12) > r.w - 6:
            s = s[1:]
        text(self.scr, s, r.x + 4, r.y + 4, WHITE, 12)
        self.hits.append((r, lambda: setattr(self, "field", key)))

    def draw(self):
        sc = self.scr
        self.hits = []
        sc.fill(BG)
        if self.scene == "menu":
            self.d_menu()
        elif self.scene == "join":
            self.d_join()
        elif self.scene == "game":
            self.d_game()
        else:
            self.d_breach()
        for i, (m, c, _) in enumerate(self.toasts[-3:]):
            w = tw(m, 12) + 10
            r = pygame.Rect(W // 2 - w // 2, 36 + i * 28, w, 24)
            pygame.draw.rect(sc, (8, 14, 18), r)
            pygame.draw.rect(sc, c, r, 1)
            text(sc, m, W // 2, 40 + i * 28, c, 12, "c")

    def d_menu(self):
        sc = self.scr
        for x, y, _ in self.rain:
            for k in range(10):
                text(sc, chr(48 + (int(y) // 16 + x // 16 + k) % 2), x, int(y) - k * 18,
                     dimc(GREEN, .09 + .04 * k), 12, sh=False)
        text(sc, "NETRUNNER", W // 2, 36, GREEN, 64, "c")
        text(sc, "B L A C K O U T", W // 2, 100, MAG, 30, "c")
        text(sc, "RANK %s  //  XP %d" % (RANKS[self.prof.get("rank", 0)], self.prof.get("xp", 0)),
             W // 2, 132, CYAN, 12, "c")
        text(sc, "HANDLE:", 264, 168, MID, 14)
        self.inp((352, 162, 152, 24), "name")
        for i, (lb, fn, col) in enumerate((
                ("SOLO RUN", lambda: self.start("solo"), GREEN),
                ("HOST LAN GAME", lambda: self.start("host"), CYAN),
                ("JOIN LAN GAME", self.open_join, CYAN),
                ("QUIT", self.quit, RED))):
            self.button((264, 200 + i * 44, 240, 34), lb, fn, col, sz=16)
        text(sc, "touch enabled  |  N mute  |  TAB cycle", W // 2, H - 24, DIM, 12, "c")

    def open_join(self):
        self.disc, self.scene = Discover(), "join"

    def d_join(self):
        sc = self.scr
        panel(sc, (120, 60, 528, 320), title="JOIN LAN GAME")
        hosts = sorted(self.disc.hosts.items()) if self.disc else []
        text(sc, "HOSTS ON YOUR NETWORK:", 144, 84, MID, 12)
        for i, (ip, (nm, cnt, _)) in enumerate(hosts[:6]):
            self.button((144, 112 + i * 40, 480, 32), "%s  %s  (%s online)" % (nm, ip, cnt),
                        lambda ip=ip: self.start("client", ip), CYAN, sz=14)
        if not hosts:
            text(sc, "searching" + "." * (int(self.t * 2) % 4), 144, 120, DIM, 12)
        text(sc, "OR TYPE HOST IP:", 144, 300, MID, 12)
        self.inp((144, 322, 260, 28), "ip")
        self.button((412, 322, 124, 28), "CONNECT",
                    lambda: (setattr(self, "field", "ip"), self.submit_field()), GREEN, sz=14)
        self.button((544, 322, 80, 28), "BACK", self.leave, RED, sz=14)

    def d_game(self):
        sc, p = self.scr, self.prof
        pygame.draw.rect(sc, (8, 14, 18), (0, 0, W, 28))
        pygame.draw.line(sc, BORDER, (0, 28), (W, 28), 1)
        text(sc, p["name"], 8, 6, PCOLORS[p["color"] % 8], 12)
        text(sc, money(p["cash"]), 148, 6, AMBER, 12)
        text(sc, "+%d/s" % self.inc, 280, 6, GREEN, 12)
        text(sc, "ZD x%d" % p["zd"], 372, 6, CYAN, 12)
        text(sc, "XP%d" % p.get("xp", 0), 440, 6, MID, 12)
        text(sc, "S%d" % int(p.get("scrap", 0)), 508, 6, WHITE, 12)
        text(sc, "HEAT", 564, 6, heatcol(p["heat"]), 12)
        bar(sc, 612, 6, 144, 16, p["heat"], 100, heatcol(p["heat"]))
        for i, kind in enumerate(TABS):
            r, on = pygame.Rect(2, 34 + i * 32, 48, 30), i == self.tab
            pygame.draw.rect(sc, (16, 40, 40) if on else PANEL, r)
            pygame.draw.rect(sc, GREEN if on else DGREEN, r, 1)
            dock_icon(sc, kind, r.centerx, r.y + 10, GREEN if on else MID)
            text(sc, TABN[i], r.centerx, r.y + 18, GREEN if on else DIM, 8, "c")
            self.hits.append((r, lambda i=i: setattr(self, "tab", i)))
        if not self.net.state["nodes"]:
            return text(sc, "CONNECTING...", W // 2 + 24, H // 2, CYAN, 18, "c")
        getattr(self, "d_" + TABS[self.tab])()

    def d_net(self):
        sc, st, p = self.scr, self.net.state, self.prof
        N, ox, oy = st["nodes"], 56, 40
        panel(sc, (56, 32, 488, 352), title="GRID")
        for (i, j) in NODE_EDGES:
            if i < len(N) and j < len(N):
                a, b = N[i], N[j]
                pygame.draw.line(sc, (20, 62, 54),
                                 (ox + a["x"], oy + a["y"]),
                                 (ox + b["x"], oy + b["y"]), 1)
        for i, a in enumerate(N):
            x, y, col = ox + a["x"], oy + a["y"], self.ocol(a["o"])
            if i == self.sel:
                pygame.draw.circle(sc, WHITE, (x, y), 20 + int(math.sin(self.t * 6)) * 2, 1)
            if i == p.get("daily_node", -1) and not p.get("daily_used", True):
                pygame.draw.circle(sc, MAG, (x, y), 20 + int(math.sin(self.t * 3) * 4), 1)
            pygame.draw.circle(sc, (10, 18, 22), (x, y), 14)
            node_icon(sc, x, y, a["t"], col)
            text(sc, fit(a["n"], 64, 11), x, y + 18, col, 11, "c")
            if a.get("mod"):
                mc = {"TURRETED": RED, "VAULTED": AMBER, "HAUNTED": MAG, "RIFT": VIOLET}.get(a["mod"], DIM)
                text(sc, a["mod"][0], x + 12, y - 22, mc, 10, "c", False)
            self.hits.append((pygame.Rect(x - 24, y - 20, 48, 44), lambda i=i: setattr(self, "sel", i)))
        panel(sc, (548, 32, 220, 352), title="NODE")
        if self.sel is None:
            text(sc, "Select a node", 560, 52, DIM, 12)
        else:
            a = N[self.sel]
            own = a["o"] == p["id"]
            known = own or self.sel in self.scanned
            text(sc, fit(a["n"], 200, 14), 560, 44, WHITE, 14)
            text(sc, a["t"], 560, 66, CYAN, 12)
            text(sc, "OWNER " + fit(self.oname(a["o"]), 120, 11), 560, 86, self.ocol(a["o"]), 11)
            if a.get("mod"):
                mc = {"TURRETED": RED, "VAULTED": AMBER, "HAUNTED": MAG, "RIFT": VIOLET}.get(a["mod"], MID)
                text(sc, a["mod"], 560, 106, mc, 11)
            if not known:
                text(sc, "UNSCANNED", 560, 132, AMBER, 12)
                if self.scan_t > 0 and self.scan_id == self.sel:
                    bar(sc, 560, 164, 196, 16, .8 - self.scan_t, .8, CYAN)
                else:
                    self.button((560, 160, 196, 32), "SCAN",
                                lambda s=self.sel: (setattr(self, "scan_t", .8),
                                                    setattr(self, "scan_id", s),
                                                    self.audio.sfx("scan")), CYAN)
            else:
                fw = st["players"].get(a["o"], {}).get("fw", 0) if a["o"] else 0
                text(sc, "DIFF " + "*" * a["d"], 560, 132, AMBER, 12)
                text(sc, "PAY $%d/s FW L%d" % (a["p"], fw), 560, 154, GREEN, 12)
                text(sc, "LOOT " + money(a["p"] * 25 * (1.6 if a["o"] else 1)), 560, 174, AMBER, 12)
                if own:
                    text(sc, "YOU OWN THIS NODE", 560, 204, GREEN, 12)
                else:
                    for k, (vn, cls) in enumerate(VECTORS[:4]):
                        self.button((560, 208 + k * 24, 196, 22), vn,
                                    lambda a=a, cls=cls: self.begin(a, cls),
                                    MAG if a["o"] else GREEN, sz=10)
        panel(sc, (56, 388, 488, 44))
        for i, lg in enumerate(st["log"][-2:]):
            text(sc, fit(lg[1], 472, 11), 66, 392 + i * 20, AMBER if lg[2] == p["id"] else MID, 11)
        panel(sc, (548, 388, 220, 44))
        text(sc, "NODES %d/%d" % (sum(1 for x in N if x["o"] == p["id"]), len(N)), 560, 394, WHITE, 11)
        text(sc, "BOT %d" % self.botnet_size(), 560, 412, CYAN, 10)

    def d_shop(self):
        sc, p = self.scr, self.prof
        panel(sc, (56, 32, 712, 400), title="BLACK MARKET")
        items = [("FIREWALL", "fw", 5, 500 * (p["fw"] + 1), "Lvl %d/5." % p["fw"]),
                 ("RIG UPGRADE", "rig", 8, 700 * (p["rig"] + 1), "Lvl %d/8. +15%% income." % p["rig"]),
                 ("ZERO-DAY", "zd", 9, 450, "Owned %d/9. Z to auto-solve." % p["zd"]),
                 ("COOLANT", None, 0, 250, "Flush 35 heat."),
                 ("SCRAP->CASH", None, 0, 0, "10 scrap -> $150")]
        for i, (nm, k, mx, cost, desc) in enumerate(items):
            y = 48 + i * 68
            panel(sc, (72, y, 680, 60), DGREEN)
            text(sc, nm, 88, y + 8, CYAN, 14)
            text(sc, fit(desc, 500, 11), 88, y + 34, MID, 11)
            if nm == "SCRAP->CASH":
                scrap_have = int(p.get("scrap", 0))
                ok = scrap_have >= 10
                self.button((620, y + 12, 116, 36), "TRADE" if ok else "%d SCRAP" % scrap_have,
                            lambda: (self.prof.__setitem__("scrap", self.prof.get("scrap", 0) - 10),
                                     self.prof.__setitem__("cash", self.prof["cash"] + 150),
                                     self.audio.sfx("buy")) if ok else self.audio.sfx("deny"),
                            AMBER, ok, sz=14)
                continue
            full = bool(k) and p[k] >= mx
            self.button((620, y + 12, 116, 36), "MAX" if full else money(cost),
                        lambda k=k, c=cost: self.buy(k, c), AMBER,
                        not full and p["cash"] >= cost, sz=14)

    def d_rig(self):
        sc, p, st = self.scr, self.prof, self.net.state
        panel(sc, (56, 32, 712, 400), title="YOUR RIG")
        col = PCOLORS[p["color"] % 8]
        text(sc, p["name"], 80, 44, col, 26)
        text(sc, RANKS[p.get("rank", 0)], 80, 80, MAG, 14)
        mine = sum(1 for x in st["nodes"] if x["o"] == p["id"])
        rows = [("CASH", money(p["cash"])), ("INCOME", "%s/s" % money(self.inc)),
                ("NODES", mine), ("FIREWALL", "L%d" % p["fw"]), ("ZERO-DAYS", p["zd"]),
                ("WINS", p["wins"]), ("BOTNET", self.botnet_size()), ("SCRAP", int(p.get("scrap", 0)))]
        for i, (a, b) in enumerate(rows):
            text(sc, a, 80, 112 + i * 24, MID, 12)
            text(sc, b, 300, 112 + i * 24, WHITE, 12)
        text(sc, "XP %d -> %d" % (p.get("xp", 0), XP_PER_RANK[min(p.get("rank", 0) + 1, len(XP_PER_RANK) - 1)]),
             80, 312, CYAN, 11)
        bar(sc, 80, 336, 400, 16, p["xp"], XP_PER_RANK[min(p.get("rank", 0) + 1, len(XP_PER_RANK) - 1)], CYAN)
        text(sc, "HEAT", 80, 364, heatcol(p["heat"]), 12)
        bar(sc, 160, 366, 320, 16, p["heat"], 100, heatcol(p["heat"]))
        text(sc, "COL", 504, 312, MID, 11)
        for i in range(8):
            r = pygame.Rect(548 + (i % 4) * 44, 308 + (i // 4) * 36, 36, 32)
            pygame.draw.rect(sc, PCOLORS[i], r)
            pygame.draw.rect(sc, WHITE if i == p["color"] else BLACK, r, 1)
            self.hits.append((r, lambda i=i: self.set_color(i)))

    def d_forge(self):
        sc, p = self.scr, self.prof
        sc.fill(BG)
        for i, kind in enumerate(HARDWARE.keys()):
            br = pygame.Rect(16 + (i % 6) * 120, 8 + (i // 6) * 26, 112, 22)
            on = kind == self.pcb["sel"]
            pygame.draw.rect(sc, (16, 40, 40) if on else PANEL, br)
            pygame.draw.rect(sc, GREEN if on else DGREEN, br, 1)
            ctext(sc, HARDWARE[kind]["label"], br, GREEN if on else MID, 10)
            self.hits.append((br, lambda kind=kind: self.forge_load_blueprint(kind)))
        board = self.forge_board_rect()
        pygame.draw.rect(sc, (6, 22, 18), board)
        for gx in range(BOARD_W + 1):
            pygame.draw.line(sc, (12, 42, 32),
                             (board.x + gx * CELL, board.y),
                             (board.x + gx * CELL, board.y + BOARD_H * CELL), 1)
        for gy in range(BOARD_H + 1):
            pygame.draw.line(sc, (12, 42, 32),
                             (board.x, board.y + gy * CELL),
                             (board.x + BOARD_W * CELL, board.y + gy * CELL), 1)
        if self.pcb["dragging"]:
            c = self.forge_cell(self.mouse)
            if c:
                sx, sy = self.pcb["dragging"]
                col = {"power": RED, "data": CYAN, "signal": AMBER, "output": MAG}[self.pcb["wire_mode"]]
                x1 = board.x + sx * CELL + CELL // 2
                y1 = board.y + sy * CELL + CELL // 2
                x2 = board.x + c[0] * CELL + CELL // 2
                y2 = board.y + c[1] * CELL + CELL // 2
                pygame.draw.line(sc, dimc(col, .6), (x1, y1), (x2, y2), 1)
        for w in self.pcb["wires"]:
            (x1, y1, x2, y2) = w
            p1 = self.forge_part_at(x1, y1)
            p2 = self.forge_part_at(x2, y2)
            if not p1 or not p2:
                continue
            r1, r2 = PART_DEFS[p1["kind"]]["role"], PART_DEFS[p2["kind"]]["role"]
            if "power" in (r1, r2):
                col = RED
            elif "signal" in (r1, r2):
                col = AMBER
            elif "output" in (r1, r2):
                col = MAG
            else:
                col = CYAN
            ax = board.x + x1 * CELL + CELL // 2
            ay = board.y + y1 * CELL + CELL // 2
            bx = board.x + x2 * CELL + CELL // 2
            by = board.y + y2 * CELL + CELL // 2
            pygame.draw.line(sc, dimc(col, .4), (ax, ay), (ax, by), 2)
            pygame.draw.line(sc, dimc(col, .4), (ax, by), (bx, by), 2)
            pygame.draw.line(sc, col, (ax, ay), (ax, by), 1)
            pygame.draw.line(sc, col, (ax, by), (bx, by), 1)
            pygame.draw.circle(sc, col, (ax, ay), 2)
            pygame.draw.circle(sc, col, (bx, by), 2)
        for pt in self.pcb["parts"]:
            kind = pt["kind"]
            x = board.x + pt["x"] * CELL
            y = board.y + pt["y"] * CELL
            d = PART_DEFS[kind]
            pygame.draw.rect(sc, (10, 18, 20), (x + 1, y + 1, CELL - 2, CELL - 2))
            pygame.draw.rect(sc, d["col"], (x + 1, y + 1, CELL - 2, CELL - 2), 1)
            ctext(sc, d["label"][:2], (pt["x"] * CELL + board.x, pt["y"] * CELL + board.y, CELL, CELL), d["col"], 9)
        text(sc, "PARTS", W - 156, 28, CYAN, 11)
        for i, (kind, d) in enumerate(PART_DEFS.items()):
            tr = pygame.Rect(W - 156, 44 + i * 26, 140, 24)
            sel = self.pcb.get("tray_sel") == kind
            pygame.draw.rect(sc, (20, 40, 36) if sel else PANEL, tr)
            pygame.draw.rect(sc, d["col"] if sel else DGREEN, tr, 1)
            pygame.draw.rect(sc, d["col"], (tr.x + 3, tr.y + 2, 14, 14))
            text(sc, d["label"], tr.x + 24, tr.y + 4, d["col"] if sel else MID, 10)
            self.hits.append((tr, lambda kind=kind, d=d: (self.pcb.update({"tray_sel": kind, "wire_mode": d["role"]}), self.audio.sfx("wire"))))
        self.button((W - 312, 52, 68, 24), "CLR", self.forge_clear, AMBER, sz=11)
        self.button((W - 312, 84, 68, 24), "BUILD", self.forge_build, GREEN, sz=11)
        for i, mode in enumerate(("PWR", "DATA", "SIG", "OUT")):
            wr = pygame.Rect(W - 312, 116 + i * 24, 68, 22)
            colmap = {"PWR": RED, "DATA": CYAN, "SIG": AMBER, "OUT": MAG}
            on = {"PWR": "power", "DATA": "data", "SIG": "signal", "OUT": "output"}[mode] == self.pcb["wire_mode"]
            pygame.draw.rect(sc, (20, 40, 36) if on else PANEL, wr)
            pygame.draw.rect(sc, colmap[mode] if on else DGREEN, wr, 1)
            ctext(sc, mode, wr, colmap[mode] if on else MID, 10)
            self.hits.append((wr, lambda m=mode: (self.pcb.update({"wire_mode": {"PWR": "power", "DATA": "data", "SIG": "signal", "OUT": "output"}[m]}), self.audio.sfx("wire"))))
        bp = HARDWARE[self.pcb["sel"]]
        text(sc, "%s: %s" % (bp["label"], bp["desc"]), 16, 264, WHITE, 11)
        text(sc, "Cost $%d + %d scrap, %ds, rank %d" % (bp["cost"], bp["scrap"], bp["time"], bp["tech"]),
             16, 288, MID, 10)
        text(sc, "Wire: %s | %s" % (self.pcb["wire_mode"], fit(self.pcb["msg"], 700, 10)),
             16, 312, RED if self.pcb["err"] else CYAN, 10)
        text(sc, "GUIDE:", 16, 336, MID, 10)
        for i, (k, x, y) in enumerate(bp["parts"]):
            gxp = 96 + (i % 20) * 24
            gyp = 336 + (i // 20) * 20
            pygame.draw.rect(sc, dimc(PART_DEFS[k]["col"], .7), (gxp, gyp, 18, 14), 1)
            ctext(sc, PART_DEFS[k]["label"][:2], (gxp, gyp, 18, 14), PART_DEFS[k]["col"], 7)
        q = self.prof.get("buildq", [])
        if q:
            text(sc, "BUILDING:", 16, 372, CYAN, 10)
            for j, b in enumerate(q[:3]):
                bx = 120 + j * 100
                bar(sc, bx, 374, 88, 12, b["t"], b["dur"], GREEN)
                text(sc, HARDWARE[b["kind"]]["label"][:3], bx, 390, MID, 9)
        text(sc, "RANK %s  CASH %s  SCRAP %d  BOT %d" % (
            RANKS[self.prof.get("rank", 0)], money(self.prof["cash"]),
            int(self.prof.get("scrap", 0)), self.botnet_size()),
            16, 412, GREEN, 11)

    def d_botnet(self):
        sc, p = self.scr, self.prof
        panel(sc, (56, 32, 712, 400), title="BOTNET")
        bots = p.get("bots", [])
        text(sc, "DEVICES %d  //  LIVE BOTS %d" % (self.device_count_total(), len(bots)), 72, 48, GREEN, 12)
        text(sc, "+%s/s" % money(self.botnet_income()), 72, 76, AMBER, 12)
        y = 104
        for i, b in enumerate(bots[:12]):
            row = pygame.Rect(64, y + i * 24, 696, 22)
            pygame.draw.rect(sc, (10, 20, 22), row)
            pygame.draw.rect(sc, DGREEN, row, 1)
            state_col = {"idle": GREEN, "scanning": CYAN, "spreading": MAG, "traced": RED}[b["state"]]
            text(sc, b["ip"], row.x + 6, row.y + 4, WHITE, 11)
            text(sc, b["os"], row.x + 160, row.y + 4, MID, 10)
            text(sc, "L%d" % b["lvl"], row.x + 240, row.y + 4, CYAN, 10)
            text(sc, b["state"].upper(), row.x + 290, row.y + 4, state_col, 10)
            bar(sc, row.x + 400, row.y + 8, 80, 12, b["heat"], 100, heatcol(b["heat"]))
            self.button((row.right - 56, row.y + 2, 48, 20), "X",
                        lambda b=b: self._purge_bot(b), RED, True, 10)
        if len(bots) > 12:
            text(sc, "+%d more..." % (len(bots) - 12), 72, y + 12 * 24, DIM, 10)
        cost = 150 + 40 * len(bots)
        self.button((64, 352, 240, 32), "ACQUIRE  %s" % money(cost),
                    self.deploy_botnet, MAG, p["cash"] >= cost, 11)
        self.button((320, 352, 240, 32), "DEPLOY RAID",
                    self._botnet_raid, CYAN, len(bots) >= 3, 11)

    def d_jobs(self):
        sc, p = self.scr, self.prof
        panel(sc, (56, 32, 712, 400), title="CONTRACTS")
        if not p.get("contracts"):
            self.roll_contracts()
        for i, c in enumerate(p.get("contracts", [])[:3]):
            y = 48 + i * 112
            d = self.contract_def(c["id"])
            prog = self.contract_progress(c)
            goal = self.contract_goal(c)
            done = prog >= goal
            panel(sc, (72, y, 680, 100), GREEN if done else DGREEN)
            text(sc, fit(d["desc"], 500, 14), 88, y + 8, WHITE, 14)
            text(sc, "Reward: %s  +%d scrap  +%d ZD" % (money(d["cash"]), d["scrap"], d["zd"]),
                 88, y + 38, AMBER, 11)
            text(sc, "%d / %d" % (min(prog, goal), goal), 88, y + 66, CYAN, 11)
            bar(sc, 180, y + 72, 320, 14, prog, goal, GREEN if done else CYAN)
            self.button((600, y + 32, 140, 36), "CLAIM" if done else "...",
                        lambda c=c: self.claim_contract(c), GREEN, done, 12)
        text(sc, "Contracts refresh as you complete them.", 72, 392, DIM, 10)

    def d_ranks(self):
        sc, st = self.scr, self.net.state
        panel(sc, (56, 32, 712, 400), title="RANKINGS")
        rows = sorted(st["players"].items(), key=lambda kv: -(kv[1]["cash"] + 400 * kv[1]["nn"]))
        for i, (k, v) in enumerate(rows[:16]):
            y = 80 + i * 28
            if k == self.prof["id"]:
                pygame.draw.rect(sc, (16, 44, 36), (64, y - 4, 696, 26))
            text(sc, "%d" % (i + 1), 76, y, MID, 12)
            pygame.draw.circle(sc, PCOLORS[v["c"] % 10], (112, y + 8), 6)
            text(sc, v["n"], 128, y, WHITE, 12)
            text(sc, str(v["nn"]), 380, y, CYAN, 12)
            text(sc, money(v["cash"]), 500, y, AMBER, 12)

    def d_chat(self):
        sc, st = self.scr, self.net.state
        panel(sc, (56, 32, 712, 400), title="COMMS")
        rows = []
        for nm, m in st["chat"]:
            rows += wrap("<%s> %s" % (nm, m), 680, 12)
        for i, l in enumerate(rows[-20:]):
            text(sc, l, 68, 48 + i * 18, WHITE, 12)
        self.inp((64, 394, 580, 28), "chat")
        self.button((652, 394, 108, 28), "SEND",
                    lambda: (setattr(self, "field", "chat"), self.submit_field()), CYAN)

    def d_sys(self):
        sc = self.scr
        panel(sc, (56, 32, 712, 400), title="SYSTEM")
        for i, k in enumerate(("music", "sfx")):
            y = 60 + i * 48
            text(sc, k.upper(), 80, y + 6, WHITE, 14)
            self.button((220, y, 36, 32), "-", lambda k=k: self.vol(k, -1))
            bar(sc, 264, y + 6, 200, 20, self.cfg[k], 10, CYAN)
            self.button((472, y, 36, 32), "+", lambda k=k: self.vol(k, 1))
        self.button((80, 164, 200, 32), "UNMUTE" if self.audio.muted else "MUTE",
                    lambda: setattr(self.audio, "muted", not self.audio.muted))
        self.button((292, 164, 200, 32), "LEAVE GAME", self.leave, RED)
        self.button((80, 216, 400, 32), "RESET DAILY GLITCH",
                    lambda: (self.prof.__setitem__("daily_node", random.randrange(NODE_COUNT)),
                             self.prof.__setitem__("daily_used", False),
                             self.audio.sfx("daily")), CYAN)
        self.button((80, 268, 400, 32), "EXPORT SAVE",
                    lambda: (export_save(self.prof), self.toast("SAVE EXPORTED", GREEN)), AMBER)

    def d_data(self):
        sc, p = self.scr, self.prof
        panel(sc, (56, 32, 712, 400), title="DATA VAULT")
        text(sc, "INTEL", 80, 48, CYAN, 14)
        rows = [
            ("Nodes owned", sum(1 for n in self.net.state["nodes"] if n["o"] == p["id"])),
            ("Nodes visible", len(self.net.state["nodes"])),
            ("Enemies raided", p.get("session_raids", 0)),
            ("Breaches won", p.get("wins", 0)),
            ("Breaches attempted", p.get("hacks", 0)),
            ("Success rate", "%d%%" % (100 * p.get("wins", 0) // max(1, p.get("hacks", 1)))),
            ("Devices deployed", self.botnet_size()),
            ("Peak heat", int(p.get("peak_heat", p["heat"]))),
        ]
        for i, (a, b) in enumerate(rows):
            text(sc, a, 88, 80 + i * 24, MID, 12)
            text(sc, str(b), 460, 80 + i * 24, WHITE, 12)
        hist = p.setdefault("cash_hist", [])
        if not hist or self.t - hist[-1][0] > 5:
            hist.append([self.t, int(p["cash"])])
            del hist[:-60]
        text(sc, "CASH GRAPH", 88, 296, CYAN, 11)
        if len(hist) > 1:
            xs = [88 + i * (600 / max(1, len(hist) - 1)) for i in range(len(hist))]
            mx = max(1, max(v for _, v in hist))
            pts = [(int(x), 392 - int(80 * v / mx)) for x, (_, v) in zip(xs, hist)]
            pygame.draw.lines(sc, GREEN, False, pts, 1)

    def d_market(self):
        sc, p = self.scr, self.prof
        panel(sc, (56, 32, 712, 400), title="SCRAP MARKET")
        text(sc, "Trade scrap for gear — prices drift every 30s.", 72, 48, MID, 11)
        if not p.get("offers") or self.t - p.get("offer_t", 0) > 30:
            p["offer_t"] = self.t
            pool = [("ZERO-DAY", 12, "zd"), ("FIREWALL+", 20, "fw"),
                    ("RIG+", 25, "rig"), ("COOLANT", 6, "heat"),
                    ("CASH", 8, "cash")]
            random.shuffle(pool)
            p["offers"] = pool[:3]
        for i, (nm, price, key) in enumerate(p.get("offers", [])):
            y = 80 + i * 88
            panel(sc, (72, y, 680, 76), DGREEN)
            text(sc, nm, 88, y + 8, CYAN, 14)
            text(sc, "%d scrap" % price, 88, y + 40, AMBER, 12)
            have = int(p.get("scrap", 0))
            self.button((600, y + 20, 140, 36), "BUY" if have >= price else "...",
                        lambda nm=nm, price=price, key=key: self._market_buy(nm, price, key),
                        GREEN, have >= price)

    def d_study(self):
        sc, p = self.scr, self.prof
        panel(sc, (56, 32, 712, 400), title="STUDY / SKILL TREE")
        skills = [
            ("STEALTH", "Reduce heat gain by 20%", 400 * (p.get("sk_stealth", 0) + 1), "sk_stealth"),
            ("INTRUSION", "Breach speed +15%", 400 * (p.get("sk_intrusion", 0) + 1), "sk_intrusion"),
            ("CODING", "Forge time -20%", 400 * (p.get("sk_coding", 0) + 1), "sk_coding"),
            ("NETWORK", "Scan reveals +1 node", 400 * (p.get("sk_network", 0) + 1), "sk_network"),
        ]
        for i, (nm, desc, cost, key) in enumerate(skills):
            y = 60 + i * 84
            lvl = p.get(key, 0)
            panel(sc, (72, y, 680, 72), DGREEN)
            text(sc, "%s  Lv%d" % (nm, lvl), 88, y + 8, CYAN, 13)
            text(sc, fit(desc, 480, 11), 88, y + 36, MID, 11)
            self.button((600, y + 18, 140, 36), money(cost),
                        lambda key=key, cost=cost: self._buy_skill(key, cost),
                        AMBER, lvl < 5 and p["cash"] >= cost)

    def d_breach(self):
        sc, b = self.scr, self.breach
        g, nd = b["game"], self.net.state["nodes"][b["node"]]
        panel(sc, (8, 6, W - 16, 44), RED)
        text(sc, "BREACH // %s" % nd["n"].upper(), 20, 12, RED, 16)
        text(sc, "%s LVL %d" % (g.title, g.d), 20, 32, MID, 12)
        text(sc, "ZERO-DAY", W - 140, 12, CYAN, 12, "r")
        self.button((W - 130, 6, 120, 28), "USE Z-DAY", self.zero, CYAN, sz=10)
        if hasattr(g, "time"):
            left = g.time - g.t
            bar(sc, 300, 32, 240, 12, left, g.time, heatcol(100 - 100 * left / g.time))
        g.draw(sc)
        text(sc, fit(g.hint, W - 16, 12), W // 2, 410, DIM, 12, "c")

    async def run(self):
        self.audio.want = "menu"
        while True:
            dt = min(self.clock.tick(FPS) / 1000.0, .05)
            self.t += dt
            self.mouse = self.mpos(pygame.mouse.get_pos())
            for e in pygame.event.get():
                self.event(e)
            self.update(dt)
            self.draw()
            k, ox, oy, vw, vh = self.view()
            self.win.fill(BLACK)
            if vw > 0 and vh > 0:
                if (vw, vh) == (W, H):
                    self.win.blit(self.scr, (ox, oy))
                else:
                    self.win.blit(pygame.transform.scale(self.scr, (vw, vh)), (ox, oy))
            pygame.display.flip()
            await asyncio.sleep(0)


async def _run_game():
    game = Game()
    await game.run()


def _start_game():
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None and loop.is_running():
        # pygbag / already inside an event loop
        loop.create_task(_run_game())
    else:
        # desktop
        asyncio.run(_run_game())


if __name__ == "__main__":
    try:
        _start_game()
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        try:
            pygame.quit()
        except Exception:
            pass
        if sys.platform.startswith("win"):
            try:
                input("Press Enter to close...")
            except Exception:
                pass