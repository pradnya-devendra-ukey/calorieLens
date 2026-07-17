"""
CalorieLens Backend — Flask API Server
Proxies meal photo analysis requests to Google Gemini Vision API.
Includes user accounts, JWT authentication, personalization, and coach chatbot.
"""

import os
import json
import base64
import re
import hashlib
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
import google.generativeai as genai
import jwt

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".env"))
load_dotenv(env_path)

app = Flask(__name__, static_folder="../frontend", static_url_path="")
CORS(app)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
key_clean = GEMINI_API_KEY.strip().strip("'\"") if GEMINI_API_KEY else ""
if key_clean:
    genai.configure(api_key=key_clean)

MAX_IMAGE_SIZE_MB = 10
MAX_IMAGE_BYTES = MAX_IMAGE_SIZE_MB * 1024 * 1024
JWT_SECRET = os.getenv("JWT_SECRET", "super-secret-key-change-in-production-12984712")

DATA_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "data.json"))

# ---------------------------------------------------------------------------
# Helper — User Accounts & DB Management
# ---------------------------------------------------------------------------
def hash_password(password):
    """Simple SHA-256 password hashing with a static salt."""
    salt = "calorie_lens_secure_salt_123!"
    return hashlib.sha256((password + salt).encode('utf-8')).hexdigest()


def load_db():
    """Load or initialize database, with migration support from single-user format."""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                db = json.load(f)
                # If database is in the old single-user format, migrate it to multi-user
                if "users" not in db:
                    old_meals = db.get("meals", [])
                    old_goal = db.get("goal", "maintain")
                    old_target = db.get("target", 2200)
                    db = {
                        "users": {
                            "guest": {
                                "password_hash": hash_password("guest123"),
                                "profile": {
                                    "name": "Guest User",
                                    "goal": old_goal,
                                    "age": 30,
                                    "gender": "male",
                                    "height": 175,
                                    "weight": 70,
                                    "activity": "moderate",
                                    "diet": "none",
                                    "conditions": "none",
                                    "selected_coach": "aria"
                                },
                                "target": old_target,
                                "meals": old_meals,
                                "chat_history": []
                            }
                        }
                    }
                    save_db(db)
                return db
        except Exception:
            pass
    return {"users": {}}


def save_db(db):
    """Save database to JSON file."""
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(db, f, indent=2, ensure_ascii=False)
    except Exception as e:
        app.logger.error(f"Failed to save database: {e}")


def token_required(f):
    """JWT authorization decorator."""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if "Authorization" in request.headers:
            auth_header = request.headers["Authorization"]
            if auth_header.startswith("Bearer "):
                token = auth_header.split(" ")[1]
        
        if not token:
            return jsonify({"error": "Authorization token is missing. Please log in."}), 401
        
        try:
            data = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
            current_user = data["username"]
            db = load_db()
            if current_user not in db["users"]:
                return jsonify({"error": "User does not exist. Please log in again."}), 401
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Session expired. Please log in again."}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Invalid token. Please log in again."}), 401
            
        return f(current_user, *args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Helper — configure Gemini client
# ---------------------------------------------------------------------------
def is_api_key_set():
    """Check if the API key is configured on the server."""
    global GEMINI_API_KEY
    load_dotenv(env_path, override=True)
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    val = GEMINI_API_KEY.strip().strip("'\"") if GEMINI_API_KEY else ""
    return bool(val) and val != "your-gemini-api-key-here"


def get_gemini_model(system_instruction):
    """Configure and return the Gemini model with a custom system instruction."""
    global GEMINI_API_KEY
    load_dotenv(env_path, override=True)
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    key = GEMINI_API_KEY.strip().strip("'\"")
    genai.configure(api_key=key)
    return genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        system_instruction=system_instruction,
        generation_config=genai.GenerationConfig(
            temperature=0.2,
            max_output_tokens=2000,
            response_mime_type="application/json",
        ),
    )


