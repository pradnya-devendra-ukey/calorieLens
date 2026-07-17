FROM python:3.10-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PORT=7860

WORKDIR /app

# Install system dependencies if any are needed
# RUN apt-get update && apt-get install -y --no-install-recommends ...

# Install python dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source files
COPY backend ./backend
COPY frontend ./frontend

# Expose port 7860 for Hugging Face Spaces
EXPOSE 7860

# Run server with Gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:7860", "--workers", "2", "backend.server:app"]
