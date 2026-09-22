"""Serveur de décision Laya (convaiinnovations/laya) exposant le contrat POST /v1/systemone.

Laya est un modèle de décision « Système 1 » non autorégressif (encodeur mmBERT + tête de
décision) : un état + des questions typées (noul / choice / score) entrent, une distribution de
probabilités calibrée par question sort, en une seule passe. Même format de réponse que Kev.
"""
import os
import threading
import time
from typing import Any, Dict, Optional, Union

import laya
import uvicorn
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

MODEL = os.environ.get("LAYA_MODEL", "convaiinnovations/laya")
SUBFOLDER = os.environ.get("LAYA_SUBFOLDER", "multilingual") or None
DEVICE = os.environ.get("LAYA_DEVICE") or None
API_KEY = os.environ.get("KEV_API_KEY") or None

agent = laya.load(MODEL, device=DEVICE, subfolder=SUBFOLDER)
lock = threading.Lock()
app = FastAPI(title="Laya /v1/systemone")


class SystemOneRequest(BaseModel):
    state: Union[str, Dict[str, Any], list]
    questions: Dict[str, Dict[str, Any]] = Field(min_length=1)
    model: Optional[str] = None


@app.post("/v1/systemone")
def systemone(req: SystemOneRequest, authorization: Optional[str] = Header(None)):
    if API_KEY and authorization != f"Bearer {API_KEY}":
        raise HTTPException(status_code=401, detail="unauthorized")
    t = time.perf_counter()
    try:
        with lock:
            out = agent.system_one(req.state, req.questions)
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=422, detail=str(e))
    out["latency_ms"] = round((time.perf_counter() - t) * 1000, 1)
    return out


@app.get("/v1/models")
def models():
    name = f"{MODEL}/{SUBFOLDER}" if SUBFOLDER else MODEL
    return {"models": [{"name": "laya", "checkpoint": name, "device": str(agent.device)}]}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8008")))