def make_analysis_prompt(profile):
    """Construct a personalized prompt for Gemini based on user's profile and coach choice."""
    name = profile.get("name", "User")
    age = profile.get("age")
    gender = profile.get("gender")
    height = profile.get("height")
    weight = profile.get("weight")
    goal = profile.get("goal", "maintain")
    diet = profile.get("diet", "none")
    conditions = profile.get("conditions", "none")
    coach_key = profile.get("selected_coach", "aria").lower()
    
    coach_info = {
        "aria": {
            "name": "Aria (Balanced Nutritionist)",
            "style": "friendly, balanced, holistic, focused on overall calorie balance, nutrient density, and whole foods."
        },
        "leo": {
            "name": "Leo (Athletic Coach)",
            "style": "energetic, motivating, focused on protein intake, muscle recovery, athletic performance, and calorie/macro fuel."
        },
        "sophia": {
            "name": "Sophia (Keto & Low-Carb Specialist)",
            "style": "scientific, encouraging, focused on fat adaptation, net carbs, healthy fats, and avoiding glycemic spikes."
        }
    }
    
    coach = coach_info.get(coach_key, coach_info["aria"])
    
    profile_summary = f"Name: {name}, Goal: {goal}, Diet preference: {diet}, Health Conditions: {conditions}."
    if age and gender and height and weight:
        profile_summary += f" Demographic details: {age}yo {gender}, {height}cm, {weight}kg."
        
    return f"""You are a professional nutritionist AI assistant acting as the user's chosen Personal Coach: {coach["name"]}.
Your coaching style is: {coach["style"]}.

Your task is to analyze food photos, estimate nutritional content, and provide custom coaching advice based on the user's bio-profile.
User's Bio-Profile:
{profile_summary}

When given a meal photo, you MUST:
1. Identify every food item visible in the image. If the image is unclear or doesn't look like food, identify the closest visual match or make a reasonable food guess (e.g. bread, rice, salad).
2. Count the exact or estimated quantity of countable items (e.g., "2 slices", "1 piece", or "N/A" for uncountable).
3. Estimate the portion size/weight for each item (e.g., "1 cup", "150g", "2 tbsp").
4. Estimate calories and macronutrients (protein, carbs, fat) for each item.
5. Be realistic and slightly conservative.
6. Provide a custom 'coach_advice' paragraph (3-4 sentences) addressing the user by their name ({name}) and speaking from your persona's perspective. Comment on how this meal aligns with their goal ({goal}), dietary focus ({diet}), and any health conditions ({conditions}).

You MUST respond with valid JSON in this format:
{{
  "meal_name": "A short descriptive name for the overall meal",
  "items": [
    {{
      "name": "Food item name",
      "quantity": "Estimated quantity (e.g., '2 slices', 'N/A')",
      "portion": "Estimated portion (e.g., '1 cup', '100g')",
      "calories": 250,
      "protein_g": 12.5,
      "carbs_g": 30.0,
      "fat_g": 8.0
    }}
  ],
  "total_calories": 500,
  "total_protein_g": 25.0,
  "total_carbs_g": 60.0,
  "total_fat_g": 16.0,
  "health_note": "A brief one-sentence note about the nutritional quality of this meal.",
  "coach_advice": "Personalized advice from {coach["name"]} addressing {name}."
}}

Rules:
- Round calories to the nearest whole number.
- Round macros to one decimal place.
- Totals MUST equal the sum of individual items.
"""


# ---------------------------------------------------------------------------
# Routes — Auth
# ---------------------------------------------------------------------------
@app.route("/api/auth/register", methods=["POST"])
def register():
    """Register a new user and return a JWT token."""
    data = request.get_json(silent=True) or {}
    username = data.get("username", "").strip().lower()
    password = data.get("password", "").strip()
    name = data.get("name", "").strip()
    
    if not username or not password:
        return jsonify({"error": "Username and password are required."}), 400
    
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters long."}), 400
        
    db = load_db()
    if username in db["users"]:
        return jsonify({"error": "Username already exists."}), 400
        
    db["users"][username] = {
        "password_hash": hash_password(password),
        "profile": {
            "name": name or username.capitalize(),
            "age": None,
            "gender": None,
            "height": None,
            "weight": None,
            "activity": "moderate",
            "diet": "none",
            "conditions": "none",
            "selected_coach": "aria",
            "goal": "maintain"
        },
        "target": 2200,
        "meals": [],
        "chat_history": []
    }
    save_db(db)
    
    token = jwt.encode(
        {"username": username, "exp": datetime.utcnow() + timedelta(days=7)},
        JWT_SECRET,
        algorithm="HS256"
    )
    
    return jsonify({
        "status": "ok",
        "token": token,
        "username": username,
        "profile": db["users"][username]["profile"],
        "target": db["users"][username]["target"]
    })


