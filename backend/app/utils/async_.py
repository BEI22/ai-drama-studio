"""Running coroutines from synchronous code.

The service layer is synchronous (sync SQLAlchemy session) while every provider
is ``async`` (PRD section 16's interfaces are coroutine-based). Something has to
bridge the two, and the naive bridge is wrong:

``asyncio.run(coro)`` raises ``RuntimeError: asyncio.run() cannot be called from a
running event loop``. That happens the moment an image task is executed inside the
request's event loop -- which is exactly what ``CELERY_TASK_ALWAYS_EAGER=true``
does, and what an ASGI test client does. The failure would be intermittent and
depend on which transport was configured, so it is fixed here once instead.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TypeVar

T = TypeVar("T")


def run_async(coro: Coroutine[Any, Any, T]) -> T:
    """Run ``coro`` to completion, whether or not a loop is already running.

    With no running loop (a Celery worker) this is plain ``asyncio.run``. Inside a
    running loop (eager mode, ASGI tests) the coroutine is executed on a fresh
    loop in a worker thread -- blocking the caller is intended: the task state
    machine is synchronous by design.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()
