import tkinter as tk
from tkinter import ttk
import psutil
import platform
import threading
import subprocess
import sys
import time
import re
from datetime import datetime


# ── Data collectors ──────────────────────────────────────────────────────────

def _run(cmd, timeout=3):
    try:
        flags = 0x08000000 if sys.platform == 'win32' else 0
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout, creationflags=flags)
        return r.stdout.strip()
    except Exception:
        return ""


def _safe_float(s):
    try:
        v = float(str(s).strip())
        return v if v >= 0 else None
    except Exception:
        return None


def get_cpu_temps():
    temps = {}
    # Linux / macOS via psutil
    try:
        sensors = psutil.sensors_temperatures()
        for chip, entries in sensors.items():
            for e in entries:
                lbl = e.label or chip
                temps[f"{chip} / {lbl}"] = {
                    "val": e.current, "high": e.high, "crit": e.critical}
    except Exception:
        pass

    # Windows: WMI thermal zones
    if not temps and sys.platform == 'win32':
        try:
            import wmi
            w = wmi.WMI(namespace="root/wmi")
            for tz in w.MSAcpi_ThermalZoneTemperature():
                c = (tz.CurrentTemperature / 10.0) - 273.15
                name = tz.InstanceName.split('\\')[-1]
                temps[f"Termal / {name}"] = {"val": c, "high": None, "crit": None}
        except Exception:
            pass

    # Windows: LibreHardwareMonitor / OpenHardwareMonitor WMI bridge
    if sys.platform == 'win32':
        for ns in ("root/LibreHardwareMonitor", "root/OpenHardwareMonitor"):
            try:
                import wmi
                w = wmi.WMI(namespace=ns)
                for s in w.Sensor():
                    if s.SensorType == 'Temperature' and s.Value is not None:
                        temps[f"{s.Parent.split('/')[-1]} / {s.Name}"] = {
                            "val": s.Value, "high": None, "crit": None}
            except Exception:
                pass

    return temps


def get_gpu_info():
    gpus = []

    # NVIDIA via nvidia-smi
    out = _run(["nvidia-smi",
                "--query-gpu=name,temperature.gpu,utilization.gpu,"
                "memory.used,memory.total,fan.speed,power.draw",
                "--format=csv,noheader,nounits"])
    if out:
        for line in out.splitlines():
            p = [x.strip() for x in line.split(',')]
            if len(p) >= 5:
                gpus.append({
                    "name":      p[0],
                    "vendor":    "NVIDIA",
                    "temp":      _safe_float(p[1]),
                    "util":      _safe_float(p[2]),
                    "mem_used":  _safe_float(p[3]),
                    "mem_total": _safe_float(p[4]),
                    "fan":       _safe_float(p[5]) if len(p) > 5 else None,
                    "power":     _safe_float(p[6]) if len(p) > 6 else None,
                })

    # AMD via rocm-smi
    if not gpus:
        out2 = _run(["rocm-smi", "--showtemp", "--showuse"])
        if out2:
            temp_m = re.search(r'Temperature.*?:\s*([\d.]+)', out2)
            use_m  = re.search(r'GPU use.*?:\s*([\d.]+)', out2)
            gpus.append({
                "name":      "AMD GPU (rocm-smi)",
                "vendor":    "AMD",
                "temp":      float(temp_m.group(1)) if temp_m else None,
                "util":      float(use_m.group(1))  if use_m  else None,
                "mem_used":  None, "mem_total": None, "fan": None, "power": None,
            })

    # Windows WMI fallback — name only
    if not gpus and sys.platform == 'win32':
        try:
            import wmi
            w = wmi.WMI()
            for g in w.Win32_VideoController():
                if not g.Name:
                    continue
                ram = int(g.AdapterRAM or 0) // (1024 * 1024)
                gpus.append({
                    "name":      g.Name,
                    "vendor":    "Unknown",
                    "temp":      None,
                    "util":      None,
                    "mem_used":  None,
                    "mem_total": ram or None,
                    "fan":       None,
                    "power":     None,
                })
        except Exception:
            pass

    return gpus


