"""
HWMonitor Pro - Gercek donanim sensor verisi
PowerShell + LibreHardwareMonitorLib.dll kalici subprocess
Yonetici olarak calistir -> CPU/GPU/anakart sicakliklari
"""
import tkinter as tk
import psutil, threading, subprocess, sys, time, os
from datetime import datetime

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

HW_ORDER = [
    "Mainboard","SuperIO","EmbeddedController",
    "Cpu","GpuNvidia","GpuAmd","GpuIntel",
    "Memory","Storage","Network","Cooler","Psu","Battery",
]

HW_LABELS = {
    "Mainboard":"ANAKART","SuperIO":"SUPER I/O","EmbeddedController":"EMBEDDED CTRL",
    "Cpu":"CPU","GpuNvidia":"GPU  NVIDIA","GpuAmd":"GPU  AMD","GpuIntel":"GPU  INTEL",
    "Memory":"BELLEK","Storage":"DEPOLAMA","Network":"AG",
    "Cooler":"SOGUTMA","Psu":"PSU","Battery":"BATARYA",
}

HW_COLORS = {
    "Cpu":"#004488","GpuNvidia":"#285500","GpuAmd":"#660000","GpuIntel":"#003366",
    "Memory":"#440066","Storage":"#553300","Network":"#005555",
    "Mainboard":"#2a3344","SuperIO":"#2a3344","EmbeddedController":"#2a3344",
    "Cooler":"#003344","Psu":"#443300","Battery":"#334400",
}

# ─── Min/Max ─────────────────────────────────────────────────────────────────
_history = {}

def track(sid, val):
    if val is None: return None, None
    if sid not in _history:
        _history[sid] = [val, val]
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
    if stype == "Power": return "#ff4400" if val>=150 else "#ff8800" if val>=80 else "#00aaff"
    if stype == "Fan": return "#00bbff"
    if stype == "Voltage": return "#ddaa00"
    if stype == "Clock": return "#00ccff"
    if stype in ("Data","SmallData"): return "#aaaaee"
    if stype == "Throughput": return "#00ccaa"
    return "#aaaacc"

def bar_pct(stype, val):
    if val is None: return 0
    if stype == "Temperature":    return min(val/110*100, 100)
    if stype in ("Load","Level"): return min(val, 100)
    if stype == "Fan":            return min(val/3000*100, 100)
    if stype == "Clock":          return min(val/6000*100, 100)
    if stype == "Power":          return min(val/300*100, 100)
    if stype == "Voltage":        return min(val/2.0*100, 100)
    if stype == "Throughput":     return min(val/1000*100, 100)
    return 0

# ─── PowerShell + LHM DLL (kalici subprocess) ────────────────────────────────
_LHM_PS = r"""
param($DllPath)
[Threading.Thread]::CurrentThread.CurrentCulture = [Globalization.CultureInfo]::InvariantCulture
try {
    Add-Type -Path $DllPath -ErrorAction Stop
    $c = New-Object LibreHardwareMonitor.Hardware.Computer
    $c.IsCpuEnabled = $true; $c.IsGpuEnabled = $true
    $c.IsMotherboardEnabled = $true; $c.IsMemoryEnabled = $true
    $c.IsStorageEnabled = $true; $c.IsBatteryEnabled = $true
    $c.Open()
    Write-Host "READY"
    [Console]::Out.Flush()
    while ($true) {
        $cmd = [Console]::ReadLine()
        if (-not $cmd -or $cmd -eq "EXIT") { $c.Close(); break }
        if ($cmd -ne "READ") { continue }
        foreach ($hw in $c.Hardware) {
            $hw.Update()
            $ht = $hw.HardwareType.ToString()
            Write-Host "HW|$($hw.Identifier)|$($hw.Name)|$ht"
            foreach ($s in $hw.Sensors) {
                if ($s.Value -ne $null) {
                    $v = $s.Value.Value.ToString([Globalization.CultureInfo]::InvariantCulture)
                    Write-Host "S|$($s.Identifier)|$($s.Name)|$($s.SensorType.ToString())|$v"
                }
            }
            foreach ($sub in $hw.SubHardware) {
                $sub.Update()
                foreach ($s in $sub.Sensors) {
                    if ($s.Value -ne $null) {
                        $v = $s.Value.Value.ToString([Globalization.CultureInfo]::InvariantCulture)
                        $sid = "$($hw.Identifier)/sub/$($s.Identifier)"
                        $sname = "$($sub.Name) / $($s.Name)"
                        Write-Host "S|$sid|$sname|$($s.SensorType.ToString())|$v"
                    }
                }
            }
        }
        Write-Host "END"
        [Console]::Out.Flush()
    }
} catch {
    Write-Host "ERROR|$($_.Exception.Message)"
    [Console]::Out.Flush()
}
"""

