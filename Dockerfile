FROM python:3.10-slim

# Install system dependencies and Google Chrome
RUN apt-get update && apt-get install -y \
    wget \
    curl \
    unzip \
    --no-install-recommends \
    && wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && apt-get install -y ./google-chrome-stable_current_amd64.deb \
    && rm google-chrome-stable_current_amd64.deb \
    && rm -rf /var/lib/apt/lists/*

# Set display port to prevent crash
ENV DISPLAY=:99
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the source code
COPY . .

# Ensure directories exist
RUN mkdir -p menus restaurants

# Run list_expander.py by default
CMD ["python", "list_expander.py"]
