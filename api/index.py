"""
Street Hunt Backend API
=======================
Three endpoints:
  GET  /api                 → health check (confirms AI is connected)
  POST /api/generate-quests → create 3 street quests with Harry Potter riddles
  POST /api/verify-sign     → OCR a street sign photo and check if it's correct

AI model used: Gemini 1.5 Flash (free tier on Google AI Studio, no credit card)
OCR: Gemini Vision (same model — reads the sign text from the uploaded photo)

Get your free API key at https://aistudio.google.com → "Get API Key"
Then set it as GOOGLE_API_KEY in Vercel Environment Variables.
"""

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
from mangum import Mangum
from pydantic import BaseModel


# ─── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


# ─── AI Setup ────────────────────────────────────────────────────────────────
# One model handles both riddle writing AND photo OCR
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
ai_model = None

if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)
    # gemini-1.5-flash: fast, free, supports text + image (vision)
    ai_model = genai.GenerativeModel("gemini-1.5-flash")
    log.info("Gemini 1.5 Flash ready ✓")
else:
    log.warning("GOOGLE_API_KEY not set — fallback riddles will be used, OCR disabled")


# ─── FastAPI App ──────────────────────────────────────────────────────────────
app = FastAPI(title="Street Hunt API")

# Allow the Svelte frontend to call this API from any domain
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ═════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═════════════════════════════════════════════════════════════════════════════

def move_point(lat: float, lng: float, bearing: float, metres: float) -> tuple:
    """
    Move a GPS coordinate `metres` metres in the given compass `bearing`
    (0 = North, 90 = East, 180 = South, 270 = West).
    Returns the new (latitude, longitude).
    """
    R = 6_371_000  # Earth radius in metres
    b = math.radians(bearing)
    lat1 = math.radians(lat)
    lng1 = math.radians(lng)

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
    """
    Use OpenStreetMap Nominatim to reverse-geocode a GPS point to a street name.
    Returns "Mystery Lane" if the request fails or finds no road.
    """
    try:
        async with httpx.AsyncClient(timeout=6) as client:
            resp = await client.get(
                "https://nominatim.openstreetmap.org/reverse",
                params={"format": "json", "lat": lat, "lon": lng},
                headers={"User-Agent": "StreetHuntApp/1.0"},
            )
            data = resp.json()
            addr = data.get("address", {})

            # Try address fields in order of preference
            return (
                addr.get("road")
                or addr.get("pedestrian")
                or addr.get("path")
                or addr.get("suburb")
                or data.get("name")
                or "Mystery Lane"
            )
    except Exception as e:
        log.warning("Reverse geocoding failed: %s", e)
        return "Mystery Lane"


def fallback_riddle(street: str, dist: int) -> str:
    """
    Pre-written Harry Potter riddles used when the AI is unavailable.
    Strips common road-type words (Street, Road, etc.) to make the hint subtle.
    """
    # Remove "Street", "Road", "Avenue" etc. so the hint isn't too obvious
    hint = re.sub(
        r"\b(street|road|avenue|lane|drive|way|boulevard|st|rd|ave|ln|dr|blvd)\b",
        "",
        street,
        flags=re.IGNORECASE,
    ).strip() or street

    options = [
        (
            f"📜 *\"Messrs Moony, Wormtail, Padfoot and Prongs solemnly swear...\"\n"
            f"⚡ Exactly {dist} paces hence, where lanterns flicker and cobblestones whisper,\n"
            f"lies an enchanted passage carrying the spirit of '{hint}'.\n"
            f"Seek the iron crest upon the wall and break the charm!* 🪄"
        ),
        (
            f"✨ *{dist} paces ahead the Marauder's Map glows gold,\n"
            f"A clandestine way waiting to be told.\n"
            f"Its soul echoes '{hint}' — find the sign and claim this quest!* 🏰"
        ),
        (
            f"🦉 *By Dumbledore's decree a hidden way stirs {dist} paces hence,\n"
            f"Its name a secret of great Wizarding consequence.\n"
            f"It echoes '{hint}' — photograph the plaque and let the magic commence!* ⚡"
        ),
    ]
    return random.choice(options)


async def make_riddle(street: str, dist: int) -> str:
    """
    Ask Gemini to write a Harry Potter style riddle for a given street.
    Falls back to a pre-written template if the API call fails.
    """
    if not ai_model:
        return fallback_riddle(street, dist)

    prompt = (
        f"You are the enchanted Marauder's Map from Harry Potter.\n"
        f"Write a beautiful, poetic 2-3 line riddle for a wizard treasure hunter.\n"
        f"The destination is '{street}', exactly {dist} paces away.\n\n"
        f"Rules:\n"
        f"- Use magical imagery: wands, Hogwarts, cobblestones, enchanted parchment\n"
        f"- Cleverly hint at '{street}' WITHOUT spelling the full name\n"
        f"- Mention '{dist} paces' somewhere in the riddle\n"
        f"- Output ONLY the riddle verse — no intro, no explanation"
    )

    try:
        response = ai_model.generate_content(
            prompt,
            # Use a plain dict — avoids genai.types.GenerationConfig version issues
            generation_config={"temperature": 0.9, "max_output_tokens": 120},
        )
        text = response.text.strip()
        if text:
            return text
    except Exception as e:
        log.warning("Riddle generation failed: %s", e)

    # AI failed — return a pre-written fallback
    return fallback_riddle(street, dist)


