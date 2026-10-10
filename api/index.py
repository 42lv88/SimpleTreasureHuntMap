"""
Street Hunt API — 3-Quest Treasure Hunt
  • POST /api/generate-quests  → 3 street targets + Harry Potter riddles (Gemma 2B)
  • POST /api/verify-sign      → upload photo → Gemini Vision OCR → fuzzy match
  • GET  /api                  → healthcheck

OCR strategy (both free / open-source friendly):
  Primary  : Gemini 1.5 Flash Vision  (free tier, zero extra packages)
  Fallback : pytesseract               (FOSS, add tesseract binary for local dev)
"""
import os, math, base64, random, re, logging
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import google.generativeai as genai
import httpx
from mangum import Mangum

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ── AI client setup ────────────────────────────────────────────────────
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
gemma_model = None
vision_model = None

if GOOGLE_API_KEY:
    try:
        genai.configure(api_key=GOOGLE_API_KEY)
        gemma_model = genai.GenerativeModel("gemma-2-2b-it")
        vision_model = genai.GenerativeModel("gemini-1.5-flash")
        log.info("AI models initialized ✓")
    except Exception as e:
        log.warning("Model init failed: %s", e)

# ── App ────────────────────────────────────────────────────────────────
app = FastAPI(title="Street Hunt – 3-Quest OCR Edition")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


# ── Geo helpers ────────────────────────────────────────────────────────
def offset_point(lat: float, lng: float, bearing_deg: float, dist_m: float):
    """Return (lat, lng) offset by dist_m metres in bearing_deg direction."""
    R = 6371000.0
    b = math.radians(bearing_deg)
    lat1 = math.radians(lat)
    lng1 = math.radians(lng)
    lat2 = math.asin(
        math.sin(lat1) * math.cos(dist_m / R)
        + math.cos(lat1) * math.sin(dist_m / R) * math.cos(b)
    )
    lng2 = lng1 + math.atan2(
        math.sin(b) * math.sin(dist_m / R) * math.cos(lat1),
        math.cos(dist_m / R) - math.sin(lat1) * math.sin(lat2),
    )
    return math.degrees(lat2), math.degrees(lng2)


async def reverse_geocode(lat: float, lng: float) -> str:
    try:
        async with httpx.AsyncClient(timeout=6) as client:
            r = await client.get(
                "https://nominatim.openstreetmap.org/reverse",
                params={"format": "json", "lat": lat, "lon": lng},
                headers={"User-Agent": "StreetHuntApp/1.0"},
            )
            d = r.json()
            a = d.get("address", {})
            return (
                a.get("road")
                or a.get("pedestrian")
                or a.get("path")
                or a.get("suburb")
                or d.get("name")
                or "Mystery Lane"
            )
    except Exception:
        return "Mystery Lane"


# ── Riddle generation ──────────────────────────────────────────────────
def _fallback_riddle(place: str, dist: int) -> str:
    clean = re.sub(
        r"\b(street|road|avenue|lane|drive|way|boulevard|st|rd|ave|ln|dr|blvd)\b",
        "",
        place,
        flags=re.IGNORECASE,
    ).strip() or place

    templates = [
        (
            f"📜 *\"Messrs Moony, Wormtail, Padfoot, and Prongs solemnly swear...\"\n"
            f"⚡ Exactly {dist} paces hence, where lanterns flicker and cobblestones"
            f" whisper, lies an enchanted passage bearing the spirit of '{clean}'.\n"
            f"Seek the iron crest upon the wall and break the charm!* 🪄"
        ),
        (
            f"✨ *{dist} paces ahead the Marauder's Map glows gold,\n"
            f"A clandestine way waiting to be told.\n"
            f"Its soul echoes '{clean}' — find the sign and claim this quest!* 🏰"
        ),
        (
            f"🦉 *By Dumbledore's decree a hidden way stirs {dist} paces from your heart,\n"
            f"Its name a secret known to the keepers of the Wizarding art.\n"
            f"It carries the soul of '{clean}' — photograph its plaque and let the"
            f" magic start!* ⚡"
        ),
    ]
    return random.choice(templates)


async def _generate_riddle(street: str, dist: int) -> str:
    prompt = (
        f"You are the enchanted Marauder's Map from Harry Potter.\n"
        f"Write a beautifully poetic 2-3 line riddle for a wizard treasure hunter.\n"
        f"Target street: '{street}', exactly {dist} meters ('{dist} paces') away.\n"
        f"Rules:\n"
        f"- Use magical imagery: wands, Hogwarts, cobblestones, enchanted parchment, Dumbledore\n"
        f"- Cleverly HINT at '{street}' WITHOUT spelling it out fully\n"
        f"- Mention '{dist} paces' somewhere\n"
        f"- Output ONLY the riddle verse, nothing else, no explanation"
    )
    for model_name in [None, "gemini-1.5-flash"]:
        model = gemma_model if model_name is None else (
            genai.GenerativeModel(model_name) if GOOGLE_API_KEY else None
        )
        if not model:
            continue
        try:
            resp = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.9, max_output_tokens=120
                ),
            )
            text = resp.text.strip()
            if text:
                return text
        except Exception as e:
            log.warning("Riddle generation failed (%s): %s", model_name or "gemma", e)
    return _fallback_riddle(street, dist)


