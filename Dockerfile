# Use a lightweight Python base image
FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set the working directory inside the container
WORKDIR /app

# Install system dependencies (if needed, e.g., for PDF processing)
RUN apt-get update && apt-get install -y \
    gcc \
    libpoppler-cpp-dev \
    && apt-get clean

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Expose a port (change if your app uses a different port)
EXPOSE 8000

# Run the app (adjust if you are not using FastAPI)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
