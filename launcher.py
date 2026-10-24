import os
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path


def port_open(host: str, port: int, timeout: float = 0.2) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, port)) == 0


def main() -> int:
    base_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    work_dir = Path(os.getcwd())

    # Prefer colocated backend exe in current folder.
    backend_exe = work_dir / "smarton-backend.exe"
    if not backend_exe.exists():
        backend_exe = base_dir / "smarton-backend.exe"

    if not port_open("127.0.0.1", 8000):
        if backend_exe.exists():
            subprocess.Popen([str(backend_exe)], cwd=str(work_dir), creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            # Fallback for source mode.
            subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"], cwd=str(work_dir), creationflags=subprocess.CREATE_NO_WINDOW)

        for _ in range(50):
            if port_open("127.0.0.1", 8000):
                break
            time.sleep(0.2)

    webbrowser.open("http://127.0.0.1:8000")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
