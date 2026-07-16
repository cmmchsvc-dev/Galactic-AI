import psutil
import os
import time
import subprocess

for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
    try:
        if proc.info['name'] == 'python.exe' and proc.info['cmdline'] and 'galactic_core_v2.py' in proc.info['cmdline']:
            print(f"Killing PID {proc.info['pid']}")
            proc.kill()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        pass

time.sleep(2)
subprocess.Popen(['powershell.exe', '-WindowStyle', 'Hidden', '-Command', "cd 'C:\\Users\\Chesley\\Galactic AI'; & 'C:\\Program Files\\Python311\\python.exe' galactic_core_v2.py"])
print('Restarted.')
