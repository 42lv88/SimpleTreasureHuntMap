# Same logic as api/index.py but without the Mangum/Vercel adapter.
# Use this for running locally: uvicorn main:app --reload

# Copy the imports and app from api/index.py, then run with:
#   cd backend
#   pip install fastapi uvicorn httpx google-generativeai python-multipart
#   uvicorn main:app --reload

import os
import math
import base64
import random
import re
import logging

import httpx
import google.generativeai as genai
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

# Load .env file for local development
load_dotenv()

# ─── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ─── AI Setup ────────────────────────────────────────────────────────────────
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
ai_model = None

if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)
    ai_model = genai.GenerativeModel("gemini-1.5-flash")
    log.info("Gemini 1.5 Flash ready ✓")
else:
    log.warning("GOOGLE_API_KEY not set — fallback riddles will be used, OCR disabled")

# ─── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(title="Street Hunt API (local)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Helpers (same as api/index.py) ──────────────────────────────────────────

def move_point(lat, lng, bearing, metres):
    """Move a GPS point by `metres` in compass `bearing` direction."""
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


async def get_street_name(lat, lng):
    """Reverse-geocode a GPS point to a street name using OpenStreetMap."""
    try:
        async with httpx.AsyncClient(timeout=6) as client:
            resp = await client.get(
                "https://nominatim.openstreetmap.org/reverse",
                params={"format": "json", "lat": lat, "lon": lng},
                headers={"User-Agent": "StreetHuntApp/1.0"},
            )
            data = resp.json()
            addr = data.get("address", {})
            return (addr.get("road") or addr.get("pedestrian") or
                    addr.get("path") or addr.get("suburb") or
                    data.get("name") or "Mystery Lane")
    except Exception as e:
        log.warning("Geocoding failed: %s", e)
        return "Mystery Lane"


def fallback_riddle(street, dist):
    """Pre-written Harry Potter riddle when AI is unavailable."""
    hint = re.sub(
        r"\b(street|road|avenue|lane|drive|way|boulevard|st|rd|ave|ln|dr|blvd)\b",
        "", street, flags=re.IGNORECASE
    ).strip() or street

    return random.choice([
        f"📜 *{dist} paces hence, where lanterns flicker and cobblestones whisper,\n"
        f"lies an enchanted passage carrying the spirit of '{hint}'.\n"
        f"Seek the iron crest upon the wall and break the charm!* 🪄",

        f"✨ *{dist} paces ahead the Marauder's Map glows gold,\n"
        f"A clandestine way echoing '{hint}' — find the sign and claim this quest!* 🏰",
    ])


async def make_riddle(street, dist):
    """Ask Gemini to write a Harry Potter riddle, or use fallback."""
    if not ai_model:
        return fallback_riddle(street, dist)
    try:
        resp = ai_model.generate_content(
            f"You are the Marauder's Map from Harry Potter.\n"
            f"Write a poetic 2-3 line riddle hinting at the street '{street}', {dist} paces away.\n"
            f"Use magical imagery. Don't spell out the full street name. Output ONLY the riddle.",
            generation_config={"temperature": 0.9, "max_output_tokens": 120},
        )
        text = resp.text.strip()
        if text:
            return text
    except Exception as e:
        log.warning("Riddle failed: %s", e)
    return fallback_riddle(street, dist)


def fuzzy_match(ocr_text, target_street):
    """Check if OCR text from a sign photo matches the target street."""
    SUFFIXES = {"street","road","avenue","lane","drive","way","boulevard",
                "st","rd","ave","ln","dr","blvd","close","court","ct"}

    def keywords(s):
        tokens = set(re.sub(r"[^a-z0-9 ]", "", s.lower()).split())
        return (tokens - SUFFIXES) or tokens

    ocr_words    = keywords(ocr_text)
    target_words = keywords(target_street)

    overlap    = len(ocr_words & target_words)
    score      = overlap / max(len(target_words), 1)
    substr_hit = any(w in ocr_text.lower() for w in target_words if len(w) > 2)
    matched    = score >= 0.5 or substr_hit
    confidence = round(max(score, 0.85 if substr_hit else 0.0), 2)
    return matched, confidence


# ─── Endpoints ────────────────────────────────────────────────────────────────

class QuestRequest(BaseModel):
    lat: float
    lng: float


@app.get("/api")
def health_check():
    return {"status": "ok", "ai_ready": ai_model is not None}


@app.post("/api/generate-quests")
async def generate_quests(req: QuestRequest):
    """Generate 3 quests with street targets and Harry Potter riddles."""
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
    """OCR the street sign photo and check if it matches the target."""
    img_bytes = await file.read()
    ocr_text  = ""

    # Read sign text with Gemini Vision
    if ai_model:
        try:
            b64  = base64.b64encode(img_bytes).decode()
            mime = file.content_type or "image/jpeg"
            resp = ai_model.generate_content([
                "Read the street sign in this photo. Output ONLY the street name text. If unreadable output: NONE",
                {"mime_type": mime, "data": b64},
            ])
            ocr_text = resp.text.strip()
        except Exception as e:
            log.warning("OCR failed: %s", e)

    if not ocr_text or ocr_text.upper() == "NONE":
        return {"matched": False, "ocr_text": "(unreadable — try a clearer photo)", "street": street, "confidence": 0.0}

    matched, confidence = fuzzy_match(ocr_text, street)
    return {"matched": matched, "ocr_text": ocr_text, "street": street, "confidence": confidence}
