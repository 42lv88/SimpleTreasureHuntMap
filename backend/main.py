"""
Treasure Hunt API — Gemma 2B running locally on Render via llama-cpp-python.

How it works:
  1. On first startup the server downloads the GGUF model (~1.5 GB) from
     HuggingFace Hub into MODEL_DIR (a Render Persistent Disk mount).
  2. llama-cpp-python loads the model and runs pure-CPU inference.
  3. No torch, no transformers, no GPU needed — works on Render's Standard plan.

Env vars (set in Render dashboard or .env):
  HF_TOKEN   — optional; only needed if you switch to a gated HF repo
  MODEL_DIR  — path to the Render Persistent Disk (default: /var/data)
"""

import os
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from huggingface_hub import hf_hub_download
from llama_cpp import Llama

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ── Model config ────────────────────────────────────────────────────────
# bartowski/gemma-2-2b-it-GGUF is a public, no-auth repo with Q4 quants.
# Q4_K_M quantization: ~1.5 GB RAM, good quality/speed trade-off on CPU.
HF_REPO   = "bartowski/gemma-2-2b-it-GGUF"
HF_FILE   = "gemma-2-2b-it-Q4_K_M.gguf"
MODEL_DIR = Path(os.getenv("MODEL_DIR", "/var/data"))
MODEL_PATH = MODEL_DIR / HF_FILE

# ── App ──────────────────────────────────────────────────────────────────
app = FastAPI(title="Street Hunt – Gemma 2B on Render")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

llm: Llama | None = None


@app.on_event("startup")
def load_model() -> None:
    global llm

    # Download model to persistent disk if not already present
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    if not MODEL_PATH.exists():
        log.info("Downloading Gemma 2B GGUF (~1.5 GB). This runs once and is cached on disk…")
        hf_hub_download(
            repo_id=HF_REPO,
            filename=HF_FILE,
            local_dir=str(MODEL_DIR),
            token=os.getenv("HF_TOKEN") or None,  # optional for this public repo
        )
        log.info("Download complete.")
    else:
        log.info("Model already cached at %s", MODEL_PATH)

    log.info("Loading Gemma 2B into llama-cpp…")
    llm = Llama(
        model_path=str(MODEL_PATH),
        n_ctx=512,          # context window — keep small to save RAM
        n_threads=2,        # Render Standard has 2 vCPU
        verbose=False,
    )
    log.info("Model ready ✓")


# ── Endpoints ────────────────────────────────────────────────────────────

class RiddleRequest(BaseModel):
    street: str
    distance: int


@app.post("/generate-riddle")
async def generate_riddle(req: RiddleRequest) -> dict:
    if llm is None:
        return {
            "riddle": (
                f"I wind through the city, {req.distance} meters near,\n"
                "Seek the sign that bears my name with care.\n"
                "Street explorers who find me win the game! 🗺️"
            )
        }

    prompt = (
        f"<start_of_turn>user\n"
        f"Write a short, fun riddle (2-3 lines) about a street named '{req.street}'. "
        f"The player is {req.distance} meters away from it. "
        f"Do NOT say the street name. Make it feel like a Pokémon GO adventure clue!\n"
        f"<end_of_turn>\n<start_of_turn>model\n"
    )

    try:
        output = llm(
            prompt,
            max_tokens=90,
            temperature=0.8,
            top_p=0.95,
            stop=["<end_of_turn>", "<start_of_turn>"],
            echo=False,
        )
        riddle = output["choices"][0]["text"].strip()
        return {"riddle": riddle}
    except Exception as exc:
        log.error("Inference error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/")
def healthcheck() -> dict:
    return {
        "status": "ok",
        "model": HF_FILE,
        "model_loaded": llm is not None,
    }
