"""
Process manager for all 3 Discord bots.

Spawns each bot as a separate Python process so that each gets its own
event loop and interactions.py Client instance. This avoids the decorator
registration issues that happen when multiple Clients share one process.

Single Railway service + single volume, but 3 fully independent bots.
If one crashes it gets auto-restarted after a short delay.
"""

import subprocess
import sys
import time
import signal
import os
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - run_all - %(levelname)s - %(message)s"
)
logger = logging.getLogger("run_all")

# Each bot is a separate Python module entry point.
# These run as completely independent processes with their own interpreters.
BOTS = [
    {"name": "trannyverse",  "module": "bots.trannyverse.bot1"},
    {"name": "protector",    "module": "bots.protector.server_helper"},
    # {"name": "persona",      "module": "bots.persona.persona_bot"},
]

# How long to wait before restarting a crashed bot
RESTART_DELAY = 10

# Track child processes so we can clean up on shutdown
processes: dict[str, subprocess.Popen] = {}
shutting_down = False

import urllib.request
import subprocess

data_dir = os.environ.get("DATA_DIR", "data")
os.makedirs(data_dir, exist_ok=True)

seeds = {
    "DB_SEED_URL": ("discord_analytics.db.xz", True),    # needs decompression
    "MODERATION_DB_SEED_URL": ("moderation.db", False),
    "CHROMA_SEED_URL": ("chroma_db.tar.xz", True),       # needs extraction
}

for env_key, (filename, needs_extract) in seeds.items():
    url = os.environ.get(env_key)
    dest = os.path.join(data_dir, filename)
    final = dest.replace(".xz", "").replace(".tar", "")

    if not url or os.path.exists(final):
        continue

    logger.info(f"Downloading {filename}...")
    # gdown handles Google Drive large file confirmation prompts
    subprocess.run(["pip", "install", "gdown"], check=True)
    subprocess.run(["gdown", url, "-O", dest], check=True)
    logger.info(f"Downloaded {os.path.getsize(dest)} bytes")

    if filename.endswith(".tar.xz"):
        import tarfile
        logger.info("Extracting tarball...")
        with tarfile.open(dest, "r:xz") as tar:
            tar.extractall(path=data_dir)
        os.remove(dest)
        logger.info("Extraction complete")
    elif filename.endswith(".xz"):
        import lzma
        logger.info("Decompressing...")
        out_path = dest.removesuffix(".xz")
        with lzma.open(dest) as xz_file:
            with open(out_path, "wb") as out_file:
                while chunk := xz_file.read(8192):
                    out_file.write(chunk)
        os.remove(dest)
        logger.info("Decompression complete")

    logger.info(f"{final} ready")

def start_bot(bot_config: dict) -> subprocess.Popen:
    """
    Spawn a bot as a child process using python -m <module>.

    Each bot runs in its own Python interpreter, so there are no
    shared state issues with interactions.py decorators or event loops.
    """
    name = bot_config["name"]
    module = bot_config["module"]

    logger.info(f"Starting {name} (python -m {module})")

    proc = subprocess.Popen(
        [sys.executable, "-m", module],
        # Inherit env vars (tokens, DATA_DIR, etc.) from parent
        env=os.environ.copy(),
        # Let child stdout/stderr flow to our stdout/stderr
        # so Railway captures all logs in one place
        stdout=sys.stdout,
        stderr=sys.stderr,
    )

    logger.info(f"{name} started with PID {proc.pid}")
    return proc


def shutdown_all(signum=None, frame=None):
    """Gracefully terminate all child processes on SIGTERM/SIGINT."""
    global shutting_down
    shutting_down = True

    sig_name = signal.Signals(signum).name if signum else "manual"
    logger.info(f"Received {sig_name}, shutting down all bots...")

    for name, proc in processes.items():
        if proc.poll() is None:  # still running
            logger.info(f"Sending SIGTERM to {name} (PID {proc.pid})")
            proc.terminate()

    # Give them a few seconds to clean up
    deadline = time.time() + 10
    for name, proc in processes.items():
        remaining = max(0, deadline - time.time())
        try:
            proc.wait(timeout=remaining)
            logger.info(f"{name} exited with code {proc.returncode}")
        except subprocess.TimeoutExpired:
            logger.warning(f"{name} didn't exit in time, killing")
            proc.kill()

    logger.info("All bots stopped.")
    sys.exit(0)


def main():
    # Register signal handlers for clean shutdown
    # Railway sends SIGTERM when stopping a service
    signal.signal(signal.SIGTERM, shutdown_all)
    signal.signal(signal.SIGINT, shutdown_all)

    logger.info(f"Starting {len(BOTS)} bots as separate processes")
    logger.info(f"DATA_DIR = {os.environ.get('DATA_DIR', '(not set, using local default)')}")

    # Initial startup of all bots
    for bot_config in BOTS:
        proc = start_bot(bot_config)
        processes[bot_config["name"]] = proc
        # Small stagger so they don't all hit Discord gateway at once
        time.sleep(2)

    logger.info("All bots launched. Monitoring for crashes...")

    # Monitor loop: restart any bot that crashes
    while not shutting_down:
        for bot_config in BOTS:
            name = bot_config["name"]
            proc = processes[name]

            # Check if process exited
            if proc.poll() is not None:
                exit_code = proc.returncode
                logger.error(f"{name} crashed with exit code {exit_code}")

                if not shutting_down:
                    logger.info(f"Restarting {name} in {RESTART_DELAY}s...")
                    time.sleep(RESTART_DELAY)
                    processes[name] = start_bot(bot_config)

        # Check every 5 seconds
        time.sleep(5)


if __name__ == "__main__":
    main()