# Multi-stage Dockerfile for YouTube Summarizer
# ==============================================
# Chainguard distroless base for minimal attack surface

# Stage 1: Build dependencies in -dev variant (has pip)
FROM cgr.dev/chainguard/python:latest-dev AS builder

WORKDIR /app
USER root
RUN python -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: Summarizer service (distroless — no shell)
FROM cgr.dev/chainguard/python:latest AS summarizer

WORKDIR /app
COPY --from=builder /app/venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

COPY src/ ./src/
COPY process_videos.py .
COPY start_summarizer.py .

ENTRYPOINT ["python", "start_summarizer.py"]

# Stage 3: Web service (distroless — no shell)
FROM cgr.dev/chainguard/python:latest AS web

WORKDIR /app
COPY --from=builder /app/venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

COPY src/ ./src/
COPY main.py .
COPY process_videos.py .

EXPOSE 8000

ENTRYPOINT ["python", "main.py"]
