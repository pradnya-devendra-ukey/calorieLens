import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv('backend/.env')
key = os.getenv("GEMINI_API_KEY", "")
print("Using key:", key[:10] + "..." + key[-5:])

genai.configure(api_key=key)
model = genai.GenerativeModel(model_name="gemini-2.5-flash")

try:
    response = model.generate_content("Hello! Say test.")
    print("Response text:", response.text)
except Exception as e:
    print("Error:", e)
