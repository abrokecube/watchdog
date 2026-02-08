import json
import os
import subprocess
import time
import psutil
import logging
from typing import List, Dict, Optional, Any
import threading

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ProcessWatcher:
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.processes: List[Dict] = []
        self.running_processes: Dict[str, int] = {}
        self.stopped_processes: set = set()
        self.lock = threading.RLock()
        self.load_config()

    def load_config(self):
        if not os.path.exists(self.config_path):
            logger.error(f"Config file not found: {self.config_path}")
            return

        try:
            with open(self.config_path, 'r') as f:
                new_config = json.load(f)
            
            with self.lock:
                self.processes = new_config
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
            pid = self.running_processes[name]
            if psutil.pid_exists(pid):
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
                
                pid = None
                
                if os.name == 'nt':
                    # Use WMI to spawn process detached from everything (daemonize)
                    # This breaks the Job Object chain completely
                    
                    # Construct command line
                    full_cmd = subprocess.list2cmdline(cmd)
                    
                    # Escape for PowerShell
                    full_cmd_ps = full_cmd.replace("'", "''")
                    cwd_ps = cwd.replace("'", "''")
                    
                    ps_script = (
                        f"$res = Invoke-WmiMethod -Class Win32_Process -Name Create -ArgumentList '{full_cmd_ps}', '{cwd_ps}'; "
                        "if ($res.ReturnValue -eq 0) { $res.ProcessId } else { exit 1 }"
                    )
                    
                    ps_cmd = ["powershell", "-NoProfile", "-Command", ps_script]
                    
                    # Run the launcher
                    try:
                        output = subprocess.check_output(ps_cmd, text=True).strip()
                    except subprocess.CalledProcessError:
                        logger.error(f"WMI failed to start process '{name}'")
                        return False

                    if output and output.isdigit():
                        pid = int(output)
                    else:
                        logger.error(f"Failed to get PID from WMI launcher for '{name}'. Output: {output}")
                        return False
                else:
                    # Fallback for non-Windows (standard Popen)
                    proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, start_new_session=True)
                    pid = proc.pid

                self.running_processes[name] = pid
                
                if 'pid_file' in config:
                    with open(config['pid_file'], 'w') as f:
                        f.write(str(pid))
                
                logger.info(f"Process '{name}' started with PID {pid}")
                return True
            except Exception as e:
                logger.error(f"Failed to start process '{name}': {e}")
                return False

    def stop_process(self, name: str) -> bool:
        with self.lock:
            pids_to_kill = set()
            
            # 1. Internal tracking
            if name in self.running_processes:
                pids_to_kill.add(self.running_processes[name])
                del self.running_processes[name]
            
            self.stopped_processes.add(name)
            
            # 2. Config based lookup (PID file, match, etc)
            # We check this even if we found an internal PID, because they might differ
            # (e.g. wrapper process vs actual process in PID file)
            config = self.get_config_by_name(name)
            if config:
                pid_from_lookup = None
                if 'pid_file' in config:
                    pid_from_lookup = self.check_pid_file(config['pid_file'], config.get('process_match'), config.get('executable_path'))
                
                if pid_from_lookup is None and 'process_match' in config:
                    pid_from_lookup = self.find_process_by_match(config['process_match'], config.get('executable_path'))

                if pid_from_lookup is None and 'executable_path' in config and 'process_match' not in config:
                    pid_from_lookup = self.find_process_by_match(None, config['executable_path'])
                
                if pid_from_lookup:
                    pids_to_kill.add(pid_from_lookup)

            if not pids_to_kill:
                logger.info(f"Process '{name}' is not running.")
                return False

            success = False
            for pid in pids_to_kill:
                try:
                    p = psutil.Process(pid)
                    p.terminate()
                    try:
                        p.wait(timeout=5)
                    except psutil.TimeoutExpired:
                        p.kill()
                    logger.info(f"Process '{name}' (PID {pid}) stopped.")
                    success = True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    logger.info(f"Process '{name}' (PID {pid}) was already gone.")
                    success = True
                except Exception as e:
                    logger.error(f"Failed to kill process '{name}' (PID {pid}): {e}")
            
            return success

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
                    if not p_config.get('enabled', True):
                        continue

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

    def run_command(self, name: str, command: List[str]) -> Dict[str, Any]:
        config = self.get_config_by_name(name)
        if not config:
            return {"success": False, "output": f"Process '{name}' not found", "error": ""}

        cwd = config.get('cwd', '.')
        try:
            logger.info(f"Running command {command} for '{name}' in {cwd}")
            # Use typing.List for command type hint if needed, but List is imported
            result = subprocess.run(
                command, 
                cwd=cwd, 
                capture_output=True, 
                text=True, 
                check=False
            )
            return {
                "success": result.returncode == 0,
                "output": result.stdout,
                "error": result.stderr
            }
        except Exception as e:
            logger.error(f"Failed to run command for '{name}': {e}")
            return {"success": False, "output": "", "error": str(e)}