_ps_proc    = None
_ps_lock    = threading.Lock()
_ps_script  = None
_lhm_ok     = False

def _dll_path():
    name = "LibreHardwareMonitorLib.dll"
    # PyInstaller onefile
    if getattr(sys, "_MEIPASS", None):
        return os.path.join(sys._MEIPASS, name)
    # Nuitka onefile: DLL is next to the exe
    p = os.path.join(os.path.dirname(sys.executable), name)
    if os.path.exists(p):
        return p
    # Dev / Nuitka standalone
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), name)

def _appdata_dir():
    d = os.path.join(os.environ.get("LOCALAPPDATA",
                     os.environ.get("APPDATA", os.path.dirname(sys.executable))),
                     "HWMonitorPro")
    os.makedirs(d, exist_ok=True)
    return d

def _ps_readline_timeout(proc, timeout=6.0):
    q = []
    def _read():
        try: q.append(proc.stdout.readline())
        except: q.append("")
    t = threading.Thread(target=_read, daemon=True)
    t.start()
    t.join(timeout)
    return q[0].strip() if q else ""

def lhm_start():
    global _ps_proc, _ps_script, _lhm_ok
    dll = _dll_path()
    if not os.path.exists(dll):
        return False
    # AppData klasorune yaz: temp klasoru yerine daha az suphe ceker
    path = os.path.join(_appdata_dir(), "lhm_sensor.ps1")
    with open(path, "w", encoding="utf-8") as f:
        f.write(_LHM_PS)
    _ps_script = path
    try:
        flags = 0x08000000  # CREATE_NO_WINDOW
        proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-File", path, dll],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, creationflags=flags,
        )
        ready = _ps_readline_timeout(proc, timeout=20.0)
        if ready == "READY":
            _ps_proc = proc
            _lhm_ok = True
            return True
        proc.kill()
        return False
    except Exception:
        return False

def lhm_read():
    global _ps_proc, _lhm_ok
    if not _lhm_ok or _ps_proc is None:
        return {}, False
    if _ps_proc.poll() is not None:
        _lhm_ok = False
        return {}, False

    with _ps_lock:
        try:
            _ps_proc.stdin.write("READ\n")
            _ps_proc.stdin.flush()
        except Exception:
            _lhm_ok = False
            return {}, False

        result = {}
        cur_hw = None
        deadline = time.time() + 10.0
        while time.time() < deadline:
            try:
                line = _ps_proc.stdout.readline()
            except Exception:
                break
            if not line:
                break
            line = line.strip()
            if line == "END":
                return result, True
            if line.startswith("ERROR|"):
                break
            parts = line.split("|", 4)
            if parts[0] == "HW" and len(parts) >= 4:
                hw_id  = parts[1]
                hw_name = parts[2]
                hw_type = parts[3].split(".")[-1]
                cur_hw = hw_id
                result[hw_id] = {"id": hw_id, "name": hw_name,
                                  "type": hw_type, "sensors": []}
            elif parts[0] == "S" and len(parts) >= 5 and cur_hw:
                try:
                    val = float(parts[4])
                    stype = parts[3].split(".")[-1]
                    result[cur_hw]["sensors"].append({
                        "id": parts[1], "name": parts[2],
                        "type": stype, "value": val,
                        "unit": UNITS.get(stype, ""),
                    })
                except ValueError:
                    pass
        return {}, False

def lhm_stop():
    global _ps_proc, _lhm_ok
    if _ps_proc and _ps_proc.poll() is None:
        try:
            _ps_proc.stdin.write("EXIT\n")
            _ps_proc.stdin.flush()
            _ps_proc.wait(timeout=3)
        except Exception:
            _ps_proc.kill()
    _ps_proc = None
    _lhm_ok = False

