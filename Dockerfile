FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Logs and trades volumes
VOLUME ["/app/logs", "/app/trades"]

# Run
CMD ["python", "main.py"]
