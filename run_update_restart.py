import os
import urllib.request
import shutil
import zipfile
import hashlib
import subprocess
from datetime import datetime

# === CONFIGURATION ===
BASE_DIR = os.path.dirname(__file__)
ITEMS_URL = "https://www.dropbox.com/scl/fi/vgs0c6ceze19p4pcuero2/items.cp311-win_amd64.pyd?rlkey=0w8l6u1ohvb3ea060hn6fro6z&st=rsycccw1&dl=1"
APP_ZIP_URL = "https://www.dropbox.com/scl/fi/qv4dlq33zsz4ieq0mg9qf/update.zip?rlkey=uzailps75sas1nrxbfdrfvkc9&st=pnn3ayxh&dl=1"

LOCAL_ITEMS_PATH = os.path.join(BASE_DIR, "items.cp311-win_amd64.pyd")
TEMP_ITEMS_PATH = os.path.join(BASE_DIR, "items_temp.cp311-win_amd64.pyd")
TEMP_ZIP_PATH = os.path.join(BASE_DIR, "update_temp.zip")
LOCAL_ZIP_HASH_PATH = os.path.join(BASE_DIR, "last_update_hash.txt")
TEMP_EXTRACT_DIR = os.path.join(BASE_DIR, "update_temp")
LOG_FILE = os.path.join(BASE_DIR, "update_log.txt")

PYTHONW_PATH = os.path.join(BASE_DIR, "WinPython", "python-3.11.9.amd64", "pythonw.exe")
LABEL_APP_PATH = os.path.join(BASE_DIR, "launch.py")

restart_needed = False


def log(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a") as f:
        f.write(f"[{timestamp}] {message}\n")


def hash_file(path):
    hasher = hashlib.sha256()
    with open(path, 'rb') as afile:
        while chunk := afile.read(8192):
            hasher.update(chunk)
    return hasher.hexdigest()


def download_file(url, dest):
    with urllib.request.urlopen(url) as response:
        if response.status != 200:
            raise Exception(f"HTTP status: {response.status}")
        with open(dest, 'wb') as out_file:
            shutil.copyfileobj(response, out_file)


def stop_label_app():
    try:
        subprocess.run([
            "powershell", "-Command",
            "Get-CimInstance Win32_Process -Filter \"Name = 'pythonw.exe'\" | "
            "Where-Object { $_.CommandLine -like '*label_app.py*' -or $_.CommandLine -like '*launch.py*' } | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
        ], check=True)
        log("Terminated running label_app process.")
    except Exception as e:
        log(f"Failed to stop running app: {e}")


def update_items():
    global restart_needed
    try:
        download_file(ITEMS_URL, TEMP_ITEMS_PATH)

        if not os.path.exists(LOCAL_ITEMS_PATH):
            shutil.move(TEMP_ITEMS_PATH, LOCAL_ITEMS_PATH)
            log("items.pyd did not exist. Downloaded and saved.")
            restart_needed = True
            return

        if hash_file(LOCAL_ITEMS_PATH) != hash_file(TEMP_ITEMS_PATH):
            shutil.move(TEMP_ITEMS_PATH, LOCAL_ITEMS_PATH)
            log("items.pyd updated.")
            restart_needed = True
        else:
            os.remove(TEMP_ITEMS_PATH)
            log("items.pyd unchanged. Skipped update.")

    except Exception as e:
        log(f"items.pyd update failed: {e}")
        if os.path.exists(TEMP_ITEMS_PATH):
            os.remove(TEMP_ITEMS_PATH)


def update_app():
    global restart_needed
    try:
        download_file(APP_ZIP_URL, TEMP_ZIP_PATH)
        new_hash = hash_file(TEMP_ZIP_PATH)

        if os.path.exists(LOCAL_ZIP_HASH_PATH):
            with open(LOCAL_ZIP_HASH_PATH, 'r') as f:
                if f.read().strip() == new_hash:
                    os.remove(TEMP_ZIP_PATH)
                    log("update.zip unchanged. Skipped app update.")
                    return

        if os.path.exists(TEMP_EXTRACT_DIR):
            shutil.rmtree(TEMP_EXTRACT_DIR)

        with zipfile.ZipFile(TEMP_ZIP_PATH, 'r') as zip_ref:
            zip_ref.extractall(TEMP_EXTRACT_DIR)

        for root, dirs, files in os.walk(TEMP_EXTRACT_DIR):
            rel_path = os.path.relpath(root, TEMP_EXTRACT_DIR)
            target_dir = os.path.join(BASE_DIR, rel_path)
            os.makedirs(target_dir, exist_ok=True)
            for file in files:
                shutil.copy2(os.path.join(root, file), os.path.join(target_dir, file))

        log("App updated from update.zip")
        with open(LOCAL_ZIP_HASH_PATH, 'w') as f:
            f.write(new_hash)
        restart_needed = True

    except Exception as e:
        log(f"App update failed: {e}")

    finally:
        if os.path.exists(TEMP_ZIP_PATH):
            os.remove(TEMP_ZIP_PATH)
        if os.path.exists(TEMP_EXTRACT_DIR):
            shutil.rmtree(TEMP_EXTRACT_DIR)


def start_label_app():
    try:
        subprocess.Popen([PYTHONW_PATH, LABEL_APP_PATH], cwd=BASE_DIR)
        log("label_app.py started.")
    except Exception as e:
        log(f"Failed to start app: {e}")


if __name__ == "__main__":
    stop_label_app()
    update_items()
    update_app()
    start_label_app()

