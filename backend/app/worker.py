"""Background worker entry point: `python -m app.worker`."""

import asyncio
import contextlib
import logging
import signal

from app.core.db import SessionLocal
from app.core.logs import setup_logging
from app.jobs import queue
from app.jobs.worker import run_worker

# job handler modules register themselves on import
HANDLER_MODULES: tuple[str, ...] = ("app.git.jobs", "app.kb.search", "app.memory.fakes", "app.memory.extract", "app.memory.dream",
                                   "app.notifications.jobs", "app.search.jobs", "app.updates.check")
# run once at start as well as on their schedule (periodic jobs otherwise wait one interval)
STARTUP_JOBS: tuple[str, ...] = ("updates.check",)


async def enqueue_startup_jobs() -> None:
    async with SessionLocal() as db:
        for kind in STARTUP_JOBS:
            await queue.enqueue(db, kind, {}, dedupe_key=kind)
        await db.commit()


async def _main() -> None:
    import importlib

    for name in HANDLER_MODULES:
        importlib.import_module(name)
    from app.search import capture  # changes made by jobs are indexed too

    capture.install()
    await enqueue_startup_jobs()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):  # Windows
            loop.add_signal_handler(sig, stop.set)
    logging.getLogger("app.worker").info("worker started")  # under -m, __name__ is __main__
    await run_worker(stop)


def main() -> None:
    setup_logging()
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_main())


if __name__ == "__main__":
    main()
