#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║        Telegram File Host Bot  —  24/7 Python Runner        ║
║                                                              ║
║  Setup:                                                      ║
║    pip install "python-telegram-bot[job-queue]==21.*"        ║
║    Windows: set BOT_TOKEN=... && set ADMIN_ID=...            ║
║                                                              ║
║  Run:                                                        ║
║    BOT_TOKEN=xxx ADMIN_ID=yyy python telegram_file_host_bot.py
╚══════════════════════════════════════════════════════════════╝
"""

import ast
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
import os, re, sys, json, time, asyncio, logging, subprocess, hashlib, threading, html, signal, ctypes, shlex, traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, Any

# ── Auto-bootstrap: install and verify the exact Telegram runtime ──────────────
def _bootstrap_bot_deps() -> None:
    """Install and verify python-telegram-bot without killing Termux startup."""
    base_dir = Path(__file__).resolve().parent
    bot_venv = base_dir / ".bot-venv"
    venv_python = bot_venv / (
        Path("Scripts") / "python.exe" if os.name == "nt"
        else Path("bin") / "python"
    )

    _pip = [sys.executable, "-m", "pip"]
    _PTB = "python-telegram-bot[job-queue]==21.*"
    _FLAGS = ["--disable-pip-version-check", "--no-input",
              "--prefer-binary", "--retries", "2", "--timeout", "60", "-q"]
    _IMPORT_CHECK = (
        "from telegram import (Update, InlineKeyboardButton, "
        "InlineKeyboardMarkup, InputFile, ReplyKeyboardMarkup, BotCommand, "
        "MenuButtonCommands, MenuButtonWebApp, WebAppInfo); "
        "from telegram.ext import (Application, CommandHandler, MessageHandler, "
        "CallbackQueryHandler, filters, ContextTypes); "
        "from telegram.error import (InvalidToken, NetworkError, TimedOut, "
        "RetryAfter, TelegramError); print('telegram runtime verified')"
    )

    def _check_runtime() -> tuple[bool, str]:
        try:
            result = subprocess.run(
                [sys.executable, "-c", _IMPORT_CHECK],
                capture_output=True, text=True, timeout=30,
            )
        except Exception as exc:
            return False, str(exc)
        detail = (result.stderr or result.stdout or "").strip()
        return result.returncode == 0, detail

    def _purge_shadow() -> None:
        try:
            subprocess.run(
                [*_pip, "uninstall", "telegram", "-y",
                 "--disable-pip-version-check", "--no-input", "-q"],
                capture_output=True, text=True, timeout=45,
            )
        except Exception as exc:
            print(f"⚠️ Could not check the conflicting 'telegram' package: {exc}",
                  flush=True)

    def _install(force: bool = False) -> None:
        command = [*_pip, "install", "--upgrade"]
        if force:
            command.append("--force-reinstall")
        result = subprocess.run(
            [*command, _PTB, *_FLAGS],
            capture_output=True, text=True, timeout=240,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "pip returned an error").strip()
            raise RuntimeError(detail[-2500:])

    # Fast-path: all symbols already import → start immediately.
    ready, _ = _check_runtime()
    if ready:
        return

    try:
        # Normal pip works on Termux in most installations and is faster than
        # creating a venv. Only fall back to a venv for externally-managed
        # interpreters or broken system package permissions.
        print("⚙️ Installing/verifying Telegram library…", flush=True)
        _purge_shadow()
        _install()
        _purge_shadow()
    except Exception as exc:
        first_error = str(exc)
        # Android/Termux and newer Linux distributions may reject writes to
        # the system interpreter. Retry inside a local venv if possible.
        if Path(sys.prefix).resolve() != bot_venv.resolve():
            print("⚙️ System Python install blocked; preparing isolated environment…",
                  flush=True)
            try:
                if not venv_python.exists():
                    result = subprocess.run(
                        [sys.executable, "-m", "venv", str(bot_venv)],
                        capture_output=True, text=True, timeout=180,
                    )
                    if result.returncode != 0 or not venv_python.exists():
                        detail = (
                            result.stderr or result.stdout or "venv creation failed"
                        ).strip()
                        raise RuntimeError(detail[-2000:])
                os.execv(
                    str(venv_python),
                    [str(venv_python), str(Path(__file__)), *sys.argv[1:]],
                )
            except SystemExit:
                raise
            except Exception as venv_error:
                print(
                    "❌ Telegram library install failed.\n"
                    f"System Python: {first_error}\n"
                    f"Isolated environment: {venv_error}\n\n"
                    "Run: python -m pip install --upgrade "
                    "'python-telegram-bot[job-queue]==21.*'",
                    flush=True,
                )
                raise SystemExit(1)
        print(
            "❌ Telegram library install failed. The bot was not started.\n"
            f"{first_error}",
            flush=True,
        )
        raise SystemExit(1)

    ready, detail = _check_runtime()
    if not ready:
        print("⚠️ Telegram import still failed; trying one clean reinstall…", flush=True)
        try:
            _purge_shadow()
            _install(force=True)
            _purge_shadow()
            ready, detail = _check_runtime()
        except Exception as exc:
            detail = str(exc)
        if not ready:
            print(
                "❌ Telegram library is still broken after installation.\n"
                f"{detail[-2500:]}\n\n"
                "Remove any package named 'telegram' and reinstall "
                "python-telegram-bot.",
                flush=True,
            )
            raise SystemExit(1)
    print("✅ Telegram runtime ready.", flush=True)

_bootstrap_bot_deps()
# ── End bootstrap ──────────────────────────────────────────────────────────────

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile,
    ReplyKeyboardMarkup, BotCommand, MenuButtonCommands, MenuButtonWebApp,
    WebAppInfo,
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes,
)
from telegram.error import (
    InvalidToken, NetworkError, TimedOut, RetryAfter, TelegramError,
)

# ══════════════════════════ CONFIG ════════════════════════════
BRAND_NAME = "ƬʜᴇΉΛᑕKΣЯ♛"

def load_local_env() -> None:
    """Load a small local .env file without requiring python-dotenv.

    This is convenient on Windows while keeping credentials outside the
    distributed source file. Existing environment variables always win.
    """
    env_file = Path(__file__).parent / ".env"
    if not env_file.exists():
        return
    try:
        for raw_line in env_file.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip()
            if value[:1] in {"'", '"'} and value[-1:] == value[:1]:
                value = value[1:-1]
            os.environ.setdefault(key, value)
    except OSError:
        # A missing/unreadable optional .env is handled by main() below.
        pass

def clean_setting(value: str) -> str:
    """Remove common copy/paste whitespace and quote artifacts."""
    return value.strip().strip("\"'").strip()

load_local_env()
BOT_TOKEN: str = clean_setting(os.getenv("BOT_TOKEN", ""))
ADMIN_ID_RAW = clean_setting(os.getenv("ADMIN_ID", "0"))
try:
    ADMIN_ID: int = int(ADMIN_ID_RAW)
except ValueError:
    ADMIN_ID = 0

BASE_DIR = Path(__file__).parent.resolve()
# Render service disks are persistent only when mounted.  STORAGE_DIR points
# all mutable bot data to that persistent disk instead of the git checkout.
STORAGE_DIR = Path(clean_setting(os.getenv("STORAGE_DIR", "/var/data"))).expanduser().resolve()
try:
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    # Local/Pydroid fallback when /var/data is unavailable.
    STORAGE_DIR = BASE_DIR / "data"
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
FILES_DIR  = STORAGE_DIR / "hosted_files"
DATA_FILE  = STORAGE_DIR / "bot_data.json"
BACKUP_FILE = STORAGE_DIR / "bot_data.json.bak"
VENV_DIR   = STORAGE_DIR / "venv"
VENV_PIP   = VENV_DIR / (Path("Scripts") / "pip.exe" if os.name == "nt" else Path("bin") / "pip")
VENV_PY    = VENV_DIR / (Path("Scripts") / "python.exe" if os.name == "nt" else Path("bin") / "python3")
KEEP_PORT  = int(os.getenv("PORT", os.getenv("KEEP_PORT", "8000")))  # Render/web health port
DROP_PENDING_UPDATES = os.getenv("DROP_PENDING_UPDATES", "1").lower() in {"1", "true", "yes"}
MAX_FILE_BYTES = int(os.getenv("MAX_FILE_BYTES", str(2 * 1024 * 1024)))
# Package installation executes third-party setup code. Keep it off by default;
# an operator can explicitly opt in after reviewing the security implications.
# Uploaded scripts are read and their dependencies are installed before the
# approval notification. Operators can still disable this with AUTO_INSTALL_PACKAGES=0.
AUTO_INSTALL_PACKAGES = os.getenv("AUTO_INSTALL_PACKAGES", "1").lower() in {"1", "true", "yes"}
AUTO_HOST_ON_UPLOAD = os.getenv("AUTO_HOST_ON_UPLOAD", "1").lower() in {"1", "true", "yes"}
AUTO_CREATE_VENV = os.getenv("AUTO_CREATE_VENV", "1").lower() in {"1", "true", "yes"}
PACKAGE_INSTALL_TIMEOUT = max(30, int(os.getenv("PACKAGE_INSTALL_TIMEOUT", "180")))
PACKAGE_INSTALL_RETRIES = max(1, int(os.getenv("PACKAGE_INSTALL_RETRIES", "3")))
PYTHON_TELEGRAM_BOT_SPEC = "python-telegram-bot[job-queue]==21.*"
MINI_APP_URL = clean_setting(os.getenv("MINI_APP_URL", "")) or (clean_setting(os.getenv("RENDER_EXTERNAL_URL", "")).rstrip("/") + "/miniapp" if os.getenv("RENDER_EXTERNAL_URL") else "")
MINI_APP_PATH = "/miniapp"
ALLOW_RISKY_OVERRIDE = os.getenv("ALLOW_RISKY_OVERRIDE", "1").lower() in {"1", "true", "yes"}

FILES_DIR.mkdir(parents=True, exist_ok=True)

# Telegram native keyboards cannot choose their own background colors. This
# embedded Web App keeps all existing bot copy while providing the premium,
# colored interface requested by the owner.
MINI_APP_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>ƬʜᴇΉΛᑕKΣЯ♛</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <style>
    :root {
      --ink: #18242b;
      --muted: #68757b;
      --paper: #fbfff9;
      --mint: #d7efd9;
      --coral: #ed696a;
      --green: #62c555;
      --blue: #48a9e8;
      --purple: #8f72d9;
      --teal: #11717a;
      --shadow: 0 18px 45px rgba(20, 84, 72, .18);
    }
    * { box-sizing: border-box; }
    html, body { margin: 0; min-height: 100%; }
    body {
      color: var(--ink);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
        "Segoe UI", sans-serif;
      background:
        radial-gradient(circle at 10% 0%, rgba(255,255,255,.96) 0 18%, transparent 42%),
        linear-gradient(140deg, #caebcf 0%, #edf8e8 46%, #b7e3ca 100%);
      padding: max(16px, env(safe-area-inset-top)) 14px max(24px, env(safe-area-inset-bottom));
    }
    .shell { max-width: 520px; margin: 0 auto; }
    .hero {
      position: relative;
      overflow: hidden;
      border-radius: 28px;
      padding: 21px 20px 19px;
      color: #fff;
      background: linear-gradient(135deg, #0c6872, #118e83);
      box-shadow: var(--shadow);
    }
    .hero:after {
      content: ""; position: absolute; width: 180px; height: 180px; right: -56px; top: -72px;
      border: 1px solid rgba(255,255,255,.25); border-radius: 50%;
      box-shadow: 0 0 0 22px rgba(255,255,255,.06), 0 0 0 44px rgba(255,255,255,.04);
    }
    .brand { display: flex; align-items: center; gap: 13px; position: relative; z-index: 1; }
    .mark {
      display: grid; place-items: center; width: 50px; height: 50px; border-radius: 17px;
      color: #fff; font-size: 23px; font-weight: 900;
      background: rgba(255,255,255,.18); border: 1px solid rgba(255,255,255,.26);
      box-shadow: inset 0 1px rgba(255,255,255,.22);
    }
    h1 { margin: 0; font-size: 22px; letter-spacing: .02em; }
    .subtitle { margin: 3px 0 0; opacity: .8; font-size: 12px; letter-spacing: .08em; text-transform: uppercase; }
    .status {
      display: inline-flex; align-items: center; gap: 7px; margin-top: 19px; position: relative; z-index: 1;
      padding: 8px 11px; border-radius: 999px; font-size: 12px; font-weight: 700;
      color: #e6fff0; background: rgba(255,255,255,.13);
    }
    .dot { width: 7px; height: 7px; border-radius: 50%; background: #8eff91; box-shadow: 0 0 0 4px rgba(142,255,145,.14); }
    .card {
      margin-top: 14px; padding: 17px; border-radius: 25px; background: rgba(255,255,255,.86);
      border: 1px solid rgba(255,255,255,.9); box-shadow: var(--shadow); backdrop-filter: blur(14px);
    }
    .eyebrow { margin: 0 0 13px; color: var(--muted); font-size: 11px; font-weight: 800; letter-spacing: .15em; text-transform: uppercase; }
    .welcome { margin: 0 0 16px; font-size: 15px; line-height: 1.5; font-weight: 650; }
    .grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px; }
    button {
      min-height: 58px; border: 0; border-radius: 17px; color: #fff; cursor: pointer;
      padding: 11px 9px; font: inherit; font-size: 13px; font-weight: 800; line-height: 1.18;
      box-shadow: 0 7px 0 rgba(0,0,0,.08), 0 11px 18px rgba(29, 80, 75, .12);
      transition: transform .16s ease, filter .16s ease, box-shadow .16s ease;
      -webkit-tap-highlight-color: transparent;
    }
    button:active { transform: translateY(4px); box-shadow: 0 3px 0 rgba(0,0,0,.08), 0 7px 12px rgba(29,80,75,.1); }
    button:hover { filter: brightness(1.04) saturate(1.05); }
    .coral { background: linear-gradient(145deg, #f07b79, var(--coral)); }
    .green { background: linear-gradient(145deg, #70cf61, var(--green)); }
    .blue { background: linear-gradient(145deg, #59b8ee, var(--blue)); }
    .purple { background: linear-gradient(145deg, #a284e5, var(--purple)); }
    .teal { background: linear-gradient(145deg, #198b92, var(--teal)); }
    .footer {
      margin: 15px 3px 0; display: flex; align-items: center; justify-content: space-between;
      color: #507166; font-size: 11px; font-weight: 700;
    }
    .footer span:last-child { opacity: .65; }
    @media (max-width: 360px) {
      body { padding-left: 10px; padding-right: 10px; }
      .card { padding: 13px; }
      button { font-size: 12px; min-height: 54px; }
    }
  </style>
</head>
<body>
  <main class="shell">
    <section class="hero">
      <div class="brand">
        <div class="mark">♛</div>
        <div><h1>ƬʜᴇΉΛᑕKΣЯ♛</h1><p class="subtitle">Private Python hosting</p></div>
      </div>
      <div class="status"><span class="dot"></span> Bot status · Online</div>
    </section>
    <section class="card">
      <p class="eyebrow">Workspace</p>
      <p class="welcome">Upload a Python file and it stays in review until approved.</p>
      <div class="grid">
        <button class="coral" data-action="updates">▸ Updates channel</button>
        <button class="coral" data-action="upload">＋ Upload file</button>
        <button class="green" data-action="files">▣ My files</button>
        <button class="green" data-action="status">◌ Bot status</button>
        <button class="blue" data-action="analytics">◌ Analytics</button>
        <button class="blue" data-action="contact">· Contact owner</button>
      </div>
    </section>
    <div class="footer"><span>Secure review before execution</span><span>v2.0</span></div>
  </main>
  <script>
    const tg = window.Telegram && window.Telegram.WebApp;
    if (tg) { tg.ready(); tg.expand(); }
    document.querySelectorAll("[data-action]").forEach((button) => {
      button.addEventListener("click", () => {
        const payload = JSON.stringify({ action: button.dataset.action });
        if (tg) { tg.sendData(payload); }
        else { button.animate([{opacity: .55}, {opacity: 1}], {duration: 260}); }
      });
    });
  </script>
</body>
</html>"""