# ── Endpoints ──────────────────────────────────────────────────────────
class QuestRequest(BaseModel):
    lat: float
    lng: float


@app.post("/api/generate-quests")
async def generate_quests(req: QuestRequest):
    """Generate 3 quest targets around the player's position with riddles."""
    bearings = [
        random.randint(10, 110),
        random.randint(130, 230),
        random.randint(250, 350),
    ]
    distances = [
        random.randint(100, 200),
        random.randint(200, 350),
        random.randint(300, 500),
    ]

    quests = []
    for i in range(3):
        tlat, tlng = offset_point(req.lat, req.lng, bearings[i], distances[i])
        street = await reverse_geocode(tlat, tlng)
        riddle = await _generate_riddle(street, distances[i])
        quests.append(
            {
                "id": i,
                "lat": tlat,
                "lng": tlng,
                "street": street,      # used for OCR verification only
                "riddle": riddle,
                "nominalDist": distances[i],
            }
        )
    return {"quests": quests}


@app.post("/api/verify-sign")
async def verify_sign(
    file: UploadFile = File(...),
    street: str = Form(...),
):
    """
    Receive a photo of a street sign.
    1. Run OCR via Gemini Vision (free, no extra packages needed on Vercel).
    2. Fuzzy-match extracted text against the target street name.
    Returns: { matched, ocr_text, street, confidence }
    """
    img_bytes = await file.read()
    ocr_text = ""

    # — Primary OCR: Gemini 1.5 Flash Vision (free tier) ——————————————
    if vision_model:
        try:
            b64 = base64.b64encode(img_bytes).decode()
            mime = file.content_type or "image/jpeg"
            resp = vision_model.generate_content(
                [
                    (
                        "Look at this photo of a street sign board. "
                        "Extract and output ONLY the street or road name text that appears on the sign. "
                        "Output just the name text, nothing else. "
                        "If no readable street name is visible output the word NONE."
                    ),
                    {"mime_type": mime, "data": b64},
                ]
            )
            ocr_text = resp.text.strip()
            log.info("OCR result: %r  |  target: %r", ocr_text, street)
        except Exception as e:
            log.warning("Vision OCR error: %s", e)

    # — Fallback OCR: pytesseract (install tesseract-ocr for local dev) —
    if not ocr_text or ocr_text.upper() == "NONE":
        try:
            import pytesseract
            from PIL import Image
            import io

            img = Image.open(io.BytesIO(img_bytes))
            ocr_text = pytesseract.image_to_string(img).strip()
        except ImportError:
            pass  # tesseract not installed — acceptable on Vercel
        except Exception as e:
            log.warning("pytesseract error: %s", e)

    if not ocr_text or ocr_text.upper() == "NONE":
        return {
            "matched": False,
            "ocr_text": "(could not read sign — try a clearer photo)",
            "street": street,
            "confidence": 0.0,
        }

    # — Fuzzy matching ————————————————————————————————————————————————
    stopwords = {
        "street", "road", "avenue", "lane", "drive", "way", "boulevard",
        "st", "rd", "ave", "ln", "dr", "blvd", "close", "court", "ct",
        "the", "a", "an",
    }

    def tokenize(s: str):
        return set(re.sub(r"[^a-z0-9 ]", "", s.lower()).split())

    ocr_tokens = tokenize(ocr_text)
    street_tokens = tokenize(street)
    key_tokens = street_tokens - stopwords or street_tokens

    overlap = len(ocr_tokens & key_tokens)
    word_score = overlap / max(len(key_tokens), 1)

    ocr_lower = ocr_text.lower()
    substr_match = any(w in ocr_lower for w in key_tokens if len(w) > 2)

    matched = word_score >= 0.5 or substr_match
    confidence = round(max(word_score, 0.85 if substr_match else 0.0), 2)

    return {
        "matched": matched,
        "ocr_text": ocr_text,
        "street": street,
        "confidence": confidence,
    }


@app.get("/api")
def healthcheck():
    return {
        "status": "ok",
        "models": {
            "gemma": gemma_model is not None,
            "vision_ocr": vision_model is not None,
        },
    }


# Vercel ASGI adapter
handler = Mangum(app, lifespan="off")
