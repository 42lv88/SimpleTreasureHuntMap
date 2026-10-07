"""
Treasure Hunt API — Vercel Python Serverless Function.
Runs as /api/* handler. Calls Gemma 2B via Google AI Studio (free, no card).

Get your free API key at https://aistudio.google.com/
Set it as GOOGLE_API_KEY in Vercel project environment variables.
"""
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import google.generativeai as genai
from mangum import Mangum

GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")

if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)
    gemma_model = genai.GenerativeModel("gemma-2-2b-it")
else:
    gemma_model = None

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class RiddleRequest(BaseModel):
    street: str
    distance: int


@app.post("/api/generate-riddle")
async def generate_riddle(req: RiddleRequest) -> dict:
    if not gemma_model:
        return {
            "riddle": f"I lie {req.distance} meters from your feet, a hidden street. 🗺️ Find my sign to complete the feat!"
        }
    prompt = (
        f"Write a fun, short riddle (2–3 lines, under 40 words) about a street named '{req.street}'. "
        f"The player is {req.distance} meters away. "
        f"Do NOT reveal the street name. Make it feel like a Pokémon GO adventure clue. "
        f"Output only the riddle text."
    )
    try:
        response = gemma_model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.85,
                max_output_tokens=80,
            ),
        )
        return {"riddle": response.text.strip()}
    except Exception as exc:
        return {"riddle": f"A path {req.distance}m away whispers your name. 🗺️ Seek the sign to win the game!"}


@app.get("/api")
def healthcheck() -> dict:
    return {
        "status": "ok",
        "model": "gemma-2-2b-it (Google AI Studio)",
        "api_configured": gemma_model is not None,
    }


# Vercel ASGI handler
handler = Mangum(app, lifespan="off")
