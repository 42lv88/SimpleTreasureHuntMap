"""
Street Hunt Backend API - Local/Offline Version
===============================================
Endpoints:
  GET  /api                 → health check
  POST /api/generate-quests → 3 Harry Potter street quests (Gemma 3B via Ollama)
  POST /api/verify-sign     → OCR a street sign photo and verify it (pytesseract)

Run locally:
  Ensure Ollama is running: ollama run gemma:2b (or gemma:3b)
  Ensure Tesseract is installed (e.g. apt-get install tesseract-ocr)
  pip install -r requirements.txt
  OLLAMA_URL=http://localhost:11434 uvicorn main:app --reload

On Render:
  Set OLLAMA_URL in the Render dashboard if hosting Ollama elsewhere.
  (Render free tier cannot run Ollama natively due to RAM limits).
"""

import os
import math
import io
import random
import re
import logging

import httpx
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from PIL import Image
import pytesseract

# ─── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ─── AI Setup (Ollama & Tesseract) ───────────────────────────────────────────
# Defaults to localhost if not set in environment
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")
# Change this model name to exactly what you have pulled in Ollama
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gemma:2b") 

log.info("Configured to use Ollama at %s with model %s", OLLAMA_URL, OLLAMA_MODEL)
log.info("Using Tesseract OCR for image verification")

# ─── App ─────────────────────────────────────────────────────────────────────
app = FastAPI(title="Street Hunt API")

# Allow the Svelte frontend (on Render static site) to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ═════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def move_point(lat: float, lng: float, bearing: float, metres: float) -> tuple:
    """Move a GPS coordinate metres in compass bearing direction."""
    R = 6_371_000
    b = math.radians(bearing)
    lat1, lng1 = math.radians(lat), math.radians(lng)
    lat2 = math.asin(
        math.sin(lat1) * math.cos(metres / R)
        + math.cos(lat1) * math.sin(metres / R) * math.cos(b)
    )
    lng2 = lng1 + math.atan2(
        math.sin(b) * math.sin(metres / R) * math.cos(lat1),
        math.cos(metres / R) - math.sin(lat1) * math.sin(lat2),
    )
    return math.degrees(lat2), math.degrees(lng2)


async def get_street_name(lat: float, lng: float) -> str:
    """Reverse-geocode a GPS point to a street name via OpenStreetMap Nominatim."""
    try:
        async with httpx.AsyncClient(timeout=6) as client:
            resp = await client.get(
                "https://nominatim.openstreetmap.org/reverse",
                params={"format": "json", "lat": lat, "lon": lng},
                headers={"User-Agent": "StreetHuntApp/1.0"},
            )
            addr = resp.json().get("address", {})
            return (
                addr.get("road") or addr.get("pedestrian") or
                addr.get("path") or addr.get("suburb") or "Mystery Lane"
            )
    except Exception as e:
        log.warning("Geocoding failed: %s", e)
        return "Mystery Lane"


def fallback_riddle(street: str, dist: int) -> str:
    """Pre-written Harry Potter riddle for when the AI is unavailable."""
    hint = re.sub(
        r"\b(street|road|avenue|lane|drive|way|boulevard|st|rd|ave|ln|dr|blvd)\b",
        "", street, flags=re.IGNORECASE
    ).strip() or street

    return random.choice([
        (
            f"📜 *\"Messrs Moony, Wormtail, Padfoot and Prongs solemnly swear...\"\n"
            f"⚡ Exactly {dist} paces hence, where lanterns flicker and cobblestones whisper,\n"
            f"lies an enchanted passage carrying the spirit of '{hint}'.\n"
            f"Seek the iron crest upon the wall and break the charm!* 🪄"
        ),
        (
            f"✨ *{dist} paces ahead the Marauder's Map glows gold,\n"
            f"A clandestine way echoing '{hint}' — find the sign and claim this quest!* 🏰"
        ),
    ])


async def make_riddle(street: str, dist: int) -> str:
    """Ask Ollama (Gemma) to write a Harry Potter riddle, fall back to template if it fails."""
    prompt = (
        f"You are the enchanted Marauder's Map from Harry Potter.\n"
        f"Write a beautiful, poetic 2-3 line riddle for a wizard treasure hunter.\n"
        f"The destination is '{street}', exactly {dist} paces away.\n"
        f"Rules: use magical imagery, cleverly hint at '{street}' without spelling it fully,\n"
        f"mention '{dist} paces', output ONLY the riddle verse."
    )
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.8
                    }
                }
            )
            resp.raise_for_status()
            data = resp.json()
            text = data.get("response", "").strip()
            if text:
                return text
    except Exception as e:
        log.warning("Ollama riddle generation failed: %s", e)
        
    return fallback_riddle(street, dist)


def fuzzy_match(ocr_text: str, target_street: str) -> tuple:
    """Check if OCR output from a sign photo matches the target street name."""
    SUFFIXES = {"street","road","avenue","lane","drive","way","boulevard",
                "st","rd","ave","ln","dr","blvd","close","court","ct"}

    def keywords(s):
        tokens = set(re.sub(r"[^a-z0-9 ]", "", s.lower()).split())
        return (tokens - SUFFIXES) or tokens

    ocr_words    = keywords(ocr_text)
    target_words = keywords(target_street)
    overlap      = len(ocr_words & target_words)
    score        = overlap / max(len(target_words), 1)
    substr_hit   = any(w in ocr_text.lower() for w in target_words if len(w) > 2)
    matched      = score >= 0.5 or substr_hit
    confidence   = round(max(score, 0.85 if substr_hit else 0.0), 2)
    return matched, confidence


# ═════════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ═════════════════════════════════════════════════════════════════════════════

class QuestRequest(BaseModel):
    lat: float
    lng: float


@app.get("/api")
def health_check():
    """Health check — confirms the API is running."""
    return {"status": "ok", "ai_ready": True, "provider": "ollama+tesseract"}


@app.post("/api/generate-quests")
async def generate_quests(req: QuestRequest):
    """Generate 3 street quests with GPS targets and Harry Potter riddles."""
    bearings  = [random.randint(10, 110),  random.randint(130, 230), random.randint(250, 350)]
    distances = [random.randint(100, 200), random.randint(201, 350), random.randint(351, 500)]

    quests = []
    for i in range(3):
        tlat, tlng = move_point(req.lat, req.lng, bearings[i], distances[i])
        street = await get_street_name(tlat, tlng)
        riddle = await make_riddle(street, distances[i])
        quests.append({
            "id": i, "lat": tlat, "lng": tlng,
            "street": street, "riddle": riddle, "nominalDist": distances[i],
        })
    return {"quests": quests}


@app.post("/api/verify-sign")
async def verify_sign(file: UploadFile = File(...), street: str = Form(...)):
    """OCR the uploaded street sign photo and check if it matches the target street."""
    img_bytes = await file.read()
    ocr_text  = ""

    try:
        # Load image with Pillow for pytesseract
        img = Image.open(io.BytesIO(img_bytes))
        
        # Extract text using offline Tesseract OCR
        # --psm 3 is default (Fully automatic page segmentation)
        ocr_text = pytesseract.image_to_string(img).strip()
        log.info("Tesseract OCR: %r vs target: %r", ocr_text, street)
    except Exception as e:
        log.warning("Offline OCR failed: %s", e)

    if not ocr_text:
        return {"matched": False, "ocr_text": "(unreadable — try a clearer photo)", "street": street, "confidence": 0.0}

    matched, confidence = fuzzy_match(ocr_text, street)
    return {"matched": matched, "ocr_text": ocr_text, "street": street, "confidence": confidence}