# ══════════════════════════ LOGGING ═══════════════════════════
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("FileHostBot")
# suppress noisy httpx logs
logging.getLogger("httpx").setLevel(logging.WARNING)

# ══════════════════════ KEEP-ALIVE SERVER ═════════════════════
class _Ping(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?", 1)[0].rstrip("/") == MINI_APP_PATH:
            body = MINI_APP_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, *_): pass

def start_keep_alive():
    try:
        srv = HTTPServer(("0.0.0.0", KEEP_PORT), _Ping)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        logger.info("Web/health server listening on :%d", KEEP_PORT)
    except Exception as e:
        logger.warning("Keep-alive failed: %s", e)

# ══════════════════════════ DATA STORE ════════════════════════
def load_data() -> dict:
    """Load persistent state, recovering from the last atomic backup if needed."""
    for candidate in (DATA_FILE, BACKUP_FILE):
        if candidate.exists():
            try:
                return normalise_data(json.loads(candidate.read_text(encoding="utf-8")))
            except Exception as exc:
                logger.error("Could not read %s: %s", candidate, exc)
    logger.warning("No valid persistent data file found; starting with empty state.")
    return {"files": {}, "force_join": {}, "settings": {}}

def save_data(data: dict):
    """Crash-safe JSON persistence: write, flush, fsync, then atomically replace."""
    payload = json.dumps(data, indent=2, default=str, ensure_ascii=False)
    tmp = DATA_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write(payload)
        fh.flush()
        os.fsync(fh.fileno())
    if DATA_FILE.exists():
        try:
            DATA_FILE.replace(BACKUP_FILE)
        except OSError:
            pass
    tmp.replace(DATA_FILE)

def normalise_data(data: dict) -> dict:
    """Keep old bot_data.json files compatible with the new controls."""
    data.setdefault("files", {})
    data.setdefault("force_join", {})
    data.setdefault("settings", {})
    for info in data["files"].values():
        # A PID is persisted so a bot restart can reconnect to a still-live
        # child process. Older data files simply become stopped/resumable.
        info.setdefault("pid", None)
        info.setdefault(
            "desired_state",
            "running"
            if info.get("pid") and not info.get("manual_stop")
            else "stopped",
        )
        info.setdefault("has_started", bool(info.get("pid")))
    return data

# in-memory {fid: Popen | RecoveredProcess}
running_processes: Dict[str, Any] = {}
paused_processes: set[str] = set()
runtime_alerted: Dict[str, float] = {}
package_install_lock = threading.Lock()

def process_is_alive(pid: Optional[int]) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        if os.name != "nt":
            proc_stat = Path(f"/proc/{pid}/stat")
            if proc_stat.exists() and proc_stat.read_text(
                encoding="utf-8", errors="ignore"
            ).split(") ", 1)[-1].startswith("Z "):
                return False
            os.kill(pid, 0)
            return True
        access = 0x1000  # PROCESS_QUERY_LIMITED_INFORMATION
        handle = ctypes.windll.kernel32.OpenProcess(access, False, pid)
        if not handle:
            return False
        exit_code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(
            handle, ctypes.byref(exit_code)
        )
        ctypes.windll.kernel32.CloseHandle(handle)
        return bool(ok and exit_code.value == 259)  # STILL_ACTIVE
    except (OSError, AttributeError):
        return False

def process_matches_file(pid: Optional[int], info: dict) -> bool:
    """Avoid treating a recycled PID as this bot's child process."""
    if not process_is_alive(pid):
        return False
    if os.name == "nt":
        return True
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().decode(
            "utf-8", errors="ignore"
        ).replace("\x00", " ")
        return info.get("filename", "") in cmdline
    except OSError:
        return False

def terminate_pid(pid: int) -> None:
    if os.name != "nt":
        os.kill(pid, signal.SIGTERM)
        return
    handle = ctypes.windll.kernel32.OpenProcess(0x0001, False, pid)
    if not handle:
        return
    ctypes.windll.kernel32.TerminateProcess(handle, 1)
    ctypes.windll.kernel32.CloseHandle(handle)

def kill_pid(pid: int) -> None:
    if os.name != "nt":
        os.kill(pid, signal.SIGKILL)
        return
    handle = ctypes.windll.kernel32.OpenProcess(0x0001, False, pid)
    if not handle:
        return
    ctypes.windll.kernel32.TerminateProcess(handle, 1)
    ctypes.windll.kernel32.CloseHandle(handle)

def suspend_pid(pid: int) -> None:
    """Pause a child without killing it, preserving its exact execution point."""
    if os.name != "nt":
        os.kill(pid, signal.SIGSTOP)
        return
    handle = ctypes.windll.kernel32.OpenProcess(0x0800, False, pid)
    if not handle:
        raise OSError(f"Could not open process {pid} for pause")
    try:
        status = ctypes.windll.ntdll.NtSuspendProcess(handle)
        if status != 0:
            raise OSError(f"Windows pause failed with status {status}")
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)

def resume_pid(pid: int) -> None:
    if os.name != "nt":
        os.kill(pid, signal.SIGCONT)
        return
    handle = ctypes.windll.kernel32.OpenProcess(0x0800, False, pid)
    if not handle:
        raise OSError(f"Could not open process {pid} for resume")
    try:
        status = ctypes.windll.ntdll.NtResumeProcess(handle)
        if status != 0:
            raise OSError(f"Windows resume failed with status {status}")
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)

class RecoveredProcess:
    """Small Popen-compatible wrapper for a child found after bot restart."""
    def __init__(self, pid: int):
        self.pid = pid

    def poll(self) -> Optional[int]:
        return None if process_is_alive(self.pid) else 1

    def terminate(self):
        terminate_pid(self.pid)

    def kill(self):
        kill_pid(self.pid)

    def wait(self, timeout: Optional[float] = None):
        deadline = time.monotonic() + timeout if timeout is not None else None
        while process_is_alive(self.pid):
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired("recovered-process", timeout)
            time.sleep(0.05)
        return 0

# ══════════════════ PACKAGE AUTO-INSTALLER ════════════════════
_STDLIB = {
    "abc","ast","asyncio","base64","binascii","builtins","cgi","cmd","code",
    "codecs","collections","concurrent","contextlib","copy","csv","ctypes",
    "dataclasses","datetime","decimal","difflib","dis","email","enum","errno",
    "fnmatch","fractions","functools","gc","getopt","getpass","glob","gzip",
    "hashlib","heapq","hmac","html","http","importlib","inspect","io",
    "itertools","json","keyword","linecache","locale","logging","math",
    "mimetypes","multiprocessing","operator","os","pathlib","pickle",
    "platform","pprint","queue","random","re","shlex","shutil","signal",
    "site","socket","socketserver","sqlite3","stat","string","struct",
    "subprocess","sys","sysconfig","tarfile","tempfile","textwrap","threading",
    "time","timeit","token","tokenize","traceback","typing","types",
    "unicodedata","unittest","urllib","uuid","warnings","weakref","xml",
    "xmlrpc","zipfile","zipimport","zlib","_thread","typing_extensions",
    "collections_abc","contextlib","functools","pathlib","dataclasses",
}

_IMPORT_TO_PKG = {
    "telegram":     PYTHON_TELEGRAM_BOT_SPEC,
    "yt_dlp":       "yt-dlp",
    "aiohttp":      "aiohttp",
    "requests":     "requests",
    "bs4":          "beautifulsoup4",
    "PIL":          "Pillow",
    "cv2":          "opencv-python",
    "numpy":        "numpy",
    "pandas":       "pandas",
    "flask":        "Flask",
    "fastapi":      "fastapi",
    "sqlalchemy":   "SQLAlchemy",
    "pydantic":     "pydantic",
    "dotenv":       "python-dotenv",
    "pymongo":      "pymongo",
    "redis":        "redis",
    "psycopg2":     "psycopg2-binary",
    "httpx":        "httpx",
    "aiofiles":     "aiofiles",
    "yaml":         "PyYAML",
    "toml":         "toml",
    "boto3":        "boto3",
    "paramiko":     "paramiko",
    "cryptography": "cryptography",
    "nacl":         "PyNaCl",
    "attr":         "attrs",
    "click":        "click",
    "rich":         "rich",
    "loguru":       "loguru",
    "tqdm":         "tqdm",
    "colorama":     "colorama",
    "pymysql":      "PyMySQL",
    "aiogram":      "aiogram",
    "pyrogram":     "pyrogram",
    "telethon":     "Telethon",
    "discord":      "discord.py",
    "tweepy":       "tweepy",
    "selenium":     "selenium",
    "scrapy":       "Scrapy",
    "lxml":         "lxml",
    "httpcore":     "httpcore",
    "anyio":        "anyio",
    "uvicorn":      "uvicorn",
    "starlette":    "starlette",
    "celery":       "celery",
    "apscheduler":  "APScheduler",
    "pytz":         "pytz",
    "dateutil":     "python-dateutil",
    "jwt":          "PyJWT",
    "stripe":       "stripe",
    "openai":       "openai",
    "anthropic":    "anthropic",
    "google":       "google-api-python-client",
    "instagrapi":   "instagrapi",
    "playwright":   "playwright",
    "werkzeug":     "Werkzeug",
    "jinja2":       "Jinja2",
    "markupsafe":   "MarkupSafe",
    "Crypto":       "pycryptodome",
}

_PACKAGE_SPEC_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*(?:\[[A-Za-z0-9_,.-]+\])?"
    r"(?:\s*(?:==|!=|<=|>=|~=|<|>)\s*[A-Za-z0-9.*!+_-]+)?$"
)

_PACKAGE_STOP_WORDS = {
    # Common words that can appear after a natural-language "pip install"
    # hint or inside copied pip error output. They are not package names.
    "a", "an", "and", "are", "available", "could", "error", "find",
    "from", "in", "is", "no", "none", "not", "of", "or", "package",
    "requirement", "requirements", "satisfies", "that", "the", "to",
    "version", "versions", "with",
}
_PACKAGE_PLACEHOLDERS = {"xxx", "example", "example-package", "your-package"}

def normalise_package_spec(value: str) -> Optional[str]:
    """Accept a safe pip spec without turning prose into a dependency.

    Uploaders commonly include hints such as ``# pip install requests OR
    aiohttp`` or paste a pip error containing ``OR (from versions: none)``.
    The old parser accepted those words as package names, which caused the
    exact ``No matching distribution found for OR`` error shown in the
    screenshot.
    """
    package = value.strip().strip("\"'`")
    # PEP 508 environment markers are valid in requirements files, but the
    # runner only needs the package portion for dependency discovery.
    package = package.split(";", 1)[0].strip()
    package = package.rstrip(".,:;")
    if not package or package.startswith("-") or "://" in package:
        return None
    lowered = package.lower()
    if lowered in _PACKAGE_STOP_WORDS or lowered in _PACKAGE_PLACEHOLDERS:
        return None
    return package if _PACKAGE_SPEC_RE.fullmatch(package) else None

def package_specs_from_text(value: str) -> list[str]:
    """Parse package names from a hint without allowing pip options or prose."""
    result = []
    try:
        tokens = shlex.split(value, comments=True, posix=True)
    except ValueError:
        tokens = re.split(r"[\s,]+", value.strip())
    for token in tokens:
        cleaned = token.strip().strip(",")
        if not cleaned or cleaned.startswith("#"):
            break
        # "OR", "and", etc. mark the end of one natural-language hint. Do
        # not continue parsing copied error text as if it were requirements.
        if cleaned.lower().rstrip(".,:;") in {"or", "and"}:
            break
        package = normalise_package_spec(cleaned)
        if package and package not in result:
            result.append(package)
    return result

def extract_packages(script_path: Path) -> list:
    """
    Extract packages to install from a script by:
    1. Parsing import statements
    2. Reading inline comments like: # pip install xxx  OR  # requirements: xxx xxx
    """
    try:
        src = script_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []

    pkgs = set()

    # Parse the complete syntax tree instead of only matching lines. This
    # catches imports inside try/except blocks, functions and multiline imports.
    try:
        tree = ast.parse(src, filename=str(script_path))
    except SyntaxError:
        tree = None
    local_modules = {
        path.stem for path in script_path.parent.glob("*.py")
        if path != script_path
    }
    local_modules.update(
        path.name for path in script_path.parent.iterdir()
        if path.is_dir() and (path / "__init__.py").exists()
    )

    if tree is not None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name.split(".", 1)[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module.split(".", 1)[0]]
            else:
                continue
            for mod in modules:
                if mod not in _STDLIB and mod not in local_modules:
                    package = _IMPORT_TO_PKG.get(mod, mod)
                    if normalise_package_spec(package):
                        pkgs.add(package)

    for line in src.splitlines():
        stripped = line.strip()

        # Parse inline hints: # pip install aiohttp requests
        m = re.search(r"#\s*pip\s+install\s+(.+)", stripped, re.IGNORECASE)
        if m:
            pkgs.update(package_specs_from_text(m.group(1)))

        # Parse: # requirements: aiohttp requests
        m = re.search(r"#\s*requirements?:\s*(.+)", stripped, re.IGNORECASE)
        if m:
            pkgs.update(package_specs_from_text(m.group(1)))

    # Also read requirements.txt if it exists next to the script
    req_txt = script_path.parent / "requirements.txt"
    if req_txt.exists():
        for line in req_txt.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                # requirements.txt may contain inline comments and markers.
                # Parse one line at a time so a bad entry cannot contaminate
                # the valid requirements around it.
                package = normalise_package_spec(line.split("#", 1)[0].strip())
                if package:
                    pkgs.add(package)

    return sorted(pkgs)

