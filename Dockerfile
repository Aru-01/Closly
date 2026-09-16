# Use official slim Python 3.12 image
FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# Install system dependencies needed for psycopg2, Pillow, and Channels
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    libjpeg-dev \
    zlib1g-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Create dedicated non-root user
RUN adduser --disabled-password --gecos "" appuser \
    && mkdir -p /app/media \
    && chown -R appuser:appuser /app

# Copy project code
COPY . /app/
RUN chown -R appuser:appuser /app

USER appuser

# Expose port 8000
EXPOSE 8000

# Default command runs Daphne ASGI server for HTTP & WebSockets
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "Config.asgi:application"]
