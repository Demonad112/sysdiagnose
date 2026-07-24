import os
from pathlib import Path

# Root folder for all persistent data (uploads-in-progress + sysdiagnose cases).
# On Railway this should be the mount path of the attached volume.
DATA_ROOT = Path(os.getenv("SYSDX_DATA_ROOT", "./data")).resolve()
UPLOADS_ROOT = DATA_ROOT / "uploads"
CASES_ROOT = DATA_ROOT / "cases"

UPLOADS_ROOT.mkdir(parents=True, exist_ok=True)
CASES_ROOT.mkdir(parents=True, exist_ok=True)

# The sysdiagnose framework reads this env var itself (see SysdiagnoseConfig).
os.environ.setdefault("SYSDIAGNOSE_CASES_PATH", str(CASES_ROOT))

DATABASE_URL = os.getenv("SYSDX_DATABASE_URL", f"sqlite:///{DATA_ROOT / 'sysdx.db'}")

# Chunk size the frontend is expected to use; also used to validate assembled size.
CHUNK_SIZE_BYTES = int(os.getenv("SYSDX_CHUNK_SIZE_BYTES", 8 * 1024 * 1024))  # 8MB

# Worker polling interval in seconds.
WORKER_POLL_INTERVAL = float(os.getenv("SYSDX_WORKER_POLL_INTERVAL", 2.0))
