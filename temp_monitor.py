"""
HWMonitor Pro - HWiNFO / LibreHardwareMonitor tarzı sistem izleyici
Tek kaydırılabilir pencere, sekme yok.
Veri kaynakları: LibreHardwareMonitor WMI > psutil > nvidia-smi
"""
import tkinter as tk
from tkinter import ttk
import psutil, platform, threading, subprocess, sys, time, re
from datetime import datetime
from collections import OrderedDict

# ─── Renk sabitleri ──────────────────────────────────────────────────────────
BG      = "#111118"
BG_HDR  = "#0a1628"
BG_SHDR = "#161625"
BG_ROW  = "#13131f"
BG_ROW2 = "#16162a"
FG      = "#d8d8ee"
FGD     = "#7878a0"
ACC     = "#0099ff"

UNITS = {
    "Temperature": "°C", "Fan": "RPM", "Voltage": "V",
    "Clock": "MHz",  "Load": "%",    "Power": "W",
    "Data": "GB",    "SmallData": "MB", "Throughput": "MB/s",
    "Level": "%",    "Energy": "mWh",   "Factor": "x",
    "Humidity": "%", "TimeSpan": "s",
}

HW_ORDER = [
    "Mainboard", "SuperIO", "EmbeddedController",
    "CPU", "GpuNvidia", "GpuAmd", "GpuIntel",
    "Memory", "Storage", "Network",
    "Cooler", "Psu", "Battery",
]

HW_LABELS = {
    "Mainboard": "ANAKART", "SuperIO": "SUPER I/O",
    "EmbeddedController": "EC",
    "CPU": "CPU", "Memory": "BELLEK",
    "GpuNvidia": "GPU  NVIDIA", "GpuAmd": "GPU  AMD", "GpuIntel": "GPU  INTEL",
    "Storage": "DEPOLAMA", "Network": "AG",
    "Cooler": "SOGUTMA", "Psu": "PSU", "Battery": "BATARYA",
}

HW_COLORS = {
    "CPU":       "#004488", "GpuNvidia": "#285500", "GpuAmd": "#660000",
    "GpuIntel":  "#003366", "Memory":    "#440066", "Storage": "#553300",
    "Network":   "#005555", "Mainboard": "#2a3344", "SuperIO": "#2a3344",
    "EmbeddedController": "#2a3344",
    "Cooler":    "#003344", "Psu": "#443300", "Battery": "#334400",
}

# ─── Min/Max takibi ──────────────────────────────────────────────────────────
_history = {}

def track(sid, val):
    if val is None:
        return None, None
    if sid not in _history:
        _history[sid] = [val, val]
    else:
        if val < _history[sid][0]: _history[sid][0] = val
        if val > _history[sid][1]: _history[sid][1] = val
    return _history[sid][0], _history[sid][1]

# ─── Değer rengi ─────────────────────────────────────────────────────────────
def val_color(stype, val):
    if val is None: return FGD
    if stype == "Temperature":
        if val >= 90: return "#ff2244"
        if val >= 75: return "#ff6600"
        if val >= 60: return "#ffcc00"
        return "#00dd88"
    if stype in ("Load", "Level"):
        if val >= 90: return "#ff2244"
        if val >= 75: return "#ff8800"
        if val >= 50: return "#ffcc00"
        return "#00dd88"
    if stype == "Power":
        if val >= 150: return "#ff4400"
        if val >= 80:  return "#ff8800"
        return "#00aaff"
    if stype == "Fan":     return "#00bbff"
    if stype == "Voltage": return "#ddaa00"
    if stype == "Clock":   return "#00ccff"
    if stype in ("Data", "SmallData"): return "#aaaaee"
    if stype == "Throughput": return "#00ccaa"
    return "#aaaacc"

def bar_pct(stype, val):
    if val is None: return 0
    if stype == "Temperature":     return min(val / 110 * 100, 100)
    if stype in ("Load", "Level"): return min(val, 100)
    if stype == "Fan":             return min(val / 3000 * 100, 100)
    if stype == "Clock":           return min(val / 6000 * 100, 100)
    if stype == "Power":           return min(val / 300 * 100, 100)
    if stype == "Voltage":         return min(val / 2.0 * 100, 100)
    if stype == "Throughput":      return min(val / 1000 * 100, 100)
    return 0

