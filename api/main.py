"""Cut Off API. Run from the repo root: uvicorn api.main:app --reload"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from api.data import DataError, get_alert, get_ice, get_layer, get_lifelines, get_stats, list_dates
from ai.llm import ask, generate_alert, infer, situation_report

LayerKind = Literal["extra", "ice", "water"]
Audience = Literal["coordinator", "community", "pilots"]


class HistoryTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class AskBody(BaseModel):
    question: str
    history: list[HistoryTurn] = Field(default_factory=list)


class AlertBody(BaseModel):
    date: str
    audience: Audience


def _call(fn, *args):
    try:
        return fn(*args)
    except DataError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Answers are cached after the first call. A startup burst trips the free-tier token limit.
    yield


app = FastAPI(title="Cut Off", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/dates")
def dates():
    return _call(list_dates)


@app.get("/api/dates/{date}/summary")
def summary(date: str):
    stats = _call(get_stats, date)
    return {
        "stats": stats,
        "ice": _call(get_ice, date),
        "lifelines": _call(get_lifelines, date),
        "alert": _call(get_alert, date),
    }


@app.get("/api/layers/normal")
def normal_layer():
    return _call(get_layer, "normal", None)


@app.get("/api/dates/{date}/layers/{kind}")
def date_layer(date: str, kind: LayerKind):
    return _call(get_layer, kind, date)


@app.post("/api/ask")
def ask_question(body: AskBody):
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question is empty.")
    history = [turn.model_dump() for turn in body.history]
    try:
        return ask(question, history)
    except DataError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc


@app.post("/api/infer")
def infer_question(body: AskBody):
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question is empty.")
    history = [turn.model_dump() for turn in body.history]
    try:
        return infer(question, history)
    except DataError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc


@app.post("/api/alert")
def alert(body: AlertBody):
    return _call(generate_alert, body.date, body.audience)


@app.get("/api/report")
def report():
    try:
        text = situation_report()
    except DataError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    return Response(content=text, media_type="text/markdown; charset=utf-8")
