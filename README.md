---
title: CalorieLens
emoji: 🥗
colorFrom: green
colorTo: yellow
sdk: static
pinned: false
---

# 🥗 CalorieLens — AI-Powered Calorie Tracking

Upload a photo of your meal and get instant AI-powered calorie and nutrition analysis. Track your daily intake towards your weight loss, gain, or maintenance goals.

## Features

- 📸 **Snap & Analyze** — Upload or drag-and-drop a meal photo for instant AI analysis
- 🎯 **Goal Setting** — Choose your goal (lose/gain/maintain) and set a daily calorie target
- 📊 **Calorie Ring** — Beautiful animated SVG ring showing daily progress
- 🥩 **Macro Tracking** — Protein, carbs, and fat breakdown for every meal
- 📝 **Meal History** — Track all meals logged throughout the day
- 📱 **Responsive** — Works on desktop and mobile, supports camera capture
- 🔒 **Secure** — API keys stay on the server, never reach the browser

## Tech Stack

- **Frontend**: React 18 (via CDN), Vanilla CSS with glassmorphism design
- **Backend**: Python Flask with rate limiting
- **AI**: Google Gemini 2.0 Flash (Vision) for meal analysis
- **Storage**: localStorage for user preferences and meal history

## Quick Start

### 1. Clone and setup

```bash
cd Calories_count_app
```

### 2. Install Python dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 3. Set your Gemini API key

**Option A** — Create a `.env` file:
```bash
cp .env.example .env
# Edit .env and add your key: GEMINI_API_KEY=AIza...
```

**Option B** — Set it through the UI after starting the server.

### 4. Run the server

```bash
python server.py
```

Open **http://localhost:5000** in your browser.

## Getting a Gemini API Key

1. Go to [Google AI Studio](https://aistudio.google.com/apikey)
2. Click "Create API Key"
3. Copy the key (starts with `AIza...`)

The free tier includes generous usage limits for personal use.

## Project Structure

```
Calories_count_app/
├── frontend/
│   └── index.html          # Complete React frontend (single file)
├── backend/
│   ├── server.py            # Flask API server
│   ├── requirements.txt     # Python dependencies
│   ├── .env.example         # Environment template
│   └── .env                 # Your API key (not committed)
├── .gitignore
└── README.md
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Health check + API key status |
| POST | `/api/set-key` | Set Gemini API key at runtime |
| POST | `/api/analyze` | Analyze a meal photo |

## License

MIT