def _runtime_python_commands() -> tuple[list[str], list[str]]:
    """Return the runner's Python and pip commands, creating its venv if needed."""
    if AUTO_CREATE_VENV and not VENV_PY.exists():
        try:
            result = subprocess.run(
                [sys.executable, "-m", "venv", str(VENV_DIR)],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode != 0:
                logger.warning("Could not create runner venv: %s", result.stderr[:300])
        except Exception as exc:
            logger.warning("Runner venv creation failed: %s", exc)
    if VENV_PY.exists() and VENV_PIP.exists():
        return [str(VENV_PY)], [str(VENV_PIP)]
    return [sys.executable], [sys.executable, "-m", "pip"]

def _run_package_command(command: list[str]) -> tuple[bool, str]:
    """Run a package-management command and return a short useful result."""
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=PACKAGE_INSTALL_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return False, f"timed out after {PACKAGE_INSTALL_TIMEOUT}s"
    except OSError as exc:
        return False, str(exc)
    output = (result.stderr or result.stdout or "").strip()
    return result.returncode == 0, output[-1000:]

def verify_runtime_imports(python_command: list[str], packages: list[str]) -> tuple[bool, str]:
    """Verify imports that commonly fail despite pip reporting success."""
    if PYTHON_TELEGRAM_BOT_SPEC not in packages:
        return True, ""
    ok, output = _run_package_command([
        *python_command, "-c",
        (
            "from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup; "
            "from telegram.ext import Application, CommandHandler; "
            "print('python-telegram-bot import verified')"
        ),
    ])
    if ok:
        return True, output or "python-telegram-bot import verified"
    return False, (
        "python-telegram-bot is installed but the telegram imports are broken. "
        "The PyPI package named 'telegram' may be shadowing it. "
        + (output or "runtime import check failed")
    )

def _purge_telegram_shadow(pip_command: list, python_command: list) -> None:
    """Remove the obsolete 'telegram' package that shadows python-telegram-bot.

    The PyPI package 'telegram' installs into the same namespace as
    python-telegram-bot, so 'from telegram import Update' fails even after
    python-telegram-bot is installed. We uninstall it, then force-reinstall
    python-telegram-bot to make sure its files win.
    """
    # Step 1 – remove the shadow package (silently, it may not exist)
    _run_package_command([*pip_command, "uninstall", "-y", "telegram"])
    # Step 2 – check whether 'telegram' is still importable (cached .pth etc.)
    ok, out = _run_package_command([
        *python_command, "-c",
        "import importlib.util; s=importlib.util.find_spec('telegram'); "
        "print('SHADOW' if s and 'python_telegram_bot' not in (s.origin or '') else 'OK')"
    ])
    if "SHADOW" in out:
        # The shadow survived – force-reinstall PTB so its files overwrite the shadow
        logger.warning("telegram shadow still present; force-reinstalling python-telegram-bot")
        _run_package_command([
            *pip_command, "install", "--force-reinstall", "--no-deps",
            PYTHON_TELEGRAM_BOT_SPEC,
            "--disable-pip-version-check", "--no-input",
            "--prefer-binary", "-q",
        ])


def install_packages(pkgs: list, log_path: Optional[Path] = None) -> tuple:
    """Install packages in the isolated runner venv.

    Strategy (fastest safe path first):
    1.  If python-telegram-bot is needed, purge the conflicting 'telegram' shadow.
    2.  Batch-install all packages in one pip call (fastest).
    3.  On batch failure, fall back to sequential individual installs. Pip is
        not safe to run concurrently against the same virtual environment.
    4.  After any install that includes python-telegram-bot, verify the runtime
        import and do a second purge+force-reinstall if still broken.
    """
    clean_pkgs = sorted({
        package for item in pkgs
        for package in [normalise_package_spec(str(item))]
        if package
    })
    if not clean_pkgs:
        return True, "No extra packages needed."

    ok_list: list = []
    fail_list: list = []
    failure_details: list = []
    needs_ptb = any("python-telegram-bot" in p for p in clean_pkgs)

    with package_install_lock:
        # Venv creation and every pip mutation stay under the same lock. Two
        # simultaneous uploads must never initialise or write site-packages
        # concurrently.
        python_command, pip_command = _runtime_python_commands()

        # ── 1. Pre-install: remove conflicting 'telegram' shadow ──────────
        if needs_ptb:
            _purge_telegram_shadow(pip_command, python_command)

        # ── 2. Batch install (all packages at once — fastest) ─────────────
        try:
            batch_r = subprocess.run(
                [
                    *pip_command, "install", *clean_pkgs,
                    "--disable-pip-version-check", "--no-input",
                    "--prefer-binary", "--retries", "2",
                    "--timeout", "30", "--exists-action", "i", "-q",
                ],
                capture_output=True, text=True,
                timeout=PACKAGE_INSTALL_TIMEOUT,
            )
            if batch_r.returncode == 0:
                logger.info("Batch-installed: %s", ", ".join(clean_pkgs))
                ok_list = list(clean_pkgs)
            else:
                logger.warning(
                    "Batch install failed, switching to parallel per-package: %s",
                    (batch_r.stderr or batch_r.stdout or "")[-300:],
                )
                # ── 3. Sequential per-package fallback ─────────────────────
                # Do not install into one venv from multiple threads. That
                # causes races in site-packages and can create the same broken
                # environment the fallback is meant to repair.
                def _install_one(pkg: str) -> tuple:
                    last_err = "unknown error"
                    for attempt in range(1, PACKAGE_INSTALL_RETRIES + 1):
                        try:
                            r = subprocess.run(
                                [
                                    *pip_command, "install", pkg,
                                    "--disable-pip-version-check", "--no-input",
                                    "--prefer-binary", "--retries", "2",
                                    "--timeout", "30", "--exists-action", "i", "-q",
                                ],
                                capture_output=True, text=True,
                                timeout=PACKAGE_INSTALL_TIMEOUT,
                            )
                            if r.returncode == 0:
                                logger.info("Installed %s (attempt %d)", pkg, attempt)
                                return pkg, True, ""
                            last_err = (r.stderr or r.stdout or "non-zero exit").strip()[-300:]
                        except subprocess.TimeoutExpired:
                            last_err = f"timed out after {PACKAGE_INSTALL_TIMEOUT}s"
                        except OSError as exc:
                            last_err = str(exc)
                        if attempt < PACKAGE_INSTALL_RETRIES:
                            time.sleep(min(2 * attempt, 5))
                    return pkg, False, last_err

                for pkg in clean_pkgs:
                    pkg_name, ok, err = _install_one(pkg)
                    if ok:
                        ok_list.append(pkg_name)
                    else:
                        fail_list.append(pkg_name)
                        failure_details.append(f"{pkg_name}: {err}")

        except subprocess.TimeoutExpired:
            logger.warning("Batch install timed out; trying packages individually")
            for pkg in clean_pkgs:
                if pkg in ok_list:
                    continue
                last_err = "unknown error"
                for attempt in range(1, PACKAGE_INSTALL_RETRIES + 1):
                    try:
                        r = subprocess.run(
                            [*pip_command, "install", pkg,
                             "--disable-pip-version-check", "--no-input",
                             "--prefer-binary", "-q"],
                            capture_output=True, text=True,
                            timeout=PACKAGE_INSTALL_TIMEOUT,
                        )
                        if r.returncode == 0:
                            ok_list.append(pkg)
                            last_err = ""
                            break
                        last_err = (r.stderr or r.stdout or "")[-300:]
                    except (subprocess.TimeoutExpired, OSError) as exc:
                        last_err = str(exc)
                    if attempt < PACKAGE_INSTALL_RETRIES:
                        time.sleep(min(2 * attempt, 5))
                if last_err:
                    fail_list.append(pkg)
                    failure_details.append(f"{pkg}: {last_err}")
        except OSError as exc:
            fail_list = [p for p in clean_pkgs if p not in ok_list]
            failure_details.append(f"pip OSError: {exc}")
            logger.error("pip could not run: %s", exc)

        # ── 4. Post-install: verify python-telegram-bot runtime import ────
        verified, verification_detail = verify_runtime_imports(python_command, clean_pkgs)
        if not verified:
            logger.warning("PTB import verification failed; attempting second purge+reinstall")
            # One more aggressive attempt: purge shadow & force-reinstall
            _purge_telegram_shadow(pip_command, python_command)
            _run_package_command([
                *pip_command, "install", "--force-reinstall",
                PYTHON_TELEGRAM_BOT_SPEC,
                "--disable-pip-version-check", "--no-input",
                "--prefer-binary", "-q",
            ])
            verified, verification_detail = verify_runtime_imports(python_command, clean_pkgs)
            if not verified:
                if PYTHON_TELEGRAM_BOT_SPEC not in fail_list:
                    fail_list.append(PYTHON_TELEGRAM_BOT_SPEC)
                # Remove from ok_list if it ended up there
                ok_list = [p for p in ok_list if p != PYTHON_TELEGRAM_BOT_SPEC]
                failure_details.append(verification_detail)
            else:
                # Second attempt worked — keep PTB in ok_list
                logger.info("PTB import verified after second purge")

    parts = []
    if ok_list:         parts.append(f"✅ Installed: {', '.join(ok_list)}")
    if fail_list:       parts.append(f"⚠️ Failed: {', '.join(fail_list)}")
    if failure_details: parts.append("Details: " + " | ".join(failure_details))
    summary = "\n".join(parts) or "Nothing to install."
    if log_path:
        try:
            with log_path.open("a", encoding="utf-8", errors="replace") as log:
                log.write(f"[{datetime.now().isoformat(timespec='seconds')}] Package setup\n")
                log.write(summary + "\n")
        except OSError as exc:
            logger.warning("Could not write package setup to %s: %s", log_path, exc)
    return len(fail_list) == 0, summary


def prepare_file_packages(fid: str, info: dict) -> str:
    """Install a file's dependencies before every execution path.

    This is intentionally called from start_process(), not only from one
    Telegram command, so inline buttons and watchdog restarts get the same
    dependency guarantee.
    """
    script = FILES_DIR / info["filename"]
    pkgs = extract_packages(script)
    if not pkgs:
        summary = "📦 No extra packages detected."
        info["package_setup"] = {
            "packages": [], "ok": True, "summary": summary,
            "verified": True,
            "checked_at": datetime.now().isoformat(timespec="seconds"),
        }
        return summary

    previous = info.get("package_setup", {})
    if (
        previous.get("ok") is True
        and previous.get("verified") is True
        and sorted(previous.get("packages", [])) == sorted(pkgs)
    ):
        return previous.get("summary", "📦 Package setup already complete.")

    if not AUTO_INSTALL_PACKAGES:
        summary = (
            "📦 Packages detected but auto-install is disabled: "
            + ", ".join(pkgs)
        )
        info["package_setup"] = {
            "packages": pkgs, "ok": False, "summary": summary,
            "checked_at": datetime.now().isoformat(timespec="seconds"),
        }
        raise RuntimeError(summary)

    ok, summary = install_packages(pkgs, log_path=FILES_DIR / f"{fid}.log")
    info["package_setup"] = {
        "packages": pkgs, "ok": ok, "summary": summary,
        "verified": ok,
        "checked_at": datetime.now().isoformat(timespec="seconds"),
    }
    if not ok:
        raise RuntimeError(
            f"Package setup failed for {fid}.\n{summary}\n"
            f"Use /logs {fid} to view the full setup output."
        )
    return summary

async def auto_install_uploaded_file(fid: str, bot) -> tuple[bool, str]:
    """Install and verify detected dependencies before approval is requested."""
    data = load_data()
    info = data.get("files", {}).get(fid)
    if not info:
        return False, "File record disappeared before dependency setup."
    script = FILES_DIR / info.get("filename", "")
    packages = extract_packages(script) if script.exists() else []
    if not packages:
        return True, "📦 No extra packages detected."
    log_path = FILES_DIR / f"{fid}.log"
    ok, summary = await asyncio.to_thread(install_packages, packages, log_path)
    latest = load_data()
    latest_info = latest.get("files", {}).get(fid)
    if not latest_info:
        return False, "File record disappeared while saving dependency setup."
    latest_info["package_setup"] = {
        "packages": packages,
        "ok": ok,
        "verified": ok,
        "summary": summary,
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "automatic": True,
    }
    save_data(latest)
    # The upload handler sends the user one final status message after this
    # function returns. Do not send a second success message here, and do not
    # show a retry command when automatic setup already succeeded.
    return ok, summary

# ══════════════════════════ HELPERS ═══════════════════════════
def make_fid(user_id: int, fname: str) -> str:
    return hashlib.md5(f"{user_id}_{fname}_{time.monotonic()}".encode()).hexdigest()[:8]

def user_files(data: dict, uid: int) -> list:
    return [(fid, i) for fid, i in data["files"].items() if i["user_id"] == uid]


def accessible_files(data: dict, uid: int) -> list:
    """Admins can inspect every file; regular users see only their own files."""
    if is_admin(uid):
        return list(data.get("files", {}).items())
    return user_files(data, uid)


def can_access_file(info: Optional[dict], uid: int) -> bool:
    return bool(info and (is_admin(uid) or info.get("user_id") == uid))

def is_admin(user_id: Optional[int]) -> bool:
    return bool(user_id and user_id == ADMIN_ID)

def force_join_entries(data: dict) -> dict:
    return data.setdefault("force_join", {})

def force_join_help_text() -> str:
    return (
        "➕ *Force-join setup*\n\n"
        "Add a public channel or group with:\n"
        "`/forcejoin_add @username`\n\n"
        "For a private invite link, use:\n"
        "`/forcejoin_add -1001234567890|https://t.me/+invite|My group`\n\n"
        "The bot must be an administrator in each chat so it can verify membership. "
        "Use the buttons below to manage the list."
    )

def admin_panel_markup(data: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("＋ Add access rule", callback_data="fj_menu_add"),
            InlineKeyboardButton("☷ View channels", callback_data="fj_list"),
        ],
        [
            InlineKeyboardButton("⌫ Remove channel", callback_data="fj_menu_remove"),
            InlineKeyboardButton("◉ Pending files", callback_data="admin_pending"),
        ],
        [
            InlineKeyboardButton("◌ Analytics", callback_data="admin_stats"),
            InlineKeyboardButton("⚙ Settings", callback_data="admin_settings"),
        ],
        [
            InlineKeyboardButton("↻ Refresh", callback_data="admin_panel"),
        ],
    ])

def admin_panel_text(data: dict) -> str:
    entries = force_join_entries(data)
    files = data.get("files", {})
    pending = sum(info.get("status") == "pending" for info in files.values())
    settings = data.setdefault("settings", {})
    if entries:
        join_lines = "\n".join(
            f"• `{chat_id}` — {item.get('title') or item.get('link') or 'chat'}"
            for chat_id, item in entries.items()
        )
    else:
        join_lines = "• No force-join chats configured."
    return (
        f"◆ *{BRAND_NAME} · ADMIN CONSOLE*\n\n"
        "Manage approvals, safety review and access rules from the controls below.\n\n"
        "*Access rules:*\n"
        f"{join_lines}\n\n"
        f"◉ Pending approvals: `{pending}`\n"
        f"◈ Safety scan: `ACTIVE`\n"
        f"▸ Updates: `{settings.get('updates_link') or 'not configured'}`\n"
        f"▸ Contact: `{settings.get('contact') or 'not configured'}`\n\n"
        "A user must be a member of every listed chat before using the bot."
    )

def safe_markdown(value: Any) -> str:
    return str(value).replace("\\", "\\\\").replace("`", "\\`")

# These checks are deliberately conservative. Uploaded scripts are arbitrary
# code and are executed in a subprocess, so a match holds the file for review.
_DANGEROUS_PATTERNS = [
    (r"\bos\.system\s*\(", "OS command execution"),
    (r"\bsubprocess\.(run|Popen|call|check_call|check_output)\s*\(", "subprocess execution"),
    (r"\b(?:eval|exec)\s*\(", "dynamic code execution"),
    (r"\b__import__\s*\(", "dynamic import"),
    (r"\b(?:shutil\.rmtree|os\.remove|os\.unlink)\s*\(", "file deletion"),
    (r"\bsocket\.(?:socket|create_connection)\s*\(", "raw network socket"),
    (r"\bpickle\.(?:load|loads)\s*\(", "unsafe deserialization"),
    (r"\bmarshal\.(?:load|loads)\s*\(", "unsafe deserialization"),
    (r"\b(?:keylog|keylogger|stealer|ransom|cryptominer|miner)\b", "malware-related keyword"),
]