def fuzzy_match(ocr_text: str, target_street: str) -> tuple:
    """
    Check if the OCR output from a sign photo matches the target street name.
    Strips common suffixes (Road, Street…) and checks for word overlap.
    Returns (matched: bool, confidence: float).
    """
    SUFFIXES = {
        "street", "road", "avenue", "lane", "drive", "way", "boulevard",
        "st", "rd", "ave", "ln", "dr", "blvd", "close", "court", "ct",
    }

    def key_words(text: str) -> set:
        """Lowercase, remove punctuation, strip road-type suffixes."""
        tokens = set(re.sub(r"[^a-z0-9 ]", "", text.lower()).split())
        meaningful = tokens - SUFFIXES
        # If everything was a suffix word, keep all tokens so we don't get empty set
        return meaningful if meaningful else tokens

    ocr_words    = key_words(ocr_text)
    target_words = key_words(target_street)

    # Word overlap score: what fraction of target words appear in OCR?
    overlap = len(ocr_words & target_words)
    score   = overlap / max(len(target_words), 1)

    # Substring check: does any important target word appear inside the OCR string?
    substr_hit = any(
        w in ocr_text.lower()
        for w in target_words
        if len(w) > 2  # skip tiny words like "al", "el"
    )

    matched    = score >= 0.5 or substr_hit
    confidence = round(max(score, 0.85 if substr_hit else 0.0), 2)
    return matched, confidence


# ═════════════════════════════════════════════════════════════════════════════
# API ENDPOINTS
# ═════════════════════════════════════════════════════════════════════════════

class QuestRequest(BaseModel):
    lat: float
    lng: float


@app.get("/")
def health_check():
    """Returns 200 OK and tells the frontend whether the AI model is connected."""
    return {
        "status":   "ok",
        "ai_ready": ai_model is not None,
    }


@app.post("/generate-quests")
async def generate_quests(req: QuestRequest):
    """
    Takes the player's GPS position and returns 3 quests.

    For each quest:
      1. Pick a random compass direction and a random distance.
      2. Calculate the GPS coords of that target point.
      3. Reverse-geocode to get the street name at that point.
      4. Ask Gemini to write a Harry Potter riddle about that street.

    The street name is included in the response so the frontend can send it
    back when verifying a sign photo (it's not displayed to the player).
    """
    # Three targets in different compass quadrants so they spread around the player
    bearings  = [random.randint(10,  110), random.randint(130, 230), random.randint(250, 350)]
    distances = [random.randint(100, 200), random.randint(201, 350), random.randint(351, 500)]

    quests = []
    for i in range(3):
        # 1. Calculate target GPS point
        tlat, tlng = move_point(req.lat, req.lng, bearings[i], distances[i])

        # 2. Find the street name there
        street = await get_street_name(tlat, tlng)

        # 3. Generate a riddle
        riddle = await make_riddle(street, distances[i])

        quests.append({
            "id":          i,
            "lat":         tlat,
            "lng":         tlng,
            "street":      street,         # used for verification — not shown to player
            "riddle":      riddle,
            "nominalDist": distances[i],   # distance at quest creation; updates live in frontend
        })

    return {"quests": quests}


@app.post("/verify-sign")
async def verify_sign(
    file:   UploadFile = File(...),   # photo taken by the player
    street: str        = Form(...),   # target street name sent from the frontend
):
    """
    Verify whether the player's photo shows the correct street sign.

    Steps:
      1. Send the photo to Gemini Vision — it reads the text on the sign.
      2. Fuzzy-match the OCR result against the target street name.
      3. Return whether it matched, plus the raw OCR text and confidence score.
    """
    img_bytes = await file.read()
    ocr_text  = ""

    # Step 1: Read the sign with Gemini Vision
    if ai_model:
        try:
            b64  = base64.b64encode(img_bytes).decode()
            mime = file.content_type or "image/jpeg"

            response = ai_model.generate_content([
                (
                    "Look at this photo of a street sign. "
                    "Extract and output ONLY the street or road name text from the sign. "
                    "Output just the name, nothing else. "
                    "If no street name is readable, output the single word: NONE"
                ),
                {"mime_type": mime, "data": b64},
            ])
            ocr_text = response.text.strip()
            log.info("OCR read: %r | target: %r", ocr_text, street)

        except Exception as e:
            log.warning("Vision OCR failed: %s", e)

    # If the AI couldn't read anything, return early
    if not ocr_text or ocr_text.upper() == "NONE":
        return {
            "matched":    False,
            "ocr_text":   "(could not read sign — try a clearer, closer photo)",
            "street":     street,
            "confidence": 0.0,
        }

    # Step 2: Check if the OCR text matches the target street
    matched, confidence = fuzzy_match(ocr_text, street)

    return {
        "matched":    matched,
        "ocr_text":   ocr_text,
        "street":     street,
        "confidence": confidence,
    }


# ─── Vercel Serverless Handler ────────────────────────────────────────────────
# Vercel rewrites /api/* → this file, so Mangum sees paths like /generate-quests.
# api_gateway_base_path="/api" tells Mangum to strip the /api prefix before
# matching FastAPI routes (which are defined as /, /generate-quests, /verify-sign).
handler = Mangum(app, lifespan="off", api_gateway_base_path="/api")