# ─── nvidia-smi (GPU yedek) ──────────────────────────────────────────────────
_nvd_ok = None

def nvidia_read():
    global _nvd_ok
    if _nvd_ok is False:
        return {}
    try:
        out = subprocess.check_output(
            ["nvidia-smi",
             "--query-gpu=name,temperature.gpu,utilization.gpu,"
             "clocks.gr,power.draw,memory.used,memory.total,fan.speed",
             "--format=csv,noheader,nounits"],
            stderr=subprocess.DEVNULL, timeout=3,
            creationflags=0x08000000,
        ).decode(errors="ignore").strip()
        gpus = {}
        for i, line in enumerate(out.splitlines()):
            cols = [c.strip() for c in line.split(",")]
            if len(cols) < 8: continue
            def fv(x):
                try: return float(x)
                except: return None
            name, temp, util, clk, pwr, mem_u, mem_t, fan = cols[:8]
            hw_id = f"gpu_nvidia_{i}"
            sens = []
            for n, v, t in [
                ("GPU Temperature", fv(temp), "Temperature"),
                ("GPU Load",        fv(util), "Load"),
                ("GPU Core Clock",  fv(clk),  "Clock"),
                ("GPU Power",       fv(pwr),  "Power"),
                ("Fan Speed",       fv(fan),  "Fan"),
            ]:
                if v is not None:
                    sens.append({"id":f"{hw_id}/{t}", "name":n,
                                 "type":t, "value":v, "unit":UNITS.get(t,"")})
            if fv(mem_u) is not None and fv(mem_t) is not None:
                mu, mt = fv(mem_u), fv(mem_t)
                sens.append({"id":f"{hw_id}/mem_used","name":"GPU Memory Used",
                             "type":"SmallData","value":mu,"unit":"MB"})
                sens.append({"id":f"{hw_id}/mem_total","name":"GPU Memory Total",
                             "type":"SmallData","value":mt,"unit":"MB"})
                if mt > 0:
                    sens.append({"id":f"{hw_id}/mem_load","name":"GPU Memory Load",
                                 "type":"Load","value":mu/mt*100,"unit":"%"})
            gpus[hw_id] = {"id":hw_id,"name":name,"type":"GpuNvidia","sensors":sens}
        _nvd_ok = True
        return gpus
    except Exception:
        _nvd_ok = False
        return {}

# ─── psutil kaynaklari ───────────────────────────────────────────────────────
_net_prev = None
_net_time  = None