# ─── LHM / OHM WMI ───────────────────────────────────────────────────────────
def get_lhm_data():
    for ns in ("root/LibreHardwareMonitor", "root/OpenHardwareMonitor"):
        try:
            import wmi
            w = wmi.WMI(namespace=ns)
            hw_map = OrderedDict()
            try:
                for hw in w.Hardware():
                    hw_map[hw.Identifier] = {
                        "id": hw.Identifier, "name": hw.Name,
                        "type": hw.HardwareType,
                        "parent": getattr(hw, "Parent", ""),
                        "sensors": [],
                    }
            except Exception:
                pass
            try:
                for s in w.Sensor():
                    if s.Value is None:
                        continue
                    pid = s.Parent
                    if pid not in hw_map:
                        hw_map[pid] = {"id": pid, "name": pid,
                                       "type": "Unknown", "parent": "", "sensors": []}
                    hw_map[pid]["sensors"].append({
                        "id":    s.Identifier,
                        "name":  s.Name,
                        "type":  s.SensorType,
                        "value": s.Value,
                        "unit":  UNITS.get(s.SensorType, ""),
                    })
            except Exception:
                pass
            if hw_map:
                return hw_map, True
        except Exception:
            pass
    return {}, False

# ─── nvidia-smi ──────────────────────────────────────────────────────────────
def get_nvidia_data():
    try:
        flags = 0x08000000 if sys.platform == "win32" else 0
        out = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=index,name,temperature.gpu,utilization.gpu,"
             "memory.used,memory.total,memory.free,fan.speed,"
             "power.draw,clocks.gr,clocks.mem",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=4, creationflags=flags
        ).stdout.strip()
    except Exception:
        return {}
    result = {}
    for line in out.splitlines():
        p = [x.strip() for x in line.split(",")]
        if len(p) < 10:
            continue
        def sf(s):
            try:
                v = float(s)
                return v if v >= 0 else None
            except Exception:
                return None
        idx  = p[0]
        name = p[1]
        sensors = [
            ("Temperature", f"nv{idx}_t",    "GPU Sicaklik",      sf(p[2]),  "C"),
            ("Load",        f"nv{idx}_ul",   "GPU Core Kullanim", sf(p[3]),  "%"),
            ("SmallData",   f"nv{idx}_muse", "VRAM Kullanilan",   sf(p[4]),  "MB"),
            ("SmallData",   f"nv{idx}_mtot", "VRAM Toplam",       sf(p[5]),  "MB"),
            ("SmallData",   f"nv{idx}_mfre", "VRAM Bos",          sf(p[6]),  "MB"),
            ("Level",       f"nv{idx}_fan",  "Fan Hizi",          sf(p[7]),  "%"),
            ("Power",       f"nv{idx}_pwr",  "GPU Guc",           sf(p[8]),  "W"),
            ("Clock",       f"nv{idx}_gcc",  "Core Clock",        sf(p[9]),  "MHz"),
            ("Clock",       f"nv{idx}_gmc",  "Memory Clock",      sf(p[10]), "MHz"),
        ]
        result[f"__nv_{idx}__"] = {
            "id": f"__nv_{idx}__", "name": name,
            "type": "GpuNvidia", "parent": "",
            "sensors": [
                {"id": sid, "name": sname, "type": stype, "value": sval, "unit": unit}
                for stype, sid, sname, sval, unit in sensors
                if sval is not None
            ],
        }
    return result

# ─── psutil verileri ─────────────────────────────────────────────────────────
_prev_net   = None
_prev_net_t = None