def inspect_python_file(script_path: Path) -> dict:
    """Return a review report without importing or executing the uploaded file."""
    report = {
        "ok": True, "risk_level": "low", "findings": [], "imports": [],
        "sha256": "", "syntax_ok": True,
    }
    try:
        source = script_path.read_text(encoding="utf-8", errors="replace")
        report["sha256"] = hashlib.sha256(source.encode("utf-8", "replace")).hexdigest()
    except Exception as exc:
        report.update(ok=False, risk_level="high", syntax_ok=False)
        report["findings"].append(f"Could not read file: {exc}")
        return report

    try:
        tree = ast.parse(source, filename=str(script_path))
    except SyntaxError as exc:
        report.update(ok=False, risk_level="high", syntax_ok=False)
        report["findings"].append(f"Syntax error at line {exc.lineno}: {exc.msg}")
        return report

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            report["imports"].extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            report["imports"].append(node.module.split(".")[0])

    for pattern, label in _DANGEROUS_PATTERNS:
        match = re.search(pattern, source, re.IGNORECASE)
        if match:
            line = source[:match.start()].count("\n") + 1
            report["findings"].append(f"{label} (line {line})")

    # Any dynamic execution, process launch, deletion or network finding is
    # high-risk; other findings still require an explicit admin override.
    high_risk_words = ("execution", "deletion", "network", "deserialization", "malware")
    if any(any(word in finding.lower() for word in high_risk_words) for finding in report["findings"]):
        report["risk_level"] = "high"
    elif report["findings"]:
        report["risk_level"] = "medium"
    report["ok"] = report["syntax_ok"] and not report["findings"]
    return report

def format_review(report: dict) -> str:
    findings = report.get("findings") or ["No suspicious patterns found by static review."]
    icon = "✅" if report.get("ok") else ("🚨" if report.get("risk_level") == "high" else "⚠️")
    return (
        f"{icon} *Pattern review:* `{report.get('risk_level', 'unknown').upper()}`\n"
        + "\n".join(f"• {item}" for item in findings)
        + f"\n• SHA-256: `{report.get('sha256', '')[:16]}…`"
    )

def format_review_html(report: dict) -> str:
    findings = report.get("findings") or ["No suspicious static patterns found."]
    icon = "✅" if report.get("ok") else (
        "🚨" if report.get("risk_level") == "high" else "⚠️"
    )
    risk = html.escape(str(report.get("risk_level", "unknown")).upper())
    sha = html.escape(str(report.get("sha256", ""))[:16])
    finding_text = "\n".join(
        f"• {html.escape(str(item))}" for item in findings
    )
    return (
        f"{icon} <b>Pattern review:</b> <code>{risk}</code>\n"
        f"{finding_text}\n"
        f"• SHA-256: <code>{sha}…</code>"
    )

def refresh_file_review(info: dict, script: Path) -> dict:
    """Re-scan the current file so old/stale metadata cannot block clean files."""
    report = inspect_python_file(script)
    info["review"] = report
    # An override is meaningful only for the exact risky content that was
    # reviewed. A newly clean/replaced file never needs an override.
    if report.get("ok"):
        info["risk_override"] = False
    return report

def force_join_status(data: dict, user_id: int) -> tuple[bool, list]:
    """Returns (is_allowed, missing chat entries)."""
    entries = force_join_entries(data)
    # No configured chats means access is open.
    return not entries, list(entries.items())

async def user_is_member(bot, user_id: int, chat_id: str) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        return member.status in {"creator", "administrator", "member", "restricted"}
    except TelegramError:
        return False

async def check_force_join(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if not user or is_admin(user.id):
        return True
    data = load_data()
    entries = force_join_entries(data)
    missing = []
    for chat_id, item in entries.items():
        if not await user_is_member(ctx.bot, user.id, chat_id):
            missing.append(item)
    if not missing:
        return True
    buttons = []
    for item in missing:
        link = item.get("link")
        if link:
            buttons.append([InlineKeyboardButton(
                f"Join {item.get('title', 'required chat')}", url=link
            )])
    buttons.append([InlineKeyboardButton("✅ I joined — check again", callback_data="check_join")])
    text = (
        "🔒 *Access locked*\n\n"
        "Please join every required channel/group, then tap “I joined — check again”."
    )
    if update.callback_query:
        await update.callback_query.answer("Join all required chats first.", show_alert=True)
        try:
            await update.callback_query.edit_message_text(
                text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons)
            )
        except TelegramError:
            pass
    elif update.message:
        await update.message.reply_text(
            text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons)
        )
    return False


