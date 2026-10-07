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
 
Shortcuts (control window focused): arrow keys move by the step size (Shift = 10x).
In the preview pane: click or drag to move the crosshair.
"""
import sys
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
        self.step = tk.IntVar(value=5)
        self.size = tk.IntVar(value=40)         # arm length (px)
        self.gap = tk.IntVar(value=6)           # gap around center (px)
        self.thick = tk.IntVar(value=2)
        self.full = tk.BooleanVar(value=False)  # full-screen lines
        self.dot = tk.BooleanVar(value=True)
        self.color = "#00ff00"
        self.visible = tk.BooleanVar(value=True)
 
        # Preview state
        self.image = None                       # PIL image loaded by the user
        self.image_path = ""
        self.fit_mode = tk.StringVar(value="Stretch")
        self.pv_scale = 1.0
        self.pv_w = self.pv_h = 0
        self._pv_photo = None
 
        self.overlay = Overlay(self)
        self.overlay.place_on(self.mon)
 
        self._build_ui()
        self._bind_keys()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.draw()
 
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
        ttk.Button(pad_f, text="▲", width=4, command=lambda: self.nudge(0, -1)).grid(row=0, column=1)
        ttk.Button(pad_f, text="◀", width=4, command=lambda: self.nudge(-1, 0)).grid(row=1, column=0)
        ttk.Button(pad_f, text="●", width=4, command=self.center).grid(row=1, column=1)
        ttk.Button(pad_f, text="▶", width=4, command=lambda: self.nudge(1, 0)).grid(row=1, column=2)
        ttk.Button(pad_f, text="▼", width=4, command=lambda: self.nudge(0, 1)).grid(row=2, column=1)
 
        self._slider(f, 4, "Step", self.step, 1, 100, redraw=False)
        self._slider(f, 5, "Arm length", self.size, 5, 1000)
        self._slider(f, 6, "Center gap", self.gap, 0, 100)
        self._slider(f, 7, "Thickness", self.thick, 1, 20)
 
        ttk.Checkbutton(f, text="Full-screen lines", variable=self.full,
                        command=self.draw).grid(row=8, column=0, columnspan=2, sticky="w", **pad)
        ttk.Checkbutton(f, text="Center dot", variable=self.dot,
                        command=self.draw).grid(row=8, column=2, columnspan=2, sticky="w", **pad)
 
        self.color_btn = tk.Button(f, text="Color…", bg=self.color, width=10,
                                   command=self.pick_color)
        self.color_btn.grid(row=9, column=0, columnspan=2, **pad)
        ttk.Checkbutton(f, text="Show crosshair", variable=self.visible,
                        command=self.draw).grid(row=9, column=2, columnspan=2, sticky="w", **pad)
 
        self.status = ttk.Label(f, text="")
        self.status.grid(row=10, column=0, columnspan=4, sticky="w", **pad)
 
    def _build_preview(self, f):
        ttk.Label(f, text="Preview", font=("TkDefaultFont", 10, "bold")).grid(row=0, column=0, sticky="w")
 
        self.pv = tk.Canvas(f, bg=PREVIEW_BG, highlightthickness=1,
                            highlightbackground="#888", cursor="crosshair")
        self.pv.grid(row=1, column=0, columnspan=3, pady=4)
        self.pv.bind("<Button-1>", self._on_preview_mouse)
        self.pv.bind("<B1-Motion>", self._on_preview_mouse)
 
        ttk.Button(f, text="Load picture…", command=self.load_image).grid(row=2, column=0, sticky="w")
        ttk.Button(f, text="Clear", command=self.clear_image).grid(row=2, column=1, sticky="w", padx=4)
        mode = ttk.Combobox(f, textvariable=self.fit_mode, state="readonly", width=9,
                            values=["Stretch", "Fit", "Fill"])
        mode.grid(row=2, column=2, sticky="e")
        mode.bind("<<ComboboxSelected>>", lambda e: self.render_preview_bg())
 
        self.img_label = ttk.Label(f, text="No picture loaded", foreground="#666")
        self.img_label.grid(row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))
        ttk.Label(f, text="Stretch: fill exactly · Fit: keep aspect, letterbox · Fill: keep aspect, crop",
                  foreground="#666", wraplength=PREVIEW_MAX[0]).grid(row=4, column=0, columnspan=3, sticky="w")
 
        self.resize_preview()
 
    def _slider(self, parent, row, label, var, lo, hi, redraw=True):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=8, pady=2)
        scale = ttk.Scale(parent, from_=lo, to=hi, variable=var, orient="horizontal",
                          length=220, command=(lambda _=None: self.draw()) if redraw else None)
        scale.grid(row=row, column=1, columnspan=2, sticky="ew", padx=8, pady=2)
        ttk.Label(parent, textvariable=var, width=5).grid(row=row, column=3)
        return scale
 
    def _bind_keys(self):
        for key, (dx, dy) in {"<Left>": (-1, 0), "<Right>": (1, 0),
                              "<Up>": (0, -1), "<Down>": (0, 1)}.items():
            self.bind(key, lambda e, dx=dx, dy=dy: self.nudge(dx, dy))
            self.bind(f"<Shift-{key[1:-1]}>", lambda e, dx=dx, dy=dy: self.nudge(dx * 10, dy * 10))
 
    # ---------- preview ----------
    def resize_preview(self):
        """Size the preview canvas to match the selected monitor's aspect ratio."""
        W, H = self.mon.width, self.mon.height
        self.pv_scale = min(PREVIEW_MAX[0] / W, PREVIEW_MAX[1] / H)
        self.pv_w = max(1, round(W * self.pv_scale))
        self.pv_h = max(1, round(H * self.pv_scale))
        self.pv.config(width=self.pv_w, height=self.pv_h)
        self.render_preview_bg()
 
    def render_preview_bg(self):
        """Redraw the background picture (only when image/mode/monitor changes)."""
        self.pv.delete("bg")
        self._pv_photo = None
        if self.image is not None:
            size = (self.pv_w, self.pv_h)
            mode = self.fit_mode.get()
            if mode == "Stretch":
                img = self.image.resize(size, Image.LANCZOS)
            elif mode == "Fill":
                img = ImageOps.fit(self.image, size, Image.LANCZOS)
            else:  # Fit / letterbox
                fitted = ImageOps.contain(self.image, size, Image.LANCZOS)
                img = Image.new("RGB", size, PREVIEW_BG)
                img.paste(fitted, ((size[0] - fitted.width) // 2, (size[1] - fitted.height) // 2))
            self._pv_photo = ImageTk.PhotoImage(img)
            self.pv.create_image(0, 0, image=self._pv_photo, anchor="nw", tags="bg")
            self.pv.tag_lower("bg")
 
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
        self.render_preview_bg()
 
    def clear_image(self):
        self.image = None
        self.img_label.config(text="No picture loaded")
        self.render_preview_bg()
 
    def _on_preview_mouse(self, event):
        x = int(max(0, min(self.mon.width - 1, event.x / self.pv_scale)))
        y = int(max(0, min(self.mon.height - 1, event.y / self.pv_scale)))
        self.x.set(x)
        self.y.set(y)
        self.draw()
 
    def _draw_preview_crosshair(self, x, y, L, g, t):
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
        if self.dot.get():
            r = max(1.5, w)
            pv.create_oval(px - r, py - r, px + r, py + r,
                           fill=self.color, outline="#000000", tags="xh")
 
    # ---------- actions ----------
    def _on_monitor(self, _=None):
        self.mon = self.monitors[self.mon_box.current()]
        self.overlay.place_on(self.mon)
        self.x_scale.config(to=self.mon.width - 1)
        self.y_scale.config(to=self.mon.height - 1)
        self.resize_preview()
        self.center()
 
    def center(self):
        self.x.set(self.mon.width // 2)
        self.y.set(self.mon.height // 2)
        self.draw()
 
    def nudge(self, dx, dy):
        s = self.step.get()
        self.x.set(max(0, min(self.mon.width - 1, self._i(self.x) + dx * s)))
        self.y.set(max(0, min(self.mon.height - 1, self._i(self.y) + dy * s)))
        self.draw()
 
    def pick_color(self):
        c = colorchooser.askcolor(color=self.color, parent=self)[1]
        if c:
            self.color = c
            self.color_btn.config(bg=c)
            self.draw()
 
    @staticmethod
    def _i(var):
        return int(round(float(var.get())))
 
    # ---------- drawing ----------
    def draw(self):
        c = self.overlay.canvas
        c.delete("all")
        x, y = self._i(self.x), self._i(self.y)
        L, g, t = self._i(self.size), self._i(self.gap), self._i(self.thick)
        self.status.config(text=f"Position on monitor: ({x}, {y})   "
                                f"Absolute: ({self.mon.x + x}, {self.mon.y + y})")
        self._draw_preview_crosshair(x, y, L, g, t)
        if not self.visible.get():
            return
        W, H = self.mon.width, self.mon.height
        if self.full.get():
            L = max(W, H)
        kw = dict(fill=self.color, width=t)
        c.create_line(x - L, y, x - g, y, **kw)
        c.create_line(x + g, y, x + L, y, **kw)
        c.create_line(x, y - L, x, y - g, **kw)
        c.create_line(x, y + g, x, y + L, **kw)
        if self.dot.get():
            r = max(1, t)
            c.create_oval(x - r, y - r, x + r, y + r, fill=self.color, outline=self.color)
 
 
if __name__ == "__main__":
    App().mainloop()