"""Single-process entrypoint that runs the API and the background worker together.

Deploy topologies vary: on a platform that gives every service its own persistent volume
(and lets two services share one), `web` and `worker` can be split as documented in
webapp/README.md. On Railway specifically, a volume can only attach to one service, and
the worker needs the same local disk the API reads case data from — so here they run as
one process instead: the worker loop runs in a background thread, uvicorn runs in the
main thread. Both still talk to the same on-disk case data and the same DB-backed job
queue; nothing about that contract changes.
"""

import os
import threading

import uvicorn

from app.worker import run_forever


def main() -> None:
    threading.Thread(target=run_forever, daemon=True, name="sysdx-worker").start()
    uvicorn.run("app.main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))


if __name__ == "__main__":
    main()