async def bot_error_handler(update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Log handler failures and show a useful reply instead of silent failure."""
    error = ctx.error
    logger.error(
        "Unhandled update error: %s\n%s",
        error,
        "".join(traceback.format_exception(type(error), error, error.__traceback__)),
    )
    message = getattr(update, "effective_message", None)
    if message is not None:
        try:
            await message.reply_text(
                "⚠️ Bot error while processing this request.\n"
                "The error was logged. Try /start again in a few seconds."
            )
        except TelegramError:
            pass

def user_home_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("▣ My files", callback_data="files_menu"),
            InlineKeyboardButton("? Quick guide", callback_data="user_help"),
        ],
    ])

def commands_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⌂ Start", callback_data="sc_start"),
            InlineKeyboardButton("? Help", callback_data="sc_help"),
        ],
        [InlineKeyboardButton("▣ My status → /mystatus", callback_data="sc_mystatus")],
        [
            InlineKeyboardButton("▶ Run file → /run", callback_data="sc_run"),
            InlineKeyboardButton("■ Stop file → /stop", callback_data="sc_stop"),
        ],
        [
            InlineKeyboardButton("≡ View logs → /logs", callback_data="sc_logs"),
            InlineKeyboardButton("⌫ Delete → /delete", callback_data="sc_delete"),
        ],
    ])

def command_file_picker_markup(files: list, action: str) -> InlineKeyboardMarkup:
    """Show a file picker so command actions never require typing an ID."""
    rows = []
    for fid, info in files:
        status = info.get("status", "pending")
        icon = {"approved": "●", "rejected": "×", "pending": "○"}.get(status, "·")
        rows.append([InlineKeyboardButton(
            f"{icon} {info.get('original_name', fid)} · {fid}",
            callback_data=f"cmdfile_{action}_{fid}",
        )])
    rows.append([InlineKeyboardButton("↩ Back to commands", callback_data="sc_back")])
    return InlineKeyboardMarkup(rows)

def command_file_picker_text(action: str) -> str:
    labels = {
        "run": ("▶ Run file", "Select an approved file to start."),
        "stop": ("■ Stop file", "Select a running file to stop."),
        "logs": ("≡ View logs", "Select a file to view its latest output."),
        "delete": ("⌫ Delete file", "Select a file to permanently remove."),
    }
    title, description = labels[action]
    return f"<b>{title}</b>\n\n<blockquote>{description}</blockquote>"

def main_menu_markup(user_id: Optional[int] = None) -> ReplyKeyboardMarkup:
    rows = [
        ["▸ Updates channel", "＋ Upload file"],
        ["▣ My files", "◌ Bot status"],
        ["◌ Analytics", "· Contact owner"],
    ]
    if is_admin(user_id):
        rows.append(["◆ Admin console"])
    return ReplyKeyboardMarkup(
        rows,
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="ƬʜᴇΉΛᑕKΣЯ♛",
    )

def user_home_text() -> str:
    return (
        f"<b>◆ {BRAND_NAME}</b>\n"
        "<i>Private Python hosting, built for control.</i>\n\n"
        "<blockquote>Upload a Python file and it stays in review until approved.\n"
        "Every upload receives syntax and suspicious-pattern checks before execution.</blockquote>\n\n"
        "<b>Workspace</b>\n"
        "▸ Upload and review scripts\n"
        "▸ Run approved files with watchdog protection\n"
        "▸ Inspect output and manage every file\n\n"
        "<b>Command palette</b>\n"
        "<blockquote>"
        "• <code>/mystatus</code> — all your hosted files\n"
        "• <code>/run &lt;id&gt;</code> — start an approved file\n"
        "• <code>/stop &lt;id&gt;</code> — stop a running file\n"
        "• <code>/logs &lt;id&gt;</code> — recent output\n"
        "• <code>/delete &lt;id&gt;</code> — remove a file\n"
        "• <code>/install &lt;id&gt; &lt;package&gt;</code> — install a missing package"
        "</blockquote>\n\n"
    )

def file_list_markup(files: list) -> InlineKeyboardMarkup:
    rows = []
    for fid, info in files:
        status = info.get("status", "pending")
        icon = {"approved": "🟢", "rejected": "🔴", "pending": "🟡"}.get(status, "⚪")
        rows.append([InlineKeyboardButton(
            f"{icon} {info.get('original_name', fid)} · {fid}",
            callback_data=f"file_{fid}",
        )])
    rows.append([InlineKeyboardButton("↩️ Back to menu", callback_data="user_home")])
    return InlineKeyboardMarkup(rows)

def file_control_markup(fid: str, info: dict) -> InlineKeyboardMarkup:
    status = info.get("status", "pending")
    rows = []
    if status == "approved":
        if is_running(fid):
            primary_button = InlineKeyboardButton(
                "■ Stop file", callback_data=f"file_stop_{fid}"
            )
        elif fid in paused_processes or (
            info.get("has_started") and info.get("desired_state") == "stopped"
        ):
            primary_button = InlineKeyboardButton(
                "▶ Continue file", callback_data=f"file_start_{fid}"
            )
        else:
            primary_button = InlineKeyboardButton(
                "▶ Start file", callback_data=f"file_start_{fid}"
            )
        rows.append([
            primary_button,
            InlineKeyboardButton("⌫ Delete", callback_data=f"file_delete_{fid}"),
        ])
        rows.append([InlineKeyboardButton("≡ View logs", callback_data=f"file_logs_{fid}")])
    else:
        rows.append([InlineKeyboardButton("⌫ Delete", callback_data=f"file_delete_{fid}")])
    rows.append([InlineKeyboardButton("◀️ Back to files", callback_data="files_menu")])
    return InlineKeyboardMarkup(rows)

def file_control_text(fid: str, info: dict) -> str:
    status = info.get("status", "pending")
    status_label = {
        "approved": "🟡 Approved",
        "pending": "🟡 Waiting for admin approval",
        "rejected": "🔴 Rejected",
    }.get(status, "⚪ Unknown")
    if is_running(fid):
        running = "🟢 Running"
    elif fid in paused_processes:
        running = "⏸️ Paused — Continue resumes the same point"
    else:
        running = "🔴 Stopped"
    review = info.get("review", {})
    return (
        f"⚙️ *Controls for:* `{info.get('original_name', fid)}`\n"
        f"🆔 File ID: `{fid}`\n"
        f"📌 Status: {status_label}\n"
        f"🚦 Process: {running}\n"
        f"🛡 Review: `{review.get('risk_level', 'unknown').upper()}`\n\n"
        "Use the buttons below to manage this file."
    )

def remove_file(fid: str, data: dict) -> Optional[dict]:
    info = data.get("files", {}).pop(fid, None)
    if not info:
        return None
    proc = running_processes.pop(fid, None)
    if proc and proc.poll() is None:
        proc.kill()
    paused_processes.discard(fid)
    save_data(data)
    for path in (FILES_DIR / info["filename"], FILES_DIR / f"{fid}.log"):
        try:
            if path.exists():
                path.unlink()
        except OSError as exc:
            logger.warning("Could not remove %s: %s", path, exc)
    return info

async def show_file_logs_callback(query, fid: str, info: dict):
    log_path = FILES_DIR / f"{fid}.log"
    if not log_path.exists():
        await query.edit_message_text(
            f"📭 No logs yet for `{info.get('original_name', fid)}`.",
            parse_mode="Markdown", reply_markup=file_control_markup(fid, info),
        )
        return
    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    tail = "\n".join(lines[-25:]).strip() or "(empty)"
    if len(tail) > 3000:
        tail = "…" + tail[-3000:]
    await query.edit_message_text(
        f"📜 *Logs:* `{info.get('original_name', fid)}`\n"
        f"```\n{tail}\n```",
        parse_mode="Markdown", reply_markup=file_control_markup(fid, info),
    )

def statistics_text(data: dict) -> str:
    files = list(data.get("files", {}).values())
    running = sum(1 for fid in data.get("files", {}) if is_running(fid))
    return (
        "📊 *Bot Statistics*\n\n"
        f"📁 Total files: `{len(files)}`\n"
        f"🟡 Pending: `{sum(i.get('status') == 'pending' for i in files)}`\n"
        f"🟢 Approved: `{sum(i.get('status') == 'approved' for i in files)}`\n"
        f"🔴 Rejected: `{sum(i.get('status') == 'rejected' for i in files)}`\n"
        f"⚡ Running now: `{running}`\n"
        f"📢 Force-join chats: `{len(data.get('force_join', {}))}`"
    )

async def show_user_files(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show the current user's file list with one-tap controls."""
    if not await check_force_join(update, ctx):
        return
    user = update.effective_user
    data = load_data()
    files = user_files(data, user.id)
    text = (
        "📁 *Your files*\n\nSelect a file to open its controls."
        if files else
        "📁 *Your files*\n\nNo files yet. Tap 📤 Upload File and send a `.py` file."
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text, parse_mode="Markdown",
            reply_markup=file_list_markup(files) if files else user_home_markup(),
        )
    else:
        await update.message.reply_text(
            text, parse_mode="Markdown",
            reply_markup=file_list_markup(files) if files else user_home_markup(),
        )

async def handle_menu_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Persistent menu actions matching the screenshot-style home screen."""
    if not update.message or not update.message.text:
        return
    text = update.message.text
    # ── Command shortcut buttons (sent as plain text by ReplyKeyboard) ──
    if text == "☰ Commands":
        await update.message.reply_text(
            "<b>☰ Command center</b>\n\n"
            "<blockquote>Tap any command below. No copy-paste or file ID typing needed.</blockquote>",
            parse_mode="HTML",
            reply_markup=commands_markup(),
        )
    elif text == "＋ Upload file":
        if await check_force_join(update, ctx):
            await update.message.reply_text(
                "<b>＋ Upload file</b>\n\n"
                "<blockquote>Send your <code>.py</code> file as a Telegram document.\n"
                "It will be scanned and sent to admin for approval.</blockquote>",
                parse_mode="HTML",
            )
    elif text == "▣ My files":
        await show_user_files(update, ctx)
    elif text == "◌ Analytics":
        if await check_force_join(update, ctx):
            await update.message.reply_text(
                statistics_text(load_data()), parse_mode="Markdown",
                reply_markup=main_menu_markup(update.effective_user.id),
            )
    elif text == "◌ Bot status":
        if await check_force_join(update, ctx):
            await update.message.reply_text(
                "<b>◌ Bot status</b>\n\n"
                "<blockquote>✅ Fast approval notifications\n"
                "✅ Automatic 30-second watchdog\n"
                "✅ Network retry protection</blockquote>",
                parse_mode="HTML",
                reply_markup=main_menu_markup(update.effective_user.id),
            )
    elif text == "▸ Updates channel":
        data = load_data()
        link = data.get("settings", {}).get("updates_link")
        await update.message.reply_text(
            f"📢 Updates: {link}" if link else "📢 Updates channel is not configured yet.",
            reply_markup=main_menu_markup(update.effective_user.id),
        )
    elif text == "· Contact owner":
        contact = load_data().get("settings", {}).get("contact")
        await update.message.reply_text(
            f"📞 Contact owner: {contact}" if contact else
            "📞 Owner contact is not configured yet.",
            reply_markup=main_menu_markup(update.effective_user.id),
        )
    elif text == "◆ Admin console":
        await cmd_admin(update, ctx)


def mini_app_button(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("◆ Open premium mini app", web_app=WebAppInfo(url=url))
    ]])


async def cmd_miniapp(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Open the colored Web App; configure MINI_APP_URL before using it."""
    if not await check_force_join(update, ctx):
        return
    if not MINI_APP_URL:
        await update.message.reply_text(
            "⚙️ Mini App URL is not configured yet.\n\n"
            "Set `MINI_APP_URL` to the public HTTPS URL ending in `/miniapp`, "
            "then restart the bot.",
            parse_mode="Markdown",
        )
        return
    await update.message.reply_text(
        f"<b>◆ {BRAND_NAME}</b>\n\n"
        "Open the premium control panel below.",
        parse_mode="HTML",
        reply_markup=mini_app_button(MINI_APP_URL),
    )


async def handle_web_app_data(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Route colored Mini App buttons into the original bot experiences."""
    if not update.message or not update.message.web_app_data:
        return
    if not await check_force_join(update, ctx):
        return
    try:
        payload = json.loads(update.message.web_app_data.data or "{}")
        action = str(payload.get("action", ""))
    except (TypeError, ValueError):
        await update.message.reply_text("❌ Invalid Mini App action.")
        return

    if action == "updates":
        data = load_data()
        link = data.get("settings", {}).get("updates_link")
        await update.message.reply_text(
            f"📢 Updates: {link}" if link else "📢 Updates channel is not configured yet.",
            reply_markup=main_menu_markup(update.effective_user.id),
        )
    elif action == "upload":
        await update.message.reply_text(
            "<b>＋ Upload file</b>\n\n"
            "<blockquote>Send your <code>.py</code> file as a Telegram document.\n"
            "It will be scanned and sent to admin for approval.</blockquote>",
            parse_mode="HTML",
        )
    elif action == "files":
        await show_user_files(update, ctx)
    elif action == "status":
        await update.message.reply_text(
            "<b>◌ Bot status</b>\n\n"
            "<blockquote>✅ Fast approval notifications\n"
            "✅ Automatic 30-second watchdog\n"
            "✅ Network retry protection</blockquote>",
            parse_mode="HTML",
            reply_markup=main_menu_markup(update.effective_user.id),
        )
    elif action == "analytics":
        await update.message.reply_text(
            statistics_text(load_data()),
            parse_mode="Markdown",
            reply_markup=main_menu_markup(update.effective_user.id),
        )
    elif action == "contact":
        contact = load_data().get("settings", {}).get("contact")
        await update.message.reply_text(
            f"📞 Contact owner: {contact}" if contact else
            "📞 Owner contact is not configured yet.",
            reply_markup=main_menu_markup(update.effective_user.id),
        )
    else:
        await update.message.reply_text("❌ Unknown Mini App action.")


async def cmd_setupdates(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not ctx.args:
        await update.message.reply_text(
            "Usage: `/setupdates https://t.me/your_channel`", parse_mode="Markdown"
        )
        return
    data = load_data()
    data["settings"]["updates_link"] = ctx.args[0]
    save_data(data)
    await update.message.reply_text(
        "✅ Updates channel saved.", reply_markup=admin_panel_markup(data)
    )

async def cmd_setcontact(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not ctx.args:
        await update.message.reply_text(
            "Usage: `/setcontact @owner_username`", parse_mode="Markdown"
        )
        return
    data = load_data()
    data["settings"]["contact"] = " ".join(ctx.args)
    save_data(data)
    await update.message.reply_text(
        "✅ Owner contact saved.", reply_markup=admin_panel_markup(data)
    )

async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("This control center is for the admin only.")
        return
    await update.message.reply_text(
        admin_panel_text(load_data()), parse_mode="Markdown",
        reply_markup=admin_panel_markup(load_data()),
    )

async def cmd_forcejoin_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not ctx.args:
        await update.message.reply_text(force_join_help_text(), parse_mode="Markdown")
        return
    raw = " ".join(ctx.args)
    parts = [part.strip() for part in raw.split("|")]
    chat_id = parts[0]
    link = parts[1] if len(parts) > 1 and parts[1] else (
        f"https://t.me/{chat_id.lstrip('@')}" if chat_id.startswith("@") else ""
    )
    title = parts[2] if len(parts) > 2 else chat_id
    data = load_data()
    data["force_join"][chat_id] = {"link": link, "title": title, "added_at": datetime.now().isoformat()}
    save_data(data)
    await update.message.reply_text(
        f"✅ Added *{title}* to force-join requirements.\n"
        "The bot must be an admin there to verify memberships.",
        parse_mode="Markdown", reply_markup=admin_panel_markup(data),
    )

async def cmd_forcejoin_remove(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not ctx.args:
        await update.message.reply_text("Usage: `/forcejoin_remove <chat_id or @username>`", parse_mode="Markdown")
        return
    data = load_data()
    removed = data["force_join"].pop(ctx.args[0], None)
    save_data(data)
    await update.message.reply_text(
        ("✅ Removed from force-join." if removed else "That chat is not configured."),
        reply_markup=admin_panel_markup(data),
    )

def is_running(fid: str) -> bool:
    p = running_processes.get(fid)
    return (
        p is not None
        and fid not in paused_processes
        and p.poll() is None
    )

def start_process(fid: str, info: dict) -> subprocess.Popen:
    file_path = FILES_DIR / info["filename"]
    if not file_path.exists():
        raise FileNotFoundError(f"Script missing: {file_path}")
    report = refresh_file_review(info, file_path)
    if not report.get("ok") and not info.get("risk_override"):
        raise PermissionError(
            "Safety review requires an explicit admin override before execution."
        )
    # All starts—commands, inline buttons and watchdog recovery—pass here.
    prepare_file_packages(fid, info)
    python    = str(VENV_PY) if VENV_PY.exists() else sys.executable
    log_f = open(FILES_DIR / f"{fid}.log", "a", buffering=1,
                 encoding="utf-8", errors="replace")
    proc = subprocess.Popen(
        [python, "-u", str(file_path)],
        stdout=log_f, stderr=log_f,
        cwd=str(FILES_DIR),
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    running_processes[fid] = proc
    paused_processes.discard(fid)
    info["pid"] = proc.pid
    info["has_started"] = True
    info["desired_state"] = "running"
    info["manual_stop"] = False
    logger.info("Started PID %d  fid=%s  file=%s", proc.pid, fid, info["filename"])
    return proc

def resume_or_start_process(fid: str, info: dict) -> subprocess.Popen:
    """Resume a paused process, or launch it once if no process survives."""
    existing = running_processes.get(fid)
    if existing is not None and existing.poll() is None:
        if fid in paused_processes:
            resume_pid(existing.pid)
            paused_processes.discard(fid)
        return existing
    running_processes.pop(fid, None)
    paused_processes.discard(fid)
    return start_process(fid, info)

def pause_process(fid: str) -> bool:
    """Suspend without killing, preserving the interpreter's exact point."""
    proc = running_processes.get(fid)
    if proc is None or proc.poll() is not None:
        return False
    if fid not in paused_processes:
        suspend_pid(proc.pid)
        paused_processes.add(fid)
    return True

def set_file_running_state(data: dict, fid: str, proc: Any) -> None:
    info = data["files"][fid]
    info["pid"] = getattr(proc, "pid", info.get("pid"))
    info["has_started"] = True
    info["desired_state"] = "running"
    info["manual_stop"] = False

def set_file_paused_state(data: dict, fid: str, proc: Any) -> None:
    info = data["files"][fid]
    info["pid"] = getattr(proc, "pid", info.get("pid"))
    info["has_started"] = True
    info["desired_state"] = "stopped"
    info["manual_stop"] = True

def restore_persisted_processes() -> list[tuple[int, str, dict, str]]:
    """Reconnect to surviving children and return user-facing restart states."""
    data = load_data()
    notifications = []
    for fid, info in data.get("files", {}).items():
        if info.get("status") != "approved":
            notifications.append((
                int(info["user_id"]), fid, info, info.get("status", "pending")
            ))
            continue
        pid = info.get("pid")
        if pid and process_matches_file(pid, info):
            running_processes[fid] = RecoveredProcess(int(pid))
            if info.get("desired_state") == "stopped":
                paused_processes.add(fid)
                state = "paused"
            else:
                state = "running"
            notifications.append((int(info["user_id"]), fid, info, state))
        else:
            # A child cannot be resumed after the OS has killed it. Keep the
            # file record and controls, but make the next action a fresh start.
            if pid:
                info["pid"] = None
            info["has_started"] = False
            info["desired_state"] = "stopped"
            info["manual_stop"] = True
            notifications.append((int(info["user_id"]), fid, info, "recoverable"))
    save_data(data)
    logger.info("Recovered %d persisted file records.", len(notifications))
    return notifications

def persist_process_state(fid: str, desired_state: str) -> None:
    """Persist the user's run/pause choice without losing other file data."""
    data = load_data()
    info = data.get("files", {}).get(fid)
    if not info:
        return
    proc = running_processes.get(fid)
    if proc is not None and proc.poll() is None:
        info["pid"] = getattr(proc, "pid", info.get("pid"))
    info["desired_state"] = desired_state
    info["manual_stop"] = desired_state != "running"
    save_data(data)

async def safe_send(bot, **kwargs):
    """Send a Telegram message with auto-retry on network errors."""
    for attempt in range(5):
        try:
            return await bot.send_message(**kwargs)
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
        except (NetworkError, TimedOut):
            if attempt == 4: raise
            await asyncio.sleep(2 ** attempt)

async def notify_approval(bot, user_id: int, fid: str, info: dict) -> bool:
    """Tell the uploader about approval and give them immediate controls.

    Telegram parse errors used to make this notification disappear because
    filenames/usernames were inserted into Markdown without escaping. HTML
    escaping plus a plain-text fallback keeps the approval path reliable.
    """
    filename = html.escape(str(info.get("original_name", fid)))
    progress_text = (
        f"<b>✨ Approval confirmed</b>\n\n"
        f"▸ <code>{filename}</code>\n"
        "▸ Admin review complete\n"
        "⏳ Preparing your controls…"
    )
    final_text = (
        f"<b>✅ Your file has been approved</b>\n\n"
        f"▸ <b>File:</b> <code>{filename}</code>\n"
        f"▸ <b>ID:</b> <code>{html.escape(fid)}</code>\n"
        "▸ <b>Status:</b> Ready to run\n\n"
        "Tap <b>▶ Start file</b> to launch it instantly."
    )
    markup = file_control_markup(fid, info)
    try:
        progress = await safe_send(
            bot, chat_id=user_id, text=progress_text,
            parse_mode="HTML", reply_markup=markup,
        )
        try:
            await asyncio.sleep(0.15)
            await progress.edit_text(
                final_text, parse_mode="HTML", reply_markup=markup,
            )
        except TelegramError:
            # The progress message is still a valid approval notification.
            logger.warning("Approval message animation update failed | fid=%s", fid)
        return True
    except TelegramError as exc:
        logger.error("Approval HTML notification failed | fid=%s | error=%s", fid, exc)
        fallback = (
            "✅ Your file has been approved.\n"
            f"File: {info.get('original_name', fid)}\n"
            f"ID: {fid}\n"
            "Use the buttons below to start or manage it."
        )
        try:
            await safe_send(bot, chat_id=user_id, text=fallback, reply_markup=markup)
            return True
        except Exception as fallback_error:
            logger.error(
                "Approval notification fallback failed | fid=%s | error=%s",
                fid, fallback_error,
            )
            return False
    except Exception as exc:
        logger.error("Approval notification failed | fid=%s | error=%s", fid, exc)
        return False

async def notify_recovered_files(
    bot, notifications: list[tuple[int, str, dict, str]]
) -> None:
    """Send fresh controls to every uploader after the bot reconnects."""
    for user_id, fid, info, state in notifications:
        filename = html.escape(str(info.get("original_name", fid)))
        if state == "running":
            status = (
                "🟢 Your file is still running. The bot reconnected to it "
                "and restored the controls."
            )
        elif state == "paused":
            status = (
                "⏸️ Your file is paused. Tap <b>▶ Continue file</b> to resume "
                "from the same execution point."
            )
        elif state == "pending":
            status = "⏳ Your file is still waiting for admin approval."
        elif state == "rejected":
            status = "❌ This file was rejected. You can delete it and upload a revised file."
        else:
            status = (
                "⚠️ The previous process did not survive the bot restart, "
                "but your file and data are safe. Tap <b>▶ Start file</b> to launch it again."
            )
        text = (
            "<b>♻️ Bot connection restored</b>\n\n"
            f"▸ <b>File:</b> <code>{filename}</code>\n"
            f"▸ <b>ID:</b> <code>{html.escape(fid)}</code>\n\n"
            f"{status}"
        )
        try:
            await safe_send(
                bot,
                chat_id=user_id,
                text=text,
                parse_mode="HTML",
                reply_markup=file_control_markup(fid, info),
            )
        except Exception as exc:
            # "Chat not found" is normal — user never messaged the bot or blocked it.
            # Log at debug level so the console stays clean.
            err_str = str(exc).lower()
            if any(k in err_str for k in ("chat not found", "bot was blocked",
                                           "user is deactivated", "forbidden")):
                logger.debug(
                    "Recovery notification skipped (user unreachable) | fid=%s", fid
                )
            else:
                logger.warning(
                    "Recovery notification failed | fid=%s | error=%s", fid, exc
                )

# ══════════════════════════ COMMANDS ══════════════════════════
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return
    if not await check_force_join(update, ctx):
        return
    try:
        await update.message.reply_text(
            user_home_text(), parse_mode="HTML",
            reply_markup=main_menu_markup(update.effective_user.id),
        )
    except TelegramError:
        # A malformed HTML entity or keyboard option must not make /start
        # appear dead. Plain text is a reliable second path.
        await update.message.reply_text(
            "✅ Bot is online.\n\n"
            "Send a .py file to upload it for review.",
            reply_markup=main_menu_markup(update.effective_user.id),
        )

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, ctx):
        return
    await cmd_start(update, ctx)

async def cmd_mystatus(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, ctx):
        return
    data  = load_data()
    uid   = update.effective_user.id
    files = user_files(data, uid)
    if not files:
        await update.message.reply_text(
            "You have no hosted files yet.\nSend a `.py` file to get started! 🚀",
            parse_mode="Markdown")
        return
    lines = ["📁 *Your Hosted Files:*\n"]
    for fid, info in files:
        s = info.get("status","pending")
        si = {"approved":"✅","rejected":"❌","pending":"⏳"}.get(s,"❓")
        ri = "🟢 Running" if is_running(fid) else "🔴 Stopped"
        lines.append(
            f"{si} `{fid}` — *{info['original_name']}*\n"
            f"   {ri}  |  {info.get('uploaded_at','')[:16]}"
        )
    await update.message.reply_text(
        "\n\n".join(lines), parse_mode="Markdown",
        reply_markup=main_menu_markup(update.effective_user.id),
    )

async def cmd_run(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, ctx):
        return
    if not ctx.args:
        files = user_files(load_data(), update.effective_user.id)
        await update.message.reply_text(
            command_file_picker_text("run"),
            parse_mode="HTML",
            reply_markup=command_file_picker_markup(files, "run")
            if files else user_home_markup(),
        )
        return
    fid  = ctx.args[0]; data = load_data()
    if fid not in data["files"]:
        await update.message.reply_text("❌ File not found."); return
    info = data["files"][fid]
    if info["user_id"] != update.effective_user.id:
        await update.message.reply_text("❌ Not your file."); return
    if info.get("status") != "approved":
        await update.message.reply_text("⏳ Not approved yet."); return
    if is_running(fid):
        await update.message.reply_text(
            f"⚠️ Already running. Use /stop `{fid}` first.", parse_mode="Markdown"); return

    msg = await update.message.reply_text("🛡️ Preparing file…")
    try:
        was_started = bool(info.get("has_started"))
        proc = resume_or_start_process(fid, info)
        set_file_running_state(data, fid, proc)
        save_data(data)
        pkg_txt = info.get("package_setup", {}).get(
            "summary", "📦 Package setup complete."
        )
        await msg.edit_text(
            f"🟢 Script `{fid}` {'resumed' if was_started else 'started'}! "
            f"(PID {proc.pid})\n{pkg_txt}\n"
            f"Use `/logs {fid}` to watch output.", parse_mode="Markdown")
    except Exception as e:
        await msg.edit_text(f"❌ Start failed: `{e}`", parse_mode="Markdown")

async def cmd_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, ctx):
        return
    if not ctx.args:
        files = user_files(load_data(), update.effective_user.id)
        await update.message.reply_text(
            command_file_picker_text("stop"),
            parse_mode="HTML",
            reply_markup=command_file_picker_markup(files, "stop")
            if files else user_home_markup(),
        )
        return
    fid  = ctx.args[0]; data = load_data()
    if fid not in data["files"]:
        await update.message.reply_text("❌ File not found."); return
    if data["files"][fid]["user_id"] != update.effective_user.id:
        await update.message.reply_text("❌ Not your file."); return
    proc = running_processes.get(fid)
    if proc and proc.poll() is None and fid not in paused_processes:
        try:
            pause_process(fid)
        except OSError as exc:
            await update.message.reply_text(f"❌ Could not pause file: `{exc}`", parse_mode="Markdown")
            return
        data["files"][fid]["manual_stop"] = True
        data["files"][fid]["desired_state"] = "stopped"
        data["files"][fid]["pid"] = proc.pid
        save_data(data)
        await update.message.reply_text(
            f"⏸️ Script `{fid}` paused. Continue will resume from the same point.",
            parse_mode="Markdown",
        )
    elif proc and proc.poll() is None and fid in paused_processes:
        await update.message.reply_text("Script is already paused. Use /run to continue it.")
    else:
        await update.message.reply_text("Script is not running.")

