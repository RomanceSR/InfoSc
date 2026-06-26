"""
HWMonitor Pro
- Sadece 'Yonetici olarak calistir' yeterli, baska program gerekmez
- LibreHardwareMonitorLib.dll (bundle icinde) -> pythonnet ile dogrudan okur
- Yedek: LHM WMI (LHM uygulamasi aciksa), psutil, nvidia-smi
"""
import tkinter as tk
from tkinter import ttk
import psutil, platform, threading, subprocess, sys, time, re, os
from datetime import datetime
from collections import OrderedDict

# ─── DLL yolu (PyInstaller frozen veya kaynak) ───────────────────────────────
def _dll_dir():
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))

# ─── Sabitler ────────────────────────────────────────────────────────────────
BG      = "#111118"
BG_HDR  = "#0a1628"
BG_SHDR = "#161625"
BG_ROW  = "#13131f"
BG_ROW2 = "#16162a"
FG      = "#d8d8ee"
FGD     = "#7878a0"
ACC     = "#0099ff"

UNITS = {
    "Temperature":"°C","Fan":"RPM","Voltage":"V","Clock":"MHz",
    "Load":"%","Power":"W","Data":"GB","SmallData":"MB",
    "Throughput":"MB/s","Level":"%","Energy":"mWh","Factor":"x",
    "Humidity":"%","TimeSpan":"s",
}

# LHM DLL'den gelen enum isimleri (orn. "Cpu") + WMI isimleri ("CPU") -- her ikisini destekle
HW_ORDER = [
    "Mainboard","SuperIO","EmbeddedController",
    "Cpu","CPU",
    "GpuNvidia","GpuAmd","GpuIntel",
    "Memory","Storage","Network","Cooler","Psu","Battery",
]

HW_LABELS = {
    "Mainboard":"ANAKART","SuperIO":"SUPER I/O","EmbeddedController":"EC",
    "Cpu":"CPU","CPU":"CPU",
    "GpuNvidia":"GPU  NVIDIA","GpuAmd":"GPU  AMD","GpuIntel":"GPU  INTEL",
    "Memory":"BELLEK","Storage":"DEPOLAMA","Network":"AG",
    "Cooler":"SOGUTMA","Psu":"PSU","Battery":"BATARYA",
}

HW_COLORS = {
    "Cpu":"#004488","CPU":"#004488",
    "GpuNvidia":"#285500","GpuAmd":"#660000","GpuIntel":"#003366",
    "Memory":"#440066","Storage":"#553300","Network":"#005555",
    "Mainboard":"#2a3344","SuperIO":"#2a3344","EmbeddedController":"#2a3344",
    "Cooler":"#003344","Psu":"#443300","Battery":"#334400",
}

# ─── Min/Max ─────────────────────────────────────────────────────────────────
_history = {}

def track(sid, val):
    if val is None: return None, None
    if sid not in _history: _history[sid] = [val, val]
    else:
        if val < _history[sid][0]: _history[sid][0] = val
        if val > _history[sid][1]: _history[sid][1] = val
    return _history[sid]

# ─── Renk ────────────────────────────────────────────────────────────────────
def val_color(stype, val):
    if val is None: return FGD
    if stype == "Temperature":
        return "#ff2244" if val>=90 else "#ff6600" if val>=75 else "#ffcc00" if val>=60 else "#00dd88"
    if stype in ("Load","Level"):
        return "#ff2244" if val>=90 else "#ff8800" if val>=75 else "#ffcc00" if val>=50 else "#00dd88"
    if stype == "Power":   return "#ff4400" if val>=150 else "#ff8800" if val>=80 else "#00aaff"
    if stype == "Fan":     return "#00bbff"
    if stype == "Voltage": return "#ddaa00"
    if stype == "Clock":   return "#00ccff"
    if stype in ("Data","SmallData"): return "#aaaaee"
    if stype == "Throughput": return "#00ccaa"
    return "#aaaacc"

