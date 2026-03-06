FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY backend/ backend/
COPY frontend/ frontend/
COPY scripts/ scripts/
COPY data/syllabi.db data/syllabi.db

# Download source PDF from GitHub Release (needed for PDF slice downloads)
# Falls back to local copy if download fails (e.g. building locally with PDF in dir)
ARG PDF_URL=https://github.com/vivek2584/srm-syllabus-finder/releases/download/v1.0.0/computing-programmes-syllabus-2021.pdf
RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    curl -fSL -o computing-programmes-syllabus-2021.pdf "$PDF_URL" || true && \
    apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*
# Also copy local PDF if present (overrides download on local builds)
COPY computing-programmes-syllabus-2021.pd[f] ./

# Build vector index at build time (no API key needed for this)
RUN python scripts/build_vectors.py

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