def psutil_read():
    global _net_prev, _net_time
    data = {}

    cpu_pct = psutil.cpu_percent(interval=None)
    cpu_percore = psutil.cpu_percent(interval=None, percpu=True)
    cpu_freq = psutil.cpu_freq()
    cpu_sens = [{"id":"ps/cpu/load","name":"CPU Total Load","type":"Load",
                  "value":cpu_pct,"unit":"%"}]
    if cpu_freq:
        cpu_sens.append({"id":"ps/cpu/freq","name":"CPU Frequency",
                         "type":"Clock","value":cpu_freq.current,"unit":"MHz"})
    for i, p in enumerate(cpu_percore):
        cpu_sens.append({"id":f"ps/cpu/core{i}","name":f"Core #{i} Load",
                         "type":"Load","value":p,"unit":"%"})
    import platform
    data["ps_cpu"] = {"id":"ps_cpu","name":f"CPU ({platform.processor() or 'CPU'})","type":"Cpu","sensors":cpu_sens}

    vm = psutil.virtual_memory()
    sw = psutil.swap_memory()
    mem_sens = [
        {"id":"ps/mem/used","name":"Memory Used","type":"Data",
         "value":round(vm.used/1e9,2),"unit":"GB"},
        {"id":"ps/mem/avail","name":"Memory Available","type":"Data",
         "value":round(vm.available/1e9,2),"unit":"GB"},
        {"id":"ps/mem/total","name":"Memory Total","type":"Data",
         "value":round(vm.total/1e9,2),"unit":"GB"},
        {"id":"ps/mem/load","name":"Memory Load","type":"Load",
         "value":vm.percent,"unit":"%"},
    ]
    if sw.total > 0:
        mem_sens.append({"id":"ps/mem/swap_used","name":"Swap Used","type":"Data",
                         "value":round(sw.used/1e9,2),"unit":"GB"})
        mem_sens.append({"id":"ps/mem/swap_load","name":"Swap Load","type":"Load",
                         "value":sw.percent,"unit":"%"})
    data["ps_mem"] = {"id":"ps_mem","name":"Bellek","type":"Memory","sensors":mem_sens}

    disk_sens = []
    for part in psutil.disk_partitions(all=False):
        try:
            u = psutil.disk_usage(part.mountpoint)
            disk_sens += [
                {"id":f"ps/disk/{part.device}_used","name":f"{part.device} Kullanilan",
                 "type":"Data","value":round(u.used/1e9,2),"unit":"GB"},
                {"id":f"ps/disk/{part.device}_total","name":f"{part.device} Toplam",
                 "type":"Data","value":round(u.total/1e9,2),"unit":"GB"},
                {"id":f"ps/disk/{part.device}_load","name":f"{part.device} Doluluk",
                 "type":"Level","value":u.percent,"unit":"%"},
            ]
        except Exception:
            pass
    data["ps_disk"] = {"id":"ps_disk","name":"Depolama","type":"Storage","sensors":disk_sens}

    now = time.time()
    net = psutil.net_io_counters()
    net_sens = []
    if _net_prev is not None and _net_time is not None:
        dt = now - _net_time
        if dt > 0:
            rx = (net.bytes_recv - _net_prev.bytes_recv)/dt/1e6
            tx = (net.bytes_sent - _net_prev.bytes_sent)/dt/1e6
            net_sens += [
                {"id":"ps/net/rx","name":"Download Hizi","type":"Throughput",
                 "value":round(rx,3),"unit":"MB/s"},
                {"id":"ps/net/tx","name":"Upload Hizi","type":"Throughput",
                 "value":round(tx,3),"unit":"MB/s"},
            ]
    net_sens += [
        {"id":"ps/net/rx_total","name":"Toplam Alinan","type":"Data",
         "value":round(net.bytes_recv/1e9,3),"unit":"GB"},
        {"id":"ps/net/tx_total","name":"Toplam Gonderilen","type":"Data",
         "value":round(net.bytes_sent/1e9,3),"unit":"GB"},
    ]
    _net_prev = net
    _net_time = now
    data["ps_net"] = {"id":"ps_net","name":"Ag","type":"Network","sensors":net_sens}

    return data

# ─── Tum verileri birlestir ──────────────────────────────────────────────────
_lhm_started = False

def collect_all():
    global _lhm_started
    if not _lhm_started:
        _lhm_started = True
        lhm_start()

    lhm_data, lhm_ok = lhm_read()
    ps = psutil_read()

    merged = {}

    if lhm_ok and lhm_data:
        for k, v in lhm_data.items():
            if v.get("sensors"):
                merged[k] = v
        mode = "lhm"
    else:
        merged["ps_cpu"] = ps["ps_cpu"]
        merged["ps_mem"] = ps["ps_mem"]
        mode = "psutil"

    # LHM varsa ama Memory yoksa psutil ekle
    if lhm_ok and not any(v.get("type") == "Memory" for v in merged.values()):
        merged["ps_mem"] = ps["ps_mem"]

    # nvidia-smi: LHM GPU yoksa
    has_nvidia_lhm = any(v.get("type") == "GpuNvidia" for v in merged.values())
    if not has_nvidia_lhm:
        merged.update(nvidia_read())

    # Disk ve Ag her zaman psutil'den
    merged["ps_disk"] = ps["ps_disk"]
    merged["ps_net"] = ps["ps_net"]

    return merged, mode

# ─── Bar widget ──────────────────────────────────────────────────────────────
class Bar(tk.Canvas):
    W, H = 120, 10
    def __init__(self, parent, **kw):
        super().__init__(parent, width=self.W, height=self.H,
                         bg=BG_ROW, highlightthickness=0, **kw)
        self._bar_w = self.W
        self._bar_h = self.H
        self._bg_rect = self.create_rectangle(0, 0, self._bar_w, self._bar_h,
                                               fill="#222235", outline="")
        self._fg_rect = self.create_rectangle(0, 0, 0, self._bar_h,
                                               fill=ACC, outline="")

    def set(self, pct, color=ACC):
        w = int(self._bar_w * max(0, min(pct, 100)) / 100)
        self.itemconfig(self._fg_rect, fill=color)
        self.coords(self._fg_rect, 0, 0, w, self._bar_h)