def get_motherboard():
    if sys.platform == 'win32':
        try:
            import wmi
            w = wmi.WMI()
            for b in w.Win32_BaseBoard():
                return {
                    "manufacturer": b.Manufacturer or "N/A",
                    "product":      b.Product      or "N/A",
                }
        except Exception:
            pass
    return {"manufacturer": "N/A", "product": "N/A"}


def get_cpu_info():
    mb   = get_motherboard()
    freq = psutil.cpu_freq()
    return {
        "model":    platform.processor() or "N/A",
        "cores_p":  psutil.cpu_count(logical=False) or "N/A",
        "cores_l":  psutil.cpu_count(logical=True)  or "N/A",
        "freq_cur": f"{freq.current:.0f} MHz" if freq else "N/A",
        "freq_max": f"{freq.max:.0f} MHz"     if freq else "N/A",
        "os":       f"{platform.system()} {platform.release()}",
        "arch":     platform.machine(),
        "mb_make":  mb["manufacturer"],
        "mb_model": mb["product"],
    }


def get_mem_info():
    m = psutil.virtual_memory()
    s = psutil.swap_memory()
    return {
        "total":  f"{m.total/1024**3:.1f} GB",
        "used":   f"{m.used/1024**3:.1f} GB",
        "avail":  f"{m.available/1024**3:.1f} GB",
        "pct":    m.percent,
        "stotal": f"{s.total/1024**3:.1f} GB",
        "sused":  f"{s.used/1024**3:.1f} GB",
        "spct":   s.percent,
    }


def get_disk_info():
    disks = []
    for part in psutil.disk_partitions(all=False):
        try:
            u = psutil.disk_usage(part.mountpoint)
            disks.append({
                "dev":   part.device,
                "mp":    part.mountpoint,
                "fs":    part.fstype,
                "total": f"{u.total/1024**3:.1f} GB",
                "used":  f"{u.used/1024**3:.1f} GB",
                "free":  f"{u.free/1024**3:.1f} GB",
                "pct":   u.percent,
            })
        except Exception:
            pass
    return disks


_prev_net      = None
_prev_net_time = None


def get_net_speed():
    global _prev_net, _prev_net_time
    now = time.time()
    cur = psutil.net_io_counters()
    if _prev_net is None:
        _prev_net, _prev_net_time = cur, now
        return {"dl": 0, "ul": 0, "tdl": cur.bytes_recv, "tul": cur.bytes_sent}
    dt = now - _prev_net_time
    dl = max(0, (cur.bytes_recv - _prev_net.bytes_recv) / dt) if dt else 0
    ul = max(0, (cur.bytes_sent - _prev_net.bytes_sent) / dt) if dt else 0
    _prev_net, _prev_net_time = cur, now
    return {"dl": dl, "ul": ul, "tdl": cur.bytes_recv, "tul": cur.bytes_sent}


def fmt_speed(bps):
    if bps < 1024:     return f"{bps:.0f} B/s"
    if bps < 1024**2:  return f"{bps/1024:.1f} KB/s"
    if bps < 1024**3:  return f"{bps/1024**2:.1f} MB/s"
    return f"{bps/1024**3:.2f} GB/s"


def fmt_bytes(b):
    if b < 1024**2:  return f"{b/1024:.1f} KB"
    if b < 1024**3:  return f"{b/1024**2:.1f} MB"
    return f"{b/1024**3:.2f} GB"


# ── Colors ───────────────────────────────────────────────────────────────────

def temp_color(v, high=None, crit=None):
    if v is None:                           return "#888899"
    if (crit and v >= crit) or v >= 90:    return "#FF2244"
    if (high and v >= high) or v >= 70:    return "#FF8800"
    if v >= 50:                             return "#FFDD00"
    return "#00DD88"


def pct_color(v):
    if v is None:  return "#888899"
    if v >= 90:    return "#FF2244"
    if v >= 70:    return "#FF8800"
    if v >= 50:    return "#FFDD00"
    return "#00DD88"


# ── Widgets ──────────────────────────────────────────────────────────────────