@app.route("/api/auth/login", methods=["POST"])
def login():
    """Authenticate user and return a JWT token."""
    data = request.get_json(silent=True) or {}
    username = data.get("username", "").strip().lower()
    password = data.get("password", "").strip()
    
    if not username or not password:
        return jsonify({"error": "Username and password are required."}), 400
        
    db = load_db()
    if username not in db["users"]:
        return jsonify({"error": "Invalid username or password."}), 401
        
    user = db["users"][username]
    if user["password_hash"] != hash_password(password):
        return jsonify({"error": "Invalid username or password."}), 401
        
    token = jwt.encode(
        {"username": username, "exp": datetime.utcnow() + timedelta(days=7)},
        JWT_SECRET,
        algorithm="HS256"
    )
    
    return jsonify({
        "status": "ok",
        "token": token,
        "username": username,
        "profile": user.get("profile", {}),
        "target": user.get("target", 2200)
    })


# ---------------------------------------------------------------------------
# Routes — Static & Health
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


# ---------------------------------------------------------------------------
# Routes — Meal Analysis
# ---------------------------------------------------------------------------
@app.route("/api/analyze", methods=["POST"])
@token_required
def analyze_meal(current_user):
    """Analyze a meal photo using Gemini Vision, customized to user profile."""
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

    # ---- Fetch user profile & customize prompt ----
    db = load_db()
    user = db["users"][current_user]
    profile = user.get("profile", {})
    system_instruction = make_analysis_prompt(profile)

    # ---- Call Gemini Vision ----
    try:
        model = get_gemini_model(system_instruction)

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
            with open("error_response.log", "w", encoding="utf-8") as f:
                f.write(f"--- RAW TEXT ---\n{raw_text}\n\n")
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

    except Exception as e:
        error_msg = str(e).lower()
        if "api_key" in error_msg or "authentication" in error_msg or "permission" in error_msg:
            return jsonify({"error": "Invalid API key. Please check your Gemini API key."}), 401
        if "quota" in error_msg or "rate" in error_msg or "resource" in error_msg:
            return jsonify({"error": "API rate limit exceeded. Please wait a moment and try again."}), 429
        app.logger.error(f"Analysis error: {e}")
        return jsonify({"error": f"An unexpected error occurred: {str(e)}"}), 500