# ─── Ana Pencere ─────────────────────────────────────────────────────────────
class HWMonitorPro(tk.Tk):
    REFRESH_MS = 2000

    def __init__(self):
        super().__init__()
        self.title("HWMonitor Pro")
        self.geometry("920x700")
        self.configure(bg=BG)
        self._build_header()
        self._build_scroll()
        self._rows = {}
        self._hw_frames = {}
        self._mode_var = tk.StringVar(value="baslatiliyor...")
        self._mode_lbl.config(textvariable=self._mode_var)
        self._time_var = tk.StringVar()
        self._time_lbl.config(textvariable=self._time_var)
        self._warn_shown = False
        self._warn_lbl = None
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._tick)

    def _build_header(self):
        hdr = tk.Frame(self, bg=BG_HDR)
        hdr.pack(fill="x", side="top")
        tk.Label(hdr, text="HW MONITOR PRO", font=("Consolas",14,"bold"),
                 bg=BG_HDR, fg=ACC).pack(side="left", padx=12, pady=8)
        self._mode_lbl = tk.Label(hdr, text="", font=("Consolas",9),
                                   bg=BG_HDR, fg="#00cc88")
        self._mode_lbl.pack(side="left", padx=4)
        self._time_lbl = tk.Label(hdr, text="", font=("Consolas",9),
                                   bg=BG_HDR, fg=FGD)
        self._time_lbl.pack(side="right", padx=12)
        cols = tk.Frame(self, bg=BG_SHDR)
        cols.pack(fill="x", side="top")
        for txt, w, anc in [("SENSOR",36,tk.W),("DEGER",10,tk.CENTER),
                              ("MIN",8,tk.CENTER),("MAX",8,tk.CENTER),
                              ("DURUM",16,tk.CENTER)]:
            tk.Label(cols, text=txt, font=("Consolas",8,"bold"),
                     bg=BG_SHDR, fg=FGD, width=w, anchor=anc
                     ).pack(side="left", padx=2, pady=3)

    def _build_scroll(self):
        frame = tk.Frame(self, bg=BG)
        frame.pack(fill="both", expand=True)
        self._canvas = tk.Canvas(frame, bg=BG, highlightthickness=0)
        sb = tk.Scrollbar(frame, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)
        self._inner = tk.Frame(self._canvas, bg=BG)
        self._win_id = self._canvas.create_window((0,0), window=self._inner,
                                                    anchor="nw")
        self._inner.bind("<Configure>", self._on_inner_cfg)
        self._canvas.bind("<Configure>", self._on_canvas_cfg)
        self._canvas.bind_all("<MouseWheel>", self._on_scroll)

    def _on_inner_cfg(self, e):
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_cfg(self, e):
        self._canvas.itemconfig(self._win_id, width=e.width)

    def _on_scroll(self, e):
        self._canvas.yview_scroll(int(-1*(e.delta/120)), "units")

    def _tick(self):
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        try:
            data, mode = collect_all()
            self.after(0, lambda: self._refresh(data, mode))
        except Exception:
            pass
        self.after(self.REFRESH_MS, self._tick)

    def _refresh(self, data, mode):
        self._time_var.set(datetime.now().strftime("%H:%M:%S"))
        mode_map = {
            "lhm":    "[LHM DLL - Tam sensor verileri]",
            "psutil": "[psutil - Sinirli / Yonetici olarak calistirin]",
        }
        self._mode_var.set(mode_map.get(mode, f"[{mode}]"))

        has_temp = any(
            s.get("type") == "Temperature"
            for hw in data.values()
            for s in hw.get("sensors",[])
        )

        if not has_temp and not self._warn_shown:
            self._warn_shown = True
            children = self._inner.winfo_children()
            self._warn_lbl = tk.Label(
                self._inner,
                text="  UYARI: Sicaklik sensoru yok — Uygulamayi Yonetici olarak calistirin!",
                font=("Consolas",9,"bold"), bg="#330000", fg="#ff4444",
                anchor="w", padx=8, pady=6,
            )
            if children:
                self._warn_lbl.pack(fill="x", before=children[0])
            else:
                self._warn_lbl.pack(fill="x")
        elif has_temp and self._warn_shown and self._warn_lbl:
            self._warn_lbl.destroy()
            self._warn_lbl = None
            self._warn_shown = False

        ordered = self._sort_hw(data)
        for hw in ordered:
            self._upsert_hw(hw)

        visible_ids = {hw["id"] for hw in ordered}
        for hw_id, frame in self._hw_frames.items():
            if hw_id not in visible_ids:
                frame.pack_forget()

    def _sort_hw(self, data):
        ordered = []
        seen = set()
        for order_type in HW_ORDER:
            for hw in data.values():
                if hw.get("type") == order_type and hw["id"] not in seen:
                    if hw.get("sensors"):
                        ordered.append(hw)
                        seen.add(hw["id"])
        for hw in data.values():
            if hw["id"] not in seen and hw.get("sensors"):
                ordered.append(hw)
                seen.add(hw["id"])
        return ordered

    def _upsert_hw(self, hw):
        hw_id = hw["id"]
        hw_type = hw.get("type","")
        label = HW_LABELS.get(hw_type, hw_type.upper())
        color = HW_COLORS.get(hw_type, "#334455")

        if hw_id not in self._hw_frames:
            outer = tk.Frame(self._inner, bg=BG)
            outer.pack(fill="x", padx=4, pady=(6,0))
            hdr = tk.Frame(outer, bg=color)
            hdr.pack(fill="x")
            tk.Label(hdr, text=f"  {label}  —  {hw['name']}",
                     font=("Consolas",9,"bold"), bg=color, fg="white",
                     anchor="w").pack(side="left", padx=4, pady=3)
            body = tk.Frame(outer, bg=BG)
            body.pack(fill="x")
            self._hw_frames[hw_id] = outer
            outer._body = body
            outer._sensor_frames = {}
        else:
            outer = self._hw_frames[hw_id]
            outer.pack(fill="x", padx=4, pady=(6,0))

        body = outer._body
        sensor_frames = outer._sensor_frames

        for i, s in enumerate(hw.get("sensors",[])):
            sid = s["id"]
            val = s.get("value")
            stype = s.get("type","")
            unit = s.get("unit","")
            mn, mx = track(sid, val)
            color_v = val_color(stype, val)
            pct = bar_pct(stype, val)
            fmt_v  = f"{val:.1f} {unit}" if val is not None else "N/A"
            fmt_mn = f"{mn:.1f}" if mn is not None else "-"
            fmt_mx = f"{mx:.1f}" if mx is not None else "-"
            bg_row = BG_ROW if i%2==0 else BG_ROW2

            if sid not in sensor_frames:
                row = tk.Frame(body, bg=bg_row)
                row.pack(fill="x")
                tk.Label(row, text=s["name"], font=("Consolas",8),
                         bg=bg_row, fg=FG, width=36, anchor="w"
                         ).pack(side="left", padx=(8,2))
                v_lbl = tk.Label(row, text=fmt_v, font=("Consolas",9,"bold"),
                                  bg=bg_row, fg=color_v, width=10, anchor="center")
                v_lbl.pack(side="left")
                mn_lbl = tk.Label(row, text=fmt_mn, font=("Consolas",8),
                                   bg=bg_row, fg=FGD, width=8, anchor="center")
                mn_lbl.pack(side="left")
                mx_lbl = tk.Label(row, text=fmt_mx, font=("Consolas",8),
                                   bg=bg_row, fg=FGD, width=8, anchor="center")
                mx_lbl.pack(side="left")
                bar = Bar(row, bg=bg_row)
                bar.pack(side="left", padx=6)
                row._widgets = (v_lbl, mn_lbl, mx_lbl, bar)
                sensor_frames[sid] = row
            else:
                row = sensor_frames[sid]
                v_lbl, mn_lbl, mx_lbl, bar = row._widgets
                v_lbl.config(text=fmt_v, fg=color_v)
                mn_lbl.config(text=fmt_mn)
                mx_lbl.config(text=fmt_mx)
                bar.set(pct, color_v)

    def _on_close(self):
        lhm_stop()
        self.destroy()

if __name__ == "__main__":
    app = HWMonitorPro()
    app.mainloop()
