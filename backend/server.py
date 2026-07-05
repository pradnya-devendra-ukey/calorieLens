"""
CalorieLens Backend — Flask API Server
Proxies meal photo analysis requests to Google Gemini Vision API.
"""

import os
import json
import base64
import re
from datetime import datetime

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
import google.generativeai as genai

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
load_dotenv()

app = Flask(__name__, static_folder="../frontend", static_url_path="")
CORS(app)

# No rate limiting for local dev

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
MAX_IMAGE_SIZE_MB = 10
MAX_IMAGE_BYTES = MAX_IMAGE_SIZE_MB * 1024 * 1024



# ---------------------------------------------------------------------------
# System prompt for Gemini Vision
# ---------------------------------------------------------------------------
ANALYSIS_SYSTEM_PROMPT = """You are a professional nutritionist AI assistant. Your task is to analyze food photos and estimate nutritional content.

When given a meal photo, you MUST:
1. Identify every food item visible in the image. If the image is unclear or doesn't look like food, identify the closest visual match or make a reasonable food guess (e.g. bread, rice, salad).
2. Estimate the portion size for each item (use common measurements like cups, oz, pieces, slices, tablespoons).
3. Estimate calories and macronutrients for each item based on the portion size.
4. Be realistic and slightly conservative with calorie estimates.

You MUST respond with valid JSON in this format:
{
  "meal_name": "A short descriptive name for the overall meal",
  "items": [
    {
      "name": "Food item name",
      "portion": "Estimated portion (e.g., '1 cup', '2 slices', '150g')",
      "calories": 250,
      "protein_g": 12.5,
      "carbs_g": 30.0,
      "fat_g": 8.0
    }
  ],
  "total_calories": 500,
  "total_protein_g": 25.0,
  "total_carbs_g": 60.0,
  "total_fat_g": 16.0,
  "health_note": "A brief one-sentence note about the nutritional quality of this meal."
}

Rules:
- You must always return food items. If no food is clearly visible, do not return an empty array. Identify a fallback estimate of a generic meal (e.g. "Mixed meal") and estimate reasonable values.
- Round calories to the nearest whole number.
- Round macros to one decimal place.
- The totals MUST equal the sum of individual items.
"""

# ---------------------------------------------------------------------------
# Helper — configure Gemini client
# ---------------------------------------------------------------------------
def is_api_key_set():
    """Check if the API key is configured and not the default placeholder."""
    global GEMINI_API_KEY
    load_dotenv(override=True)
    load_dotenv('backend/.env', override=True)
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    val = GEMINI_API_KEY.strip().strip("'\"") if GEMINI_API_KEY else ""
    return bool(val) and val != "your-gemini-api-key-here"


def get_gemini_model():
    """Configure and return the Gemini model."""
    global GEMINI_API_KEY
    load_dotenv(override=True)
    load_dotenv('backend/.env', override=True)
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    key = GEMINI_API_KEY.strip().strip("'\"")
    genai.configure(api_key=key)
    return genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        system_instruction=ANALYSIS_SYSTEM_PROMPT,
        generation_config=genai.GenerationConfig(
            temperature=0.2,
            max_output_tokens=2000,
            response_mime_type="application/json",
        ),
    )

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def serve_index():
    """Serve the frontend."""
    return send_from_directory(app.static_folder, "index.html")


@app.route("/<path:path>")
def serve_static(path):
    """Serve static assets."""
    return send_from_directory(app.static_folder, path)


@app.route("/api/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "has_api_key": is_api_key_set(),
    })


@app.route("/api/set-key", methods=["POST"])
def set_api_key():
    """Allow the user to set their Gemini API key at runtime."""
    global GEMINI_API_KEY
    data = request.get_json(silent=True)
    if not data or not data.get("api_key", "").strip():
        return jsonify({"error": "No API key provided"}), 400

    key = data["api_key"].strip()

    # Basic validation — Gemini keys start with "AIza"
    if not key.startswith("AIza"):
        return jsonify({
            "error": "Invalid Gemini API key format. It should start with 'AIza...' — get one at https://aistudio.google.com/apikey"
        }), 400

    GEMINI_API_KEY = key
    return jsonify({"status": "ok", "message": "API key saved successfully"})