def bar_pct(stype, val):
    if val is None: return 0
    if stype == "Temperature":     return min(val/110*100, 100)
    if stype in ("Load","Level"):  return min(val, 100)
    if stype == "Fan":             return min(val/3000*100, 100)
    if stype == "Clock":           return min(val/6000*100, 100)
    if stype == "Power":           return min(val/300*100, 100)
    if stype == "Voltage":         return min(val/2.0*100, 100)
    if stype == "Throughput":      return min(val/1000*100, 100)
    return 0

# ─── LHM DLL (pythonnet) ─────────────────────────────────────────────────────
_lhm_computer = None

def lhm_init():
    """DLL'yi pythonnet ile yukle, Computer nesnesini baslat."""
    global _lhm_computer
    dll_path = os.path.join(_dll_dir(), "LibreHardwareMonitorLib.dll")
    if not os.path.exists(dll_path):
        return False
    try:
        import clr  # pythonnet
        base = os.path.dirname(dll_path)
        if base not in sys.path:
            sys.path.insert(0, base)
        clr.AddReference("LibreHardwareMonitorLib")
        from LibreHardwareMonitor.Hardware import Computer
        c = Computer()
        c.IsCpuEnabled         = True
        c.IsGpuEnabled         = True
        c.IsMotherboardEnabled = True
        c.IsMemoryEnabled      = True
        c.IsStorageEnabled     = True
        c.IsBatteryEnabled     = True
        c.Open()
        _lhm_computer = c
        return True
    except Exception:
        return False

def lhm_read():
    """Computer.Hardware uzerinden tum sensorleri oku."""
    if _lhm_computer is None:
        return {}, False
    result = {}
    try:
        for hw in _lhm_computer.Hardware:
            hw.Update()
            hw_id   = str(hw.Identifier)
            hw_type = str(hw.HardwareType).split(".")[-1]  # "Cpu", "GpuNvidia" ...
            hw_name = str(hw.Name)
            sensors = []

            def add_sensor(s, prefix=""):
                v = s.Value
                if v is None: return
                stype = str(s.SensorType).split(".")[-1]
                sensors.append({
                    "id":    str(s.Identifier),
                    "name":  (prefix + str(s.Name)) if prefix else str(s.Name),
                    "type":  stype,
                    "value": float(v),
                    "unit":  UNITS.get(stype, ""),
                })

            for s in hw.Sensors:
                add_sensor(s)
            for sub in hw.SubHardware:
                sub.Update()
                for s in sub.Sensors:
                    add_sensor(s, prefix=f"{sub.Name} / ")

            if sensors:
                result[hw_id] = {
                    "id": hw_id, "name": hw_name,
                    "type": hw_type, "sensors": sensors,
                }
        return result, True
    except Exception:
        return {}, False

# ─── LHM WMI yedek (LHM uygulamasi aciksa) ──────────────────────────────────
def lhm_wmi_read():
    for ns in ("root/LibreHardwareMonitor", "root/OpenHardwareMonitor"):
        try:
            import wmi
            w = wmi.WMI(namespace=ns)
            hw_map = OrderedDict()
            try:
                for hw in w.Hardware():
                    hw_map[hw.Identifier] = {
                        "id": hw.Identifier, "name": hw.Name,
                        "type": hw.HardwareType, "sensors": [],
                    }
            except Exception:
                pass
            try:
                for s in w.Sensor():
                    if s.Value is None: continue
                    pid = s.Parent
                    if pid not in hw_map:
                        hw_map[pid] = {"id":pid,"name":pid,"type":"Unknown","sensors":[]}
                    stype = s.SensorType
                    hw_map[pid]["sensors"].append({
                        "id": s.Identifier, "name": s.Name,
                        "type": stype, "value": s.Value,
                        "unit": UNITS.get(stype, ""),
                    })
            except Exception:
                pass
            if any(v["sensors"] for v in hw_map.values()):
                return hw_map, True
        except Exception:
            pass
    return {}, False

