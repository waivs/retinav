#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Oct  7 17:47:49 2026

@author: J.D. Rogers jeremy.rogers@wisc.edu

A dynamic fixation target for naigating the retina with with a SLO or similar instrument

The plan is to use Claude or similar AI code building tools and refine it manually

"""

"""
Crosshair display: shows a crosshair on a black full-screen window on a chosen monitor
(default: a secondary one) and lets you move it from a control window. The control window also has a preview
pane showing the crosshair position over a picture you load.

Install:  pip install screeninfo pillow
Run:      python crosshair.py

Trajectories: type coordinates (one "x, y [, wait_seconds]" per line) or generate a pattern
(circle, square, figure-8, spiral, raster, random), then press Start. The crosshair follows the
path at the rate in the Speed field. Coordinates are degrees from the monitor center (+X right,
+Y up) or pixels from the monitor's top-left corner.

Movement: the X/Y sliders, the recenter button and clicks/drags in the preview set a TARGET
position; the crosshair glides there at the rate in the Speed field. Holding the arrow keys
(control window focused) or the on-screen arrow buttons moves the crosshair directly at that
speed (Shift = 10x); a quick tap moves it 1 pixel.
In the preview pane: click or drag to move the crosshair.
"""
import math
import random
import re
import sys
import time
import tkinter as tk
from tkinter import ttk, colorchooser, filedialog, messagebox

from PIL import Image, ImageOps, ImageTk
from screeninfo import get_monitors

# Make coordinates match real pixels on high-DPI Windows displays
if sys.platform == "win32":
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        ctypes.windll.user32.SetProcessDPIAware()

PREVIEW_MAX = (480, 320)   # max preview pane size in pixels
OVERLAY_BG = "#000000"     # background of the full-screen window on the second monitor
PREVIEW_BG = OVERLAY_BG

PATTERNS = ["Custom list", "Circle", "Square", "Figure-8", "Spiral", "Raster", "Random"]
PATTERN_POINTS = {"Circle": 36, "Square": 4, "Figure-8": 72, "Spiral": 120, "Raster": 6, "Random": 8}


# ---- trajectory helpers (pure functions, no GUI) ----
_NUM = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def parse_waypoints(text):
    """'x, y[, wait]' per line -> [(x, y, wait_seconds)]. '#' starts a comment."""
    pts = []
    for n, line in enumerate(text.splitlines(), 1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        nums = _NUM.findall(line)
        if len(nums) < 2:
            raise ValueError(f"Line {n}: need at least an x and a y value")
        wait = float(nums[2]) if len(nums) > 2 else 0.0
        pts.append((float(nums[0]), float(nums[1]), max(0.0, wait)))
    return pts


def to_pixels(pts, unit, W, H, ppd):
    """Convert waypoints to monitor pixels (top-left origin), clamped to the screen.
    Returns (points, number_clamped)."""
    out, clamped = [], 0
    for x, y, w in pts:
        if unit == "deg":
            x, y = W / 2 + x * ppd, H / 2 - y * ppd
        cx, cy = min(max(x, 0.0), W - 1.0), min(max(y, 0.0), H - 1.0)
        clamped += (cx != x) or (cy != y)
        out.append((cx, cy, w))
    return out, clamped


def gen_pattern(name, R, n, rng=random):
    """Pattern offsets (u, v) from the center, v pointing up, in the same unit as R."""
    if name == "Circle":
        return [(R * math.cos(2 * math.pi * i / n), R * math.sin(2 * math.pi * i / n))
                for i in range(n + 1)]
    if name == "Square":
        return [(-R, R), (R, R), (R, -R), (-R, -R), (-R, R)]
    if name == "Figure-8":
        return [(R * math.sin(2 * math.pi * i / n), 0.5 * R * math.sin(4 * math.pi * i / n))
                for i in range(n + 1)]
    if name == "Spiral":
        out = []
        for i in range(n):
            f = i / max(1, n - 1)
            th = 3 * 2 * math.pi * f            # three turns
            out.append((R * f * math.cos(th), R * f * math.sin(th)))
        return out
    if name == "Raster":
        rows, out = max(2, n), []
        for r in range(rows):
            v = R - 2 * R * r / (rows - 1)
            xs = (-R, R) if r % 2 == 0 else (R, -R)
            out += [(xs[0], v), (xs[1], v)]
        return out
    if name == "Random":
        return [(rng.uniform(-R, R), rng.uniform(-R, R)) for _ in range(n)]
    return []


def advance_path(state, px, py, speed, dt):
    """Move (px, py) along state['pts'] for dt seconds at `speed` px/s, carrying leftover
    distance through corners. state: pts, i (next point), wait, loop, done. Returns new (px, py)."""
    pts, tleft, guard = state["pts"], dt, 0
    while tleft > 1e-12 and not state["done"] and guard < 2000:
        guard += 1
        if state["wait"] > 0:                       # dwelling at a point
            d = min(state["wait"], tleft)
            state["wait"] -= d
            tleft -= d
            continue
        tx, ty, w = pts[state["i"]]
        dist = math.hypot(tx - px, ty - py)
        if dist <= speed * tleft:                   # reach this point and keep going
            tleft -= dist / speed
            px, py = tx, ty
            state["wait"] = w
            state["i"] += 1
            if state["i"] >= len(pts):
                if state["loop"]:
                    state["i"] = 0
                else:
                    state["done"] = True
        else:
            f = speed * tleft / dist
            px += (tx - px) * f
            py += (ty - py) * f
            tleft = 0
    return px, py
# ---- end trajectory helpers ----


class Overlay(tk.Toplevel):
    """Borderless, always-on-top, black window covering one monitor."""

    def __init__(self, master):
        super().__init__(master)
        self.config(bg=OVERLAY_BG)
        self.canvas = tk.Canvas(self, bg=OVERLAY_BG, highlightthickness=0, bd=0,
                                cursor="none")
        self.canvas.pack(fill="both", expand=True)

        if sys.platform == "darwin":
            # overrideredirect is unreliable on macOS Tk; use MacWindowStyle instead
            self.tk.call("::tk::unsupported::MacWindowStyle", "style",
                         self._w, "plain", "none")
        else:
            self.overrideredirect(True)
        self.attributes("-topmost", True)

    def place_on(self, mon):
        self.geometry(f"{mon.width}x{mon.height}{mon.x:+d}{mon.y:+d}")
        self.update_idletasks()
        self.lift()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Crosshair Controller")
        self.resizable(False, False)

        self.monitors = get_monitors()
        self.mon = self._default_monitor()

        self.x = tk.IntVar(value=self.mon.width // 2)
        self.y = tk.IntVar(value=self.mon.height // 2)
        self.size = tk.IntVar(value=40)         # arm length (px)
        self.gap = tk.IntVar(value=6)           # gap around center (px)
        self.thick = tk.IntVar(value=2)
        self.full = tk.BooleanVar(value=False)  # full-screen lines
        self.dot_style = tk.StringVar(value="Sparkle")   # None / Dot / Sparkle / Spin
        self._anim_id = None

        # Trajectory state
        self.pat_name = tk.StringVar(value="Circle")
        self.pat_size = tk.StringVar(value="10")
        self.pat_n = tk.StringVar(value=str(PATTERN_POINTS["Circle"]))
        self.traj_unit = tk.StringVar(value="deg")
        self._unit_prev = "deg"
        self.traj_loop = tk.BooleanVar(value=False)
        self._traj = None            # running trajectory state, or None
        self._path_after = None
        self.color = "#00ff00"
        self.visible = tk.BooleanVar(value=True)
        self.ppd = tk.StringVar(value="40")     # pixels per degree (string so partial typing is OK)

        # Continuous-movement state
        self.speed = tk.StringVar(value="200")
        self.speed_unit = tk.StringVar(value="px/s")
        self._held = set()          # direction names currently held
        self._rel = {}              # pending (debounced) key releases
        self._shift = False
        self._loop_id = None
        self._last_t = 0.0
        # self.x / self.y are the TARGET; px / py are where the crosshair actually is right now
        self.px = self.mon.width / 2
        self.py = self.mon.height / 2
        self.x.trace_add("write", lambda *_: self._ensure_loop())
        self.y.trace_add("write", lambda *_: self._ensure_loop())

        # Preview state
        self.image = None                       # PIL image loaded by the user
        self.image_path = ""
        self.fit_mode = tk.StringVar(value="Stretch")
        self.pv_scale = 1.0
        self.pv_w = self.pv_h = 0
        self._pv_photo = None
        self._base = None                       # image after Stretch/Fit/Fill, before zoom/rotate
        self.img_scale = tk.IntVar(value=100)   # percent
        self.img_rot = tk.IntVar(value=0)       # degrees, counter-clockwise

        self.overlay = Overlay(self)
        self.overlay.place_on(self.mon)

        self._build_ui()
        self._bind_keys()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.draw()
        self._update_anim()

        # Put the controller on the primary monitor
        primary = next((m for m in self.monitors if m.is_primary), self.monitors[0])
        self.geometry(f"+{primary.x + 80}+{primary.y + 80}")

    # ---------- setup ----------
    def _default_monitor(self):
        for m in self.monitors:
            if not m.is_primary:
                return m
        return self.monitors[0]  # only one monitor available

    def _build_ui(self):
        root = ttk.Frame(self, padding=10)
        root.grid()
        left = ttk.Frame(root)
        left.grid(row=0, column=0, sticky="n")
        right = ttk.Frame(root)
        right.grid(row=0, column=1, sticky="n", padx=(12, 0))

        self._build_controls(left)
        self._build_preview(right)

    def _build_controls(self, f):
        pad = {"padx": 8, "pady": 4}

        ttk.Label(f, text="Monitor").grid(row=0, column=0, sticky="w", **pad)
        names = [f"{i}: {m.width}x{m.height} @ ({m.x},{m.y})"
                 + (" [primary]" if m.is_primary else "")
                 for i, m in enumerate(self.monitors)]
        self.mon_box = ttk.Combobox(f, values=names, state="readonly", width=32)
        self.mon_box.current(self.monitors.index(self.mon))
        self.mon_box.grid(row=0, column=1, columnspan=3, sticky="ew", **pad)
        self.mon_box.bind("<<ComboboxSelected>>", self._on_monitor)

        self.x_scale = self._slider(f, 1, "X", self.x, 0, self.mon.width - 1)
        self.y_scale = self._slider(f, 2, "Y", self.y, 0, self.mon.height - 1)

        pad_f = ttk.Frame(f)
        pad_f.grid(row=3, column=0, columnspan=4, pady=8)
        self._dir_button(pad_f, "▲", "Up", 0, 1)
        self._dir_button(pad_f, "◀", "Left", 1, 0)
        ttk.Button(pad_f, text="●", width=4, command=self.center).grid(row=1, column=1)
        self._dir_button(pad_f, "▶", "Right", 1, 2)
        self._dir_button(pad_f, "▼", "Down", 2, 1)

        ttk.Label(f, text="Speed").grid(row=4, column=0, sticky="w", **pad)
        ttk.Spinbox(f, from_=0.1, to=100000, increment=10, width=8,
                    textvariable=self.speed).grid(row=4, column=1, sticky="w", **pad)
        ttk.Combobox(f, textvariable=self.speed_unit, values=["px/s", "°/s"],
                     state="readonly", width=5).grid(row=4, column=2, sticky="w", **pad)
        ttk.Label(f, text="Shift = 10×", foreground="#666").grid(row=4, column=3, sticky="w")
        self._slider(f, 5, "Arm length", self.size, 5, 1000)
        self._slider(f, 6, "Center gap", self.gap, 0, 100)
        self._slider(f, 7, "Thickness", self.thick, 1, 20)

        ttk.Checkbutton(f, text="Full-screen lines", variable=self.full,
                        command=self.draw).grid(row=8, column=0, columnspan=2, sticky="w", **pad)
        cf = ttk.Frame(f)
        cf.grid(row=8, column=2, columnspan=2, sticky="w", **pad)
        ttk.Label(cf, text="Center").pack(side="left")
        cb = ttk.Combobox(cf, textvariable=self.dot_style, state="readonly", width=8,
                          values=["None", "Dot", "Sparkle", "Spin"])
        cb.pack(side="left", padx=4)
        cb.bind("<<ComboboxSelected>>", lambda e: self._on_visible())

        self.color_btn = tk.Button(f, text="Color…", bg=self.color, width=10,
                                   command=self.pick_color)
        self.color_btn.grid(row=9, column=0, columnspan=2, **pad)
        ttk.Checkbutton(f, text="Show crosshair", variable=self.visible,
                        command=self._on_visible).grid(row=9, column=2, columnspan=2, sticky="w", **pad)

        ttk.Label(f, text="Pixels / degree").grid(row=10, column=0, sticky="w", **pad)
        spin = ttk.Spinbox(f, from_=0.1, to=10000, increment=1, width=8,
                           textvariable=self.ppd, command=self.draw)
        spin.grid(row=10, column=1, sticky="w", **pad)
        self.ppd.trace_add("write", lambda *_: (self.draw(), self._sched_path_refresh()))
        ttk.Label(f, text="origin = monitor center\n+X right, +Y up",
                  foreground="#666").grid(row=10, column=2, columnspan=2, sticky="w", **pad)

        self.deg_label = ttk.Label(f, text="", font=("TkDefaultFont", 11, "bold"))
        self.deg_label.grid(row=11, column=0, columnspan=4, sticky="w", **pad)
        self.status = ttk.Label(f, text="", justify="left")
        self.status.grid(row=12, column=0, columnspan=4, sticky="w", **pad)

    def _build_preview(self, f):
        ttk.Label(f, text="Preview", font=("TkDefaultFont", 10, "bold")).grid(row=0, column=0, sticky="w")

        self.pv = tk.Canvas(f, bg=PREVIEW_BG, highlightthickness=1,
                            highlightbackground="#888", cursor="crosshair")
        self.pv.grid(row=1, column=0, columnspan=4, pady=4)
        self.pv.bind("<Button-1>", self._on_preview_mouse)
        self.pv.bind("<B1-Motion>", self._on_preview_mouse)

        bar = ttk.Frame(f)
        bar.grid(row=2, column=0, columnspan=4, sticky="ew")
        ttk.Button(bar, text="Load picture…", command=self.load_image).pack(side="left")
        ttk.Button(bar, text="Clear", command=self.clear_image).pack(side="left", padx=4)
        mode = ttk.Combobox(bar, textvariable=self.fit_mode, state="readonly", width=9,
                            values=["Stretch", "Fit", "Fill"])
        mode.pack(side="right")
        mode.bind("<<ComboboxSelected>>", lambda e: self.rebuild_base())

        # Image scale / rotation
        self._slider(f, 3, "Scale %", self.img_scale, 10, 400, command=self._on_transform)
        self._slider(f, 4, "Rotate °", self.img_rot, -180, 180, command=self._on_transform)
        tools = ttk.Frame(f)
        tools.grid(row=5, column=0, columnspan=4, sticky="w", padx=8, pady=2)
        ttk.Button(tools, text="⟲ 90°", width=7, command=lambda: self.rotate_by(90)).pack(side="left")
        ttk.Button(tools, text="⟳ 90°", width=7, command=lambda: self.rotate_by(-90)).pack(side="left", padx=4)
        ttk.Button(tools, text="Reset scale/rotation", command=self.reset_transform).pack(side="left")

        self.img_label = ttk.Label(f, text="No picture loaded", foreground="#666")
        self.img_label.grid(row=6, column=0, columnspan=4, sticky="w", pady=(4, 0))
        ttk.Label(f, text="Stretch: fill exactly · Fit: keep aspect, letterbox · Fill: keep aspect, crop. "
                          "Scale and rotation apply on top of the mode, around the center.",
                  foreground="#666", wraplength=PREVIEW_MAX[0]).grid(row=7, column=0, columnspan=4, sticky="w")

        # Trajectory panel
        tf = ttk.LabelFrame(f, text="Trajectory", padding=6)
        tf.grid(row=8, column=0, columnspan=4, sticky="ew", pady=(8, 0))

        r1 = ttk.Frame(tf)
        r1.grid(row=0, column=0, sticky="w")
        ttk.Label(r1, text="Pattern").pack(side="left")
        pat = ttk.Combobox(r1, textvariable=self.pat_name, state="readonly", width=10, values=PATTERNS)
        pat.pack(side="left", padx=4)
        pat.bind("<<ComboboxSelected>>", self._on_pattern_change)
        ttk.Label(r1, text="Size").pack(side="left")
        ttk.Spinbox(r1, from_=0.1, to=10000, increment=1, width=6,
                    textvariable=self.pat_size).pack(side="left", padx=4)
        ttk.Label(r1, text="Points").pack(side="left")
        ttk.Spinbox(r1, from_=2, to=2000, increment=1, width=5,
                    textvariable=self.pat_n).pack(side="left", padx=4)
        ttk.Button(r1, text="Generate", command=self.generate_pattern).pack(side="left", padx=4)

        r2 = ttk.Frame(tf)
        r2.grid(row=1, column=0, sticky="w", pady=4)
        ttk.Label(r2, text="Coordinates in").pack(side="left")
        ucb = ttk.Combobox(r2, textvariable=self.traj_unit, state="readonly", width=5,
                           values=["deg", "px"])
        ucb.pack(side="left", padx=4)
        ucb.bind("<<ComboboxSelected>>", self._on_traj_unit)
        ttk.Checkbutton(r2, text="Loop", variable=self.traj_loop,
                        command=self._refresh_path).pack(side="left", padx=10)

        tw = ttk.Frame(tf)
        tw.grid(row=2, column=0, sticky="ew")
        self.traj_text = tk.Text(tw, width=52, height=6, wrap="none", font="TkFixedFont", undo=True)
        sb = ttk.Scrollbar(tw, orient="vertical", command=self.traj_text.yview)
        self.traj_text.config(yscrollcommand=sb.set)
        self.traj_text.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self.traj_text.bind("<KeyRelease>", lambda e: self._sched_path_refresh())
        self.traj_text.bind("<<Paste>>", lambda e: self._sched_path_refresh())
        self.traj_text.bind("<<Cut>>", lambda e: self._sched_path_refresh())

        r3 = ttk.Frame(tf)
        r3.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        self.traj_btn = ttk.Button(r3, text="▶ Start", width=10, command=self.toggle_trajectory)
        self.traj_btn.pack(side="left")
        self.traj_status = ttk.Label(r3, text="", foreground="#666", wraplength=340)
        self.traj_status.pack(side="left", padx=8)
        ttk.Label(tf, foreground="#666", wraplength=PREVIEW_MAX[0],
                  text="One point per line: x, y [, wait seconds]. Lines starting with # are "
                       "comments. The crosshair follows the path at the Speed setting."
                  ).grid(row=4, column=0, sticky="w", pady=(4, 0))

        self.generate_pattern()
        self.resize_preview()

    def _slider(self, parent, row, label, var, lo, hi, redraw=True, command=None):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=8, pady=2)
        scale = ttk.Scale(parent, from_=lo, to=hi, variable=var, orient="horizontal",
                          length=220,
                          command=(lambda _=None: command()) if command
                          else (lambda _=None: self.draw()) if redraw else None)
        scale.grid(row=row, column=1, columnspan=2, sticky="ew", padx=8, pady=2)
        ttk.Label(parent, textvariable=var, width=5).grid(row=row, column=3)
        return scale

    def _bind_keys(self):
        self.bind("<KeyPress>", self._on_key_press)
        self.bind("<KeyRelease>", self._on_key_release)
        self.bind("<FocusOut>", self._on_focus_out)

    def _dir_button(self, parent, text, name, row, col):
        b = ttk.Button(parent, text=text, width=4)
        b.grid(row=row, column=col)
        b.bind("<ButtonPress-1>", lambda e: self.press_dir(name))
        b.bind("<ButtonRelease-1>", lambda e: self.release_dir(name))

    def _on_key_press(self, e):
        cls = e.widget.winfo_class() if hasattr(e.widget, "winfo_class") else ""
        if cls in ("Text", "Entry", "TEntry", "TSpinbox", "TCombobox"):
            return                                   # let the widget handle its own keys
        if e.keysym in ("Shift_L", "Shift_R"):
            self._shift = True
        elif e.keysym in self.DIRS:
            if e.state & 0x1:
                self._shift = True
            pending = self._rel.pop(e.keysym, None)
            if pending:                      # X11 auto-repeat: release+press pair, ignore it
                self.after_cancel(pending)
            self.press_dir(e.keysym)

    def _on_key_release(self, e):
        if e.keysym in ("Shift_L", "Shift_R"):
            self._shift = False
        elif e.keysym in self.DIRS:
            # debounce so auto-repeat on some platforms doesn't stutter the motion
            self._rel[e.keysym] = self.after(30, lambda k=e.keysym: self._finish_release(k))

    def _finish_release(self, key):
        self._rel.pop(key, None)
        self.release_dir(key)

    def _on_focus_out(self, e):
        if e.widget is self:                 # window lost focus: stop any movement
            self._held.clear()
            self._shift = False

    # ---------- preview ----------
    def resize_preview(self):
        """Size the preview canvas to match the selected monitor's aspect ratio."""
        W, H = self.mon.width, self.mon.height
        self.pv_scale = min(PREVIEW_MAX[0] / W, PREVIEW_MAX[1] / H)
        self.pv_w = max(1, round(W * self.pv_scale))
        self.pv_h = max(1, round(H * self.pv_scale))
        self.pv.config(width=self.pv_w, height=self.pv_h)
        self.rebuild_base()
        self._refresh_path()

    def rebuild_base(self):
        """Fit the loaded picture to the monitor rectangle (Stretch / Fit / Fill)."""
        self._base = None
        if self.image is not None:
            size = (self.pv_w, self.pv_h)
            mode = self.fit_mode.get()
            if mode == "Stretch":
                self._base = self.image.resize(size, Image.LANCZOS)
            elif mode == "Fill":
                self._base = ImageOps.fit(self.image, size, Image.LANCZOS)
            else:  # Fit / letterbox
                fitted = ImageOps.contain(self.image, size, Image.LANCZOS)
                self._base = Image.new("RGB", size, (0, 0, 0))
                self._base.paste(fitted, ((size[0] - fitted.width) // 2,
                                          (size[1] - fitted.height) // 2))
        self.render_preview_bg()

    def render_preview_bg(self):
        """Apply zoom + rotation about the center and show the result."""
        self.pv.delete("bg")
        self._pv_photo = None
        if self._base is None:
            return
        sc = max(0.01, self.img_scale.get() / 100.0)
        th = math.radians(self.img_rot.get())
        c, s_ = math.cos(th), math.sin(th)
        cx, cy = self.pv_w / 2, self.pv_h / 2
        # Inverse affine: output pixel -> source pixel
        coeffs = (c / sc, -s_ / sc, cx - (cx * c - cy * s_) / sc,
                  s_ / sc, c / sc, cy - (cx * s_ + cy * c) / sc)
        img = self._base.transform((self.pv_w, self.pv_h), Image.AFFINE, coeffs,
                                   Image.BILINEAR, fillcolor=(0, 0, 0))
        self._pv_photo = ImageTk.PhotoImage(img)
        self.pv.create_image(0, 0, image=self._pv_photo, anchor="nw", tags="bg")
        self.pv.tag_lower("bg")

    def _on_transform(self):
        self.render_preview_bg()

    def rotate_by(self, deg):
        r = (self.img_rot.get() + deg + 180) % 360 - 180   # keep within -180..179
        self.img_rot.set(r)
        self.render_preview_bg()

    def reset_transform(self):
        self.img_scale.set(100)
        self.img_rot.set(0)
        self.render_preview_bg()

    def load_image(self):
        path = filedialog.askopenfilename(
            parent=self, title="Choose a picture",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.gif *.bmp *.webp *.tif *.tiff"),
                       ("All files", "*.*")])
        if not path:
            return
        try:
            img = Image.open(path)
            img.load()
            self.image = img.convert("RGB")
        except Exception as e:
            messagebox.showerror("Could not open image", str(e), parent=self)
            return
        self.image_path = path
        name = path.replace("\\", "/").rsplit("/", 1)[-1]
        self.img_label.config(text=f"{name} ({self.image.width}×{self.image.height})")
        self.img_scale.set(100)
        self.img_rot.set(0)
        self.rebuild_base()

    def clear_image(self):
        self.image = None
        self.img_label.config(text="No picture loaded")
        self.rebuild_base()

    def _on_preview_mouse(self, event):
        if self._traj is not None:
            self.stop_trajectory("Stopped (manual move).")
        x = int(max(0, min(self.mon.width - 1, event.x / self.pv_scale)))
        y = int(max(0, min(self.mon.height - 1, event.y / self.pv_scale)))
        self.x.set(x)
        self.y.set(y)
        self.draw()

    def _draw_preview_crosshair(self, x, y, L, g, t, target=None):
        pv, s = self.pv, self.pv_scale
        pv.delete("xh")
        if not self.visible.get():
            return
        px, py = x * s, y * s
        if self.full.get():
            L = max(self.mon.width, self.mon.height)
        L, g = L * s, g * s
        w = max(1, round(t * s))
        # thin dark outline so the crosshair stays visible over any picture
        for color, extra in (("#000000", 2), (self.color, 0)):
            kw = dict(fill=color, width=w + extra, tags="xh")
            pv.create_line(px - L, py, px - g, py, **kw)
            pv.create_line(px + g, py, px + L, py, **kw)
            pv.create_line(px, py - L, px, py - g, **kw)
            pv.create_line(px, py + g, px, py + L, **kw)
        self._draw_center(pv, px, py, s, t, "#000000", ("xh",))
        if target is not None:               # ring showing where the crosshair is heading
            tx, ty = target[0] * s, target[1] * s
            pv.create_oval(tx - 5, ty - 5, tx + 5, ty + 5, outline="#ffffff", width=1,
                           dash=(2, 2), tags="xh")

    # ---------- actions ----------
    def _on_monitor(self, _=None):
        if self._traj is not None:
            self.stop_trajectory("Stopped (monitor changed).")
        self.mon = self.monitors[self.mon_box.current()]
        self.px, self.py = self.mon.width / 2, self.mon.height / 2   # snap, don't glide
        self.overlay.place_on(self.mon)
        self.x_scale.config(to=self.mon.width - 1)
        self.y_scale.config(to=self.mon.height - 1)
        self.resize_preview()
        self.center()

    def center(self):
        self.x.set(self.mon.width // 2)
        self.y.set(self.mon.height // 2)
        self.draw()

    # ---------- continuous movement ----------
    DIRS = {"Left": (-1, 0), "Right": (1, 0), "Up": (0, -1), "Down": (0, 1)}

    def _speed_px(self):
        """Current speed in pixels/second, or None if the field is invalid."""
        try:
            v = float(self.speed.get())
        except (ValueError, tk.TclError):
            return None
        if v <= 0:
            return None
        if self.speed_unit.get() == "°/s":
            ppd = self._ppd()
            if ppd is None:
                return None
            v *= ppd
        return v

    def press_dir(self, name):
        if name in self._held:
            return
        if self._traj is not None:
            self.stop_trajectory("Stopped (manual move).")
        self._held.add(name)
        dx, dy = self.DIRS[name]
        self._move_by(dx, dy)                # 1-pixel nudge so a tap is precise
        self._ensure_loop()

    def release_dir(self, name):
        self._held.discard(name)

    def _ensure_loop(self):
        if self._loop_id is None:
            self._last_t = time.monotonic()
            self._loop_id = self.after(16, self._tick)

    def _tick(self):
        """Animation step (~60 Hz): hold-to-move, or glide toward the target at the set speed."""
        now = time.monotonic()
        dt = min(now - self._last_t, 0.1)
        self._last_t = now
        speed = self._speed_px()
        busy = False

        if self._held:                       # direct movement from arrow keys / buttons
            busy = True
            if speed is not None:
                if self._shift:
                    speed *= 10
                vx = sum(self.DIRS[d][0] for d in self._held)
                vy = sum(self.DIRS[d][1] for d in self._held)
                n = math.hypot(vx, vy)
                if n:                        # normalize so diagonals aren't faster
                    self._move_by(vx / n * speed * dt, vy / n * speed * dt)
        elif self._traj is not None:         # following a trajectory
            busy = True
            T = self._traj
            if speed is None:
                self.stop_trajectory("Stopped: enter a valid speed.")
            else:
                T["loop"] = self.traj_loop.get()
                self.px, self.py = advance_path(T, self.px, self.py, speed, dt)
                self.x.set(round(self.px))
                self.y.set(round(self.py))
                self.draw()
                if T["done"]:
                    self.stop_trajectory("Finished.")
                else:
                    msg = f"Running – heading to point {T['i'] + 1} of {len(T['pts'])}"
                    if T["wait"] > 0:
                        msg += f" (waiting {T['wait']:.1f}s)"
                    self.traj_status.config(text=msg, foreground="#666")
        else:                                # glide toward target
            tx, ty = self._i(self.x), self._i(self.y)
            dx, dy = tx - self.px, ty - self.py
            dist = math.hypot(dx, dy)
            if dist > 1e-6:
                step = None if speed is None else speed * dt
                if step is None or step >= dist:      # arrived (or no valid speed: jump)
                    self.px, self.py = float(tx), float(ty)
                else:
                    self.px += dx / dist * step
                    self.py += dy / dist * step
                    busy = True
                self.draw()

        # Keep _loop_id non-None while running so variable traces don't start a second loop
        self._loop_id = self.after(16, self._tick) if busy else None

    def _move_by(self, dx, dy):
        """Move the crosshair directly (target follows, so no gliding afterwards)."""
        self.px = max(0.0, min(self.mon.width - 1, self.px + dx))
        self.py = max(0.0, min(self.mon.height - 1, self.py + dy))
        self.x.set(round(self.px))
        self.y.set(round(self.py))
        self.draw()

    def pick_color(self):
        c = colorchooser.askcolor(color=self.color, parent=self)[1]
        if c:
            self.color = c
            self.color_btn.config(bg=c)
            self.draw()

    def _ppd(self):
        """Pixels per degree as a positive float, or None if the field is invalid."""
        try:
            v = float(self.ppd.get())
            return v if v > 0 else None
        except (ValueError, tk.TclError):
            return None

    @staticmethod
    def _i(var):
        return int(round(float(var.get())))

    # ---------- drawing ----------
    # ---------- trajectory ----------
    def _set_traj_text(self, text):
        self.traj_text.delete("1.0", "end")
        self.traj_text.insert("1.0", text + "\n")
        self._refresh_path(True)

    def _on_pattern_change(self, _=None):
        n = PATTERN_POINTS.get(self.pat_name.get())
        if n:
            self.pat_n.set(str(n))
        self.generate_pattern()

    def generate_pattern(self):
        name = self.pat_name.get()
        if name == "Custom list":
            self.traj_status.config(text="Type your own coordinates, or pick a pattern.", foreground="#666")
            return
        try:
            R, n = float(self.pat_size.get()), int(float(self.pat_n.get()))
        except ValueError:
            self.traj_status.config(text="Size and Points must be numbers.", foreground="#b00020")
            return
        if R <= 0 or n < 1:
            self.traj_status.config(text="Size must be > 0 and Points ≥ 1.", foreground="#b00020")
            return
        W, H = self.mon.width, self.mon.height
        lines = []
        for u, v in gen_pattern(name, R, max(2, n) if name != "Random" else n):
            x, y = (u, v) if self.traj_unit.get() == "deg" else (W / 2 + u, H / 2 - v)
            lines.append(f"{x:.3f}, {y:.3f}")
        self._set_traj_text(f"# {name}\n" + "\n".join(lines))

    def _on_traj_unit(self, _=None):
        """Switching units converts the existing coordinates so the path stays the same."""
        new, old = self.traj_unit.get(), self._unit_prev
        if new == old:
            return
        ppd = self._ppd()
        if ppd is None:
            self.traj_unit.set(old)
            self.traj_status.config(text="Set a valid pixels/degree before converting units.",
                                    foreground="#b00020")
            return
        W, H = self.mon.width, self.mon.height
        try:
            lines = []
            for x, y, w in parse_waypoints(self.traj_text.get("1.0", "end")):
                if old == "deg":
                    x, y = W / 2 + x * ppd, H / 2 - y * ppd
                else:
                    x, y = (x - W / 2) / ppd, (H / 2 - y) / ppd
                lines.append(f"{x:.3f}, {y:.3f}" + (f", {w:g}" if w else ""))
            self._set_traj_text("\n".join(lines))
        except ValueError:
            pass                                        # invalid text: leave it as typed
        try:
            sz = float(self.pat_size.get())
            self.pat_size.set(f"{sz * ppd:g}" if old == "deg" else f"{sz / ppd:g}")
        except ValueError:
            pass
        self._unit_prev = new
        self._refresh_path()

    def _sched_path_refresh(self):
        if self._path_after is not None:
            self.after_cancel(self._path_after)
        self._path_after = self.after(250, lambda: self._refresh_path(True))

    def _refresh_path(self, update_status=False):
        """Parse the coordinate box and draw the path over the preview picture."""
        if self._path_after is not None:
            self.after_cancel(self._path_after)
            self._path_after = None
        self.pv.delete("path")
        try:
            pts = parse_waypoints(self.traj_text.get("1.0", "end"))
        except ValueError as e:
            if update_status:
                self.traj_status.config(text=str(e), foreground="#b00020")
            return
        ppd = self._ppd()
        if not pts or (self.traj_unit.get() == "deg" and ppd is None):
            return
        pix, clamped = to_pixels(pts, self.traj_unit.get(), self.mon.width, self.mon.height, ppd)
        k, col = self.pv_scale, "#00e5ff"
        if len(pix) >= 2:
            self.pv.create_line(*[c * k for p in pix for c in p[:2]],
                                fill=col, dash=(4, 3), tags="path")
            if self.traj_loop.get() and len(pix) > 2:
                self.pv.create_line(pix[-1][0] * k, pix[-1][1] * k, pix[0][0] * k, pix[0][1] * k,
                                    fill=col, dash=(1, 4), tags="path")
        if len(pix) <= 300:
            for i, (x, y, _w) in enumerate(pix):
                r = 4 if i == 0 else 2.5
                self.pv.create_oval(x * k - r, y * k - r, x * k + r, y * k + r,
                                    fill=col, outline="", tags="path")
        if len(pix) <= 24:
            for i, (x, y, _w) in enumerate(pix):
                self.pv.create_text(x * k + 8, y * k - 8, text=str(i + 1), fill=col,
                                    font=("TkDefaultFont", 8), tags="path")
        self.pv.tag_raise("xh")
        if update_status and self._traj is None:
            note = f" ({clamped} outside the screen – clamped)" if clamped else ""
            self.traj_status.config(text=f"{len(pts)} point(s){note}", foreground="#666")

    def toggle_trajectory(self):
        if self._traj is not None:
            self.stop_trajectory("Stopped.")
        else:
            self.start_trajectory()

    def start_trajectory(self):
        speed = self._speed_px()
        if speed is None:
            self.traj_status.config(text="Enter a valid positive Speed first.", foreground="#b00020")
            return
        try:
            pts = parse_waypoints(self.traj_text.get("1.0", "end"))
        except ValueError as e:
            self.traj_status.config(text=str(e), foreground="#b00020")
            return
        if not pts:
            self.traj_status.config(text="No coordinates to follow.", foreground="#b00020")
            return
        ppd = self._ppd()
        if self.traj_unit.get() == "deg" and ppd is None:
            self.traj_status.config(text="Enter a valid pixels/degree value.", foreground="#b00020")
            return
        pix, _ = to_pixels(pts, self.traj_unit.get(), self.mon.width, self.mon.height, ppd)
        self._traj = {"pts": pix, "i": 0, "wait": 0.0, "loop": self.traj_loop.get(), "done": False}
        self._held.clear()
        self.traj_btn.config(text="■ Stop")
        self.traj_status.config(text="Running…", foreground="#666")
        self._ensure_loop()

    def stop_trajectory(self, msg=""):
        self._traj = None
        self.traj_btn.config(text="▶ Start")
        if msg:
            self.traj_status.config(text=msg, foreground="#666")

    # ---------- center marker + animation ----------
    @staticmethod
    def _star(cv, x, y, R, rot, fill, outline, kw):
        """Four-pointed star (a 'sparkle' glyph)."""
        pts = []
        for i in range(8):
            a = rot + i * math.pi / 4
            rad = R if i % 2 == 0 else R * 0.28
            pts += [x + rad * math.cos(a), y + rad * math.sin(a)]
        cv.create_polygon(pts, fill=fill, outline=outline, **kw)

    def _draw_center(self, cv, x, y, k, t, outline=None, tags=()):
        """Draw the center marker. k = canvas scale (1.0 for the overlay), t = thickness in px."""
        style = self.dot_style.get()
        if style == "None":
            return
        col, ol = self.color, (outline or self.color)
        kw = {"tags": tags} if tags else {}
        now = time.monotonic()
        S = lambda v: max(1.5, v * k)          # scaled size with a visible minimum

        if style == "Dot":
            r = S(max(1, t))
            cv.create_oval(x - r, y - r, x + r, y + r, fill=col, outline=ol, **kw)

        elif style == "Spin":
            R, r = S(max(8, 4 * t)), S(max(2, t * 0.9))
            ang = now * 2 * math.pi * 1.2      # 1.2 revolutions / second
            for i in range(3):
                a = ang + i * 2 * math.pi / 3
                ox, oy = x + R * math.cos(a), y + R * math.sin(a)
                cv.create_oval(ox - r, oy - r, ox + r, oy + r, fill=col, outline=ol, **kw)
            r0 = S(max(1, t * 0.6))
            cv.create_oval(x - r0, y - r0, x + r0, y + r0, fill=col, outline=ol, **kw)

        else:  # Sparkle
            base = max(6, t * 3)
            pulse = 0.75 + 0.35 * math.sin(now * 2 * math.pi * 2.2)
            self._star(cv, x, y, S(base * pulse), now * 0.8, col, ol, kw)
            for i in range(5):                 # small twinkles that pop in and fade out
                phase = now * 2.5 + i * 0.37
                bucket, frac = int(phase), phase - int(phase)
                rnd = random.Random(bucket * 131 + i * 977)
                a = rnd.uniform(0, 2 * math.pi)
                d = rnd.uniform(1.2, 2.6) * base * k
                size = base * 0.55 * math.sin(math.pi * frac) * k
                if size >= 0.8:
                    self._star(cv, x + d * math.cos(a), y + d * math.sin(a), size,
                               rnd.uniform(0, math.pi), "#ffffff", "#ffffff", kw)

    def _on_visible(self):
        self.draw()
        self._update_anim()

    def _update_anim(self):
        """Run a ~30 fps redraw loop only while an animated center style is showing."""
        animated = self.visible.get() and self.dot_style.get() in ("Sparkle", "Spin")
        if animated and self._anim_id is None:
            self._anim_id = self.after(33, self._anim_tick)

    def _anim_tick(self):
        self._anim_id = None
        self.draw()
        self._update_anim()

    def draw(self):
        c = self.overlay.canvas
        c.delete("all")
        x, y = self.px, self.py                       # where the crosshair is right now
        tx, ty = self._i(self.x), self._i(self.y)     # where it is heading
        L, g, t = self._i(self.size), self._i(self.gap), self._i(self.thick)
        W, H = self.mon.width, self.mon.height
        moving = math.hypot(tx - x, ty - y) > 0.5

        ppd = self._ppd()
        extra = ""
        if ppd is None:
            self.deg_label.config(text="Degrees: enter a positive pixels/degree value")
        else:
            self.deg_label.config(
                text=f"X {(x - W / 2) / ppd:+.2f}°    Y {(H / 2 - y) / ppd:+.2f}°")
            extra = f"\nMonitor spans {W / ppd:.1f}° × {H / ppd:.1f}°"
            if moving:
                extra += (f"\nTarget: X {(tx - W / 2) / ppd:+.2f}°  Y {(H / 2 - ty) / ppd:+.2f}°"
                          f"  ({math.hypot(tx - x, ty - y) / ppd:.2f}° to go)")
        xi, yi = round(x), round(y)
        self.status.config(text=f"Pixels: ({xi}, {yi})   "
                                f"Absolute: ({self.mon.x + xi}, {self.mon.y + yi})" + extra)

        self._draw_preview_crosshair(x, y, L, g, t, (tx, ty) if moving else None)
        if not self.visible.get():
            return
        if self.full.get():
            L = max(W, H)
        kw = dict(fill=self.color, width=t)
        c.create_line(x - L, y, x - g, y, **kw)
        c.create_line(x + g, y, x + L, y, **kw)
        c.create_line(x, y - L, x, y - g, **kw)
        c.create_line(x, y + g, x, y + L, **kw)
        self._draw_center(c, x, y, 1.0, t)


if __name__ == "__main__":
    App().mainloop()