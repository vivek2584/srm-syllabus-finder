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

# Create syllabi directory
RUN mkdir -p syllabi

# All PDFs live in syllabi/ — downloaded from GitHub Releases at build time.
# computing is in v1.0.0; everything else is in v1.2.0 (including csbs).
ARG BASE=https://github.com/vivek2584/srm-syllabus-finder/releases/download

RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    curl -fSL -o syllabi/computing-programmes-syllabus-2021.pdf  "$BASE/v1.0.0/computing-programmes-syllabus-2021.pdf" || true && \
    curl -fSL -o syllabi/csbs-syllabus-2021.pdf                  "$BASE/v1.2.0/csbs-syllabus-2021.pdf" || true && \
    curl -fSL -o syllabi/aerospace-syllabus-2021.pdf                                        "$BASE/v1.2.0/aerospace-syllabus-2021.pdf" || true && \
    curl -fSL -o syllabi/automation-robotics-syllabus-2021.pdf                             "$BASE/v1.2.0/automation-robotics-syllabus-2021.pdf" || true && \
    curl -fSL -o syllabi/automobile-engineering-syllabus.pdf                               "$BASE/v1.2.0/automobile-engineering-syllabus.pdf" || true && \
    curl -fSL -o syllabi/automotive-electronics-syllabus.pdf                               "$BASE/v1.2.0/automotive-electronics-syllabus.pdf" || true && \
    curl -fSL -o syllabi/biomedical-engineering-syllabus.pdf                               "$BASE/v1.2.0/biomedical-engineering-syllabus.pdf" || true && \
    curl -fSL -o syllabi/biomedical-machine-intelligence-syllabus.pdf                      "$BASE/v1.2.0/biomedical-machine-intelligence-syllabus.pdf" || true && \
    curl -fSL -o syllabi/biotechnology-syllabus-2021.pdf                                   "$BASE/v1.2.0/biotechnology-syllabus-2021.pdf" || true && \
    curl -fSL -o syllabi/biotechnology-syllabus.pdf                                        "$BASE/v1.2.0/biotechnology-syllabus.pdf" || true && \
    curl -fSL -o syllabi/btech-materials-science-syllabus.pdf                              "$BASE/v1.2.0/btech-materials-science-syllabus.pdf" || true && \
    curl -fSL -o syllabi/btech-nanotechnology-syllabus.pdf                                 "$BASE/v1.2.0/btech-nanotechnology-syllabus.pdf" || true && \
    curl -fSL -o syllabi/chemical-engineering-syllabus-2021.pdf                            "$BASE/v1.2.0/chemical-engineering-syllabus-2021.pdf" || true && \
    curl -fSL -o syllabi/civil-engg-with-computer-applications-syllabus.pdf                "$BASE/v1.2.0/civil-engg-with-computer-applications-syllabus.pdf" || true && \
    curl -fSL -o syllabi/civil-engineering-syllabus.pdf                                    "$BASE/v1.2.0/civil-engineering-syllabus.pdf" || true && \
    curl -fSL -o syllabi/computational-biotechnology-syllabus.pdf                          "$BASE/v1.2.0/computational-biotechnology-syllabus.pdf" || true && \
    curl -fSL -o syllabi/ece-syllabus-2021.pdf                                             "$BASE/v1.2.0/ece-syllabus-2021.pdf" || true && \
    curl -fSL -o syllabi/electric-vehicle-technology-syllabus.pdf                          "$BASE/v1.2.0/electric-vehicle-technology-syllabus.pdf" || true && \
    curl -fSL -o syllabi/electrical-and-electronics-engineering-syllabus.pdf               "$BASE/v1.2.0/electrical-and-electronics-engineering-syllabus.pdf" || true && \
    curl -fSL -o syllabi/genetics-syllabus.pdf                                             "$BASE/v1.2.0/genetics-syllabus.pdf" || true && \
    curl -fSL -o syllabi/mechanical-engineering-automation-and-robotics-syllabus.pdf       "$BASE/v1.2.0/mechanical-engineering-automation-and-robotics-syllabus.pdf" || true && \
    curl -fSL -o syllabi/mechatronics-engineering-autonomous-driving-syllabus-.pdf         "$BASE/v1.2.0/mechatronics-engineering-autonomous-driving-syllabus-.pdf" || true && \
    curl -fSL -o syllabi/mechatronics-engineering-immersive-technologies-syllabus.pdf      "$BASE/v1.2.0/mechatronics-engineering-immersive-technologies-syllabus.pdf" || true && \
    curl -fSL -o syllabi/mechatronics-engineering-industrial-iot-and-systems-engineering-syllabus.pdf "$BASE/v1.2.0/mechatronics-engineering-industrial-iot-and-systems-engineering-syllabus.pdf" || true && \
    curl -fSL -o syllabi/mechatronics-syllabus.pdf                                         "$BASE/v1.2.0/mechatronics-syllabus.pdf" || true && \
    curl -fSL -o syllabi/regenerative-medicine-syllabus.pdf                                "$BASE/v1.2.0/regenerative-medicine-syllabus.pdf" || true && \
    curl -fSL -o syllabi/robotics-btech-syllabus.pdf                                       "$BASE/v1.2.0/robotics-btech-syllabus.pdf" || true && \
    curl -fSL -o syllabi/vehicle-testing-syllabus.pdf                                      "$BASE/v1.2.0/vehicle-testing-syllabus.pdf" || true && \
    apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

# Copy local syllabi/ if present (overrides downloads on local builds)
COPY syllabi syllabi/

# Build vector index at build time (no API key needed for this)
RUN python scripts/build_vectors.py

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
