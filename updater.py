import time
import subprocess
import os
import sys
import logging

try:
    import psutil
except ImportError:
    subprocess.run([sys.executable, '-m', 'pip', 'install', 'psutil'], check=True)
    import psutil

logging.basicConfig(
    format='%(asctime)s - [Updater] - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler("updater.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

# Interval in seconds to check for updates
CHECK_INTERVAL = 10

def get_local_commit():
    try:
        return subprocess.check_output(['git', 'rev-parse', 'HEAD']).strip().decode('utf-8')
    except Exception as e:
        logger.error(f"Failed to get local commit: {e}")
        return None

def get_remote_commit():
    try:
        subprocess.run(['git', 'fetch', 'origin', 'master'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return subprocess.check_output(['git', 'rev-parse', 'origin/master']).strip().decode('utf-8')
    except Exception as e:
        logger.error(f"Failed to get remote commit: {e}")
        return None

def start_bot():
    logger.info("Starting bot.py...")
    # sys.executable ensures we use the same Python interpreter (the .venv one if executed from .venv)
    return subprocess.Popen([sys.executable, "bot.py"])

def stop_bot(proc):
    if proc and proc.poll() is None:
        logger.info("Stopping bot.py...")
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            logger.warning("Bot didn't stop in 10s, killing process...")
            proc.kill()
            proc.wait()

def kill_ghosts():
    logger.info("Scanning for ghost processes from previous runs...")
    current_proc = psutil.Process(os.getpid())
    
    # Get all parent PIDs to avoid killing the venv shim or cmd.exe
    safe_pids = {current_proc.pid}
    for p in current_proc.parents():
        safe_pids.add(p.pid)
        
    target_dir = os.path.abspath(os.path.dirname(__file__)).lower()
    
    killed = 0
    for p in psutil.process_iter(['pid', 'name', 'cmdline', 'cwd']):
        try:
            if p.info['pid'] in safe_pids:
                continue
                
            cmd = p.info.get('cmdline') or []
            if not cmd:
                continue
                
            cmd_str = " ".join(cmd).lower()
            
            # Check if this is a python process running our bot or updater
            if 'python' in p.info['name'].lower() and ('bot.py' in cmd_str or 'updater.py' in cmd_str):
                # Verify it's running from our specific directory
                cwd = p.info.get('cwd', '').lower()
                if not cwd or cwd == target_dir:
                    logger.warning(f"Found ghost process PID {p.info['pid']} ({cmd_str}). Killing it...")
                    p.kill()
                    killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
            
    if killed > 0:
        logger.info(f"Successfully killed {killed} ghost process(es).")

def main():
    logger.info("Starting Auto-Updater...")
    kill_ghosts()
    bot_process = start_bot()
    
    while True:
        try:
            time.sleep(CHECK_INTERVAL)
            
            local = get_local_commit()
            remote = get_remote_commit()
            
            if local and remote and local != remote:
                logger.info(f"Update detected! Local: {local[:7]} -> Remote: {remote[:7]}")
                
                logger.info("Pulling changes from git...")
                pull_result = subprocess.run(['git', 'pull', 'origin', 'master'], capture_output=True, text=True)
                if pull_result.returncode != 0:
                    logger.error(f"Git pull failed: {pull_result.stderr}")
                    continue
                
                logger.info("Installing requirements...")
                pip_result = subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt'], capture_output=True, text=True)
                if pip_result.returncode != 0:
                    logger.error(f"Pip install failed: {pip_result.stderr}")
                else:
                    logger.info("Requirements installed successfully.")
                
                logger.info("Restarting bot for update...")
                stop_bot(bot_process)
                bot_process = start_bot()
                
            elif bot_process.poll() is not None:
                logger.warning("Bot crashed or stopped unexpectedly. Restarting...")
                bot_process = start_bot()
                
        except Exception as e:
            logger.error(f"Error in updater loop: {e}")

if __name__ == "__main__":
    main()
