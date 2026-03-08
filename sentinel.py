
import time
import os
import subprocess

# --- Configuration ---
LOG_FILE_PATH = r"C:\Users\Chesley\Galactic AI\logs\gateway.log"
COMMAND_FILE_PATH = r"C:\Users\Chesley\Galactic AI\messages\command.in"
STATUS_FILE_PATH = r"C:\Users\Chesley\Galactic AI\logs\sentinel_status.log"
HEARTBEAT_INTERVAL = 5  # seconds
LOG_CHECK_INTERVAL = 2 # seconds
CWD = r"C:\Users\Chesley\Galactic AI"

# --- Main Sentinel Logic ---

def write_status(message):
    """Writes a status message with a timestamp."""
    with open(STATUS_FILE_PATH, "a") as f:
        f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")

def check_for_commands():
    """Checks for and executes commands from the command file."""
    if os.path.exists(COMMAND_FILE_PATH):
        write_status("Command file detected.")
        with open(COMMAND_FILE_PATH, "r") as f:
            command = f.read().strip()
        
        # Immediately delete the file to prevent re-execution
        os.remove(COMMAND_FILE_PATH)

        if command:
            write_status(f"Executing command: {command}")
            try:
                # Execute the command using PowerShell
                result = subprocess.run(
                    ["powershell", "-Command", command],
                    capture_output=True,
                    text=True,
                    cwd=CWD,
                    timeout=300 # 5 minute timeout
                )
                stdout = result.stdout.strip()
                stderr = result.stderr.strip()
                if stdout:
                    write_status(f"COMMAND STDOUT:\n{stdout}")
                if stderr:
                    write_status(f"COMMAND STDERR:\n{stderr}")
                write_status("Command execution finished.")
            except Exception as e:
                write_status(f"Command execution failed: {e}")

def tail(f, n=10):
    """Returns the last n lines of a file."""
    # Simple tail implementation for watching logs
    try:
        with open(f, 'r') as f_handle:
            lines = f_handle.readlines()
            return lines[-n:]
    except FileNotFoundError:
        return []
    except Exception as e:
        write_status(f"Error tailing log file: {e}")
        return []

def watch_logs():
    """Monitors the log file for critical errors."""
    # This is a placeholder for more advanced logic.
    # For now, it just demonstrates reading the log.
    recent_lines = tail(LOG_FILE_PATH)
    for line in recent_lines:
        if "ERROR" in line or "CRITICAL" in line:
            # In the future, this could trigger a self-healing script.
            pass # Placeholder for now

def main_loop():
    """The main execution loop for the Sentinel."""
    write_status("Sentinel Core Process Started. PID: " + str(os.getpid()))
    last_heartbeat_time = time.time()

    while True:
        # Check for commands
        check_for_commands()
        
        # Monitor logs
        watch_logs()

        # Heartbeat
        current_time = time.time()
        if current_time - last_heartbeat_time >= HEARTBEAT_INTERVAL:
            write_status("...heartbeat...")
            last_heartbeat_time = current_time
        
        time.sleep(LOG_CHECK_INTERVAL)

if __name__ == "__main__":
    # Ensure messages directory exists
    os.makedirs(os.path.dirname(COMMAND_FILE_PATH), exist_ok=True)
    main_loop()