async def cmd_logs(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, ctx):
        return
    if not ctx.args:
        files = accessible_files(load_data(), update.effective_user.id)
        await update.message.reply_text(
            command_file_picker_text("logs"),
            parse_mode="HTML",
            reply_markup=command_file_picker_markup(files, "logs")
            if files else user_home_markup(),
        )
        return
    fid  = ctx.args[0]; data = load_data()
    if fid not in data["files"]:
        await update.message.reply_text("❌ File not found."); return
    if not can_access_file(data["files"].get(fid), update.effective_user.id):
        await update.message.reply_text("❌ Not your file."); return
    info = data["files"][fid]
    log_path = FILES_DIR / f"{fid}.log"
    if not log_path.exists():
        await update.message.reply_text("📭 No logs yet."); return
    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    tail  = "\n".join(lines[-30:]).strip() or "(empty)"
    if len(tail) > 3800: tail = "…" + tail[-3800:]
    status = "🟢 Running" if is_running(fid) else "🔴 Stopped"
    owner_line = ""
    if is_admin(update.effective_user.id):
        owner = html.escape(str(info.get("username") or info.get("user_id") or "unknown"))
        owner_line = f"\n👤 Uploader: <code>{owner}</code>"
    await update.message.reply_text(
        f"📋 <b>Logs</b> <code>{html.escape(fid)}</code> ({status}):"
        f"{owner_line}\n<pre>{html.escape(tail)}</pre>",
        parse_mode="HTML")

async def cmd_delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, ctx):
        return
    if not ctx.args:
        files = user_files(load_data(), update.effective_user.id)
        await update.message.reply_text(
            command_file_picker_text("delete"),
            parse_mode="HTML",
            reply_markup=command_file_picker_markup(files, "delete")
            if files else user_home_markup(),
        )
        return
    fid  = ctx.args[0]; data = load_data()
    if fid not in data["files"]:
        await update.message.reply_text("❌ File not found."); return
    if data["files"][fid]["user_id"] != update.effective_user.id:
        await update.message.reply_text("❌ Not your file."); return
    proc = running_processes.pop(fid, None)
    if proc and proc.poll() is None: proc.terminate()
    info = data["files"].pop(fid); save_data(data)
    for p in [FILES_DIR / info["filename"], FILES_DIR / f"{fid}.log"]:
        if p.exists(): p.unlink()
    await update.message.reply_text(f"🗑️ File `{fid}` deleted.", parse_mode="Markdown")