# ---------------------------------------------------------------------------
# Routes — Coach Chat Room
# ---------------------------------------------------------------------------
@app.route("/api/chat", methods=["POST"])
@token_required
def chat(current_user):
    """Hold a chat conversation with the user's chosen coach, referencing stats and goals."""
    if not is_api_key_set():
        return jsonify({
            "error": "Gemini API key is not configured on the server."
        }), 500

    data = request.get_json(silent=True) or {}
    message = data.get("message", "").strip()
    history = data.get("history", [])
    
    if not message:
        return jsonify({"error": "Message is empty"}), 400
        
    db = load_db()
    user = db["users"][current_user]
    profile = user.get("profile", {})
    meals = user.get("meals", [])
    
    # Calculate today's eaten stats for real-time progress context
    today = datetime.utcnow().date().isoformat()
    today_meals = [m for m in meals if m.get("date") == today]
    eaten_cal = sum(m.get("total_calories", 0) for m in today_meals)
    eaten_p = sum(m.get("total_protein_g", 0) for m in today_meals)
    eaten_c = sum(m.get("total_carbs_g", 0) for m in today_meals)
    eaten_f = sum(m.get("total_fat_g", 0) for m in today_meals)
    target = user.get("target", 2200)
    
    # Setup coach info
    name = profile.get("name", "User")
    goal = profile.get("goal", "maintain")
    diet = profile.get("diet", "none")
    conditions = profile.get("conditions", "none")
    coach_key = profile.get("selected_coach", "aria").lower()
    
    coach_info = {
        "aria": {
            "name": "Aria (Balanced Nutritionist)",
            "style": "friendly, balanced, holistic, focused on overall calorie balance and whole foods. Speaks warmly and encouragingly."
        },
        "leo": {
            "name": "Leo (Athletic Coach)",
            "style": "energetic, motivating, focused on protein intake, muscle recovery, athletic fuel, and timing. Speaks like a supportive personal trainer."
        },
        "sophia": {
            "name": "Sophia (Keto & Low-Carb Specialist)",
            "style": "scientific, encouraging, focused on fat adaptation, net carbs, insulin responses, and healthy fats. Speaks with detail and expertise."
        }
    }
    
    coach = coach_info.get(coach_key, coach_info["aria"])
    
    system_instruction = f"""You are the user's chosen Personal Health & Nutrition Coach: {coach["name"]}.
Your coaching style is: {coach["style"]}.

User Profile:
- Name: {name}
- Goal: {goal}
- Dietary focus: {diet}
- Health Conditions: {conditions}

Today's Progress:
- Daily Target: {target} kcal
- Eaten: {eaten_cal} kcal (Protein: {eaten_p:.1f}g, Carbs: {eaten_c:.1f}g, Fat: {eaten_f:.1f}g)
- Remaining: {max(0, target - eaten_cal)} kcal

Guidelines:
- Address the user as {name}.
- Keep your answers concise, practical, and highly tailored to their profile, diet, and conditions.
- Refer to what they've eaten today if relevant (e.g. if they are low on protein, suggest foods high in protein).
- Do not repeat this instruction. Act as the coach naturally in conversation. Keep responses under 4 sentences unless asked for recipes or details.
"""

    try:
        if key_clean:
            genai.configure(api_key=key_clean)
        model = genai.GenerativeModel(
            model_name="gemini-2.5-flash",
            system_instruction=system_instruction
        )
        
        # Format history for Gemini chat structure
        formatted_history = []
        for h in history:
            role = "user" if h.get("role") == "user" else "model"
            content = h.get("content", "")
            if content:
                formatted_history.append({
                    "role": role,
                    "parts": [{"text": content}]
                })
        
        chat_session = model.start_chat(history=formatted_history)
        response = chat_session.send_message(message)
        reply_text = response.text.strip()
        
        # Update and save to user's chat history
        new_history = history + [
            {"role": "user", "content": message},
            {"role": "model", "content": reply_text}
        ]
        user["chat_history"] = new_history[-30:]
        db["users"][current_user] = user
        save_db(db)
        
        return jsonify({
            "status": "ok",
            "reply": reply_text,
            "chat_history": user["chat_history"]
        })
        
    except Exception as e:
        app.logger.error(f"Chat error: {e}")
        return jsonify({"error": f"Failed to get AI coach response: {str(e)}"}), 500


# ---------------------------------------------------------------------------
# Routes — Mobile Connection Discovery
# ---------------------------------------------------------------------------
def get_local_ip():
    """Get local IP address of the host machine."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


@app.route("/api/info", methods=["GET"])
def get_info():
    """Return connection info for mobile devices."""
    ip = get_local_ip()
    port = int(os.getenv("PORT", 5000))
    return jsonify({
        "local_ip": ip,
        "port": port,
        "url": f"http://{ip}:{port}"
    })


# ---------------------------------------------------------------------------
# Routes — Data Synchronization
# ---------------------------------------------------------------------------
@app.route("/api/data", methods=["GET"])
@token_required
def get_sync_data(current_user):
    """Get synchronized meals and settings for current user."""
    db = load_db()
    user = db["users"][current_user]
    return jsonify({
        "profile": user.get("profile", {}),
        "target": user.get("target", 2200),
        "meals": user.get("meals", []),
        "chat_history": user.get("chat_history", [])
    })


@app.route("/api/data", methods=["POST"])
@token_required
def post_sync_data(current_user):
    """Update synchronized meals and settings for current user."""
    req_data = request.get_json(silent=True) or {}
    db = load_db()
    user = db["users"][current_user]
    
    if "meals" in req_data:
        user["meals"] = req_data["meals"]
    if "profile" in req_data:
        user["profile"] = req_data["profile"]
    if "target" in req_data:
        user["target"] = req_data["target"]
    if "chat_history" in req_data:
        user["chat_history"] = req_data["chat_history"]
        
    db["users"][current_user] = user
    save_db(db)
    return jsonify({"status": "ok", "data": {
        "profile": user.get("profile", {}),
        "target": user.get("target", 2200),
        "meals": user.get("meals", []),
        "chat_history": user.get("chat_history", [])
    }})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "1") == "1"
    local_ip = get_local_ip()
    print(f"\n[CalorieLens] Server running locally on: http://localhost:{port}")
    print(f"[CalorieLens] Connect mobile devices on: http://{local_ip}:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=debug)