# ─── nvidia-smi ──────────────────────────────────────────────────────────────
def nvidia_read():
    try:
        flags = 0x08000000 if sys.platform == "win32" else 0
        out = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=index,name,temperature.gpu,utilization.gpu,"
             "memory.used,memory.total,memory.free,fan.speed,power.draw,clocks.gr,clocks.mem",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=4, creationflags=flags,
        ).stdout.strip()
    except Exception:
        return {}
    result = {}
    for line in out.splitlines():
        p = [x.strip() for x in line.split(",")]
        if len(p) < 10: continue
        def sf(s):
            try: v=float(s); return v if v>=0 else None
            except: return None
        idx = p[0]
        rows = [
            ("Temperature","nv%s_t"%idx,   "GPU Sicaklik",     sf(p[2]),  "°C"),
            ("Load",       "nv%s_ul"%idx,  "GPU Core Kullanim",sf(p[3]),  "%"),
            ("SmallData",  "nv%s_mu"%idx,  "VRAM Kullanilan",  sf(p[4]),  "MB"),
            ("SmallData",  "nv%s_mt"%idx,  "VRAM Toplam",      sf(p[5]),  "MB"),
            ("SmallData",  "nv%s_mf"%idx,  "VRAM Bos",         sf(p[6]),  "MB"),
            ("Level",      "nv%s_fan"%idx, "Fan Hizi",         sf(p[7]),  "%"),
            ("Power",      "nv%s_pwr"%idx, "GPU Guc",          sf(p[8]),  "W"),
            ("Clock",      "nv%s_gcc"%idx, "Core Clock",       sf(p[9]),  "MHz"),
            ("Clock",      "nv%s_mc"%idx,  "Memory Clock",     sf(p[10]), "MHz"),
        ]
        result["__nv_%s__"%idx] = {
            "id":"__nv_%s__"%idx, "name":p[1], "type":"GpuNvidia",
            "sensors":[{"id":sid,"name":nm,"type":st,"value":sv,"unit":un}
                       for st,sid,nm,sv,un in rows if sv is not None],
        }
    return result

# ─── psutil verileri ─────────────────────────────────────────────────────────
_prev_net=None; _prev_net_t=None