async def cmd_install(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Install detected or explicitly named packages for an accessible file."""
    if not await check_force_join(update, ctx):
        return
    if not update.message or not update.effective_user:
        return
    if len(ctx.args) < 1:
        await update.message.reply_text(
            "Usage:\n"
            "`/install <file_id>` — detect and install the file's imports\n"
            "`/install <file_id> yt-dlp requests` — install named packages\n\n"
            "`/install yt-dlp requests` — admin-only global runner install\n\n"
            "The uploader and admin can use the file-specific command. "
            "It never starts the file.",
            parse_mode="Markdown",
        )
        return

    fid = ctx.args[0].strip()
    data = load_data()
    info = data.get("files", {}).get(fid)
    if not info:
        if not is_admin(update.effective_user.id):
            await update.message.reply_text(
                "❌ Include a valid file ID. Only the admin can use the "
                "package-only form: `/install yt-dlp`.",
                parse_mode="Markdown",
            )
            return
        packages = package_specs_from_text(" ".join(ctx.args))
        invalid = [
            token for token in ctx.args
            if token and normalise_package_spec(token) is None
        ]
        if invalid or not packages:
            await update.message.reply_text(
                "❌ Invalid package name(s). Example: `/install yt-dlp requests`.",
                parse_mode="Markdown",
            )
            return
        status = await update.message.reply_text(
            "📦 Installing in the shared isolated runner environment…\n"
            + ", ".join(packages[:20]),
        )
        ok, summary = await asyncio.to_thread(
            install_packages, packages, BASE_DIR / "package-install.log"
        )
        icon = "✅" if ok else "⚠️"
        await status.edit_text(
            f"{icon} Global package setup finished.\n\n{summary}\n\n"
            "No hosted file was started.",
            parse_mode="Markdown",
        )
        return
    if not can_access_file(info, update.effective_user.id):
        await update.message.reply_text("❌ File not found or you do not have access.")
        return
    script = FILES_DIR / info.get("filename", "")
    if not script.exists():
        await update.message.reply_text("❌ The hosted file is missing from storage.")
        return

    requested = package_specs_from_text(" ".join(ctx.args[1:]))
    packages = requested or extract_packages(script)
    if not packages:
        await update.message.reply_text("📦 No valid packages were found for this file.")
        return
    invalid = [
        token for token in ctx.args[1:]
        if token and normalise_package_spec(token) is None
    ]
    if invalid:
        await update.message.reply_text(
            "❌ Invalid package name(s): "
            + ", ".join(invalid[:8])
            + "\nUse names such as `yt-dlp` or `requests==2.32.3`.",
            parse_mode="Markdown",
        )
        return

    status = await update.message.reply_text(
        "📦 Installing in the isolated runner environment…\n"
        + ", ".join(packages[:20]),
    )
    log_path = FILES_DIR / f"{fid}.log"
    ok, summary = await asyncio.to_thread(install_packages, packages, log_path)
    info["package_setup"] = {
        "packages": packages,
        "ok": ok,
        "verified": ok,
        "summary": summary,
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "manual": True,
    }
    save_data(data)
    icon = "✅" if ok else "⚠️"
    await status.edit_text(
        f"{icon} Package setup finished for `{fid}`.\n\n{summary}\n\n"
        "The file was not started. Use Start/`/run` when you are ready.",
        parse_mode="Markdown",
    )
    if ok and info.get("status") == "pending" and is_admin(update.effective_user.id):
        script_review = refresh_file_review(info, script)
        info["package_setup"]["status"] = "verified"
        data["files"][fid] = info
        save_data(data)
        if script_review.get("ok"):
            approval_rows = [[
                InlineKeyboardButton("✅ Approve", callback_data=f"approve_{fid}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject_{fid}"),
            ]]
        else:
            approval_rows = [[
                InlineKeyboardButton(
                    "🚨 Approve anyway",
                    callback_data=f"approve_anyway_{fid}",
                ),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject_{fid}"),
            ], [
                InlineKeyboardButton(
                    "🚨 Review before running",
                    callback_data=f"review_{fid}",
                ),
            ]]
        try:
            await ctx.bot.send_document(
                chat_id=ADMIN_ID,
                document=InputFile(str(script), filename=info["original_name"]),
                caption=(
                    "📦 <b>Dependencies repaired</b>\n\n"
                    f"File: <code>{html.escape(info['original_name'])}</code>\n"
                    f"ID: <code>{html.escape(fid)}</code>\n"
                    "✅ Libraries installed and runtime imports verified.\n\n"
                    "Choose an approval action below."
                ),
                reply_markup=InlineKeyboardMarkup(approval_rows),
                parse_mode="HTML",
            )
            await update.message.reply_text(
                "✅ Dependencies repaired. The file was sent to admin again "
                "for approval.",
            )
        except TelegramError as exc:
            logger.error("Re-approval notification failed | fid=%s | error=%s", fid, exc)
            await update.message.reply_text(
                "✅ Dependencies repaired, but approval notification failed. "
                "Please use /admin to review pending files.",
            )

# ══════════════════════ FILE UPLOAD HANDLER ═══════════════════
def _extract_bot_token_from_script(script_path: Path) -> Optional[str]:
    """Best-effort extraction of a literal Telegram bot token for username lookup.
    Never logs or sends the token; it is used only for Telegram getMe.
    """
    try:
        src = script_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    patterns = [
        r"(?i)(?:BOT_TOKEN|TELEGRAM_BOT_TOKEN|TOKEN)\s*=\s*[\"']([0-9]{6,12}:[A-Za-z0-9_-]{20,})[\"']",
        r"(?i)(?:BOT_TOKEN|TELEGRAM_BOT_TOKEN|TOKEN)\s*:\s*str\s*=\s*[\"']([0-9]{6,12}:[A-Za-z0-9_-]{20,})[\"']",
    ]
    for pat in patterns:
        m = re.search(pat, src)
        if m:
            return m.group(1)
    # Fallback: find a token-shaped literal anywhere in source.
    m = re.search(r"\b([0-9]{6,12}:[A-Za-z0-9_-]{20,})\b", src)
    return m.group(1) if m else None


def lookup_bot_username(script_path: Path, timeout: float = 6.0) -> Optional[str]:
    """Return @username via Telegram getMe without exposing the bot token."""
    token = _extract_bot_token_from_script(script_path)
    if not token:
        return None
    try:
        req = Request(
            f"https://api.telegram.org/bot{token}/getMe",
            headers={"User-Agent": "TelegramFileHost/1.0"},
        )
        with urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
        if payload.get("ok") and payload.get("result", {}).get("username"):
            return "@" + payload["result"]["username"]
    except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
        logger.warning("Could not resolve uploaded bot username: %s", exc)
    except Exception as exc:
        logger.warning("Unexpected username lookup failure: %s", exc)
    return None


def wait_for_process_start(proc: subprocess.Popen, seconds: float = 1.5) -> bool:
    """Give a newly launched child a short grace period; don't block the bot."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return False
        time.sleep(0.15)
    return proc.poll() is None

async def handle_document(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    doc  = update.message.document
    user = update.effective_user

    if not await check_force_join(update, ctx):
        return
    if not (doc.file_name or "").endswith(".py"):
        await update.message.reply_text("❌ Only `.py` files are accepted!", parse_mode="Markdown")
        return
    if (doc.file_size or 0) > MAX_FILE_BYTES:
        await update.message.reply_text(
            f"❌ File is too large. Maximum allowed size is {MAX_FILE_BYTES // (1024 * 1024)} MB."
        )
        return

    data  = load_data()
    fid   = make_fid(user.id, doc.file_name)
    fname = f"{fid}_{doc.file_name}"
    dest  = FILES_DIR / fname   # absolute path

    msg = await update.message.reply_text("⬇️ Downloading your file…")
    try:
        tg_file = await ctx.bot.get_file(doc.file_id)
        await tg_file.download_to_drive(str(dest))
    except Exception as e:
        await msg.edit_text(f"❌ Download failed: {e}"); return

    review = inspect_python_file(dest)
    data["files"][fid] = {
        "user_id":       user.id,
        "username":      user.username or user.first_name,
        "filename":      fname,
        "original_name": doc.file_name,
        "tg_file_id":    doc.file_id,    # store so admin gets the real file
        "status":        "pending",
        "manual_stop":   False,
        "desired_state": "stopped",
        "has_started":   False,
        "pid":           None,
        "review":        review,
        "risk_override": False,
        "uploaded_at":   datetime.now().isoformat(),
        "package_setup": {
            "packages": extract_packages(dest),
            "ok": False,
            "verified": False,
            "status": "queued",
            "summary": "📦 Automatic dependency setup queued.",
        },
    }
    save_data(data)

    dependency_ok = True
    dependency_summary = "📦 No extra packages detected."
    if AUTO_INSTALL_PACKAGES and data["files"][fid]["package_setup"]["packages"]:
        await msg.edit_text(
            f"📂 File loading & installing required libraries…\n🆔 ID: `{fid}`",
            parse_mode="Markdown",
        )
        dependency_ok, dependency_summary = await auto_install_uploaded_file(
            fid, ctx.bot
        )
        if not dependency_ok:
            await msg.edit_text(
                f"⚠️ File saved, but dependency setup failed.\n🆔 `{fid}`\n\n"
                f"{dependency_summary[:3000]}\n\n"
                "The file was not started. Fix packages with `/install "
                f"{fid}` and retry.",
                parse_mode="Markdown",
            )
            try:
                await ctx.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=(
                        f"⚠️ <b>Dependency setup failed</b>\n\n"
                        f"File: <code>{html.escape(doc.file_name)}</code>\n"
                        f"ID: <code>{html.escape(fid)}</code>\n\n"
                        f"<pre>{html.escape(dependency_summary[-3000:])}</pre>\n\n"
                        "Approval is blocked until the libraries are repaired."
                    ),
                    parse_mode="HTML",
                )
            except TelegramError as exc:
                logger.warning(
                    "Dependency failure notification failed | fid=%s | error=%s",
                    fid, exc,
                )
            return
        else:
            await msg.edit_text(
                f"✅ File ready!\n🆔 `{fid}`\n"
                "⏳ Sending file for admin approval…",
                parse_mode="Markdown",
            )
    else:
        await msg.edit_text(
            f"✅ File received!\n🆔 ID: `{fid}`\n⏳ Waiting for admin approval…",
            parse_mode="Markdown")

    # ── Automatic production hosting ──
    # Safe-reviewed uploads are approved and launched immediately after their
    # dependencies pass. Risky files retain the explicit admin safety gate.
    if AUTO_HOST_ON_UPLOAD and dependency_ok and review.get("ok"):
        try:
            data = load_data()
            info = data["files"][fid]
            info["status"] = "approved"
            info["desired_state"] = "running"
            info["manual_stop"] = False
            info["package_setup"]["status"] = "ready"
            info["package_setup"]["ok"] = True
            info["package_setup"]["verified"] = True
            save_data(data)

            proc = start_process(fid, info)
            data = load_data()
            info = data["files"][fid]
            info["status"] = "approved"
            info["desired_state"] = "running"
            info["manual_stop"] = False
            info["pid"] = proc.pid
            save_data(data)

            alive = wait_for_process_start(proc)
            username = lookup_bot_username(dest) if alive else None
            if username:
                info["bot_username"] = username
                info["hosted_at"] = datetime.now().isoformat()
                save_data(data)
                await msg.edit_text(
                    f"✅ <b>Hosted successfully!</b>\n\n"
                    f"📄 <code>{html.escape(doc.file_name)}</code>\n"
                    f"🤖 <b>{html.escape(username)}</b>\n"
                    f"🟢 Running • PID <code>{proc.pid}</code>\n\n"
                    "♻️ Persistent storage enabled; watchdog will restart it if it crashes.",
                    parse_mode="HTML",
                )
            else:
                await msg.edit_text(
                    f"{'✅' if alive else '⚠️'} <b>Hosting {'started' if alive else 'needs attention'}</b>\n\n"
                    f"📄 <code>{html.escape(doc.file_name)}</code>\n"
                    f"🟢 PID <code>{proc.pid}</code>\n\n"
                    "Bot username could not be resolved automatically. Make sure the uploaded bot token is configured in the file.\n"
                    "The process/logs are saved on persistent storage.",
                    parse_mode="HTML",
                )
        except Exception as exc:
            logger.exception("Automatic hosting failed | fid=%s", fid)
            data = load_data()
            info = data["files"].get(fid, {})
            info["status"] = "approved"
            info["desired_state"] = "stopped"
            info["manual_stop"] = True
            info["host_error"] = str(exc)[-2000:]
            if fid in data.get("files", {}):
                data["files"][fid] = info
            save_data(data)
            await msg.edit_text(
                f"⚠️ <b>File saved, but automatic hosting failed.</b>\n\n"
                f"ID: <code>{html.escape(fid)}</code>\n"
                f"Error: <code>{html.escape(str(exc)[-1800:])}</code>\n\n"
                "Your uploaded file/data was preserved. Use the admin controls to retry.",
                parse_mode="HTML",
            )

    # ── Notify admin: send the actual .py file + approve/reject buttons ──
    if review["ok"]:
        kb_rows = [[
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_{fid}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_{fid}"),
        ]]
    else:
        kb_rows = [[
            InlineKeyboardButton("🚨 Approve anyway", callback_data=f"approve_anyway_{fid}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_{fid}"),
        ]]
        kb_rows.insert(0, [InlineKeyboardButton(
            "🚨 Risky — review before running", callback_data=f"review_{fid}"
        )])
    kb = InlineKeyboardMarkup(kb_rows)
    admin_name = html.escape(user.username or user.first_name or "user")
    safe_filename = html.escape(doc.file_name)
    caption = (
        f"📂 <b>New File Upload</b>\n\n"
        f"👤 User: @{admin_name} (<code>{user.id}</code>)\n"
        f"📄 File: <code>{safe_filename}</code>\n"
        f"🆔 ID: <code>{fid}</code>\n"
        f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"{format_review_html(review)}\n\n"
        f"📦 <b>Dependency setup:</b> "
        f"{'✅ verified' if dependency_ok else '⚠️ failed'}\n"
        f"<code>{html.escape(dependency_summary[-1200:])}</code>\n\n"
        f"{'🚨 This file can be harmful if executed. Do not approve without reviewing it.' if not review['ok'] else 'No suspicious static patterns detected.'}\n\n"
        "Choose an action below."
    )
    try:
        # Send the actual .py file to admin with buttons in caption
        await ctx.bot.send_document(
            chat_id=ADMIN_ID,
            document=InputFile(str(dest), filename=doc.file_name),
            caption=caption,
            reply_markup=kb,
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error("Admin notify failed: %s", e)
        # Fallback: send text only
        try:
            await ctx.bot.send_message(
                chat_id=ADMIN_ID, text=caption,
                reply_markup=kb, parse_mode="HTML")
        except Exception as e2:
            logger.error("Admin fallback also failed: %s", e2)
            await update.message.reply_text(
                "⚠️ Could not notify admin — check ADMIN_ID.")

# ══════════════════════ ADMIN CALLBACK ════════════════════════
async def admin_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    callback = query.data or ""

    if callback == "check_join":
        if await check_force_join(update, ctx):
            await query.answer("Access verified.")
            await query.edit_message_text(
                user_home_text(), parse_mode="HTML", reply_markup=user_home_markup(),
            )
        return
    if callback == "user_home":
        if await check_force_join(update, ctx):
            await query.answer()
            await query.edit_message_text(
                user_home_text(), parse_mode="HTML", reply_markup=user_home_markup()
            )
        return
    if callback == "files_menu":
        if await check_force_join(update, ctx):
            await query.answer()
            await show_user_files(update, ctx)
        return
    if callback.startswith("file_"):
        if not await check_force_join(update, ctx):
            return
        parts = callback.split("_", 2)
        if len(parts) < 2:
            return
        if len(parts) == 2:
            file_action, fid = "open", parts[1]
        else:
            file_action, fid = parts[1], parts[2]
        data = load_data()
        info = data.get("files", {}).get(fid)
        if not info or info.get("user_id") != query.from_user.id:
            await query.answer("File not found or not yours.", show_alert=True)
            return
        await query.answer()
        if file_action == "open":
            await query.edit_message_text(
                file_control_text(fid, info), parse_mode="Markdown",
                reply_markup=file_control_markup(fid, info),
            )
        elif file_action == "start":
            if info.get("status") != "approved":
                await query.edit_message_text(
                    "⏳ This file is not approved yet.",
                    reply_markup=file_control_markup(fid, info),
                )
                return
            if is_running(fid):
                await query.edit_message_text(
                    "🟢 This file is already running.",
                    reply_markup=file_control_markup(fid, info),
                )
                return
            try:
                was_started = bool(info.get("has_started"))
                proc = resume_or_start_process(fid, info)
                set_file_running_state(data, fid, proc)
                save_data(data)
                await query.edit_message_text(
                    f"🟢 <b>{'File resumed' if was_started else 'File started'}</b>\n\n"
                    f"▸ <code>{html.escape(info['original_name'])}</code>\n"
                    f"▸ PID: <code>{proc.pid}</code>",
                    parse_mode="HTML",
                    reply_markup=file_control_markup(fid, info),
                )
            except Exception as exc:
                await query.edit_message_text(
                    f"❌ <b>Could not start file</b>\n\n"
                    f"<code>{html.escape(str(exc))}</code>",
                    parse_mode="HTML",
                    reply_markup=file_control_markup(fid, info),
                )
        elif file_action == "stop":
            proc = running_processes.get(fid)
            if proc and proc.poll() is None:
                try:
                    pause_process(fid)
                except OSError as exc:
                    await query.edit_message_text(
                        f"❌ <b>Could not pause file</b>\n\n"
                        f"<code>{html.escape(str(exc))}</code>",
                        parse_mode="HTML",
                        reply_markup=file_control_markup(fid, info),
                    )
                    return
                set_file_paused_state(data, fid, proc)
                save_data(data)
                stop_text = (
                    f"⏸️ <b>File paused</b>\n\n"
                    f"▸ <code>{html.escape(info['original_name'])}</code>\n"
                    "Continue will resume it from the same execution point."
                )
            else:
                stop_text = (
                    f"· <b>File is already paused</b>\n\n"
                    f"▸ <code>{html.escape(info['original_name'])}</code>"
                )
            await query.edit_message_text(
                stop_text, parse_mode="HTML",
                reply_markup=file_control_markup(fid, info),
            )
        elif file_action == "delete":
            removed = remove_file(fid, data)
            if removed:
                files = user_files(data, query.from_user.id)
                await query.edit_message_text(
                    "🗑️ File deleted.\n\nSelect another file:",
                    reply_markup=file_list_markup(files) if files else user_home_markup(),
                )
        elif file_action == "logs":
            await show_file_logs_callback(query, fid, info)
        return
    if callback == "user_status":
        if await check_force_join(update, ctx):
            await query.answer()
            data = load_data()
            files = user_files(data, query.from_user.id)
            if not files:
                await query.edit_message_text(
                    "You have no hosted files yet.\nSend a `.py` file to get started.",
                    reply_markup=user_home_markup(),
                )
            else:
                lines = ["📁 *Your Hosted Files:*\n"]
                for fid, info in files:
                    status = info.get("status", "pending")
                    icon = {"approved": "✅", "rejected": "❌", "pending": "⏳"}.get(status, "❓")
                    running = "🟢 Running" if is_running(fid) else "🔴 Stopped"
                    lines.append(
                        f"{icon} `{fid}` — *{info['original_name']}*\n"
                        f"   {running}  |  {info.get('uploaded_at', '')[:16]}"
                    )
                await query.edit_message_text(
                    "\n\n".join(lines), parse_mode="Markdown",
                    reply_markup=user_home_markup(),
                )
        return
    if callback == "user_help":
        if await check_force_join(update, ctx):
            await query.answer()
            await query.edit_message_text(
                user_home_text(), parse_mode="HTML", reply_markup=user_home_markup()
            )
        return

    # ── COMMAND CENTER ─────────────────────────────────────────
    if callback in {"sc_start", "sc_help"}:
        await query.answer()
        await query.edit_message_text(
            user_home_text(), parse_mode="HTML", reply_markup=user_home_markup()
        )
        return
    if callback == "sc_mystatus":
        if not await check_force_join(update, ctx):
            return
        await query.answer()
        data  = load_data()
        uid   = query.from_user.id
        files = user_files(data, uid)
        if not files:
            await query.edit_message_text(
                "📁 <b>Your Files</b>\n\n"
                "<blockquote>No files yet. Tap ＋ Upload file and send a <code>.py</code> file.</blockquote>",
                parse_mode="HTML", reply_markup=commands_markup(),
            )
        else:
            lines = ["📁 <b>Your Hosted Files:</b>\n"]
            for fid, info in files:
                s  = info.get("status", "pending")
                si = {"approved": "✅", "rejected": "❌", "pending": "⏳"}.get(s, "❓")
                ri = "🟢 Running" if is_running(fid) else "🔴 Stopped"
                lines.append(
                    f"{si} <code>{fid}</code> — <b>{info['original_name']}</b>\n"
                    f"   {ri}  |  {info.get('uploaded_at', '')[:16]}"
                )
            await query.edit_message_text(
                "\n\n".join(lines), parse_mode="HTML", reply_markup=commands_markup(),
            )
        return
    if callback in {"sc_run", "sc_stop", "sc_logs", "sc_delete"}:
        if not await check_force_join(update, ctx):
            return
        await query.answer()
        labels = {
            "sc_run":    "run",
            "sc_stop":   "stop",
            "sc_logs":   "logs",
            "sc_delete": "delete",
        }
        action = labels[callback]
        files = user_files(load_data(), query.from_user.id)
        await query.edit_message_text(
            command_file_picker_text(action),
            parse_mode="HTML",
            reply_markup=command_file_picker_markup(files, action)
            if files else InlineKeyboardMarkup([[
                InlineKeyboardButton("◀ Back to commands", callback_data="sc_back")
            ]]),
        )
        return
    if callback.startswith("cmdfile_"):
        parts = callback.split("_", 2)
        if len(parts) != 3:
            await query.answer("Invalid command action.", show_alert=True)
            return
        _, action, fid = parts
        if action not in {"run", "stop", "logs", "delete"}:
            await query.answer("Unknown command action.", show_alert=True)
            return
        if not await check_force_join(update, ctx):
            return
        data = load_data()
        info = data.get("files", {}).get(fid)
        if not info or info.get("user_id") != query.from_user.id:
            await query.answer("File not found or not yours.", show_alert=True)
            return
        await query.answer()

        if action == "run":
            if info.get("status") != "approved":
                await query.edit_message_text(
                    "⏳ This file is not approved yet.",
                    reply_markup=command_file_picker_markup(
                        user_files(data, query.from_user.id), "run"
                    ),
                )
                return
            if is_running(fid):
                await query.edit_message_text(
                    f"🟢 <b>{info['original_name']}</b> is already running.",
                    parse_mode="HTML",
                    reply_markup=file_control_markup(fid, info),
                )
                return
            try:
                was_started = bool(info.get("has_started"))
                proc = resume_or_start_process(fid, info)
                set_file_running_state(data, fid, proc)
                save_data(data)
                await query.edit_message_text(
                    f"🟢 <b>{'File resumed' if was_started else 'File started'}</b>\n\n"
                    f"▸ <code>{info['original_name']}</code>\n"
                    f"▸ PID: <code>{proc.pid}</code>",
                    parse_mode="HTML",
                    reply_markup=file_control_markup(fid, info),
                )
            except Exception as exc:
                await query.edit_message_text(
                    f"❌ <b>Could not start file</b>\n\n<code>{exc}</code>",
                    parse_mode="HTML",
                    reply_markup=file_control_markup(fid, info),
                )
            return

        if action == "stop":
            proc = running_processes.get(fid)
            if proc and proc.poll() is None and fid not in paused_processes:
                try:
                    pause_process(fid)
                except OSError as exc:
                    await query.edit_message_text(
                        f"❌ <b>Could not pause file</b>\n\n<code>{html.escape(str(exc))}</code>",
                        parse_mode="HTML",
                        reply_markup=file_control_markup(fid, info),
                    )
                    return
                set_file_paused_state(data, fid, proc)
                save_data(data)
                result_text = (
                    f"⏸️ <b>File paused</b>\n\n"
                    f"▸ <code>{html.escape(info['original_name'])}</code>\n"
                    "Continue will resume from the same execution point."
                )
            elif proc and proc.poll() is None and fid in paused_processes:
                result_text = (
                    f"· <b>File is already paused</b>\n\n"
                    f"▸ <code>{html.escape(info['original_name'])}</code>"
                )
            else:
                result_text = f"· <b>File is not running</b>\n\n▸ <code>{info['original_name']}</code>"
            await query.edit_message_text(
                result_text, parse_mode="HTML",
                reply_markup=file_control_markup(fid, info),
            )
            return

        if action == "logs":
            await show_file_logs_callback(query, fid, info)
            return

        removed = remove_file(fid, data)
        await query.edit_message_text(
            "⌫ <b>File deleted</b>\n\n"
            "Select another command from the command center.",
            parse_mode="HTML", reply_markup=commands_markup(),
        ) if removed else await query.edit_message_text(
            "File was already removed.", reply_markup=commands_markup()
        )
        return
    if callback == "sc_back":
        await query.answer()
        await query.edit_message_text(
            "<b>📨 Commands</b>\n\n"
            "<blockquote>Tap any button below to execute that command instantly.</blockquote>",
            parse_mode="HTML",
            reply_markup=commands_markup(),
        )
        return

    if query.from_user.id != ADMIN_ID:
        await query.answer("❌ You are not the admin!", show_alert=True); return
    await query.answer()

    if callback == "admin_panel":
        data = load_data()
        await query.edit_message_text(
            admin_panel_text(data), parse_mode="Markdown",
            reply_markup=admin_panel_markup(data),
        )
        return
    if callback == "admin_pending":
        pending = [
            (fid, info) for fid, info in load_data().get("files", {}).items()
            if info.get("status") == "pending"
        ]
        buttons = [[InlineKeyboardButton(
            f"🟡 {info.get('original_name', fid)} · {fid}",
            callback_data=f"review_{fid}",
        )] for fid, info in pending]
        buttons.append([InlineKeyboardButton("↩️ Back", callback_data="admin_panel")])
        await query.edit_message_text(
            "🟡 *Pending approvals*\n\n"
            + ("\n".join(f"• `{fid}` — {info.get('original_name', '')}" for fid, info in pending)
               if pending else "No pending files."),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return
    if callback == "admin_stats":
        await query.edit_message_text(
            statistics_text(load_data()),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Back", callback_data="admin_panel")
            ]]),
        )
        return
    if callback == "admin_settings":
        await query.edit_message_text(
            "⚙️ *Admin settings*\n\n"
            "Configure the bot using these commands:\n\n"
            "• `/forcejoin_add @channel`\n"
            "• `/forcejoin_add -100123|https://t.me/+invite|Group name`\n"
            "• `/forcejoin_remove @channel`\n"
            "• `/setupdates https://t.me/your_channel`\n"
            "• `/setcontact @owner_username`\n\n"
            "The bot must be an admin in every force-join chat.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Back", callback_data="admin_panel")
            ]]),
        )
        return
    if callback == "fj_menu_add":
        await query.edit_message_text(
            force_join_help_text(), parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Back", callback_data="admin_panel")
            ]]),
        )
        return
    if callback == "fj_menu_remove":
        data = load_data()
        entries = force_join_entries(data)
        buttons = [[InlineKeyboardButton(
            f"🧹 Remove {item.get('title', chat_id)}",
            callback_data=f"fj_remove_{chat_id}",
        )] for chat_id, item in entries.items()]
        buttons.append([InlineKeyboardButton("↩️ Back", callback_data="admin_panel")])
        await query.edit_message_text(
            "Select a force-join chat to remove:",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return
    if callback == "fj_list":
        data = load_data()
        await query.edit_message_text(
            admin_panel_text(data), parse_mode="Markdown",
            reply_markup=admin_panel_markup(data),
        )
        return
    if callback.startswith("fj_remove_"):
        chat_id = callback[len("fj_remove_"):]
        data = load_data()
        removed = data["force_join"].pop(chat_id, None)
        save_data(data)
        await query.edit_message_text(
            ("✅ Force-join chat removed." if removed else "That chat is no longer configured."),
            reply_markup=admin_panel_markup(data),
        )
        return

    if callback.startswith("approve_anyway_"):
        action, fid = "approve_anyway", callback[len("approve_anyway_"):]
    elif callback.startswith("approve_"):
        action, fid = "approve", callback[len("approve_"):]
    elif callback.startswith("reject_"):
        action, fid = "reject", callback[len("reject_"):]
    elif callback.startswith("review_"):
        action, fid = "review", callback[len("review_"):]
    else:
        return

    data = load_data()
    if fid not in data["files"]:
        await query.edit_message_text("❌ File not found (may have been deleted).")
        return

    info    = data["files"][fid]
    user_id = info["user_id"]
    script  = FILES_DIR / info["filename"]
    current_review = refresh_file_review(info, script)
    data["files"][fid]["review"] = current_review

    if action == "review":
        report = info.get("review", {})
        if report.get("ok"):
            buttons = [[
                InlineKeyboardButton("✅ Approve", callback_data=f"approve_{fid}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject_{fid}"),
            ]]
        else:
            buttons = [[
                InlineKeyboardButton("❌ Reject", callback_data=f"reject_{fid}"),
            ]]
            if ALLOW_RISKY_OVERRIDE:
                buttons.insert(0, [InlineKeyboardButton(
                    "🚨 Approve anyway (explicit override)",
                    callback_data=f"approve_anyway_{fid}",
                )])
        review_text = (
            f"🔍 *Security review — `{fid}`*\n\n"
            f"{format_review(report)}\n\n"
            "This is static analysis only; it cannot prove that arbitrary code is safe. "
            "Only approve code you have personally reviewed."
        )
        try:
            await query.edit_message_caption(
                review_text, parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(buttons),
            )
        except TelegramError:
            await query.edit_message_text(
                review_text, parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(buttons),
            )
        return

    # ── APPROVE ──────────────────────────────────────────────
    if action in {"approve", "approve_anyway"}:
        if action == "approve" and not current_review.get("ok"):
            # The callback was already acknowledged near the top of this
            # handler. Do not answer it a second time; simply leave the
            # dangerous-file controls in place for an explicit override.
            return
        if action == "approve_anyway" and not ALLOW_RISKY_OVERRIDE:
            return
        data["files"][fid]["risk_override"] = action == "approve_anyway"
        data["files"][fid]["status"]      = "approved"
        data["files"][fid]["manual_stop"] = False
        save_data(data)

        initial_text = (
            f"✅ Approved `{fid}` — notifying uploader…"
            if action == "approve" else
            f"🚨 Override recorded for `{fid}` — notifying uploader…"
        )
        try:
            await query.edit_message_caption(initial_text, parse_mode="Markdown")
        except TelegramError:
            await query.edit_message_text(initial_text, parse_mode="Markdown")

        # Dependencies were already installed and runtime-verified before this
        # approval callback. Approval only changes state; it never starts the
        # uploaded script.
        user_notified = await notify_approval(ctx.bot, user_id, fid, info)
        edit_txt = (
            f"✅ Approved — uploader notified\n"
            f"File: `{fid}`\n"
            "The file will start when the user taps Start."
        )
        if not user_notified:
            edit_txt += "\n⚠️ Could not deliver the uploader notification; check the user ID/privacy settings."

        try:
            await query.edit_message_caption(edit_txt, parse_mode="Markdown")
        except TelegramError:
            try:
                await query.edit_message_text(edit_txt, parse_mode="Markdown")
            except TelegramError:
                pass

    # ── REJECT ───────────────────────────────────────────────
    elif action == "reject":
        data["files"][fid]["status"] = "rejected"
        save_data(data)
        try:
            await query.edit_message_caption(
                f"❌ Rejected `{fid}` — {info['original_name']}", parse_mode="Markdown")
        except TelegramError:
            try:
                await query.edit_message_text(
                    f"❌ Rejected `{fid}` — {info['original_name']}", parse_mode="Markdown")
            except TelegramError:
                pass
        if script.exists(): script.unlink()
        try:
            await safe_send(ctx.bot, chat_id=user_id,
                text=f"❌ *File rejected by admin.*\n📄 `{info['original_name']}`\n"
                     f"You can upload a revised version anytime.",
                parse_mode="Markdown")
        except Exception as e: logger.error("User reject notify failed: %s", e)

# ══════════════════════════ WATCHDOG ══════════════════════════
async def watchdog_tick(bot):
    """Run one watchdog pass and restart approved scripts that died."""
    data = load_data()
    for fid, proc in list(running_processes.items()):
        if proc.poll() is not None:   # exited
            info = data["files"].get(fid, {})
            if info.get("status") == "approved" and not info.get("manual_stop"):
                logger.info("Watchdog restarting %s", fid)
                try:
                    new_proc = start_process(fid, info)
                    save_data(data)
                    logger.info("Watchdog restarted %s → PID %d", fid, new_proc.pid)
                except Exception as e:
                    logger.error("Watchdog restart failed %s: %s", fid, e)
                    running_processes.pop(fid, None)
                    now = time.time()
                    if now - runtime_alerted.get(fid, 0) > 300:
                        runtime_alerted[fid] = now
                        try:
                            await safe_send(
                                bot,
                                chat_id=ADMIN_ID,
                                text=(
                                    f"🚨 *Runtime safety alert*\n\n"
                                    f"Approved file `{fid}` stopped and could not be restarted.\n"
                                    f"Reason: `{e}`\n\n"
                                    "It has been left stopped for manual review."
                                ),
                                parse_mode="Markdown",
                            )
                        except Exception as notify_error:
                            logger.error("Runtime alert notify failed: %s", notify_error)
            else:
                running_processes.pop(fid, None)

async def watchdog(ctx: ContextTypes.DEFAULT_TYPE):
    """JobQueue callback when the optional job-queue extra is installed."""
    await watchdog_tick(ctx.bot)

async def watchdog_loop(application: Application):
    """Fallback watchdog for installs without python-telegram-bot[job-queue]."""
    try:
        while True:
            await asyncio.sleep(30)
            await watchdog_tick(application.bot)
    except asyncio.CancelledError:
        logger.info("Fallback watchdog stopped.")
        raise

async def application_post_init(application: Application):
    """Keep watchdog protection active even when Application.job_queue is None."""
    try:
        bot_identity = await application.bot.get_me()
        logger.info(
            "Telegram API connected | bot=@%s | id=%s",
            bot_identity.username or "(no username)",
            bot_identity.id,
        )
    except TelegramError as exc:
        logger.error(
            "Telegram API preflight failed. Check BOT_TOKEN, internet access, "
            "and whether another bot instance is polling: %s",
            exc,
        )
        raise

    try:
        await application.bot.set_my_commands([
            BotCommand("start", "Open ƬʜᴇΉΛᑕKΣЯ♛ home"),
            BotCommand("help", "Quick guide"),
            BotCommand("mystatus", "View my hosted files"),
            BotCommand("run", "Choose a file to start"),
            BotCommand("stop", "Choose a file to stop"),
            BotCommand("logs", "Choose a file to view logs"),
            BotCommand("delete", "Choose a file to delete"),
            BotCommand("miniapp", "Open premium control panel"),
        ])
        if MINI_APP_URL:
            await application.bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(
                    text="Premium panel",
                    web_app=WebAppInfo(url=MINI_APP_URL),
                )
            )
            logger.info("Premium Mini App menu button configured.")
        else:
            await application.bot.set_chat_menu_button(
                menu_button=MenuButtonCommands()
            )
            logger.info("Native message-bar command menu configured.")
    except TelegramError as exc:
        logger.warning("Could not configure Telegram command menu: %s", exc)

    # Reconnect to children that survived a bot restart, keep paused files
    # paused, and send every uploader a fresh control message.
    try:
        recovered = restore_persisted_processes()
        if recovered:
            await notify_recovered_files(application.bot, recovered)
    except Exception as exc:
        logger.error("Persisted process recovery failed: %s", exc)

    if application.job_queue is None:
        logger.warning(
            "JobQueue extra is not installed; using the built-in async watchdog. "
            "Optional: pip install 'python-telegram-bot[job-queue]==21.*'."
        )
        application.bot_data["fallback_watchdog"] = asyncio.create_task(
            watchdog_loop(application)
        )

