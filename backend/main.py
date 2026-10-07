"""
Treasure Hunt API — Gemma 2B via Google AI Studio (free, no card needed).

Setup:
  1. Go to https://aistudio.google.com/ and sign in with your Google account.
  2. Click 'Get API Key' → 'Create API key'. That's it — completely free.
  3. Set that key as GOOGLE_API_KEY in Render's Environment Variables
     (or in your local .env file for dev).

Runs on Render's FREE tier (512 MB RAM) since no model is loaded locally.
"""
import os
import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

# Configure the Google Generative AI client
if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)
    # Use Gemma 2B via AI Studio — model ID for Gemma 2 2B instruction-tuned
    gemma_model = genai.GenerativeModel("gemma-2-2b-it")
    log.info("Google AI Studio configured with Gemma 2B ✓")
else:
    gemma_model = None
    log.warning("GOOGLE_API_KEY not set — riddle fallback will be used.")

app = FastAPI(title="Street Hunt – Gemma 2B via Google AI Studio")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class RiddleRequest(BaseModel):
    street: str
    distance: int


FALLBACK_RIDDLES = [
    "I'm a path that stretches far and wide,\n{d} meters from where you stand with pride.\nMy name hangs on a sign — find me to decide! 🗺️",
    "Winds carry my name through the city air,\n{d} steps away, if you only dare.\nLook for my board and claim your trophy rare! 🏆",
]


@app.post("/generate-riddle")
async def generate_riddle(req: RiddleRequest) -> dict:
    if not gemma_model:
        import random
        template = random.choice(FALLBACK_RIDDLES)
        return {"riddle": template.format(d=req.distance)}

    prompt = (
        f"Write a fun, short riddle (2–3 lines, under 40 words) about a street named '{req.street}'. "
        f"The player is {req.distance} meters away from it. "
        f"Do NOT reveal the street name. Make it feel like a Pokémon GO adventure clue. "
        f"Output only the riddle text, nothing else."
    )

    try:
        response = gemma_model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.85,
                max_output_tokens=80,
            ),
        )
        riddle = response.text.strip()
        return {"riddle": riddle}
    except Exception as exc:
        log.error("Gemma API error: %s", exc)
        # Graceful fallback so the game always continues
        return {"riddle": f"I lie {req.distance} meters from your feet, a hidden street. 🗺️ Find my sign to complete the feat!"}


@app.get("/")
def healthcheck() -> dict:
    return {
        "status": "ok",
        "model": "gemma-2-2b-it (Google AI Studio)",
        "api_configured": gemma_model is not None,
    }
