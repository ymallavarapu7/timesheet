"""
Start the arq background worker.

Run from the backend/ directory:
    python run_worker.py
Or with arq directly:
    arq app.workers.settings.WorkerSettings
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


if __name__ == "__main__":
    from arq import run_worker

    from app.workers.settings import WorkerSettings

    asyncio.run(run_worker(WorkerSettings))