async def application_post_shutdown(application: Application):
    task = application.bot_data.pop("fallback_watchdog", None)
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

# ══════════════════════════ INSTANCE LOCK ═════════════════════
_PID_FILE = BASE_DIR / "bot.pid"

def _acquire_instance_lock() -> None:
    """Ensure only one bot instance runs at a time.

    Writes the current PID to bot.pid.  If a stale PID is found from a
    previous run it is silently overwritten.  If another live instance is
    detected its process is terminated before we continue, so the
    'Conflict: terminated by other getUpdates request' error can never occur.
    """
    current_pid = os.getpid()

    if _PID_FILE.exists():
        try:
            old_pid = int(_PID_FILE.read_text().strip())
        except (ValueError, OSError):
            old_pid = None

        if old_pid and old_pid != current_pid:
            try:
                import signal as _sig
                os.kill(old_pid, _sig.SIGTERM)
                time.sleep(1)          # give it a moment to die
                try:
                    os.kill(old_pid, _sig.SIGKILL)   # force-kill if still alive
                except OSError:
                    pass
                logger.info("Stopped previous bot instance (PID %d).", old_pid)
            except (OSError, ProcessLookupError):
                pass   # process already gone — that's fine

    try:
        _PID_FILE.write_text(str(current_pid))
    except OSError:
        pass   # non-fatal; just proceed without the lock file

def _release_instance_lock() -> None:
    try:
        if _PID_FILE.exists():
            _PID_FILE.unlink()
    except OSError:
        pass

# ══════════════════════════ MAIN ══════════════════════════════
def main():
    if not BOT_TOKEN:
        sys.exit("❌ Set BOT_TOKEN env var (do not put it directly in this file).")
    if ADMIN_ID == 0:
        sys.exit("❌ Set ADMIN_ID env var.")

    # Kill any leftover instance so Telegram never sees two pollers at once
    _acquire_instance_lock()

    start_keep_alive()
    logger.info("Bot starting | Admin: %d | Port: %d", ADMIN_ID, KEEP_PORT)

    app = Application.builder().token(BOT_TOKEN) \
        .connect_timeout(30).read_timeout(30).write_timeout(30) \
        .pool_timeout(30).get_updates_read_timeout(60) \
        .post_init(application_post_init) \
        .post_shutdown(application_post_shutdown) \
        .build()

    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("help",     cmd_help))
    app.add_handler(CommandHandler("mystatus", cmd_mystatus))
    app.add_handler(CommandHandler("run",      cmd_run))
    app.add_handler(CommandHandler("stop",     cmd_stop))
    app.add_handler(CommandHandler("logs",     cmd_logs))
    app.add_handler(CommandHandler("delete",   cmd_delete))
    app.add_handler(CommandHandler("install",  cmd_install))
    app.add_handler(CommandHandler("miniapp",  cmd_miniapp))
    app.add_handler(CommandHandler("admin",    cmd_admin))
    app.add_handler(CommandHandler("forcejoin_add",    cmd_forcejoin_add))
    app.add_handler(CommandHandler("forcejoin_remove", cmd_forcejoin_remove))
    app.add_handler(CommandHandler("setupdates", cmd_setupdates))
    app.add_handler(CommandHandler("setcontact", cmd_setcontact))
    app.add_handler(MessageHandler(
        filters.StatusUpdate.WEB_APP_DATA, handle_web_app_data
    ))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu_text))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(CallbackQueryHandler(admin_callback))
    app.add_error_handler(bot_error_handler)

    # Use PTB's scheduler when available; post_init starts the async fallback
    # for the normal package install where job_queue is None.
    if app.job_queue is not None:
        app.job_queue.run_repeating(watchdog, interval=30, first=10)

    logger.info("Polling started.")
    # Keep this call intentionally minimal. The accepted keyword arguments of
    # Application.run_polling differ between python-telegram-bot releases;
    # timeout values are already configured on the Application builder above.
    try:
        app.run_polling(drop_pending_updates=DROP_PENDING_UPDATES)
    except InvalidToken:
        _release_instance_lock()
        sys.exit(
            "❌ Telegram rejected BOT_TOKEN (InvalidToken).\n"
            "Create a fresh token with @BotFather, then set it before launch:\n"
            "  Windows CMD:   set BOT_TOKEN=123456:ABC...\n"
            "  PowerShell:    $env:BOT_TOKEN='123456:ABC...'\n"
            "  Or create .env beside this file with BOT_TOKEN=...\n"
            "Also confirm ADMIN_ID is your numeric Telegram user ID."
        )
    except Exception as _poll_exc:
        from telegram.error import Conflict as _TgConflict
        if isinstance(_poll_exc, _TgConflict):
            logger.error(
                "Telegram polling conflict: another bot instance is using this token. "
                "Render should run exactly one instance of this service."
            )
        _release_instance_lock()
        raise
    finally:
        _release_instance_lock()

if __name__ == "__main__":
    main()
