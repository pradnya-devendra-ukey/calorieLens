import os
import sys

# Ensure backend folder is in Python search path
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from backend.server import app

if __name__ == "__main__":
    # Hugging Face sets the PORT environment variable to 7860
    port = int(os.getenv("PORT", 7860))
    # Run the server
    app.run(host="0.0.0.0", port=port)
