"""Lance kev.serve en écoutant sur 0.0.0.0 (le CLI amont est figé sur 127.0.0.1)."""
import os, sys
import uvicorn

_run = uvicorn.run
uvicorn.run = lambda app, host=None, port=8008, **kw: _run(app, host=os.environ.get("KEV_HOST", "0.0.0.0"), port=port, **kw)

from kev.serve import main

sys.argv = ["kev.serve", *sys.argv[1:]]
main()
