"""
Hindi Video Generator — 4K UHD Edition with Quality Selection GUI
"""
import sys, os, time, math, random, json, copy, logging, subprocess, unicodedata
import importlib.util
from pathlib import Path

# Windows consoles / redirected output can use a legacy codepage and crash on emoji
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding='utf-8', errors='replace')
    except Exception: pass
from functools import lru_cache
from collections import deque
from concurrent.futures import ProcessPoolExecutor, as_completed

# ==========================================
# 1. DEPENDENCY CHECK
# ==========================================
REQUIRED = {'PIL': 'Pillow', 'numpy': 'numpy', 'moviepy': 'moviepy', 'imageio_ffmpeg': 'imageio-ffmpeg'}
AUTO_INSTALL = ('--install' in sys.argv) or (os.environ.get('HV_AUTO_INSTALL') == '1')

def _pip(pkg):
    subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-q"])

def check_deps():
    missing = [pkg for mod, pkg in REQUIRED.items() if importlib.util.find_spec(mod) is None]
    if missing:
        print("❌ Missing required packages:", ", ".join(missing))
        if AUTO_INSTALL:
            for p in missing: _pip(p)
        else:
            print("   Fix with: pip install " + " ".join(missing))
            sys.exit(1)
check_deps()

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageTk, ImageFilter
import tkinter as tk
from tkinter import filedialog

try:
    import uharfbuzz as hb
except Exception:
    hb = None

try:
    from moviepy.editor import VideoClip
except ImportError:
    from moviepy import VideoClip

# ==========================================
# 2. LOGGING
# ==========================================
BASE_DIR = Path(__file__).parent
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(BASE_DIR / "render.log", encoding='utf-8')],
)
log = logging.getLogger("hv")

# ==========================================
# 3. CONFIG
# ==========================================
CONFIG_PATH = BASE_DIR / "config.json"
DEFAULT_CONFIG = {
    "output": {"width": 3840, "height": 2160, "fps": 30, "duration": 12.0,
               "fade_out": 0.8, "preset": "ultrafast"},
    "timing": {"letter": 0.5, "se": 1.9, "word": 2.9, "clip": 4.5, "burst": 5.2},
    "layout": {"left_x": 320, "cx": 935, "cy": 520, "show_big_letter_left": True,
               "mascot_right_margin": 40, "mascot_bottom_offset": 60},
    "particles": {"num_mini": 28, "gravity": 1800},
    "colors": {"bg": [218, 228, 226], "letter": [230, 60, 20],
               "word": [230, 60, 20], "se": [30, 30, 30]},
    "workers": 2,
    "resume": True,
    "background_image": "",
    "only_letters": [],
    "mascot_path": "",
    "clipart_dir": "",
}

