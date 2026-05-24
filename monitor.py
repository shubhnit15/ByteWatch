import threading
import time
import psutil
from database import log_metrics

class SystemMonitor:
    """
    Background system monitoring thread that collects live telemetry metrics
    using psutil and caches them in a thread-safe manner for instantaneous reads.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(SystemMonitor, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, interval=1.0):
        if self._initialized:
            return
        
        self.interval = interval
        self.running = False
        self.thread = None
        self.lock = threading.Lock()
        
        # In-memory metrics cache
        self.stats = {
            "cpu_percent": 0.0,
            "cpu_cores_logical": psutil.cpu_count(logical=True),
            "cpu_cores_physical": psutil.cpu_count(logical=False),
            "cpu_frequency_mhz": 0.0,
            "cpu_load_avg": [0.0, 0.0, 0.0],
            "memory_percent": 0.0,
            "memory_total_gb": 0.0,
            "memory_used_gb": 0.0,
            "memory_available_gb": 0.0,
            "processes": []
        }
        
        # Prime the psutil cpu_percent calls (first call returns 0.0)
        psutil.cpu_percent(interval=None)
        for proc in psutil.process_iter(['cpu_percent']):
            try:
                proc.cpu_percent()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
                
        self._initialized = True

    def start(self):
        """Start the background monitor thread."""
        with self.lock:
            if not self.running:
                self.running = True
                self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
                self.thread.start()
                print("ByteWatch system telemetry daemon started.")

    def stop(self):
        """Stop the background monitor thread."""
        with self.lock:
            self.running = False
        if self.thread:
            self.thread.join(timeout=2.0)
            print("ByteWatch system telemetry daemon stopped.")

    def get_latest_stats(self):
        """Return a copy of the latest system stats in a thread-safe way. Refreshes live on serverless Vercel."""
        import os
        if os.environ.get("VERCEL") or os.environ.get("NOW_REGION"):
            self._update_stats_live()
        with self.lock:
            return self.stats.copy()

    def _update_stats_live(self):
        """Synchronously pull stats once (designed for Serverless/Vercel environments)."""
        try:
            # Query CPU percent (without blocking using interval=None)
            cpu_p = psutil.cpu_percent(interval=None)
            
            cpu_freq = 0.0
            try:
                freq_info = psutil.cpu_freq()
                if freq_info:
                    cpu_freq = freq_info.current
            except Exception:
                pass
                
            load_avg = [0.0, 0.0, 0.0]
            if hasattr(psutil, "getloadavg"):
                try:
                    load_avg = list(psutil.getloadavg())
                except Exception:
                    pass
            else:
                load_avg = [round(cpu_p / 100.0 * self.stats["cpu_cores_logical"], 2), 0.0, 0.0]

            mem = psutil.virtual_memory()
            mem_p = mem.percent
            mem_total = round(mem.total / (1024 ** 3), 2)
            mem_used = round(mem.used / (1024 ** 3), 2)
            mem_avail = round(mem.available / (1024 ** 3), 2)

            # Write metrics history
            log_metrics(cpu_p, mem_p)
            
            # Fetch processes list
            processes_list = self._fetch_top_processes()

            with self.lock:
                self.stats.update({
                    "cpu_percent": cpu_p,
                    "cpu_frequency_mhz": round(cpu_freq, 1),
                    "cpu_load_avg": load_avg,
                    "memory_percent": mem_p,
                    "memory_total_gb": mem_total,
                    "memory_used_gb": mem_used,
                    "memory_available_gb": mem_avail,
                    "processes": processes_list
                })
        except Exception as e:
            print(f"Error updating stats live: {e}")

    def _monitor_loop(self):
        """Daemon thread loop for gathering telemetry metrics."""
        process_refresh_counter = 0
        
        while True:
            # Check running state safely
            with self.lock:
                if not self.running:
                    break
            
            try:
                # 1. Capture CPU stats
                cpu_p = psutil.cpu_percent(interval=None)
                
                # Fetch cpu freq safely
                cpu_freq = 0.0
                try:
                    freq_info = psutil.cpu_freq()
                    if freq_info:
                        cpu_freq = freq_info.current
                except Exception:
                    pass
                
                # Fetch load average safely (fallback on Windows)
                load_avg = [0.0, 0.0, 0.0]
                if hasattr(psutil, "getloadavg"):
                    try:
                        load_avg = list(psutil.getloadavg())
                    except Exception:
                        pass
                else:
                    # Windows fallback: represent mock load averages using current cpu percent
                    load_avg = [round(cpu_p / 100.0 * self.stats["cpu_cores_logical"], 2), 0.0, 0.0]

                # 2. Capture Memory stats
                mem = psutil.virtual_memory()
                mem_p = mem.percent
                mem_total = round(mem.total / (1024 ** 3), 2)
                mem_used = round(mem.used / (1024 ** 3), 2)
                mem_avail = round(mem.available / (1024 ** 3), 2)

                # 3. Log to SQLite
                log_metrics(cpu_p, mem_p)

                # 4. Refresh processes (every 2 cycles to save CPU)
                processes_list = self.stats["processes"]
                process_refresh_counter += 1
                if process_refresh_counter >= 2 or not processes_list:
                    process_refresh_counter = 0
                    processes_list = self._fetch_top_processes()

                # 5. Update thread-safe stats cache
                with self.lock:
                    self.stats.update({
                        "cpu_percent": cpu_p,
                        "cpu_frequency_mhz": round(cpu_freq, 1),
                        "cpu_load_avg": load_avg,
                        "memory_percent": mem_p,
                        "memory_total_gb": mem_total,
                        "memory_used_gb": mem_used,
                        "memory_available_gb": mem_avail,
                        "processes": processes_list
                    })

            except Exception as e:
                print(f"Error gathering telemetry metrics: {e}")
                
            time.sleep(self.interval)

    def _fetch_top_processes(self):
        """Fetch the top 15 running processes sorted by CPU percentage."""
        temp_processes = []
        for proc in psutil.process_iter(['pid', 'name', 'username', 'cpu_percent', 'memory_percent']):
            try:
                # Handle permissions / zombie processes
                info = proc.info
                if info['cpu_percent'] is None:
                    info['cpu_percent'] = 0.0
                if info['memory_percent'] is None:
                    info['memory_percent'] = 0.0
                
                # Fetch memory usage in MB
                try:
                    mem_info = proc.memory_info()
                    info['memory_mb'] = round(mem_info.rss / (1024 * 1024), 1)
                except Exception:
                    info['memory_mb'] = 0.0

                temp_processes.append(info)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        
        # Sort by cpu_percent descending and slice to top 15
        temp_processes.sort(key=lambda p: p['cpu_percent'], reverse=True)
        return temp_processes[:15]

# Singleton instance accessor
monitor = SystemMonitor()