def psutil_read():
    global _prev_net, _prev_net_t
    result = {}
    now = time.time()

    # CPU kullanim
    cpu_tot  = psutil.cpu_percent()
    cpu_pcts = psutil.cpu_percent(percpu=True)
    freq     = psutil.cpu_freq()
    cpu_s = [{"id":"ps_cpu_tot","name":"CPU Toplam Kullanim","type":"Load","value":cpu_tot,"unit":"%"}]
    for i,p in enumerate(cpu_pcts):
        cpu_s.append({"id":f"ps_core{i}","name":f"CPU Core #{i} Kullanim","type":"Load","value":p,"unit":"%"})
    if freq:
        cpu_s.append({"id":"ps_freq","name":"CPU Frekans","type":"Clock","value":round(freq.current),"unit":"MHz"})
    result["__ps_cpu__"] = {
        "id":"__ps_cpu__","name":platform.processor()[:70] or "CPU","type":"Cpu","sensors":cpu_s,
    }

    # Bellek
    m=psutil.virtual_memory(); s=psutil.swap_memory()
    result["__ps_mem__"] = {
        "id":"__ps_mem__","name":"Bellek","type":"Memory","sensors":[
            {"id":"ps_rm_use","name":"RAM Kullanilan","type":"Data","value":round(m.used/1024**3,2),"unit":"GB"},
            {"id":"ps_rm_avl","name":"RAM Musait",    "type":"Data","value":round(m.available/1024**3,2),"unit":"GB"},
            {"id":"ps_rm_tot","name":"RAM Toplam",    "type":"Data","value":round(m.total/1024**3,2),"unit":"GB"},
            {"id":"ps_rm_pct","name":"RAM Kullanim",  "type":"Load","value":m.percent,"unit":"%"},
            {"id":"ps_sw_use","name":"Sanal Kullanilan","type":"Data","value":round(s.used/1024**3,2),"unit":"GB"},
            {"id":"ps_sw_pct","name":"Sanal Kullanim", "type":"Load","value":s.percent,"unit":"%"},
        ],
    }

    # Diskler
    for part in psutil.disk_partitions(all=False):
        try:
            u = psutil.disk_usage(part.mountpoint)
            dev = re.sub(r'[\\/:*?"<>|]','_',part.device)
            result[f"__ps_d_{dev}__"] = {
                "id":f"__ps_d_{dev}__",
                "name":f"{part.device}  ({part.mountpoint})  [{part.fstype}]",
                "type":"Storage","sensors":[
                    {"id":f"d_{dev}_use","name":"Kullanilan","type":"Data","value":round(u.used/1024**3,2),"unit":"GB"},
                    {"id":f"d_{dev}_fre","name":"Bos",       "type":"Data","value":round(u.free/1024**3,2),"unit":"GB"},
                    {"id":f"d_{dev}_tot","name":"Toplam",    "type":"Data","value":round(u.total/1024**3,2),"unit":"GB"},
                    {"id":f"d_{dev}_pct","name":"Kullanim",  "type":"Level","value":u.percent,"unit":"%"},
                ],
            }
        except Exception:
            pass

    # Ag hizlari
    try:
        cur = psutil.net_io_counters(pernic=True)
        if _prev_net is not None:
            dt = now - _prev_net_t
            for nic, st in cur.items():
                if nic not in _prev_net or dt<=0: continue
                dl = max(0,(st.bytes_recv-_prev_net[nic].bytes_recv)/dt)
                ul = max(0,(st.bytes_sent-_prev_net[nic].bytes_sent)/dt)
                safe = re.sub(r'[^a-zA-Z0-9]','_',nic)
                result[f"__ps_n_{safe}__"] = {
                    "id":f"__ps_n_{safe}__","name":nic,"type":"Network","sensors":[
                        {"id":f"n_{safe}_dl","name":"Download",        "type":"Throughput","value":round(dl/1024**2,3),"unit":"MB/s"},
                        {"id":f"n_{safe}_ul","name":"Upload",          "type":"Throughput","value":round(ul/1024**2,3),"unit":"MB/s"},
                        {"id":f"n_{safe}_td","name":"Toplam Indirilen","type":"Data",      "value":round(st.bytes_recv/1024**3,3),"unit":"GB"},
                        {"id":f"n_{safe}_tu","name":"Toplam Yuklenen", "type":"Data",      "value":round(st.bytes_sent/1024**3,3),"unit":"GB"},
                    ],
                }
        _prev_net=cur; _prev_net_t=now
    except Exception:
        pass

    return result

# ─── Tum veriyi topla ────────────────────────────────────────────────────────
_dll_initialized = False
_dll_ok          = False
_wmi_ok          = False

def collect_all():
    global _dll_initialized, _dll_ok, _wmi_ok

    # DLL'yi bir kez baslat
    if not _dll_initialized:
        _dll_initialized = True
        _dll_ok = lhm_init()

    merged   = OrderedDict()
    lhm_data = {}
    lhm_ok   = False

    if _dll_ok:
        lhm_data, lhm_ok = lhm_read()
    if not lhm_ok:
        lhm_data, lhm_ok = lhm_wmi_read()
        _wmi_ok = lhm_ok

    ps_data = psutil_read()
    nv_data = nvidia_read()

    def hw_key(item):
        try: return HW_ORDER.index(item[1].get("type",""))
        except ValueError: return 99

    if lhm_ok:
        for hid, hdata in sorted(lhm_data.items(), key=hw_key):
            if hdata.get("sensors"): merged[hid] = hdata
        lhm_types = {v.get("type","") for v in lhm_data.values()}
        if not any("Gpu" in t for t in lhm_types):
            merged.update(nv_data)
        # Bellek, disk, ag her zaman psutil'den ekle
        for k,v in ps_data.items():
            if v.get("type") in ("Memory","Storage","Network") and k not in merged:
                merged[k] = v
    else:
        for k,v in sorted(ps_data.items(), key=hw_key):
            merged[k] = v
        merged.update(nv_data)

    # Mod bilgisi: "dll" | "wmi" | "psutil"
    mode = "dll" if _dll_ok else ("wmi" if _wmi_ok else "psutil")
    return merged, mode

