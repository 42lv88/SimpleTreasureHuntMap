# 🗺️ Street Hunt: Offline AI Edition

A GPS-based mobile web game where you explore the real world to find dynamically generated street quests. This version is completely **free and offline-first**, powered by a local FastAPI backend using **Ollama (Gemma)** to generate Harry Potter-style riddles, and **Tesseract OCR** to verify the photos you take of street signs!

---

## 🏗️ Architecture

- **Frontend**: Svelte + Vite + Leaflet (Map)
- **Backend**: Python + FastAPI
- **AI Riddles**: Local [Ollama](https://ollama.com/) running a Gemma model
- **Sign Verification**: Local [Tesseract OCR](https://github.com/tesseract-ocr/tesseract)

---

## 📋 Prerequisites

Before running the app, ensure you have the following installed on your Linux machine:

1. **Node.js & npm** (for the frontend)
2. **Python 3.10+** (for the backend)
3. **Tesseract OCR** (System library for reading images)
   - *Fedora:* `sudo dnf install tesseract`
   - *Ubuntu/Debian:* `sudo apt-get install tesseract-ocr`
4. **Ollama** (for local AI)
   - Install from [ollama.com](https://ollama.com/)
   - Pull the model: `ollama run gemma:2b` (or `gemma:3b`)

---

## 🚀 How to Run the Game (Local Network)

To play the game on your phone, both your computer and your phone must be connected to the **same Wi-Fi network**. You will run two terminals on your computer: one for the backend, one for the frontend.

### Step 1: Start the Backend (Terminal 1)
This starts the Python server that handles the AI generation and OCR processing.

```bash
cd backend

# Create and activate a virtual environment (Recommended, especially on Fedora)
python3 -m venv venv
source venv/bin/activate

# Install the Python dependencies
pip install -r requirements.txt

# Start the server exposed to your local network
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```
*(Leave this terminal open and running)*

### Step 2: Start the Frontend (Terminal 2)
This hosts the Svelte game UI so your phone can access it.

```bash
cd frontend

# Install dependencies (only needed the first time)
npm install

# Start the development server and expose it to the network
npm run dev -- --host
```
In the terminal output, look for the **Network** URL. It will look something like this:
`➜  Network: http://192.168.X.X:5173/`

### Step 3: Play on your Phone!

1. Open your smartphone's web browser (Safari/Chrome).
2. Go to the Network URL provided by the frontend step (e.g., `http://192.168.1.9:5173`).
3. The game will load and show a **"Wand Setup"** screen.
4. In the text box, type your backend's local network address: 
   👉 `http://192.168.X.X:8000` *(Replacing the X's with your computer's actual IP, the same one from step 2)*.
5. Click **Connect Server**.
6. Grant GPS/Location permissions when prompted, and start hunting!

---

## ⚙️ Configuration (Optional)

If your Ollama instance is running on a different port or machine, or if you are using a differently named model, you can configure the backend using environment variables before starting `uvicorn`:

```bash
export OLLAMA_URL="http://localhost:11434"
export OLLAMA_MODEL="gemma:2b"
```