BG  = "#0d0d1a"
BG2 = "#1a1a2e"
BG3 = "#16213e"
ACC = "#00aaff"
FG  = "#ddddff"
FGD = "#aaaacc"


class Bar(tk.Canvas):
    def __init__(self, parent, w=260, h=16, **kw):
        super().__init__(parent, width=w, height=h, bg=BG2,
                         highlightthickness=0, **kw)
        self._bar_w, self._bar_h = w, h  # _w/_h are reserved by tkinter internals

    def set_val(self, pct, color="#00DD88", label=None):
        self.delete("all")
        self.create_rectangle(0, 0, self._bar_w, self._bar_h,
                              fill="#2a2a3e", outline="#333355")
        fw = int(self._bar_w * min(max(pct, 0), 100) / 100)
        if fw:
            self.create_rectangle(0, 0, fw, self._bar_h, fill=color, outline="")
        txt = label or f"{pct:.0f}%"
        self.create_text(self._bar_w // 2, self._bar_h // 2, text=txt,
                         fill="white", font=("Consolas", 8, "bold"))


# ── App ──────────────────────────────────────────────────────────────────────

class HWMonitor(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("HWMonitor - Sistem Sicaklik Izleyici")
        self.geometry("980x720")
        self.configure(bg=BG)
        self.resizable(True, True)

        self._temp_rows = {}
        self._gpu_rows  = {}
        self._disk_rows = []

        self._build_ui()
        self._refresh()

    # ── UI ───────────────────────────────────────────────────────────────────

    def _scrollable(self, parent):
        c  = tk.Canvas(parent, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(parent, orient="vertical", command=c.yview)
        f  = tk.Frame(c, bg=BG)
        f.bind("<Configure>",
               lambda e: c.configure(scrollregion=c.bbox("all")))
        c.create_window((0, 0), window=f, anchor="nw")
        c.configure(yscrollcommand=sb.set)
        c.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        c.bind_all("<MouseWheel>",
                   lambda e: c.yview_scroll(-1*(e.delta//120), "units"))
        return f

    def _sec(self, parent, title):
        f = tk.Frame(parent, bg=BG3, pady=5)
        f.pack(fill="x", padx=8, pady=(10, 2))
        tk.Label(f, text=f"  {title}", font=("Consolas", 10, "bold"),
                 fg=ACC, bg=BG3, anchor="w").pack(fill="x", padx=6)

    def _lrow(self, parent, label, val="—", wl=30, wv=24):
        f = tk.Frame(parent, bg=BG2)
        f.pack(fill="x", padx=14, pady=1)
        tk.Label(f, text=label, font=("Consolas", 9), fg=FGD,
                 bg=BG2, width=wl, anchor="w").pack(side="left")
        v = tk.Label(f, text=val, font=("Consolas", 9, "bold"),
                     fg=FG, bg=BG2, width=wv, anchor="w")
        v.pack(side="left")
        return v

    def _build_ui(self):
        # header
        hdr = tk.Frame(self, bg=BG3, pady=8)
        hdr.pack(fill="x")
        tk.Label(hdr, text="  HWMonitor", font=("Consolas", 17, "bold"),
                 fg=ACC, bg=BG3).pack(side="left", padx=14)
        self._lbl_time = tk.Label(hdr, text="", font=("Consolas", 9),
                                   fg="#666677", bg=BG3)
        self._lbl_time.pack(side="right", padx=14)

        # CPU bar strip
        strip = tk.Frame(self, bg=BG, pady=5)
        strip.pack(fill="x", padx=14)
        tk.Label(strip, text="CPU:", font=("Consolas", 10),
                 fg=FGD, bg=BG).pack(side="left")
        self._cpu_bar = Bar(strip, w=380, h=20)
        self._cpu_bar.pack(side="left", padx=8)
        self._cpu_pct = tk.Label(strip, text="0%", font=("Consolas", 10, "bold"),
                                  fg=ACC, bg=BG, width=8)
        self._cpu_pct.pack(side="left")

        # notebook
        sty = ttk.Style(self)
        sty.theme_use("clam")
        sty.configure("D.TNotebook",     background=BG,  borderwidth=0)
        sty.configure("D.TNotebook.Tab", background=BG3, foreground=FGD,
                      padding=[12, 5],   font=("Consolas", 9, "bold"))
        sty.map("D.TNotebook.Tab",
                background=[("selected", "#0f3460")],
                foreground=[("selected", ACC)])

        nb = ttk.Notebook(self, style="D.TNotebook")
        nb.pack(fill="both", expand=True, padx=8, pady=4)

        tabs = {}
        for name in ("Sicakliklar", "GPU", "CPU", "Bellek", "Disk", "Ag"):
            f = tk.Frame(nb, bg=BG)
            nb.add(f, text=f"  {name}  ")
            tabs[name] = f

        self._build_temp_tab(tabs["Sicakliklar"])
        self._build_gpu_tab(tabs["GPU"])
        self._build_cpu_tab(tabs["CPU"])
        self._build_mem_tab(tabs["Bellek"])
        self._build_disk_tab(tabs["Disk"])
        self._build_net_tab(tabs["Ag"])

    def _build_temp_tab(self, parent):
        self._temp_scroll = self._scrollable(parent)
        self._sec(self._temp_scroll, "CPU / Sistem Sicakliklari")
        self._temp_empty = tk.Label(
            self._temp_scroll,
            text=("  Sensor verisi bulunamadi.\n"
                  "  Windows icin: LibreHardwareMonitor'i yonetici olarak calistirin,\n"
                  "  sonra bu programi yeniden baslatın."),
            font=("Consolas", 9), fg="#666677", bg=BG, justify="left")
        self._temp_empty.pack(anchor="w", padx=16, pady=8)

    def _build_gpu_tab(self, parent):
        self._gpu_scroll = self._scrollable(parent)
        self._sec(self._gpu_scroll, "Grafik Karti")
        self._gpu_empty = tk.Label(
            self._gpu_scroll,
            text=("  GPU verisi alinamadi.\n"
                  "  NVIDIA: nvidia-smi PATH'te olmali.\n"
                  "  AMD: rocm-smi gerekli.\n"
                  "  Her iki GPU da WMI ile temel bilgi gosterilir."),
            font=("Consolas", 9), fg="#666677", bg=BG, justify="left")
        self._gpu_empty.pack(anchor="w", padx=16, pady=8)

    def _build_cpu_tab(self, parent):
        frame = self._scrollable(parent)
        self._sec(frame, "Islemci Bilgileri")
        info = get_cpu_info()
        self._lrow(frame, "Model:",             info["model"])
        self._lrow(frame, "Fiziksel Cekirdek:", str(info["cores_p"]))
        self._lrow(frame, "Mantiksal Cekirdek:",str(info["cores_l"]))
        self._freq_lbl = self._lrow(frame, "Mevcut Frekans:")
        self._lrow(frame, "Maks. Frekans:",    info["freq_max"])
        self._lrow(frame, "Isletim Sistemi:",  info["os"])
        self._lrow(frame, "Mimari:",            info["arch"])

        self._sec(frame, "Anakart")
        self._lrow(frame, "Uretici:",  info["mb_make"])
        self._lrow(frame, "Model:",    info["mb_model"])

        self._sec(frame, "Cekirdek Kullanimi")
        self._core_bars = []
        for i in range(psutil.cpu_count(logical=True) or 1):
            row = tk.Frame(frame, bg=BG2)
            row.pack(fill="x", padx=14, pady=1)
            tk.Label(row, text=f"Cekirdek {i:>2}:", font=("Consolas", 9),
                     fg=FGD, bg=BG2, width=14, anchor="w").pack(side="left")
            bar = Bar(row, w=300, h=15)
            bar.pack(side="left", padx=4)
            lbl = tk.Label(row, text="0%", font=("Consolas", 9, "bold"),
                           fg=ACC, bg=BG2, width=6)
            lbl.pack(side="left")
            self._core_bars.append((bar, lbl))

    def _build_mem_tab(self, parent):
        frame = self._scrollable(parent)
        self._sec(frame, "RAM Bellek")
        self._ml = {
            "total": self._lrow(frame, "Toplam RAM:"),
            "used":  self._lrow(frame, "Kullanilan:"),
            "avail": self._lrow(frame, "Musait:"),
            "pct":   self._lrow(frame, "Kullanim %:"),
        }
        mrow = tk.Frame(frame, bg=BG2)
        mrow.pack(fill="x", padx=14, pady=3)
        tk.Label(mrow, text="Kullanim:", font=("Consolas", 9),
                 fg=FGD, bg=BG2, width=30, anchor="w").pack(side="left")
        self._mem_bar = Bar(mrow, w=380, h=18)
        self._mem_bar.pack(side="left")

        self._sec(frame, "Swap")
        self._sl = {
            "stotal": self._lrow(frame, "Toplam Swap:"),
            "sused":  self._lrow(frame, "Kullanilan:"),
            "spct":   self._lrow(frame, "Kullanim %:"),
        }
        srow = tk.Frame(frame, bg=BG2)
        srow.pack(fill="x", padx=14, pady=3)
        tk.Label(srow, text="Kullanim:", font=("Consolas", 9),
                 fg=FGD, bg=BG2, width=30, anchor="w").pack(side="left")
        self._swap_bar = Bar(srow, w=380, h=18)
        self._swap_bar.pack(side="left")

    def _build_disk_tab(self, parent):
        self._disk_scroll = self._scrollable(parent)

    def _build_net_tab(self, parent):
        frame = self._scrollable(parent)
        self._sec(frame, "Anlik Hiz")
        self._nl = {
            "dl":  self._lrow(frame, "Download:"),
            "ul":  self._lrow(frame, "Upload:"),
            "tdl": self._lrow(frame, "Toplam Indirilen:"),
            "tul": self._lrow(frame, "Toplam Yuklenen:"),
        }
        self._sec(frame, "Ag Arayuzleri")
        for iface, addrs in psutil.net_if_addrs().items():
            row = tk.Frame(frame, bg=BG2)
            row.pack(fill="x", padx=14, pady=1)
            tk.Label(row, text=iface, font=("Consolas", 9, "bold"),
                     fg=ACC, bg=BG2, width=22, anchor="w").pack(side="left")
            ip = next((a.address for a in addrs
                       if str(getattr(a, 'family', '')) in
                       ('AddressFamily.AF_INET', '2',
                        '<AddressFamily.AF_INET: 2>')), "")
            tk.Label(row, text=ip or "—", font=("Consolas", 9),
                     fg=FG, bg=BG2).pack(side="left")

    # ── Refresh ──────────────────────────────────────────────────────────────

    def _refresh(self):
        self._lbl_time.config(
            text=datetime.now().strftime("Son guncelleme: %H:%M:%S"))
        threading.Thread(target=self._worker, daemon=True).start()
        self.after(2000, self._refresh)

    def _worker(self):
        try:
            data = {
                "cpu_pct":   psutil.cpu_percent(),
                "core_pcts": psutil.cpu_percent(percpu=True),
                "freq":      psutil.cpu_freq(),
                "mem":       get_mem_info(),
                "disks":     get_disk_info(),
                "net":       get_net_speed(),
                "temps":     get_cpu_temps(),
                "gpus":      get_gpu_info(),
            }
            self.after(0, lambda d=data: self._apply(d))
        except Exception:
            pass

    def _apply(self, d):
        # CPU bar
        p   = d["cpu_pct"]
        col = pct_color(p)
        self._cpu_bar.set_val(p, col)
        self._cpu_pct.config(text=f"{p:.1f}%", fg=col)

        if d["freq"] and hasattr(self, "_freq_lbl"):
            self._freq_lbl.config(text=f"{d['freq'].current:.0f} MHz")

        for i, (bar, lbl) in enumerate(self._core_bars):
            if i < len(d["core_pcts"]):
                cp  = d["core_pcts"][i]
                cc  = pct_color(cp)
                bar.set_val(cp, cc)
                lbl.config(text=f"{cp:.0f}%", fg=cc)

        m = d["mem"]
        self._ml["total"].config(text=m["total"])
        self._ml["used"].config(text=m["used"],
                                fg="#FF8800" if m["pct"] > 80 else "#00DD88")
        self._ml["avail"].config(text=m["avail"])
        self._ml["pct"].config(text=f"{m['pct']}%", fg=pct_color(m["pct"]))
        self._mem_bar.set_val(m["pct"], pct_color(m["pct"]))
        self._sl["stotal"].config(text=m["stotal"])
        self._sl["sused"].config(text=m["sused"])
        self._sl["spct"].config(text=f"{m['spct']}%", fg=pct_color(m["spct"]))
        self._swap_bar.set_val(m["spct"], pct_color(m["spct"]))

        self._update_disks(d["disks"])

        n = d["net"]
        self._nl["dl"].config(text=fmt_speed(n["dl"]),  fg="#00DDFF")
        self._nl["ul"].config(text=fmt_speed(n["ul"]),  fg="#FFAA00")
        self._nl["tdl"].config(text=fmt_bytes(n["tdl"]))
        self._nl["tul"].config(text=fmt_bytes(n["tul"]))

        self._update_temps(d["temps"])
        self._update_gpus(d["gpus"])

    # ── Disk (no rebuild) ────────────────────────────────────────────────────

    def _update_disks(self, disks):
        for i, disk in enumerate(disks):
            if i >= len(self._disk_rows):
                sec = tk.Frame(self._disk_scroll, bg=BG3, pady=4)
                sec.pack(fill="x", padx=8, pady=(8, 1))
                name_lbl = tk.Label(sec, text="", font=("Consolas", 9, "bold"),
                                    fg=ACC, bg=BG3, anchor="w")
                name_lbl.pack(fill="x", padx=8)

                vals = {}
                for key, lbl in (("fs", "Dosya Sistemi:"), ("total", "Toplam:"),
                                  ("used", "Kullanilan:"),  ("free", "Bos:")):
                    row = tk.Frame(self._disk_scroll, bg=BG2)
                    row.pack(fill="x", padx=14, pady=1)
                    tk.Label(row, text=lbl, font=("Consolas", 9), fg=FGD,
                             bg=BG2, width=20, anchor="w").pack(side="left")
                    v = tk.Label(row, text="", font=("Consolas", 9, "bold"),
                                 fg=FG, bg=BG2)
                    v.pack(side="left")
                    vals[key] = v

                brow = tk.Frame(self._disk_scroll, bg=BG2)
                brow.pack(fill="x", padx=14, pady=2)
                tk.Label(brow, text="Kullanim:", font=("Consolas", 9), fg=FGD,
                         bg=BG2, width=20, anchor="w").pack(side="left")
                bar  = Bar(brow, w=340, h=18)
                bar.pack(side="left", padx=4)
                plbl = tk.Label(brow, text="", font=("Consolas", 9, "bold"),
                                fg=FG, bg=BG2, width=6)
                plbl.pack(side="left")

                self._disk_rows.append((sec, name_lbl, vals, bar, plbl))

            _, nlbl, vals, bar, plbl = self._disk_rows[i]
            nlbl.config(text=f"  {disk['dev']}  ({disk['mp']})")
            vals["fs"].config(text=disk["fs"])
            vals["total"].config(text=disk["total"])
            vals["used"].config(text=disk["used"])
            vals["free"].config(text=disk["free"])
            c = pct_color(disk["pct"])
            bar.set_val(disk["pct"], c)
            plbl.config(text=f"{disk['pct']}%", fg=c)

    # ── Temp (no rebuild) ────────────────────────────────────────────────────

    def _update_temps(self, temps):
        if not temps:
            self._temp_empty.pack(anchor="w", padx=16, pady=8)
            return
        self._temp_empty.pack_forget()

        for key, data in temps.items():
            val = data["val"]
            col = temp_color(val, data.get("high"), data.get("crit"))
            if key not in self._temp_rows:
                row = tk.Frame(self._temp_scroll, bg=BG2)
                row.pack(fill="x", padx=14, pady=1)
                tk.Label(row, text=key[:44], font=("Consolas", 9), fg=FGD,
                         bg=BG2, width=46, anchor="w").pack(side="left")
                v = tk.Label(row, text="", font=("Consolas", 9, "bold"),
                             fg=col, bg=BG2, width=12)
                v.pack(side="left")
                b = Bar(row, w=180, h=14)
                b.pack(side="left", padx=4)
                self._temp_rows[key] = (row, v, b)
            _, vlbl, bar = self._temp_rows[key]
            vlbl.config(text=f"{val:.1f} °C", fg=col)
            bar.set_val(min(val, 120) / 120 * 100, col)

    # ── GPU (no rebuild) ─────────────────────────────────────────────────────

    def _update_gpus(self, gpus):
        if not gpus:
            self._gpu_empty.pack(anchor="w", padx=16, pady=8)
            return
        self._gpu_empty.pack_forget()

        for g in gpus:
            name = g["name"]
            if name not in self._gpu_rows:
                self._sec(self._gpu_scroll, name)
                rows = {}
                rows["vendor"] = self._lrow(self._gpu_scroll, "Uretici:",
                                             g.get("vendor", "N/A"))
                rows["temp"]   = self._lrow(self._gpu_scroll, "Sicaklik:")
                rows["util"]   = self._lrow(self._gpu_scroll, "GPU Kullanim:")
                rows["mem"]    = self._lrow(self._gpu_scroll, "VRAM:")
                rows["fan"]    = self._lrow(self._gpu_scroll, "Fan Hizi:")
                rows["power"]  = self._lrow(self._gpu_scroll, "Guc Tuketimi:")

                brow = tk.Frame(self._gpu_scroll, bg=BG2)
                brow.pack(fill="x", padx=14, pady=3)
                tk.Label(brow, text="GPU Kullanim:", font=("Consolas", 9),
                         fg=FGD, bg=BG2, width=30, anchor="w").pack(side="left")
                rows["util_bar"] = Bar(brow, w=320, h=18)
                rows["util_bar"].pack(side="left")

                trow = tk.Frame(self._gpu_scroll, bg=BG2)
                trow.pack(fill="x", padx=14, pady=3)
                tk.Label(trow, text="Sicaklik:", font=("Consolas", 9),
                         fg=FGD, bg=BG2, width=30, anchor="w").pack(side="left")
                rows["temp_bar"] = Bar(trow, w=320, h=18)
                rows["temp_bar"].pack(side="left")

                self._gpu_rows[name] = rows

            rows = self._gpu_rows[name]
            t  = g.get("temp")
            u  = g.get("util")
            mu = g.get("mem_used")
            mt = g.get("mem_total")
            fn = g.get("fan")
            pw = g.get("power")

            rows["temp"].config(
                text=f"{t:.1f} °C" if t is not None else "N/A",
                fg=temp_color(t))
            rows["util"].config(
                text=f"{u:.0f}%" if u is not None else "N/A",
                fg=pct_color(u) if u is not None else "#888899")

            if mu is not None and mt and mt > 0:
                rows["mem"].config(
                    text=f"{mu:.0f} / {mt:.0f} MB",
                    fg=pct_color(mu / mt * 100))
            elif mt:
                rows["mem"].config(text=f"Toplam: {mt:.0f} MB")
            else:
                rows["mem"].config(text="N/A")

            rows["fan"].config(
                text=f"{fn:.0f}%" if fn is not None else "N/A")
            rows["power"].config(
                text=f"{pw:.1f} W" if pw is not None else "N/A")

            rows["util_bar"].set_val(
                u if u is not None else 0,
                pct_color(u) if u is not None else "#444466",
                label=f"{u:.0f}%" if u is not None else "N/A")
            rows["temp_bar"].set_val(
                min(t, 120) / 120 * 100 if t is not None else 0,
                temp_color(t),
                label=f"{t:.1f}°C" if t is not None else "N/A")


if __name__ == "__main__":
    app = HWMonitor()
    app.mainloop()