# ─── Uygulama ─────────────────────────────────────────────────────────────────
class HWMonitorPro(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("HWMonitor Pro")
        self.geometry("900x900")
        self.configure(bg=BG)
        self.resizable(True, True)
        self._hw_frames   = {}
        self._sensor_rows = {}
        self._row_count   = 0
        self._build_ui()
        self._refresh()

    # ── Arayuz ───────────────────────────────────────────────────────────────
    def _build_ui(self):
        # Baslik
        top = tk.Frame(self, bg=BG_HDR, pady=8)
        top.pack(fill="x")
        tk.Label(top, text="  HWMonitor Pro",
                 font=("Consolas",15,"bold"), fg=ACC, bg=BG_HDR).pack(side="left",padx=12)
        self._lbl_time   = tk.Label(top, text="", font=("Consolas",9), fg=FGD, bg=BG_HDR)
        self._lbl_time.pack(side="right", padx=12)
        self._lbl_mode   = tk.Label(top, text="", font=("Consolas",8), fg="#888888", bg=BG_HDR)
        self._lbl_mode.pack(side="right", padx=6)

        # Ozet seridi
        sb = tk.Frame(self, bg=BG_SHDR, pady=5)
        sb.pack(fill="x")
        self._s = {k: self._chip(sb,k) for k in ("CPU","GPU","RAM","CPU °C","GPU °C")}

        # Uyari banner (gizli baslangicta)
        self._banner = tk.Frame(self, bg="#200800")
        tk.Label(self._banner,
                 text=("  [!]  Sicaklik sensoru yok.  Cozum:\n"
                       "  Bu programi sag tik → 'Yonetici olarak calistir'  ile acin.\n"
                       "  Yeterli degilse: LibreHardwareMonitor.exe'yi de yonetici olarak acik tutun."),
                 font=("Consolas",8), fg="#ff9933", bg="#200800",
                 anchor="w", justify="left",
                 ).pack(fill="x", padx=10, pady=4)

        # Sutun basliklari
        ch = tk.Frame(self, bg=BG_SHDR, pady=3)
        ch.pack(fill="x", padx=6)
        for txt,w in (("Sensor Adi",44),("Deger",13),("Min",12),("Max",12),("",22)):
            tk.Label(ch, text=txt, font=("Consolas",8,"bold"),
                     fg=FGD, bg=BG_SHDR, width=w, anchor="w").pack(side="left")

        # Kaydirilebilir alan
        outer = tk.Frame(self, bg=BG)
        outer.pack(fill="both", expand=True, padx=4, pady=2)
        self._cv = tk.Canvas(outer, bg=BG, highlightthickness=0)
        sb2 = ttk.Scrollbar(outer, orient="vertical", command=self._cv.yview)
        self._sf = tk.Frame(self._cv, bg=BG)
        self._sf.bind("<Configure>",
                      lambda e: self._cv.configure(scrollregion=self._cv.bbox("all")))
        self._cv.create_window((0,0), window=self._sf, anchor="nw")
        self._cv.configure(yscrollcommand=sb2.set)
        self._cv.pack(side="left", fill="both", expand=True)
        sb2.pack(side="right", fill="y")
        self._cv.bind("<MouseWheel>",
                      lambda e: self._cv.yview_scroll(-1*(e.delta//120),"units"))
        self._sf.bind("<MouseWheel>",
                      lambda e: self._cv.yview_scroll(-1*(e.delta//120),"units"))

    def _chip(self, parent, label):
        f = tk.Frame(parent, bg=BG_SHDR, padx=14)
        f.pack(side="left")
        tk.Label(f, text=label, font=("Consolas",7), fg=FGD, bg=BG_SHDR).pack()
        v = tk.Label(f, text="—", font=("Consolas",11,"bold"), fg=FG, bg=BG_SHDR)
        v.pack()
        return v

    # ── Refresh ──────────────────────────────────────────────────────────────
    def _refresh(self):
        self._lbl_time.config(text=datetime.now().strftime("%H:%M:%S"))
        threading.Thread(target=self._worker, daemon=True).start()
        self.after(2000, self._refresh)

    def _worker(self):
        try:
            data, mode = collect_all()
            self.after(0, lambda d=data, m=mode: self._apply(d, m))
        except Exception:
            pass

    def _apply(self, data, mode):
        # Mod etiketi
        mode_txt = {"dll":"[DLL: Aktif]","wmi":"[WMI: Aktif]","psutil":"[Sadece psutil]"}
        mode_col = {"dll":"#00dd88","wmi":"#ffcc00","psutil":"#ff8800"}
        self._lbl_mode.config(text=mode_txt.get(mode,""), fg=mode_col.get(mode,FGD))

        # Sicaklik uyarisi goster/gizle
        has_temp = any(
            s["type"]=="Temperature"
            for hd in data.values()
            for s in hd.get("sensors",[])
        )
        if has_temp:
            self._banner.pack_forget()
        else:
            self._banner.pack(fill="x", before=self._sf.master.master)

        # Ozet degerler
        cpu_l=gpu_l=ram_l=cpu_t=gpu_t=None
        for hd in data.values():
            ht = hd.get("type","")
            for s in hd.get("sensors",[]):
                st,sv = s["type"],s["value"]
                if sv is None: continue
                nm = s["name"].lower()
                if cpu_l is None and st=="Load" and ht in ("Cpu","CPU"):
                    if "total" in nm or "toplam" in nm: cpu_l=sv
                if gpu_l is None and st=="Load" and "Gpu" in ht:
                    if "core" in nm or "kullanim" in nm: gpu_l=sv
                if ram_l is None and st=="Load" and ht=="Memory" and "kullanim" in nm:
                    ram_l=sv
                if cpu_t is None and st=="Temperature" and ht in ("Cpu","CPU"):
                    cpu_t=sv
                if gpu_t is None and st=="Temperature" and "Gpu" in ht:
                    gpu_t=sv

        def sc(lbl,val,unit,st):
            if val is None: lbl.config(text="N/A",fg=FGD)
            else: lbl.config(text=f"{val:.1f}{unit}",fg=val_color(st,val))

        sc(self._s["CPU"],    cpu_l, "%",  "Load")
        sc(self._s["GPU"],    gpu_l, "%",  "Load")
        sc(self._s["RAM"],    ram_l, "%",  "Load")
        sc(self._s["CPU °C"], cpu_t, "°C", "Temperature")
        sc(self._s["GPU °C"], gpu_t, "°C", "Temperature")

        # Widget olustur/guncelle
        for hw_id, hdata in data.items():
            if not hdata.get("sensors"): continue
            if hw_id not in self._hw_frames:
                self._make_hw_block(hw_id, hdata)
            for s in hdata["sensors"]:
                sid,val = s["id"],s["value"]
                if val is None: continue
                if sid not in self._sensor_rows:
                    self._make_sensor_row(hw_id, s)
                if sid not in self._sensor_rows: continue
                mn,mx   = track(sid, val)
                unit    = s.get("unit","")
                stype   = s.get("type","")
                color   = val_color(stype, val)
                _,vlbl,mlbl,xlbl,bar = self._sensor_rows[sid]
                vlbl.config(text=self._fmt(val,unit), fg=color)
                if mn is not None:
                    mlbl.config(text=self._fmt(mn,unit), fg=FGD)
                    xlbl.config(text=self._fmt(mx,unit), fg="#ff6644")
                self._draw_bar(bar, bar_pct(stype,val), color)

    # ── Widget fabrikasi ─────────────────────────────────────────────────────
    def _make_hw_block(self, hw_id, hdata):
        hw_type = hdata.get("type","Unknown")
        color   = HW_COLORS.get(hw_type,"#2a3344")
        label   = HW_LABELS.get(hw_type, hw_type.upper())
        tk.Frame(self._sf, bg=BG, height=4).pack(fill="x")
        hdr = tk.Frame(self._sf, bg=color, pady=4)
        hdr.pack(fill="x")
        hdr.bind("<MouseWheel>",
                 lambda e: self._cv.yview_scroll(-1*(e.delta//120),"units"))
        tk.Label(hdr, text=f"  [{label}]   {hdata.get('name',hw_id)}",
                 font=("Consolas",9,"bold"), fg="white", bg=color, anchor="w",
                 ).pack(side="left", padx=8)
        body = tk.Frame(self._sf, bg=BG)
        body.pack(fill="x")
        self._hw_frames[hw_id] = (hdr, body)

    def _make_sensor_row(self, hw_id, s):
        if hw_id not in self._hw_frames: return
        _, body = self._hw_frames[hw_id]
        sid = s["id"]
        bg  = BG_ROW if self._row_count%2==0 else BG_ROW2
        self._row_count += 1

        row = tk.Frame(body, bg=bg)
        row.pack(fill="x")

        def mw(w):
            w.bind("<MouseWheel>",
                   lambda e: self._cv.yview_scroll(-1*(e.delta//120),"units"))

        nl = tk.Label(row, text=s["name"], font=("Consolas",9),
                      fg=FG, bg=bg, width=44, anchor="w")
        nl.pack(side="left", padx=(10,2), pady=1); mw(nl)

        vl = tk.Label(row, text="—", font=("Consolas",9,"bold"),
                      fg=FGD, bg=bg, width=13, anchor="e")
        vl.pack(side="left", padx=1); mw(vl)

        ml = tk.Label(row, text="—", font=("Consolas",8),
                      fg=FGD, bg=bg, width=12, anchor="e")
        ml.pack(side="left", padx=1); mw(ml)

        xl = tk.Label(row, text="—", font=("Consolas",8),
                      fg="#ff6644", bg=bg, width=12, anchor="e")
        xl.pack(side="left", padx=1); mw(xl)

        bar = tk.Canvas(row, width=155, height=13, bg=bg, highlightthickness=0)
        bar.pack(side="left", padx=(4,8)); mw(bar)

        self._sensor_rows[sid] = (row, vl, ml, xl, bar)

    # ── Yardimcilar ──────────────────────────────────────────────────────────
    @staticmethod
    def _fmt(val, unit):
        if val is None: return "—"
        u = unit.strip()
        if u in ("%","RPM","MHz"): return f"{val:.0f} {u}"
        if u == "V":               return f"{val:.3f} {u}"
        if u in ("W","°C","C"):    return f"{val:.1f} {u}"
        if u in ("GB","MB"):       return f"{val:.2f} {u}"
        if u == "MB/s":            return f"{val:.3f} {u}"
        if val == int(val):        return f"{int(val)} {u}".strip()
        return f"{val:.1f} {u}".strip()

    @staticmethod
    def _draw_bar(cv, pct, color):
        cv.delete("all")
        W,H = 155,13
        cv.create_rectangle(0,0,W,H, fill="#1a1a2a", outline="#2a2a44")
        fw = int(W * min(max(pct,0),100)/100)
        if fw: cv.create_rectangle(1,1,fw,H-1, fill=color, outline="")


if __name__ == "__main__":
    app = HWMonitorPro()
    app.mainloop()