def get_psutil_data():
    global _prev_net, _prev_net_t
    result = {}
    now = time.time()

    # CPU
    cpu_tot  = psutil.cpu_percent()
    cpu_pcts = psutil.cpu_percent(percpu=True)
    freq     = psutil.cpu_freq()
    cpu_sens = [
        {"id": "ps_cpu_tot", "name": "CPU Toplam Kullanim",
         "type": "Load", "value": cpu_tot, "unit": "%"},
    ]
    for i, p in enumerate(cpu_pcts):
        cpu_sens.append({
            "id": f"ps_core{i}", "name": f"CPU Core #{i}",
            "type": "Load", "value": p, "unit": "%",
        })
    if freq:
        cpu_sens.append({
            "id": "ps_freq", "name": "CPU Frekans",
            "type": "Clock", "value": round(freq.current), "unit": "MHz",
        })
    result["__ps_cpu__"] = {
        "id": "__ps_cpu__",
        "name": platform.processor()[:70] or "CPU",
        "type": "CPU", "parent": "", "sensors": cpu_sens,
    }

    # Bellek
    m = psutil.virtual_memory()
    s = psutil.swap_memory()
    result["__ps_mem__"] = {
        "id": "__ps_mem__", "name": "Bellek", "type": "Memory", "parent": "",
        "sensors": [
            {"id": "ps_ram_used",  "name": "RAM Kullanilan",  "type": "Data",  "value": round(m.used/1024**3, 2),      "unit": "GB"},
            {"id": "ps_ram_avail", "name": "RAM Musait",      "type": "Data",  "value": round(m.available/1024**3, 2), "unit": "GB"},
            {"id": "ps_ram_total", "name": "RAM Toplam",      "type": "Data",  "value": round(m.total/1024**3, 2),     "unit": "GB"},
            {"id": "ps_ram_load",  "name": "RAM Kullanim",    "type": "Load",  "value": m.percent,                     "unit": "%"},
            {"id": "ps_swp_used",  "name": "Sanal Kullanilan","type": "Data",  "value": round(s.used/1024**3, 2),      "unit": "GB"},
            {"id": "ps_swp_load",  "name": "Sanal Kullanim",  "type": "Load",  "value": s.percent,                     "unit": "%"},
        ],
    }

    # Diskler
    for part in psutil.disk_partitions(all=False):
        try:
            u   = psutil.disk_usage(part.mountpoint)
            dev = re.sub(r'[\\/:*?"<>|]', '_', part.device)
            result[f"__ps_disk_{dev}__"] = {
                "id": f"__ps_disk_{dev}__",
                "name": f"{part.device}  ({part.mountpoint})  [{part.fstype}]",
                "type": "Storage", "parent": "",
                "sensors": [
                    {"id": f"d_{dev}_use",  "name": "Kullanilan", "type": "Data",  "value": round(u.used/1024**3, 2),  "unit": "GB"},
                    {"id": f"d_{dev}_free", "name": "Bos",        "type": "Data",  "value": round(u.free/1024**3, 2),  "unit": "GB"},
                    {"id": f"d_{dev}_tot",  "name": "Toplam",     "type": "Data",  "value": round(u.total/1024**3, 2), "unit": "GB"},
                    {"id": f"d_{dev}_pct",  "name": "Kullanim",   "type": "Level", "value": u.percent,                 "unit": "%"},
                ],
            }
        except Exception:
            pass

    # Ag hizlari
    try:
        cur_net = psutil.net_io_counters(pernic=True)
        if _prev_net is not None:
            dt = now - _prev_net_t
            for nic, st in cur_net.items():
                if nic not in _prev_net or dt <= 0:
                    continue
                dl   = max(0, (st.bytes_recv - _prev_net[nic].bytes_recv) / dt)
                ul   = max(0, (st.bytes_sent - _prev_net[nic].bytes_sent) / dt)
                safe = re.sub(r'[^a-zA-Z0-9]', '_', nic)
                result[f"__ps_net_{safe}__"] = {
                    "id": f"__ps_net_{safe}__", "name": nic,
                    "type": "Network", "parent": "",
                    "sensors": [
                        {"id": f"n_{safe}_dl",  "name": "Download",          "type": "Throughput", "value": round(dl/1024**2, 3),            "unit": "MB/s"},
                        {"id": f"n_{safe}_ul",  "name": "Upload",            "type": "Throughput", "value": round(ul/1024**2, 3),            "unit": "MB/s"},
                        {"id": f"n_{safe}_tdl", "name": "Toplam Indirilen",  "type": "Data",       "value": round(st.bytes_recv/1024**3, 3), "unit": "GB"},
                        {"id": f"n_{safe}_tul", "name": "Toplam Yuklenen",   "type": "Data",       "value": round(st.bytes_sent/1024**3, 3), "unit": "GB"},
                    ],
                }
        _prev_net   = cur_net
        _prev_net_t = now
    except Exception:
        pass

    return result