def _deep_merge(base, override):
    out = copy.deepcopy(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out

def save_config(cfg):
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception: pass

def load_config():
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                return _deep_merge(DEFAULT_CONFIG, json.load(f))
        except Exception as e:
            # Keep the user's file untouched (don't overwrite it) and fall back to defaults
            print(f"⚠ config.json could not be read ({e}). Using defaults.", file=sys.stderr)
            return copy.deepcopy(DEFAULT_CONFIG)
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    save_config(cfg)
    return cfg

def resolve_path(p):
    """Relative paths in config.json are relative to the project folder, not the current directory."""
    if not p: return ""
    q = Path(p).expanduser()
    return str(q if q.is_absolute() else BASE_DIR / q)

CFG = load_config()

# These will be overwritten by GUI
W, H = CFG['output']['width'], CFG['output']['height']
SCALE = W / 1920.0
FPS = CFG['output']['fps']

DURATION = CFG['output']['duration']
FADE_OUT = CFG['output']['fade_out']
PRESET = CFG['output']['preset']
T_LETTER, T_SE, T_WORD = CFG['timing']['letter'], CFG['timing']['se'], CFG['timing']['word']
T_CLIP, T_BURST = CFG['timing']['clip'], CFG['timing']['burst']

LEFT_X = int(CFG['layout']['left_x'] * SCALE)
CX, CY = int(CFG['layout']['cx'] * SCALE), int(CFG['layout']['cy'] * SCALE)
SHOW_BIG_LETTER_LEFT = CFG['layout']['show_big_letter_left']
MASCOT_RM = int(CFG['layout']['mascot_right_margin'] * SCALE)
MASCOT_BO = int(CFG['layout']['mascot_bottom_offset'] * SCALE)
NUM_MINI = CFG['particles']['num_mini']
GRAVITY = CFG['particles']['gravity'] * SCALE

BG_COLOR = tuple(CFG['colors']['bg'])
COLOR_LETTER = tuple(CFG['colors']['letter']) + (255,)
COLOR_WORD = tuple(CFG['colors']['word']) + (255,)
COLOR_SE = tuple(CFG['colors']['se']) + (255,)
BG_IMAGE_PATH = resolve_path(CFG.get('background_image', ''))
WORKERS = max(1, min(6, CFG.get('workers', 2)))
ONLY_LETTERS = CFG.get('only_letters', [])
RESUME = CFG.get('resume', True)

# ==========================================
# 4. FONT & TEXT RENDERING
# ==========================================
FONT_DIR = BASE_DIR / "fonts"
FONT_DIR.mkdir(exist_ok=True)
KHAND_BOLD = FONT_DIR / "Khand-Bold.ttf"

def get_font_path():
    if KHAND_BOLD.exists() and KHAND_BOLD.stat().st_size > 10000: return str(KHAND_BOLD)
    try:
        import urllib.request
        url = "https://github.com/google/fonts/raw/main/ofl/khand/Khand-Bold.ttf"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r, open(KHAND_BOLD, "wb") as f:
            f.write(r.read())
        if KHAND_BOLD.stat().st_size > 10000: return str(KHAND_BOLD)
    except Exception: pass
    for p in ["C:/Windows/Fonts/NirmalaB.ttf", "C:/Windows/Fonts/Nirmala.ttf"]:
        if os.path.exists(p): return p
    return None

FONT_PATH = get_font_path()

SS = 4
_HB = {}
_HB_FAIL = [False]

def _hb_ready():
    return hb is not None and FONT_PATH and not _HB_FAIL[0] and os.environ.get('HV_NO_HB') != '1'

def _hb_font():
    if 'f' not in _HB:
        with open(FONT_PATH, 'rb') as fh:
            blob = hb.Blob(fh.read())
        face = hb.Face(blob)
        _HB['f'] = (hb.Font(face), face.upem)
    return _HB['f']

class _Pen:
    def __init__(self): self.contours, self.cur = [], None
    def moveTo(self, pt): self._close(); self.cur = [tuple(pt)]
    def lineTo(self, pt): self.cur.append(tuple(pt))
    def qCurveTo(self, *pts):
        p0 = self.cur[-1]; offs, end = pts[:-1], pts[-1]
        for i, c in enumerate(offs):
            nxt = offs[i + 1] if i + 1 < len(offs) else None
            to = ((c[0] + nxt[0]) / 2, (c[1] + nxt[1]) / 2) if nxt else end
            for k in range(1, 9):
                t = k / 8
                self.cur.append(((1-t)**2*p0[0] + 2*(1-t)*t*c[0] + t*t*to[0],
                                 (1-t)**2*p0[1] + 2*(1-t)*t*c[1] + t*t*to[1]))
            p0 = to
    def curveTo(self, *pts):
        p0 = self.cur[-1]
        for i in range(0, len(pts) - 2, 3):
            c1, c2, to = pts[i], pts[i+1], pts[i+2]
            for k in range(1, 11):
                t = k / 10; u = 1 - t
                self.cur.append((u**3*p0[0] + 3*u*u*t*c1[0] + 3*u*t*t*c2[0] + t**3*to[0],
                                 u**3*p0[1] + 3*u*u*t*c1[1] + 3*u*t*t*c2[1] + t**3*to[1]))
            p0 = to
    def _close(self):
        if self.cur and len(self.cur) > 2: self.contours.append(self.cur)
        self.cur = None
    def closePath(self): self._close()
    def endPath(self): self._close()

_GLYPHS = {}
def _glyph_polys(gid):
    if gid in _GLYPHS: return _GLYPHS[gid]
    font, _ = _hb_font()
    pen = _Pen(); font.draw_glyph_with_pen(gid, pen); pen._close()
    def area(c):
        n = len(c)
        return sum(c[i][0]*c[(i+1)%n][1] - c[(i+1)%n][0]*c[i][1] for i in range(n)) / 2
    areas = [area(c) for c in pen.contours]
    pos, neg = [], []
    if areas:
        outer_pos = areas[max(range(len(areas)), key=lambda i: abs(areas[i]))] > 0
        for c, a in zip(pen.contours, areas):
            (pos if (a > 0) == outer_pos else neg).append(c)
    _GLYPHS[gid] = (pos, neg); return _GLYPHS[gid]

def render_text_hb(text, size, color):
    font, upem = _hb_font()
    buf = hb.Buffer(); buf.add_str(text); buf.guess_segment_properties()
    hb.shape(font, buf)
    placed, x = [], 0
    minx = miny = 1e18; maxx = maxy = -1e18
    for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
        P, N = _glyph_polys(info.codepoint)
        ox, oy = x + pos.x_offset, pos.y_offset
        for poly in P:
            for px, py in poly:
                minx, maxx = min(minx, ox+px), max(maxx, ox+px)
                miny, maxy = min(miny, oy+py), max(maxy, oy+py)
        placed.append((P, N, ox, oy)); x += pos.x_advance
    if minx > maxx: return Image.new('RGBA', (10, 10), tuple(color[:3]) + (0,))
    s = size / upem * SS
    PAD = 10 * SS
    w = int((maxx - minx) * s) + 2 * PAD + SS
    h = int((maxy - miny) * s) + 2 * PAD + SS
    w += (-w) % SS; h += (-h) % SS
    full = Image.new('L', (w, h), 0)
    for P, N, ox, oy in placed:
        if not P: continue
        def tx(p): return ((ox + p[0] - minx) * s + PAD, (maxy - (oy + p[1])) * s + PAD)
        P2 = [[tx(p) for p in poly] for poly in P]
        N2 = [[tx(p) for p in poly] for poly in N]
        xs = [p[0] for poly in P2 for p in poly]
        ys = [p[1] for poly in P2 for p in poly]
        gx0, gy0 = int(min(xs)) - 2, int(min(ys)) - 2
        gw, gh = int(max(xs)) - gx0 + 3, int(max(ys)) - gy0 + 3
        gm = Image.new('L', (gw, gh), 0); d = ImageDraw.Draw(gm)
        for poly in P2: d.polygon([(a - gx0, b - gy0) for a, b in poly], fill=255)
        for poly in N2: d.polygon([(a - gx0, b - gy0) for a, b in poly], fill=0)
        full.paste(255, (gx0, gy0), gm)
    mask = full.resize((w // SS, h // SS), Image.Resampling.LANCZOS)
    out = Image.new('RGBA', mask.size, tuple(color[:3]) + (0,))
    out.putalpha(mask)
    return out

@lru_cache(maxsize=None)
def get_font(size):
    try: return ImageFont.truetype(FONT_PATH, size)
    except Exception: return ImageFont.load_default()

def render_text_pil(text, size, color):
    font = get_font(size)
    tmp = Image.new('RGBA', (1, 1))
    bbox = ImageDraw.Draw(tmp).textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0] + 20, bbox[3] - bbox[1] + 20
    img = Image.new('RGBA', (max(w, 10), max(h, 10)), tuple(color[:3]) + (0,))
    ImageDraw.Draw(img).text((10 - bbox[0], 10 - bbox[1]), text, font=font, fill=color)
    return img

@lru_cache(maxsize=None)
def render_text(text, size, color):
    if _hb_ready():
        try: return render_text_hb(text, size, color)
        except Exception: _HB_FAIL[0] = True
    return render_text_pil(text, size, color)

# ==========================================
# 5. EASING + DRAW HELPERS
# ==========================================
def clamp01(x): return max(0.0, min(1.0, x))
def ease_out_cubic(x): x = clamp01(x); return 1 - (1 - x) ** 3
def ease_out_back(x, c1=1.2):
    x = clamp01(x); c3 = c1 + 1
    return 1 + c3 * ((x - 1) ** 3) + c1 * ((x - 1) ** 2)
def hop(t, t0, height, dur=0.55):
    p = (t - t0) / dur
    return -height * math.sin(math.pi * p) if 0 <= p <= 1 else 0.0

def _premul(spr):
    try: return spr.convert('RGBa')
    except Exception: return spr
def _unpremul(spr):
    return spr.convert('RGBA') if spr.mode != 'RGBA' else spr

def paste_center(img, spr, cx, cy, scale=1.0, alpha=1.0, angle=0.0, scale_x=None, scale_y=None):
    if spr is None or alpha <= 0.01: return
    if scale_x is None: scale_x = scale
    if scale_y is None: scale_y = scale
    if scale_x <= 0.01 or scale_y <= 0.01: return
    if angle:
        spr = _unpremul(_premul(spr).rotate(angle, expand=True, resample=Image.Resampling.BICUBIC))
    if abs(scale_x - 1.0) > 0.001 or abs(scale_y - 1.0) > 0.001:
        w, h = max(1, int(spr.width * scale_x)), max(1, int(spr.height * scale_y))
        spr = spr.resize((w, h), Image.Resampling.BILINEAR)
    if alpha < 0.999:
        spr = spr.copy()
        spr.putalpha(spr.getchannel('A').point(lambda p: int(p * alpha)))
    x0, y0 = cx - spr.width / 2, cy - spr.height / 2
    ix, iy = math.floor(x0), math.floor(y0)
    fx, fy = x0 - ix, y0 - iy
    if fx > 0.04 or fy > 0.04:
        spr = _unpremul(_premul(spr).transform((spr.width + 1, spr.height + 1),
                          Image.Transform.AFFINE, (1, 0, -fx, 0, 1, -fy),
                          resample=Image.Resampling.BILINEAR))
    img.paste(spr, (ix, iy), spr)

def fit_inside(spr, max_w, max_h):
    s = min(max_w / spr.width, max_h / spr.height, 1.0)
    if s < 1.0:
        spr = spr.resize((max(1, int(spr.width * s)), max(1, int(spr.height * s))), Image.Resampling.LANCZOS)
    return spr

# ==========================================
# 6. BACKGROUND & CARDS
# ==========================================
@lru_cache(maxsize=None)
def _vignette_mask():
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    d = np.sqrt(((xx - W/2)/(W/2))**2 + ((yy - H/2)/(H/2))**2) / math.sqrt(2)
    vig = np.clip((d - 0.5) * 1.4, 0, 0.35)
    return Image.fromarray((vig * 255).astype(np.uint8), mode='L')

@lru_cache(maxsize=None)
def _bg_base():
    if BG_IMAGE_PATH and os.path.exists(BG_IMAGE_PATH):
        bg = Image.open(BG_IMAGE_PATH).convert('RGBA').resize((W, H), Image.Resampling.LANCZOS)
    else:
        bg = Image.new('RGBA', (W, H), BG_COLOR + (255,))
    dark = Image.new('RGBA', (W, H), (0, 0, 0, 255))
    dark.putalpha(_vignette_mask())
    bg = bg.copy(); bg.alpha_composite(dark)
    return bg

def get_background(): return _bg_base().copy()

@lru_cache(maxsize=None)
def text_card_sprite(w, h):
    pad = int(50 * SCALE)
    size = (w + pad*2, h + pad*2)
    out = Image.new('RGBA', size, (0, 0, 0, 0))
    
    # Shadow
    sh = Image.new('L', size, 0)
    ImageDraw.Draw(sh).rounded_rectangle([pad, pad+int(10*SCALE), pad+w, pad+h], radius=int(40*SCALE), fill=120)
    sh = sh.filter(ImageFilter.GaussianBlur(int(15*SCALE)))
    out.paste(Image.new('RGBA', size, (0,0,0,255)), (0,0), sh)
    
    # Card
    card = Image.new('RGBA', size, (0, 0, 0, 0))
    ImageDraw.Draw(card).rounded_rectangle([pad, pad, pad+w, pad+h], radius=int(40*SCALE), fill=(255, 255, 255, 245))
    out.alpha_composite(card)
    return out

# ==========================================
# 7. SPARKLES & RING
# ==========================================
@lru_cache(maxsize=None)
def star_sprite(size, color):
    n = size * 4; mask = Image.new('L', (n, n), 0); c = n / 2
    pts = []
    for i in range(8):
        r = c * 0.98 if i % 2 == 0 else c * 0.28
        a = i * math.pi / 4 - math.pi / 2
        pts.append((c + r * math.cos(a), c + r * math.sin(a)))
    ImageDraw.Draw(mask).polygon(pts, fill=255)
    mask = mask.resize((size, size), Image.Resampling.LANCZOS)
    out = Image.new('RGBA', (size, size), tuple(color[:3]) + (0,))
    out.putalpha(mask); return out

_STAR_COLORS = [(255, 190, 30), (255, 120, 40), (240, 70, 100), (60, 170, 220)]
SPARKS = []
def build_sparks():
    _srng = random.Random(7)
    SPARKS.clear()
    for _i in range(12):
        SPARKS.append(dict(angle=_i * (2*math.pi/12) + _srng.uniform(-0.2, 0.2),
                           size=int(_srng.choice([44, 56, 70]) * SCALE),
                           color=_srng.choice(_STAR_COLORS),
                           delay=_srng.uniform(0, 0.15)))
build_sparks()

def draw_sparkles(img, t, t0, cx, cy, radius):
    for s in SPARKS:
        dt = t - t0 - s['delay']
        if dt < 0 or dt > 0.9: continue
        p = dt / 0.9
        r = radius * (0.35 + 0.65 * ease_out_cubic(p))
        x, y = cx + math.cos(s['angle']) * r, cy + math.sin(s['angle']) * r
        a = clamp01(dt / 0.08) * (1 - p)
        paste_center(img, star_sprite(s['size'], s['color']), x, y,
                     scale=1.0 - 0.4 * p, alpha=a, angle=120 * p)

def draw_ring(img, t, t0, cx, cy):
    p = (t - t0) / 0.8
    if p < 0 or p > 1: return
    r = int((120 + 360 * ease_out_cubic(p)) * SCALE)
    a = int(255 * (1 - p) * 0.8)
    wd = max(2, int(14 * (1 - p) * SCALE))
    size = int(2 * r) + wd * 2 + 4
    ring = Image.new('RGBA', (size, size), (255, 196, 64, 0))
    d = ImageDraw.Draw(ring)
    d.ellipse([wd+2, wd+2, size-wd-3, size-wd-3], outline=(255, 196, 64, a), width=wd)
    img.paste(ring, (int(cx - size/2), int(cy - size/2)), ring)

# ==========================================
# 8. SLATE DETECTION & GUI
# ==========================================
def find_slate(mascot_img, box, tol=1.0):
    arr = np.array(mascot_img.convert('RGBA')).astype(np.int16)
    R, G, B, A = arr[..., 0], arr[..., 1], arr[..., 2], arr[..., 3]
    mask = (A > 200) & (R > max(60, int(150 - 30 * (tol - 1.0)))) & (R - G > max(30, int(95 - 20 * (tol - 1.0)))) & (R - B > max(40, int(110 - 20 * (tol - 1.0)))) & (G < min(220, int(140 + 30 * (tol - 1.0))))
    ds = 3; small = mask[::ds, ::ds]
    h, w = small.shape
    bx, by, bw, bh = box
    cx, cy = (bx + bw/2)/ds, (by + bh/2)/ds
    ys, xs = np.nonzero(small)
    if len(xs) == 0: return None
    i = int(np.argmin((xs - cx)**2 + (ys - cy)**2))
    if ((xs[i] - cx)**2 + (ys[i] - cy)**2) ** 0.5 * ds > max(bw, bh) * 1.2: return None
    visited = np.zeros_like(small, dtype=bool)
    dq = deque([(int(ys[i]), int(xs[i]))]); visited[ys[i], xs[i]] = True
    pts = []
    while dq:
        y, x = dq.popleft(); pts.append((x, y))
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                ny, nx = y + dy, x + dx
                if 0 <= ny < h and 0 <= nx < w and small[ny, nx] and not visited[ny, nx]:
                    visited[ny, nx] = True; dq.append((ny, nx))
    if len(pts) < 150: return None
    P = np.array(pts, dtype=np.float64) * ds
    mean = P.mean(axis=0)
    vals, vecs = np.linalg.eigh(np.cov((P - mean).T))
    u = vecs[:, int(np.argmax(vals))]
    n = np.array([-u[1], u[0]])
    theta = math.degrees(math.atan2(u[1], u[0]))
    if theta > 90: theta -= 180
    elif theta <= -90: theta += 180
    pu, pn = (P - mean) @ u, (P - mean) @ n
    p1, p2 = np.percentile(pu, [1, 99])
    q1, q2 = np.percentile(pn, [1, 99])
    center = mean + u * (p1 + p2) / 2 + n * (q1 + q2) / 2
    return (float(center[0]), float(center[1]), float(p2 - p1), float(q2 - q1), theta)

def _get_corners(cx, cy, w, h, tilt_deg):
    a = math.radians(tilt_deg); ca, sa = math.cos(a), math.sin(a)
    hw, hh = w/2, h/2
    return [(cx + lx*ca - ly*sa, cy + lx*sa + ly*ca) for lx, ly in [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]]

def slate_preview_gui(mascot_img, initial_info):
    orig_w, orig_h = mascot_img.size
    scale = min(900/orig_w, 650/orig_h, 1.0)
    disp_w, disp_h = int(orig_w*scale), int(orig_h*scale)

    bg = Image.new('RGBA', (disp_w, disp_h), (210, 210, 210, 255))
    disp = mascot_img.resize((disp_w, disp_h), Image.Resampling.LANCZOS)
    bg.alpha_composite(disp)

    root = tk.Tk()
    root.title("Slate Preview")
    root.attributes('-topmost', True)
    tk_img = ImageTk.PhotoImage(bg.convert('RGB'), master=root)
    canvas = tk.Canvas(root, width=disp_w, height=disp_h, bg='gray')
    canvas.pack()
    canvas.create_image(0, 0, anchor=tk.NW, image=tk_img)
    canvas.image = tk_img

    state = {'cx': initial_info[0] if initial_info else orig_w/2, 'cy': initial_info[1] if initial_info else orig_h/2,
             'w': initial_info[2] if initial_info else orig_w*0.4, 'h': initial_info[3] if initial_info else orig_h*0.25,
             'tilt': initial_info[4] if initial_info else 0.0, 'tolerance': 1.0, 'drag_mode': None, 'drag_start': None, 'drag_center': None, 'drag_opp': None}
    rect_id, handle_ids = [None], []
    status_var = tk.StringVar()

    def to_disp(x, y): return x * scale, y * scale
    def to_orig(x, y): return x / scale, y / scale

    def draw_rect():
        if rect_id[0]: canvas.delete(rect_id[0])
        for hid in handle_ids: canvas.delete(hid)
        handle_ids.clear()
        corners = _get_corners(state['cx'], state['cy'], state['w'], state['h'], state['tilt'])
        dc = [to_disp(x, y) for x, y in corners]
        flat = [c for pair in dc for c in pair]
        rect_id[0] = canvas.create_polygon(flat, outline='cyan', fill='', width=3)
        for x, y in dc: handle_ids.append(canvas.create_oval(x-7, y-7, x+7, y+7, fill='white', outline='black', width=2))
        status_var.set(f"Center ({state['cx']:.0f}, {state['cy']:.0f}) Size {state['w']:.0f}×{state['h']:.0f} Tilt {state['tilt']:.1f}°")

    def point_in_rect(px, py):
        c = _get_corners(state['cx'], state['cy'], state['w'], state['h'], state['tilt'])
        inside = False; n = len(c)
        for i in range(n):
            x1, y1 = c[i]; x2, y2 = c[(i+1) % n]
            if ((y1 > py) != (y2 > py)) and (px < (x2-x1)*(py-y1)/(y2-y1)+x1): inside = not inside
        return inside

    def nearest_handle(px, py):
        c = _get_corners(state['cx'], state['cy'], state['w'], state['h'], state['tilt'])
        thr = (15 / scale) ** 2
        for i, (x, y) in enumerate(c):
            if (x-px)**2 + (y-py)**2 < thr: return i
        return -1

    def on_press(e):
        ox, oy = to_orig(e.x, e.y)
        hidx = nearest_handle(ox, oy)
        if hidx >= 0:
            state['drag_mode'] = 'resize'
            state['drag_opp'] = _get_corners(state['cx'], state['cy'], state['w'], state['h'], state['tilt'])[(hidx + 2) % 4]
        elif point_in_rect(ox, oy):
            state['drag_mode'] = 'move'; state['drag_start'] = (ox, oy); state['drag_center'] = (state['cx'], state['cy'])
        else: state['drag_mode'] = None

    def on_drag(e):
        if not state['drag_mode']: return
        ox, oy = to_orig(e.x, e.y)
        if state['drag_mode'] == 'move':
            sx, sy = state['drag_start']; c0x, c0y = state['drag_center']
            state['cx'], state['cy'] = c0x + (ox - sx), c0y + (oy - sy)
        else:
            fx, fy = state['drag_opp']
            a = math.radians(-state['tilt'])
            dx, dy = ox - fx, oy - fy
            lx = dx*math.cos(a) - dy*math.sin(a)
            ly = dx*math.sin(a) + dy*math.cos(a)
            state['cx'], state['cy'] = (fx + ox)/2, (fy + oy)/2
            state['w'] = max(20, abs(lx)); state['h'] = max(20, abs(ly))
        draw_rect()

    def on_release(e): state['drag_mode'] = None
    def redetect():
        info = find_slate(mascot_img, (0, 0, orig_w, orig_h), tol=state['tolerance'])
        if info: state['cx'], state['cy'], state['w'], state['h'], state['tilt'] = info
        draw_rect()
    def confirm(): root.result = (state['cx'], state['cy'], state['w'], state['h'], state['tilt']); root.destroy()
    def cancel(): root.result = None; root.destroy()

    canvas.bind("<ButtonPress-1>", on_press); canvas.bind("<B1-Motion>", on_drag); canvas.bind("<ButtonRelease-1>", on_release)
    tk.Label(root, textvariable=status_var, font=("Arial", 10)).pack(pady=4)
    ctrl = tk.Frame(root); ctrl.pack(pady=4)
    tk.Label(ctrl, text="Tolerance:").pack(side=tk.LEFT)
    tk.Scale(ctrl, from_=0.5, to=2.0, resolution=0.1, orient=tk.HORIZONTAL, length=200, command=lambda v: state.update(tolerance=float(v))).pack(side=tk.LEFT, padx=5)
    tk.Button(ctrl, text="🔍 Redo Detection", command=redetect).pack(side=tk.LEFT, padx=5)
    btns = tk.Frame(root); btns.pack(pady=8)
    tk.Button(btns, text="✅ Use This", command=confirm, bg='green', fg='white', font=("Arial", 12, "bold"), width=15).pack(side=tk.LEFT, padx=5)
    tk.Button(btns, text="❌ Cancel", command=cancel, bg='red', fg='white', font=("Arial", 12, "bold"), width=15).pack(side=tk.LEFT, padx=5)

    root.result = None; draw_rect(); root.mainloop()
    return root.result

def quality_selection_gui():
    root = tk.Tk()
    root.title("Video Quality Select")
    root.geometry("350x250")
    root.attributes('-topmost', True)
    root.eval('tk::PlaceWindow . center')

    res_var = tk.StringVar(value="4K UHD (Fast Export)")
    fps_var = tk.IntVar(value=30)

    tk.Label(root, text="Select Resolution:", font=("Arial", 11, "bold")).pack(pady=(15,5))
    tk.OptionMenu(root, res_var, "1080p (1920x1080)", "2K QHD (2560x1440)", "4K UHD (Fast Export)").pack(pady=5)

    tk.Label(root, text="Select FPS:", font=("Arial", 11, "bold")).pack(pady=5)
    tk.OptionMenu(root, fps_var, 30, 60).pack(pady=5)

    result = {}
    def on_start():
        r = res_var.get()
        if "1080p" in r: result['res'] = (1920, 1080)
        elif "2K" in r: result['res'] = (2560, 1440)
        else: result['res'] = (3840, 2160)
        result['fps'] = fps_var.get()
        root.destroy()

    tk.Button(root, text="🚀 Start Rendering", command=on_start, bg='green', fg='white', font=("Arial", 12, "bold"), width=20).pack(pady=15)
    root.mainloop()
    return result.get('res'), result.get('fps', 30)

# ==========================================
# 9. CACHE & HINDI DATA
# ==========================================
SLATE_CACHE_PATH = BASE_DIR / "slate_cache.json"
def get_slate_cached(mascot_path):
    try:
        key = f"{mascot_path}|{os.path.getmtime(mascot_path)}"
        if SLATE_CACHE_PATH.exists():
            with open(SLATE_CACHE_PATH) as f: return tuple(json.load(f).get(key, [])) or None
    except Exception: pass
    return None

def save_slate_cache(mascot_path, info):
    try:
        key = f"{mascot_path}|{os.path.getmtime(mascot_path)}"
        cache = {}
        if SLATE_CACHE_PATH.exists():
            with open(SLATE_CACHE_PATH) as f: cache = json.load(f)
        cache[key] = list(info)
        with open(SLATE_CACHE_PATH, 'w') as f: json.dump(cache, f, indent=2)
    except Exception: pass

HINDI_DATA = [
    ("अ", "अनार"), ("आ", "आम"), ("इ", "इमली"), ("ई", "ईख"), ("उ", "उल्लू"), ("ऊ", "ऊन"),
    ("ऋ", "ऋषि"), ("ए", "एड़ी"), ("ऐ", "ऐनक"), ("ओ", "ओखली"), ("औ", "औरत"), ("अं", "अंगूर"), ("अः", ""),
    ("क", "कबूतर"), ("ख", "खरगोश"), ("ग", "गमला"), ("घ", "घड़ी"),
    ("ङ", ""), ("च", "चरखा"), ("छ", "छतरी"), ("ज", "जहाज"), ("झ", "झंडा"),
    ("ञ", ""), ("ट", "टमाटर"), ("ठ", "ठठेरा"), ("ड", "डमरू"), ("ढ", "ढक्कन"),
    ("ण", ""), ("त", "तरबूज"), ("थ", "थाली"), ("द", "दवात"), ("ध", "धनुष"), ("न", "नल"),
    ("प", "पतंग"), ("फ", "फल"), ("ब", "बतख"), ("भ", "भालू"), ("म", "मछली"),
    ("य", "यज्ञ"), ("र", "रथ"), ("ल", "लट्टू"), ("व", "वकील"),
    ("श", "शेर"), ("ष", "षट्कोण"), ("स", "सेब"), ("ह", "हल"),
    ("क्ष", "क्षत्रिय"), ("त्र", "त्रिशूल"), ("ज्ञ", "ज्ञानी")
]

# ==========================================
# 10. 3D LETTER & MASCOT
# ==========================================
@lru_cache(maxsize=None)
def make_3d_letter(letter, font_size, angle):
    face = render_text(letter, font_size, (255, 255, 255, 255))
    depth = max(2, int(font_size * 0.035))
    pad = depth * 3 + 16
    size = (face.width + pad * 2, face.height + pad * 2)
    mask = face.getchannel('A')
    out = Image.new('RGBA', size, (0, 0, 0, 0))
    sh = Image.new('L', size, 0)
    sh.paste(255, (pad + depth + 2, pad + depth + 2), mask)
    sh = sh.filter(ImageFilter.GaussianBlur(int(3 * SCALE))).point(lambda p: int(p * 0.35))
    out.paste(Image.new('RGBA', size, (0, 0, 0, 255)), (0, 0), sh)
    edge = Image.new('L', size, 0)
    for k in range(1, depth + 1): edge.paste(255, (pad + k, pad + k), mask)
    out.paste(Image.new('RGBA', size, (150, 130, 120, 255)), (0, 0), edge)
    out.alpha_composite(face, (pad, pad))
    return out.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)

def make_mascot_with_letter(mascot_img, slate_info, letter, target_h=None):
    if target_h is None: target_h = int(700 * SCALE)
    cx, cy, sw, sh, theta = slate_info
    s = target_h / mascot_img.height
    m = mascot_img.resize((int(mascot_img.width * s), target_h), Image.Resampling.LANCZOS)
    ref = render_text(letter, 200, (255, 255, 255, 255))
    rw, rh = ref.width - 20, ref.height - 20
    k = min(sw * s * 0.5 / rw, sh * s * 0.62 / rh)
    font_size = max(20, int(200 * k))
    spr = make_3d_letter(letter, font_size, round(-theta, 1))
    m.paste(spr, (int(cx * s - spr.width / 2), int(cy * s - spr.height / 2)), spr)
    return m

# ==========================================
# 11. PARTICLES
# ==========================================
PARTICLES = []
def build_particles():
    _rng = random.Random(42)
    PARTICLES.clear()
    for _ in range(NUM_MINI):
        ang = _rng.uniform(math.radians(200), math.radians(340))
        spd = _rng.uniform(500, 1000) * SCALE
        PARTICLES.append(dict(
            vx=math.cos(ang) * spd * 1.3, vy=math.sin(ang) * spd,
            scale=_rng.uniform(0.55, 1.0), rot0=_rng.uniform(0, 360),
            rotv=_rng.uniform(-300, 300), delay=_rng.uniform(0, 0.25)))
build_particles()

def apply_resolution(w, h, fps):
    """Single place that sets every resolution-dependent global.
    Called in main() AND in every worker (spawn re-imports the module)."""
    global W, H, FPS, SCALE, LEFT_X, CX, CY, MASCOT_RM, MASCOT_BO, GRAVITY
    W, H, FPS = w, h, fps
    SCALE = W / 1920.0
    LEFT_X = int(CFG['layout']['left_x'] * SCALE)
    CX, CY = int(CFG['layout']['cx'] * SCALE), int(CFG['layout']['cy'] * SCALE)
    MASCOT_RM = int(CFG['layout']['mascot_right_margin'] * SCALE)
    MASCOT_BO = int(CFG['layout']['mascot_bottom_offset'] * SCALE)
    GRAVITY = CFG['particles']['gravity'] * SCALE
    _bg_base.cache_clear(); _vignette_mask.cache_clear(); text_card_sprite.cache_clear()
    build_sparks(); build_particles()

# ==========================================
# 12. FRAME RENDERER
# ==========================================
def create_frame(t, ctx):
    img = get_background()

    m = ctx.get('mascot')
    if m is not None:
        idle_y = 6 * SCALE * math.sin(2 * math.pi * t / 2.4)
        idle_rot = 1.0 * math.sin(2 * math.pi * t / 3.5)
        dy = idle_y + hop(t, T_LETTER + 0.8, 22 * SCALE) + hop(t, T_CLIP + 0.1, 40 * SCALE)
        paste_center(img, m, W - m.width // 2 - MASCOT_RM, H // 2 + MASCOT_BO + dy, angle=idle_rot)

    if t >= T_LETTER:
        card_alpha = clamp01((t - T_LETTER) * 2) * 0.95
        paste_center(img, ctx['text_card'], LEFT_X, int(540 * SCALE), alpha=card_alpha)

    if SHOW_BIG_LETTER_LEFT and t >= T_LETTER:
        prog = (t - T_LETTER) / 1.1
        angle = 360 * (1 - ease_out_cubic(prog))
        # Letter drop Y updated to 340 to stay inside the card
        y = int(-260 * SCALE) + (int(340 * SCALE) + int(260 * SCALE)) * ease_out_back(prog, 0.9)
        tt = t - T_LETTER - 1.1
        sq = math.exp(-tt * 5) * math.sin(tt * 20) * 0.10 if tt > 0 else 0.0
        pulse = 1 + 0.03 * math.sin(2 * math.pi * tt / 1.8) * clamp01(tt / 0.5) if tt > 0 else 1.0
        paste_center(img, ctx['letter'], LEFT_X, y, scale_x=(1 + sq) * pulse, scale_y=(1 - sq) * pulse, angle=angle, alpha=clamp01(prog * 4))
        draw_sparkles(img, t, T_LETTER + 0.75, LEFT_X, int(340 * SCALE), int(280 * SCALE))

    if ctx.get('has_word'):
        if t >= T_SE:
            p = ease_out_cubic((t - T_SE) / 0.7)
            paste_center(img, ctx['se'], LEFT_X, int(550 * SCALE), alpha=p)
        if t >= T_WORD:
            p = (t - T_WORD) / 0.8
            # Word drop Y updated to 780
            paste_center(img, ctx['word'], LEFT_X, int(780 * SCALE) + int(30 * SCALE) * (1 - ease_out_cubic(p)), scale=0.7 + 0.3 * ease_out_back(p, 1.5), alpha=clamp01(p * 2))

    if ctx.get('mini') is not None:
        for p in PARTICLES:
            dt = t - T_BURST - p['delay']
            if dt < 0: continue
            x = CX + p['vx'] * dt
            y = CY + p['vy'] * dt + 0.5 * GRAVITY * dt * dt
            if y > H + 150 or x < -150 or x > W + 150: continue
            paste_center(img, ctx['mini'], x, y, scale=p['scale'], alpha=clamp01(dt / 0.12), angle=p['rot0'] + p['rotv'] * dt)

    if t >= T_CLIP:
        draw_ring(img, t, T_CLIP, CX, CY)

    if ctx.get('clip') is not None and t >= T_CLIP:
        p = (t - T_CLIP) / 0.8
        tt = t - T_CLIP - 0.8
        bob = 9 * SCALE * math.sin(2 * math.pi * tt / 2.6) * clamp01(tt / 0.6) if tt > 0 else 0.0
        jiggle = 10 * (1 - clamp01(p)) * math.sin(clamp01(p) * math.pi * 2.5)
        sq = math.exp(-tt * 5) * math.sin(tt * 20) * 0.08 if tt > 0 else 0.0
        base = ease_out_back(p, 1.9) if p < 1 else 1.0

        if p > 0.5:
            shadow = ctx['clip_shadow']
            paste_center(img, shadow, CX, CY + bob + int(25 * SCALE), scale_x=base * (1 + sq), scale_y=base * (1 - sq))

        paste_center(img, ctx['clip'], CX, CY + bob, scale_x=base * (1 + sq), scale_y=base * (1 - sq), angle=jiggle, alpha=clamp01(p * 3))
        draw_sparkles(img, t, T_CLIP + 0.2, CX, CY, int(340 * SCALE))

    if t > DURATION - FADE_OUT:
        a = clamp01((DURATION - t) / FADE_OUT)
        img = Image.blend(get_background(), img, a)

    return np.array(img.convert('RGB'))

# ==========================================
# 13. CLIPART MATCHING
# ==========================================
_EXTS = ('.png', '.jpg', '.jpeg', '.webp')
_DIR_INDEX = {}

def _norm(s): return unicodedata.normalize('NFC', s)

def find_clipart(clipart_dir, letter, word):
    if clipart_dir not in _DIR_INDEX:
        idx = {}
        for p in Path(clipart_dir).iterdir():
            if p.suffix.lower() in _EXTS: idx.setdefault(_norm(p.stem), p)
        _DIR_INDEX[clipart_dir] = idx
    idx = _DIR_INDEX[clipart_dir]
    for name in (word, letter):
        if _norm(name) in idx: return idx[_norm(name)]
    return None

def precheck_clipart(hindi_data, clipart_dir, only_letters):
    found, missing = [], []
    for i, (letter, word) in enumerate(hindi_data):
        if only_letters and letter not in only_letters: continue
        if not word:
            found.append((i, letter, word, None))
            continue
        p = find_clipart(clipart_dir, letter, word)
        if p is None: missing.append((letter, word))
        else: found.append((i, letter, word, p))
    return found, missing

def print_precheck(found, missing):
    print("\n" + "=" * 60)
    print("📋 CLIPART PRE-CHECK")
    print("=" * 60)
    print(f"✔ Found/Ready: {len(found)}")
    print(f"✖ Missing:     {len(missing)}")
    if missing:
        print("\nMissing cliparts (skipped):")
        for letter, word in missing: print(f"   {letter} → {word}.png")
    print("=" * 60)

# ==========================================
# 14. RENDER WORKER
# ==========================================
_WORKER_CACHE = {}

def is_done(path):
    try: return path.exists() and path.stat().st_size > 100000
    except Exception: return False

def render_single_video(idx, letter, word, clipart_dir, mascot_img, slate_info, output_dir):
    t_start = time.time()
    print(f"⏳ [start] {letter} {word} ({idx})", flush=True)
    out_path = Path(output_dir) / f"{idx:03d}_{letter}_{word}.mp4"

    art = None
    if word and clipart_dir:
        p = find_clipart(clipart_dir, letter, word)
        if p: art = Image.open(p).convert('RGBA')
    
    big = fit_inside(art, int(560 * SCALE), int(560 * SCALE)) if art else None
    mini = fit_inside(art, int(130 * SCALE), int(130 * SCALE)) if art else None

    letter_spr = fit_inside(render_text(letter, int(400 * SCALE), COLOR_LETTER), int(480 * SCALE), int(360 * SCALE))
    se_spr = render_text("से", int(100 * SCALE), COLOR_SE)
    
    if word:
        word_spr = fit_inside(render_text(word, int(140 * SCALE), COLOR_WORD), int(520 * SCALE), int(200 * SCALE))
    else:
        word_spr = None

    # Card dimensions
    card_w = int(600 * SCALE)
    card_h = int(800 * SCALE)

    ctx = dict(
        clip=big, mini=mini, letter=letter_spr, se=se_spr, word=word_spr,
        text_card=text_card_sprite(card_w, card_h),
        mascot=make_mascot_with_letter(mascot_img, slate_info, letter),
        has_word=bool(word)
    )
    if big is not None:
        sh_ = big.copy()
        sh_.putalpha(sh_.split()[3].point(lambda px: int(px * 0.35)))
        ctx['clip_shadow'] = sh_.filter(ImageFilter.GaussianBlur(int(15 * SCALE)))
    
    clip = VideoClip(lambda t: create_frame(t, ctx), duration=DURATION)

    tmp_path = out_path.with_name(out_path.stem + ".part.mp4")
    clip.write_videofile(
        str(tmp_path), fps=FPS, codec='libx264', audio=False,
        preset=PRESET, threads=4, 
        ffmpeg_params=["-threads", "4", "-crf", "22"],
        logger=None
    )
    os.replace(tmp_path, out_path)

    print(f"✔ [done]  {letter} {word} in {time.time()-t_start:.1f}s", flush=True)
    return str(out_path)

def worker_render(job):
    idx, letter, word, clipart_dir, mascot_path, slate_info, output_dir, res, fps = job
    try:
        apply_resolution(res[0], res[1], fps)
        if mascot_path not in _WORKER_CACHE:
            _WORKER_CACHE[mascot_path] = Image.open(mascot_path).convert('RGBA')
        render_single_video(idx, letter, word, clipart_dir, _WORKER_CACHE[mascot_path], slate_info, output_dir)
        return idx, letter, word, None
    except Exception as e:
        log.exception(f"render failed: {letter} {word}")
        return idx, letter, word, str(e)

# ==========================================
# 15. PROGRESS + FOLDER OPEN
# ==========================================
def progress(done, total, suffix=""):
    bar_len = 30
    filled = int(bar_len * done / total) if total else 0
    bar = "█" * filled + "░" * (bar_len - filled)
    pct = 100 * done / total if total else 0
    sys.stderr.write(f"\r[{bar}] {done}/{total} ({pct:5.1f}%) {suffix:<40}")
    sys.stderr.flush()

def open_folder(path):
    try:
        if sys.platform == 'win32': os.startfile(path)
        elif sys.platform == 'darwin': subprocess.Popen(['open', path])
        else: subprocess.Popen(['xdg-open', path])
    except Exception: pass

# ==========================================
# 16. PATH + SLATE FLOW
# ==========================================
def get_paths():
    saved_m, saved_c = resolve_path(CFG.get('mascot_path', '')), resolve_path(CFG.get('clipart_dir', ''))
    if saved_m and saved_c and os.path.exists(saved_m) and os.path.exists(saved_c):
        print(f"📁 Last used:\n   Mascot: {saved_m}\n   Clipart: {saved_c}")
        if input("Use these paths? [Y/n]: ").strip().lower() != 'n': return saved_m, saved_c
    root = tk.Tk(); root.withdraw()
    mascot_path = filedialog.askopenfilename(title="Select mascot image", filetypes=[("Images", "*.png *.jpg *.jpeg *.webp")])
    if not mascot_path: sys.exit(0)
    clipart_dir = filedialog.askdirectory(title="Select clipart folder")
    if not clipart_dir: sys.exit(0)
    root.destroy()
    CFG['mascot_path'], CFG['clipart_dir'] = mascot_path, clipart_dir
    save_config(CFG)
    return mascot_path, clipart_dir

def get_or_select_slate(mascot_path, mascot_img):
    cached = get_slate_cached(mascot_path)
    if cached:
        print("💾 Saved slate found.")
        if input("Use saved slate? [Y/n]: ").strip().lower() != 'n': return cached
    log.info("Auto-detecting slate...")
    auto = find_slate(mascot_img, (0, 0, mascot_img.width, mascot_img.height), tol=1.0)
    result = slate_preview_gui(mascot_img, auto)
    if result: save_slate_cache(mascot_path, result)
    return result

# ==========================================
# 17. MAIN
# ==========================================
def main():
    # 1. Ask for Quality
    res, fps = quality_selection_gui()
    if not res: return 0
    
    # 2. Sets every resolution-dependent global and clears the caches
    apply_resolution(res[0], res[1], fps)

    print("=" * 60)
    print("🎬 HINDI VIDEO GENERATOR — 4K UHD EDITION")
    print("=" * 60)
    print(f"📺 Resolution: {W}x{H} @ {FPS}fps")
    print(f"🔤 Engine: {'HarfBuzz ✔' if _hb_ready() else 'Pillow'}")
    print(f"⚡ Preset: {PRESET} (Ultra Fast Export)")

    mascot_path, clipart_dir = get_paths()
    mascot_img = Image.open(mascot_path).convert('RGBA')
    slate_info = get_or_select_slate(mascot_path, mascot_img)
    
    if slate_info is None:
        log.error("Slate selection cancelled."); return 1

    preview = make_mascot_with_letter(mascot_img, slate_info, HINDI_DATA[0][0])
    preview.save(BASE_DIR / "preview_mascot.png")

    found, missing = precheck_clipart(HINDI_DATA, clipart_dir, ONLY_LETTERS)
    print_precheck(found, missing)
    if not found: return 1
    if missing and input(f"\nContinue with {len(found)} videos? [Y/n]: ").strip().lower() == 'n': return 0

    output_dir = BASE_DIR / "OUTPUT_VIDEOS"
    output_dir.mkdir(exist_ok=True)

    jobs = []
    for i, letter, word, _p in found:
        out_path = output_dir / f"{i:03d}_{letter}_{word}.mp4"
        if RESUME and is_done(out_path): continue
        jobs.append((i, letter, word, clipart_dir, mascot_path, slate_info, str(output_dir), (W, H), FPS))

    if not jobs:
        print("✅ All videos exist. Opening folder..."); open_folder(str(output_dir)); return 0

    total = len(jobs)
    start = time.time()
    ok = done_count = 0
    finished = set()
    progress(0, total, "Starting...")

    if WORKERS > 1 and total > 1:
        try:
            with ProcessPoolExecutor(max_workers=WORKERS) as ex:
                futures = [ex.submit(worker_render, j) for j in jobs]
                for fut in as_completed(futures):
                    idx, letter, word, err = fut.result()
                    finished.add(idx)
                    done_count += 1
                    if err is None: ok += 1
                    progress(done_count, total, f"✔ {letter} {word}" if err is None else f"✖ {letter} {word}")
        except Exception:
            log.exception("Process pool failed - continuing one by one")
            for j in jobs:
                if j[0] in finished: continue   # don't re-render what already finished
                idx, letter, word, err = worker_render(j)
                done_count += 1
                if err is None: ok += 1
                progress(done_count, total, f"✔ {letter} {word}" if err is None else f"✖ {letter} {word}")
    else:
        for j in jobs:
            idx, letter, word, err = worker_render(j)
            done_count += 1
            if err is None: ok += 1
            progress(done_count, total, f"✔ {letter} {word}" if err is None else f"✖ {letter} {word}")

    print(f"\n✅ DONE! {ok}/{total} rendered in {(time.time()-start)/60:.1f} mins.")
    open_folder(str(output_dir))
    return 0

if __name__ == '__main__':
    try: sys.exit(main())
    except KeyboardInterrupt: sys.exit(130)
    except Exception: log.exception("Fatal error"); sys.exit(1)
