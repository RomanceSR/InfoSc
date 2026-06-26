import tkinter as tk
from tkinter import ttk, font
import psutil
import platform
import threading
import time
import subprocess
import re
from datetime import datetime


def get_cpu_temps():
    temps = {}
    try:
        sensors = psutil.sensors_temperatures()
        if sensors:
            for name, entries in sensors.items():
                for entry in entries:
                    label = entry.label or name
                    temps[f"{name} / {label}"] = {
                        "current": entry.current,
                        "high": entry.high,
                        "critical": entry.critical,
                    }
    except Exception:
        pass

    if not temps:
        try:
            result = subprocess.run(
                ["sensors"], capture_output=True, text=True, timeout=3
            )
            current_chip = ""
            for line in result.stdout.splitlines():
                line = line.strip()
                if line and not line.startswith(" ") and ":" not in line:
                    current_chip = line
                elif "°C" in line or "temp" in line.lower():
                    match = re.search(r"(.+?):\s+\+?([\d.]+)°C", line)
                    if match:
                        label = match.group(1).strip()
                        val = float(match.group(2))
                        key = f"{current_chip} / {label}" if current_chip else label
                        temps[key] = {"current": val, "high": None, "critical": None}
        except Exception:
            pass

    return temps


def get_cpu_info():
    info = {}
    info["model"] = platform.processor() or "N/A"
    info["cores_physical"] = psutil.cpu_count(logical=False) or "N/A"
    info["cores_logical"] = psutil.cpu_count(logical=True) or "N/A"
    freq = psutil.cpu_freq()
    if freq:
        info["freq_current"] = f"{freq.current:.0f} MHz"
        info["freq_max"] = f"{freq.max:.0f} MHz"
    else:
        info["freq_current"] = "N/A"
        info["freq_max"] = "N/A"
    return info


def get_memory_info():
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    return {
        "total": f"{mem.total / 1024**3:.1f} GB",
        "used": f"{mem.used / 1024**3:.1f} GB",
        "available": f"{mem.available / 1024**3:.1f} GB",
        "percent": mem.percent,
        "swap_total": f"{swap.total / 1024**3:.1f} GB",
        "swap_used": f"{swap.used / 1024**3:.1f} GB",
        "swap_percent": swap.percent,
    }


def get_disk_info():
    disks = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
            disks.append({
                "device": part.device,
                "mountpoint": part.mountpoint,
                "fstype": part.fstype,
                "total": f"{usage.total / 1024**3:.1f} GB",
                "used": f"{usage.used / 1024**3:.1f} GB",
                "free": f"{usage.free / 1024**3:.1f} GB",
                "percent": usage.percent,
            })
        except Exception:
            pass
    return disks


def get_network_info():
    net = psutil.net_io_counters()
    return {
        "bytes_sent": f"{net.bytes_sent / 1024**2:.1f} MB",
        "bytes_recv": f"{net.bytes_recv / 1024**2:.1f} MB",
        "packets_sent": net.packets_sent,
        "packets_recv": net.packets_recv,
    }


def temp_color(value, high=None, critical=None):
    if critical and value >= critical:
        return "#FF2244"
    if high and value >= high:
        return "#FF8800"
    if value >= 90:
        return "#FF2244"
    if value >= 70:
        return "#FF8800"
    if value >= 50:
        return "#FFDD00"
    return "#00DD88"


class TempBar(tk.Canvas):
    def __init__(self, parent, width=220, height=18, **kwargs):
        super().__init__(parent, width=width, height=height,
                         bg="#1a1a2e", highlightthickness=0, **kwargs)
        self.width = width
        self.height = height

    def set_value(self, value, color="#00DD88"):
        self.delete("all")
        self.create_rectangle(0, 0, self.width, self.height,
                              fill="#2a2a3e", outline="#444466")
        fill_w = int(self.width * min(value, 100) / 100)
        if fill_w > 0:
            self.create_rectangle(0, 0, fill_w, self.height, fill=color, outline="")
        self.create_text(self.width // 2, self.height // 2,
                         text=f"{value:.0f}%", fill="white",
                         font=("Consolas", 9, "bold"))


class HWInfoApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("HWMonitor - Sistem Sicaklik Izleyici")
        self.geometry("900x700")
        self.configure(bg="#0d0d1a")
        self.resizable(True, True)
        self._build_ui()
        self._refresh()

    def _build_ui(self):
        # Title bar
        title_frame = tk.Frame(self, bg="#16213e", pady=10)
        title_frame.pack(fill="x")
        tk.Label(title_frame, text="  HWMonitor", font=("Consolas", 18, "bold"),
                 fg="#00aaff", bg="#16213e").pack(side="left", padx=15)
        self.time_label = tk.Label(title_frame, text="", font=("Consolas", 10),
                                    fg="#888899", bg="#16213e")
        self.time_label.pack(side="right", padx=15)

        # CPU usage bar at top
        cpu_top = tk.Frame(self, bg="#0d0d1a", pady=6)
        cpu_top.pack(fill="x", padx=15)
        tk.Label(cpu_top, text="CPU Kullanimi:", font=("Consolas", 10),
                 fg="#aaaacc", bg="#0d0d1a").pack(side="left")
        self.cpu_bar = TempBar(cpu_top, width=400, height=20)
        self.cpu_bar.pack(side="left", padx=10)
        self.cpu_pct_label = tk.Label(cpu_top, text="", font=("Consolas", 10, "bold"),
                                       fg="#00aaff", bg="#0d0d1a")
        self.cpu_pct_label.pack(side="left")

        # Notebook tabs
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Dark.TNotebook", background="#0d0d1a", borderwidth=0)
        style.configure("Dark.TNotebook.Tab", background="#16213e", foreground="#aaaacc",
                        padding=[14, 6], font=("Consolas", 10))
        style.map("Dark.TNotebook.Tab",
                  background=[("selected", "#0f3460")],
                  foreground=[("selected", "#00aaff")])

        nb = ttk.Notebook(self, style="Dark.TNotebook")
        nb.pack(fill="both", expand=True, padx=10, pady=5)

        # Tab frames
        self.temp_tab = tk.Frame(nb, bg="#0d0d1a")
        self.cpu_tab = tk.Frame(nb, bg="#0d0d1a")
        self.mem_tab = tk.Frame(nb, bg="#0d0d1a")
        self.disk_tab = tk.Frame(nb, bg="#0d0d1a")
        self.net_tab = tk.Frame(nb, bg="#0d0d1a")

        nb.add(self.temp_tab, text="  Sicakliklar  ")
        nb.add(self.cpu_tab, text="  CPU  ")
        nb.add(self.mem_tab, text="  Bellek  ")
        nb.add(self.disk_tab, text="  Disk  ")
        nb.add(self.net_tab, text="  Ag  ")

        self._build_temp_tab()
        self._build_cpu_tab()
        self._build_mem_tab()
        self._build_disk_tab()
        self._build_net_tab()

    def _scrollable(self, parent):
        canvas = tk.Canvas(parent, bg="#0d0d1a", highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        frame = tk.Frame(canvas, bg="#0d0d1a")
        frame.bind("<Configure>", lambda e: canvas.configure(
            scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(
            -1 * (e.delta // 120), "units"))
        return frame

    def _section(self, parent, title):
        tk.Label(parent, text=f"  {title}", font=("Consolas", 11, "bold"),
                 fg="#00aaff", bg="#16213e", pady=6, anchor="w").pack(
            fill="x", padx=10, pady=(10, 2))

    def _row(self, parent, label, value_text="", color="#ddddff"):
        f = tk.Frame(parent, bg="#1a1a2e")
        f.pack(fill="x", padx=20, pady=2)
        tk.Label(f, text=label, font=("Consolas", 10), fg="#aaaacc",
                 bg="#1a1a2e", width=30, anchor="w").pack(side="left")
        lbl = tk.Label(f, text=value_text, font=("Consolas", 10, "bold"),
                       fg=color, bg="#1a1a2e", anchor="w")
        lbl.pack(side="left")
        return lbl

    def _build_temp_tab(self):
        self.temp_frame = self._scrollable(self.temp_tab)
        self.temp_widgets = {}
        self._section(self.temp_frame, "Sicaklik Sensörleri")
        self.no_temp_label = tk.Label(
            self.temp_frame,
            text="  Sicaklik verisi aliniyor...",
            font=("Consolas", 10), fg="#888899", bg="#0d0d1a"
        )
        self.no_temp_label.pack(anchor="w", padx=20)

    def _build_cpu_tab(self):
        frame = self._scrollable(self.cpu_tab)
        self._section(frame, "İşlemci Bilgileri")
        info = get_cpu_info()
        self._row(frame, "Model:", info["model"], "#ffffff")
        self._row(frame, "Fiziksel Çekirdek:", str(info["cores_physical"]))
        self._row(frame, "Mantiksal Çekirdek:", str(info["cores_logical"]))
        self._row(frame, "Mevcut Frekans:", info["freq_current"])
        self._row(frame, "Maksimum Frekans:", info["freq_max"])
        self._row(frame, "İşletim Sistemi:", f"{platform.system()} {platform.release()}")
        self._row(frame, "Mimari:", platform.machine())

        self._section(frame, "Çekirdek Kullanimi")
        self.core_bars = []
        for i in range(psutil.cpu_count(logical=True) or 1):
            f = tk.Frame(frame, bg="#1a1a2e")
            f.pack(fill="x", padx=20, pady=2)
            tk.Label(f, text=f"Çekirdek {i}:", font=("Consolas", 10),
                     fg="#aaaacc", bg="#1a1a2e", width=12, anchor="w").pack(side="left")
            bar = TempBar(f, width=300, height=16)
            bar.pack(side="left", padx=5)
            lbl = tk.Label(f, text="0%", font=("Consolas", 10, "bold"),
                           fg="#00aaff", bg="#1a1a2e", width=6)
            lbl.pack(side="left")
            self.core_bars.append((bar, lbl))

    def _build_mem_tab(self):
        frame = self._scrollable(self.mem_tab)
        self._section(frame, "RAM Bellek")
        self.mem_labels = {}
        for k, label in [
            ("total", "Toplam RAM:"), ("used", "Kullanilan:"),
            ("available", "Musait:"), ("percent", "Kullanim %:"),
        ]:
            self.mem_labels[k] = self._row(frame, label)
        self.mem_bar = None
        f = tk.Frame(frame, bg="#1a1a2e")
        f.pack(fill="x", padx=20, pady=4)
        tk.Label(f, text="Kullanim:", font=("Consolas", 10),
                 fg="#aaaacc", bg="#1a1a2e", width=30, anchor="w").pack(side="left")
        self.mem_bar = TempBar(f, width=300, height=20)
        self.mem_bar.pack(side="left")

        self._section(frame, "Swap Bellek")
        self.swap_labels = {}
        for k, label in [
            ("swap_total", "Toplam Swap:"), ("swap_used", "Kullanilan:"),
            ("swap_percent", "Kullanim %:"),
        ]:
            self.swap_labels[k] = self._row(frame, label)
        f2 = tk.Frame(frame, bg="#1a1a2e")
        f2.pack(fill="x", padx=20, pady=4)
        tk.Label(f2, text="Kullanim:", font=("Consolas", 10),
                 fg="#aaaacc", bg="#1a1a2e", width=30, anchor="w").pack(side="left")
        self.swap_bar = TempBar(f2, width=300, height=20)
        self.swap_bar.pack(side="left")

    def _build_disk_tab(self):
        self.disk_frame = self._scrollable(self.disk_tab)
        self.disk_widgets = []

    def _build_net_tab(self):
        frame = self._scrollable(self.net_tab)
        self._section(frame, "Ag İstatistikleri")
        self.net_labels = {}
        for k, label in [
            ("bytes_sent", "Gönderilen:"), ("bytes_recv", "Alinan:"),
            ("packets_sent", "Gönderilen Paket:"), ("packets_recv", "Alinan Paket:"),
        ]:
            self.net_labels[k] = self._row(frame, label)

        self._section(frame, "Ag Arayüzleri")
        self.iface_frame = tk.Frame(frame, bg="#0d0d1a")
        self.iface_frame.pack(fill="x")
        for iface, addrs in psutil.net_if_addrs().items():
            f = tk.Frame(self.iface_frame, bg="#1a1a2e")
            f.pack(fill="x", padx=20, pady=2)
            tk.Label(f, text=iface, font=("Consolas", 10, "bold"),
                     fg="#00aaff", bg="#1a1a2e", width=20, anchor="w").pack(side="left")
            ip = next((a.address for a in addrs if a.family.name == "AF_INET"), "")
            tk.Label(f, text=ip, font=("Consolas", 10),
                     fg="#ddddff", bg="#1a1a2e").pack(side="left")

    def _update_temps(self):
        temps = get_cpu_temps()
        if not temps:
            self.no_temp_label.config(
                text="  Sicaklik sensörü bulunamadi.\n  Linux: 'sensors' komutunu deneyin (lm-sensors paketi)."
            )
            return
        self.no_temp_label.pack_forget()

        existing = set(self.temp_widgets.keys())
        new_keys = set(temps.keys())

        for key in existing - new_keys:
            if key in self.temp_widgets:
                self.temp_widgets[key][0].destroy()
                del self.temp_widgets[key]

        for key, data in temps.items():
            val = data["current"]
            high = data.get("high")
            crit = data.get("critical")
            color = temp_color(val, high, crit)

            if key not in self.temp_widgets:
                f = tk.Frame(self.temp_frame, bg="#1a1a2e")
                f.pack(fill="x", padx=20, pady=2)
                tk.Label(f, text=key[:38], font=("Consolas", 10),
                         fg="#aaaacc", bg="#1a1a2e", width=40, anchor="w").pack(side="left")
                val_lbl = tk.Label(f, text="", font=("Consolas", 11, "bold"),
                                   bg="#1a1a2e", width=10, anchor="w")
                val_lbl.pack(side="left")
                bar = TempBar(f, width=200, height=16)
                bar.pack(side="left", padx=5)
                self.temp_widgets[key] = (f, val_lbl, bar)

            _, val_lbl, bar = self.temp_widgets[key]
            val_lbl.config(text=f"{val:.1f} °C", fg=color)
            bar.set_value(min(val, 120) / 120 * 100, color)

    def _update_cpu_cores(self):
        percore = psutil.cpu_percent(percpu=True)
        for i, (bar, lbl) in enumerate(self.core_bars):
            if i < len(percore):
                pct = percore[i]
                color = temp_color(pct)
                bar.set_value(pct, color)
                lbl.config(text=f"{pct:.0f}%", fg=color)

        total_pct = psutil.cpu_percent()
        color = temp_color(total_pct)
        self.cpu_bar.set_value(total_pct, color)
        self.cpu_pct_label.config(text=f"{total_pct:.1f}%", fg=color)

    def _update_mem(self):
        info = get_memory_info()
        self.mem_labels["total"].config(text=info["total"])
        self.mem_labels["used"].config(text=info["used"], fg="#FF8800" if info["percent"] > 80 else "#00DD88")
        self.mem_labels["available"].config(text=info["available"])
        pct = info["percent"]
        self.mem_labels["percent"].config(text=f"{pct}%", fg=temp_color(pct))
        self.mem_bar.set_value(pct, temp_color(pct))

        self.swap_labels["swap_total"].config(text=info["swap_total"])
        self.swap_labels["swap_used"].config(text=info["swap_used"])
        sp = info["swap_percent"]
        self.swap_labels["swap_percent"].config(text=f"{sp}%", fg=temp_color(sp))
        self.swap_bar.set_value(sp, temp_color(sp))

    def _update_disk(self):
        disks = get_disk_info()
        for w in self.disk_widgets:
            w.destroy()
        self.disk_widgets.clear()

        for disk in disks:
            self._section(self.disk_frame, f"{disk['device']}  ({disk['mountpoint']})")
            for label, val in [
                ("Dosya Sistemi:", disk["fstype"]),
                ("Toplam:", disk["total"]),
                ("Kullanilan:", disk["used"]),
                ("Bos:", disk["free"]),
            ]:
                f = tk.Frame(self.disk_frame, bg="#1a1a2e")
                f.pack(fill="x", padx=20, pady=2)
                tk.Label(f, text=label, font=("Consolas", 10),
                         fg="#aaaacc", bg="#1a1a2e", width=30, anchor="w").pack(side="left")
                tk.Label(f, text=val, font=("Consolas", 10, "bold"),
                         fg="#ddddff", bg="#1a1a2e").pack(side="left")
                self.disk_widgets.append(f)

            f2 = tk.Frame(self.disk_frame, bg="#1a1a2e")
            f2.pack(fill="x", padx=20, pady=2)
            tk.Label(f2, text="Kullanim:", font=("Consolas", 10),
                     fg="#aaaacc", bg="#1a1a2e", width=30, anchor="w").pack(side="left")
            bar = TempBar(f2, width=300, height=18)
            bar.set_value(disk["percent"], temp_color(disk["percent"]))
            bar.pack(side="left")
            pct_lbl = tk.Label(f2, text=f"  {disk['percent']}%",
                                font=("Consolas", 10, "bold"),
                                fg=temp_color(disk["percent"]), bg="#1a1a2e")
            pct_lbl.pack(side="left")
            self.disk_widgets.extend([f2])

    def _update_net(self):
        info = get_network_info()
        for k, lbl in self.net_labels.items():
            lbl.config(text=str(info[k]))

    def _refresh(self):
        self.time_label.config(text=datetime.now().strftime("Son güncelleme: %H:%M:%S"))

        def worker():
            self._update_temps()
            self._update_cpu_cores()
            self._update_mem()
            self._update_disk()
            self._update_net()

        threading.Thread(target=worker, daemon=True).start()
        self.after(2000, self._refresh)


if __name__ == "__main__":
    app = HWInfoApp()
    app.mainloop()