# ─── Veri birleştirme ────────────────────────────────────────────────────────
def collect_all():
    lhm_data, lhm_ok = get_lhm_data()
    ps_data           = get_psutil_data()
    nv_data           = get_nvidia_data()

    merged = OrderedDict()

    def hw_sort_key(item):
        try:
            return HW_ORDER.index(item[1].get("type", ""))
        except ValueError:
            return 99

    if lhm_ok:
        for hid, hdata in sorted(lhm_data.items(), key=hw_sort_key):
            if hdata.get("sensors"):
                merged[hid] = hdata
        lhm_types = {v.get("type", "") for v in lhm_data.values()}
        if "GpuNvidia" not in lhm_types:
            merged.update(nv_data)
        # Bellek, disk, ag her zaman psutil'den
        for k, v in ps_data.items():
            if v.get("type") in ("Memory", "Storage", "Network"):
                if k not in merged:
                    merged[k] = v
    else:
        # LHM yok: tümü psutil + nvidia
        for k, v in sorted(ps_data.items(),
                            key=lambda x: hw_sort_key((x[0], x[1]))):
            merged[k] = v
        merged.update(nv_data)

    return merged, lhm_ok

# ─── Ana Uygulama ─────────────────────────────────────────────────────────────
class HWMonitorPro(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("HWMonitor Pro")
        self.geometry("900x900")
        self.configure(bg=BG)
        self.resizable(True, True)

        self._hw_frames   = {}   # hw_id -> (hdr_frame, body_frame)
        self._sensor_rows = {}   # sensor_id -> (row, val_lbl, min_lbl, max_lbl, bar_cv)
        self._row_count   = 0

        self._build_chrome()
        self._refresh()

    # ── Chrome ───────────────────────────────────────────────────────────────
    def _build_chrome(self):
        # Baslik
        top = tk.Frame(self, bg=BG_HDR, pady=8)
        top.pack(fill="x")
        tk.Label(top, text="  HWMonitor Pro",
                 font=("Consolas", 15, "bold"), fg=ACC, bg=BG_HDR).pack(side="left", padx=12)
        self._lbl_time = tk.Label(top, text="", font=("Consolas", 9), fg=FGD, bg=BG_HDR)
        self._lbl_time.pack(side="right", padx=12)

        # Ozet seridi
        sumbar = tk.Frame(self, bg=BG_SHDR, pady=5)
        sumbar.pack(fill="x")
        self._sum_cpu  = self._sum_chip(sumbar, "CPU")
        self._sum_gpu  = self._sum_chip(sumbar, "GPU")
        self._sum_ram  = self._sum_chip(sumbar, "RAM")
        self._sum_ctemp = self._sum_chip(sumbar, "CPU TEMP")
        self._sum_gtemp = self._sum_chip(sumbar, "GPU TEMP")

        # LHM uyari bandi (baslangicta gizli)
        self._banner_frame = tk.Frame(self, bg="#200800", pady=4)
        tk.Label(
            self._banner_frame,
            text=("  UYARI: LibreHardwareMonitor calismıyor → CPU / GPU sicaklıkları gorunmez.\n"
                  "  Cozum: LibreHardwareMonitor'u indirin, YONETICI olarak baslatın, sonra bu programı yeniden baslatın."),
            font=("Consolas", 8), fg="#ff9933", bg="#200800",
            anchor="w", justify="left",
        ).pack(fill="x", padx=10)
        self._banner_visible = False

        # Sutun basliklari
        col_hdr = tk.Frame(self, bg=BG_SHDR, pady=3)
        col_hdr.pack(fill="x", padx=6)
        for text, w in (("Sensor Adi", 42), ("Deger", 12), ("Min", 11), ("Max", 11), ("", 21)):
            tk.Label(col_hdr, text=text, font=("Consolas", 8, "bold"),
                     fg=FGD, bg=BG_SHDR, width=w, anchor="w").pack(side="left")

        # Kaydirilebilir alan
        outer = tk.Frame(self, bg=BG)
        outer.pack(fill="both", expand=True, padx=4, pady=2)
        self._canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(outer, orient="vertical", command=self._canvas.yview)
        self._sf = tk.Frame(self._canvas, bg=BG)
        self._sf.bind("<Configure>",
                      lambda e: self._canvas.configure(
                          scrollregion=self._canvas.bbox("all")))
        self._canvas.create_window((0, 0), window=self._sf, anchor="nw")
        self._canvas.configure(yscrollcommand=sb.set)
        self._canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self._canvas.bind("<MouseWheel>",
                          lambda e: self._canvas.yview_scroll(-1*(e.delta//120), "units"))
        self._sf.bind("<MouseWheel>",
                      lambda e: self._canvas.yview_scroll(-1*(e.delta//120), "units"))

    def _sum_chip(self, parent, label):
        f = tk.Frame(parent, bg=BG_SHDR, padx=14)
        f.pack(side="left")
        tk.Label(f, text=label, font=("Consolas", 7), fg=FGD, bg=BG_SHDR).pack()
        v = tk.Label(f, text="—", font=("Consolas", 11, "bold"), fg=FG, bg=BG_SHDR)
        v.pack()
        return v

    # ── Refresh ──────────────────────────────────────────────────────────────
    def _refresh(self):
        self._lbl_time.config(text=datetime.now().strftime("%H:%M:%S"))
        threading.Thread(target=self._worker, daemon=True).start()
        self.after(2000, self._refresh)

    def _worker(self):
        try:
            data, lhm_ok = collect_all()
            self.after(0, lambda d=data, ok=lhm_ok: self._apply(d, ok))
        except Exception:
            pass

    def _apply(self, data, lhm_ok):
        # Banner goster/gizle
        if lhm_ok and self._banner_visible:
            self._banner_frame.pack_forget()
            self._banner_visible = False
        elif not lhm_ok and not self._banner_visible:
            self._banner_frame.pack(fill="x", before=self._sf.master.master)
            self._banner_visible = True

        # Ozet degerleri
        cpu_load = gpu_load = ram_load = cpu_temp = gpu_temp = None
        for hdata in data.values():
            ht = hdata.get("type", "")
            for s in hdata.get("sensors", []):
                st  = s["type"]
                sv  = s["value"]
                sid = s["id"]
                if sv is None:
                    continue
                if cpu_load is None and st == "Load" and ht == "CPU":
                    if "total" in s["name"].lower() or "toplam" in s["name"].lower():
                        cpu_load = sv
                if gpu_load is None and st == "Load" and "Gpu" in ht:
                    if "core" in s["name"].lower() or "kullanim" in s["name"].lower():
                        gpu_load = sv
                if ram_load is None and st == "Load" and ht == "Memory":
                    ram_load = sv
                if cpu_temp is None and st == "Temperature" and ht == "CPU":
                    if "package" in s["name"].lower() or "tdie" in s["name"].lower() or "sicaklik" in s["name"].lower():
                        cpu_temp = sv
                    elif cpu_temp is None:
                        cpu_temp = sv
                if gpu_temp is None and st == "Temperature" and "Gpu" in ht:
                    gpu_temp = sv

        def _s(lbl, val, unit, stype):
            if val is None:
                lbl.config(text="N/A", fg=FGD)
            else:
                lbl.config(text=f"{val:.1f}{unit}", fg=val_color(stype, val))

        _s(self._sum_cpu,   cpu_load, "%",  "Load")
        _s(self._sum_gpu,   gpu_load, "%",  "Load")
        _s(self._sum_ram,   ram_load, "%",  "Load")
        _s(self._sum_ctemp, cpu_temp, "C",  "Temperature")
        _s(self._sum_gtemp, gpu_temp, "C",  "Temperature")

        # Donanim bloklarini ve sensor satirlarini olustur/guncelle
        for hw_id, hdata in data.items():
            if not hdata.get("sensors"):
                continue
            if hw_id not in self._hw_frames:
                self._create_hw_block(hw_id, hdata)
            for s in hdata["sensors"]:
                sid = s["id"]
                val = s["value"]
                if val is None:
                    continue
                if sid not in self._sensor_rows:
                    self._create_sensor_row(hw_id, s)
                if sid not in self._sensor_rows:
                    continue
                mn, mx  = track(sid, val)
                unit    = s.get("unit", "")
                stype   = s.get("type", "")
                color   = val_color(stype, val)
                _, vlbl, mlbl, xlbl, bar_cv = self._sensor_rows[sid]
                vlbl.config(text=self._fmt(val, unit), fg=color)
                if mn is not None:
                    mlbl.config(text=self._fmt(mn, unit), fg=FGD)
                    xlbl.config(text=self._fmt(mx, unit), fg="#ff6644")
                pct = bar_pct(stype, val)
                self._draw_bar(bar_cv, pct, color)

    # ── Widget olusturma ─────────────────────────────────────────────────────
    def _create_hw_block(self, hw_id, hdata):
        hw_type = hdata.get("type", "Unknown")
        hw_name = hdata.get("name", hw_id)
        label   = HW_LABELS.get(hw_type, hw_type.upper())
        color   = HW_COLORS.get(hw_type, "#2a3344")

        # Bosluk + baslik
        tk.Frame(self._sf, bg=BG, height=4).pack(fill="x")
        hdr = tk.Frame(self._sf, bg=color, pady=4)
        hdr.pack(fill="x")
        tk.Label(hdr, text=f"  [{label}]   {hw_name}",
                 font=("Consolas", 9, "bold"), fg="white",
                 bg=color, anchor="w").pack(side="left", padx=8)

        # Sensor govdesi
        body = tk.Frame(self._sf, bg=BG)
        body.pack(fill="x")

        self._hw_frames[hw_id] = (hdr, body)

    def _create_sensor_row(self, hw_id, s):
        if hw_id not in self._hw_frames:
            return
        _, body = self._hw_frames[hw_id]
        sid     = s["id"]

        bg = BG_ROW if self._row_count % 2 == 0 else BG_ROW2
        self._row_count += 1

        row = tk.Frame(body, bg=bg)
        row.pack(fill="x")
        row.bind("<MouseWheel>",
                 lambda e: self._canvas.yview_scroll(-1*(e.delta//120), "units"))

        def mw_bind(w):
            w.bind("<MouseWheel>",
                   lambda e: self._canvas.yview_scroll(-1*(e.delta//120), "units"))

        # Sensor adi
        nl = tk.Label(row, text=s["name"], font=("Consolas", 9),
                      fg=FG, bg=bg, width=44, anchor="w")
        nl.pack(side="left", padx=(10, 2), pady=1)
        mw_bind(nl)

        # Deger
        vl = tk.Label(row, text="—", font=("Consolas", 9, "bold"),
                      fg=FGD, bg=bg, width=12, anchor="e")
        vl.pack(side="left", padx=1)
        mw_bind(vl)

        # Min
        ml = tk.Label(row, text="—", font=("Consolas", 8),
                      fg=FGD, bg=bg, width=11, anchor="e")
        ml.pack(side="left", padx=1)
        mw_bind(ml)

        # Max
        xl = tk.Label(row, text="—", font=("Consolas", 8),
                      fg="#ff6644", bg=bg, width=11, anchor="e")
        xl.pack(side="left", padx=1)
        mw_bind(xl)

        # Bar
        bar_cv = tk.Canvas(row, width=155, height=13, bg=bg, highlightthickness=0)
        bar_cv.pack(side="left", padx=(4, 8))
        mw_bind(bar_cv)

        self._sensor_rows[sid] = (row, vl, ml, xl, bar_cv)

    # ── Yardimcilar ──────────────────────────────────────────────────────────
    @staticmethod
    def _fmt(val, unit):
        if val is None: return "—"
        u = unit.strip()
        if u in ("%", "RPM"):   return f"{val:.0f} {u}"
        if u == "MHz":          return f"{val:.0f} {u}"
        if u == "V":            return f"{val:.3f} {u}"
        if u in ("W", "C"):     return f"{val:.1f} {u}"
        if u in ("GB", "MB"):   return f"{val:.2f} {u}"
        if u == "MB/s":         return f"{val:.3f} {u}"
        if u == "mWh":          return f"{val:.0f} {u}"
        if val == int(val):     return f"{int(val)} {u}".strip()
        return f"{val:.1f} {u}".strip()

    @staticmethod
    def _draw_bar(cv, pct, color):
        cv.delete("all")
        W, H = 155, 13
        cv.create_rectangle(0, 0, W, H, fill="#1a1a2a", outline="#2a2a44")
        fw = int(W * min(max(pct, 0), 100) / 100)
        if fw:
            cv.create_rectangle(1, 1, fw, H - 1, fill=color, outline="")


if __name__ == "__main__":
    app = HWMonitorPro()
    app.mainloop()
