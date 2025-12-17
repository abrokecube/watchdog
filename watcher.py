import json
import os
import subprocess
import time
import psutil
import logging
from typing import List, Dict, Optional
import threading

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ProcessWatcher:
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.processes: List[Dict] = []
        self.running_processes: Dict[str, subprocess.Popen] = {}
        self.stopped_processes: set = set()
        self.lock = threading.RLock()
        self.load_config()

    def load_config(self):
        if not os.path.exists(self.config_path):
            logger.error(f"Config file not found: {self.config_path}")
            return

        try:
            with open(self.config_path, 'r') as f:
                self.processes = json.load(f)
            logger.info("Configuration loaded.")
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding JSON config: {e}")

    def check_pid_file(self, pid_file: str, match_string: str = None, executable_path: str = None) -> Optional[int]:
        if os.path.exists(pid_file):
            try:
                with open(pid_file, 'r') as f:
                    pid = int(f.read().strip())
                if psutil.pid_exists(pid):
                    try:
                        proc = psutil.Process(pid)
                        # Verify executable path if provided
                        if executable_path:
                            if not proc.exe() or os.path.normpath(executable_path).lower() != os.path.normpath(proc.exe()).lower():
                                return None
                        
                        # Verify match string if provided
                        if match_string:
                            cmdline = proc.cmdline()
                            if not cmdline or match_string not in " ".join(cmdline):
                                return None
                                
                        return pid
                    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                        pass
            except (ValueError, OSError):
                pass
        return None

    def find_process_by_match(self, match_string: str, executable_path: str = None) -> Optional[int]:
        for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'exe']):
            try:
                if executable_path and proc.info['exe'] and os.path.normpath(executable_path).lower() == os.path.normpath(proc.info['exe']).lower():
                     return proc.info['pid']
                
                if match_string:
                    cmdline = proc.info['cmdline']
                    if cmdline:
                        # Join cmdline to search for the match string
                        full_cmd = " ".join(cmdline)
                        if match_string in full_cmd:
                            return proc.info['pid']
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        return None

    def is_running(self, name: str) -> bool:
        # Check if we are tracking it internally
        if name in self.running_processes:
            proc = self.running_processes[name]
            if proc.poll() is None:
                return True
            else:
                del self.running_processes[name]
        
        # Check if we can find it via PID file or matching
        config = self.get_config_by_name(name)
        if not config:
            return False

        pid = None
        if 'pid_file' in config:
            pid = self.check_pid_file(config['pid_file'], config.get('process_match'), config.get('executable_path'))
        
        if pid is None and 'process_match' in config:
             pid = self.find_process_by_match(config['process_match'], config.get('executable_path'))
        
        if pid is None and 'executable_path' in config and 'process_match' not in config:
             pid = self.find_process_by_match(None, config['executable_path'])

        return pid is not None

    def get_config_by_name(self, name: str) -> Optional[Dict]:
        for p in self.processes:
            if p['name'] == name:
                return p
        return None

    def start_process(self, name: str) -> bool:
        with self.lock:
            if self.is_running(name):
                logger.info(f"Process '{name}' is already running.")
                return True

            # Remove from stopped set if we are manually starting it
            if name in self.stopped_processes:
                self.stopped_processes.remove(name)

            config = self.get_config_by_name(name)
            if not config:
                logger.error(f"No configuration found for process '{name}'")
                return False

            try:
                logger.info(f"Starting process '{name}'...")
                cwd = config.get('cwd', '.')
                cmd = config['command']
                
                kwargs = {}
                if os.name == 'nt':
                    # CREATE_NEW_PROCESS_GROUP (0x200) | DETACHED_PROCESS (0x08)
                    kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000008
                
                proc = subprocess.Popen(
                    cmd, 
                    cwd=cwd, 
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                    **kwargs
                )
                self.running_processes[name] = proc
                
                if 'pid_file' in config:
                    with open(config['pid_file'], 'w') as f:
                        f.write(str(proc.pid))
                
                logger.info(f"Process '{name}' started with PID {proc.pid}")
                return True
            except Exception as e:
                logger.error(f"Failed to start process '{name}': {e}")
                return False

    def stop_process(self, name: str) -> bool:
        with self.lock:
            # First check internal tracking
            if name in self.running_processes:
                proc = self.running_processes[name]
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                del self.running_processes[name]
                self.stopped_processes.add(name)
                logger.info(f"Process '{name}' stopped.")
                return True
            
            # If not tracked internally, try to find it and kill it
            config = self.get_config_by_name(name)
            if not config:
                return False
            
            # Mark as stopped even if we haven't found the PID yet, 
            # effectively disabling auto-restart for this process
            self.stopped_processes.add(name)

            pid = None
            if 'pid_file' in config:
                pid = self.check_pid_file(config['pid_file'])
            
            if pid is None and 'process_match' in config:
                pid = self.find_process_by_match(config['process_match'], config.get('executable_path'))

            if pid is None and 'executable_path' in config and 'process_match' not in config:
                pid = self.find_process_by_match(None, config['executable_path'])

            if pid:
                try:
                    p = psutil.Process(pid)
                    p.terminate()
                    p.wait(timeout=5)
                    logger.info(f"Process '{name}' (PID {pid}) stopped.")
                    return True
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
                    try:
                        p.kill()
                        return True
                    except:
                        logger.error(f"Failed to kill process '{name}' (PID {pid})")
                        return False
            
            logger.info(f"Process '{name}' is not running.")
            return False

    def restart_process(self, name: str) -> bool:
        self.stop_process(name)
        time.sleep(1)
        return self.start_process(name)

    def monitor_loop(self):
        logger.info("Starting monitor loop...")
        while True:
            with self.lock:
                for p_config in self.processes:
                    name = p_config['name']
                    if name in self.stopped_processes:
                        continue
                        
                    if not self.is_running(name):
                        logger.warning(f"Process '{name}' is down. Restarting...")
                        self.start_process(name)
            time.sleep(5)

    def get_all_statuses(self) -> Dict[str, str]:
        statuses = {}
        for p in self.processes:
            name = p['name']
            if self.is_running(name):
                statuses[name] = "Running"
            elif name in self.stopped_processes:
                statuses[name] = "Stopped (Manual)"
            else:
                statuses[name] = "Stopped"
        return statuses