@app.route("/api/analyze", methods=["POST"])
def analyze_meal():
    """Analyze a meal photo using Gemini Vision."""
    global GEMINI_API_KEY

    # ---- Validate API key ----
    if not is_api_key_set():
        return jsonify({
            "error": "Gemini API key is not configured on the server. Please check the backend .env configuration."
        }), 500

    # ---- Parse request ----
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid request body"}), 400

    image_data = data.get("image", "")
    mime_type = data.get("mimeType", "image/jpeg")

    if not image_data:
        return jsonify({"error": "No image provided"}), 400

    # Strip data URL prefix if present
    if "," in image_data:
        image_data = image_data.split(",", 1)[1]

    # ---- Validate image size ----
    try:
        decoded = base64.b64decode(image_data)
        if len(decoded) > MAX_IMAGE_BYTES:
            return jsonify({
                "error": f"Image too large. Maximum size is {MAX_IMAGE_SIZE_MB}MB."
            }), 413
    except Exception:
        return jsonify({"error": "Invalid base64 image data"}), 400

    # ---- Call Gemini Vision ----
    try:
        model = get_gemini_model()

        # Build the image part for Gemini
        image_part = {
            "inline_data": {
                "mime_type": mime_type,
                "data": image_data,
            }
        }

        response = model.generate_content(
            [
                image_part,
                "Analyze this meal and estimate the calories and macronutrients for each food item. Return ONLY valid JSON.",
            ]
        )

        # ---- Parse Gemini's response ----
        raw_text = response.text.strip()
        print("RAW GEMINI RESPONSE:")
        print(raw_text)

        # Strategy 1: Try to extract JSON from markdown fences
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', raw_text)
        if json_match:
            raw_text = json_match.group(1).strip()

        # Strategy 2: If it doesn't start with '{', try to find a JSON object
        if not raw_text.startswith('{'):
            obj_match = re.search(r'\{[\s\S]*\}', raw_text)
            if obj_match:
                raw_text = obj_match.group(0)

        # Strategy 3: Remove trailing commas before closing braces/brackets
        raw_text = re.sub(r',\s*([}\]])', r'\1', raw_text)

        result = None
        try:
            result = json.loads(raw_text)
        except json.JSONDecodeError:
            # Strategy 4: Try to fix common JSON issues
            cleaned = raw_text.replace("'", '"')
            cleaned = re.sub(r'(\w+)\s*:', r'"\1":', cleaned)  # unquoted keys
            try:
                result = json.loads(cleaned)
            except json.JSONDecodeError:
                pass

        if result is None:
            app.logger.error(f"Failed to parse Gemini response: {raw_text[:500]}")
            return jsonify({
                "error": "Failed to parse AI response. Please try again with a clearer photo."
            }), 502

        # Validate structure
        if "items" not in result or not isinstance(result["items"], list):
            return jsonify({"error": "AI returned unexpected format. Please try again."}), 502

        return jsonify({
            "status": "ok",
            "analysis": result,
            "analyzed_at": datetime.utcnow().isoformat(),
        })

    except json.JSONDecodeError:
        return jsonify({
            "error": "Failed to parse AI response. Please try again with a clearer photo."
        }), 502
    except Exception as e:
        error_msg = str(e).lower()
        if "api_key" in error_msg or "authentication" in error_msg or "permission" in error_msg:
            return jsonify({"error": "Invalid API key. Please check your Gemini API key."}), 401
        if "quota" in error_msg or "rate" in error_msg or "resource" in error_msg:
            return jsonify({"error": "API rate limit exceeded. Please wait a moment and try again."}), 429
        app.logger.error(f"Analysis error: {e}")
        return jsonify({"error": f"An unexpected error occurred: {str(e)}"}), 500


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "1") == "1"
    print(f"\n[CalorieLens] Server running on http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=debug)
