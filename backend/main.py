"""
Treasure Hunt API — Gemma 2B via Google AI Studio (Harry Potter Marauder's Map Edition)
"""
import os
import random
import re
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

gemma_model = None
if GOOGLE_API_KEY:
    try:
        genai.configure(api_key=GOOGLE_API_KEY)
        gemma_model = genai.GenerativeModel("gemma-2-2b-it")
        log.info("Google AI Studio configured with Gemma 2B ✓")
    except Exception as e:
        log.warning(f"Could not init gemma model: {e}")

app = FastAPI(title="Street Hunt – Gemma 2B Marauder's Map API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class RiddleRequest(BaseModel):
    street: str
    distance: int


def make_magical_verse(place: str, distance: int) -> str:
    clean = re.sub(r'\b(street|road|avenue|lane|drive|way|boulevard|st|rd|ave|ln|dr|blvd)\b', '', place, flags=re.IGNORECASE).strip()
    name_hint = clean if clean else place

    templates = [
        (
            f"📜 \"Messrs Moony, Wormtail, Padfoot, and Prongs whisper a secret...\"\n"
            f"⚡ Exactly {distance} paces ahead, where shadows bend and cobblestones tread, "
            f"lies an enchanted realm carrying the spirit of '{name_hint}'.\n"
            f"Seek the iron crest upon the wall to break the charm! 🪄"
        ),
        (
            f"✨ Cobblestones hum and golden parchment glows {distance} paces from where you stand.\n"
            f"A clandestine pathway echoing the mystery of '{name_hint}' awaits your wand.\n"
            f"Whisper 'Lumos', gaze upon the signpost, and claim your wizarding triumph! 🦉"
        ),
        (
            f"🏰 By ancient decree of Hogwarts, a magical passage stirs {distance} meters hence.\n"
            f"Shrouded from mortal Muggle eyes, bearing the crest of '{name_hint}'.\n"
            f"Find the silver plaque before the spell dissolves into the night! 📜"
        )
    ]
    return random.choice(templates)


@app.post("/generate-riddle")
async def generate_riddle(req: RiddleRequest) -> dict:
    prompt = (
        f"You are the Marauder's Map and Sorting Hat from Harry Potter writing an enchanting, mysterious riddle. "
        f"The destination is '{req.street}', located exactly {req.distance} meters away. "
        f"Write a beautiful, poetic 2-to-3 line Harry Potter style riddle hinting at this place and its distance ({req.distance} paces). "
        f"Use magical imagery (wands, spells, enchanted maps, Marauders, Hogwarts, ancient cobblestones). "
        f"Cleverly hint at the place '{req.street}' without spelling out its full name directly. "
        f"Output ONLY the magical riddle verse, nothing else."
    )

    if gemma_model:
        try:
            response = gemma_model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.85,
                    max_output_tokens=100,
                ),
            )
            riddle_text = response.text.strip()
            if riddle_text:
                return {"riddle": riddle_text}
        except Exception:
            try:
                flash = genai.GenerativeModel("gemini-1.5-flash")
                resp = flash.generate_content(prompt)
                if resp.text.strip():
                    return {"riddle": resp.text.strip()}
            except Exception:
                pass

    return {"riddle": make_magical_verse(req.street, req.distance)}


@app.get("/")
def healthcheck() -> dict:
    return {
        "status": "ok",
        "model": "gemma-2-2b-it (Harry Potter edition)",
        "api_configured": gemma_model is not None,
    }
