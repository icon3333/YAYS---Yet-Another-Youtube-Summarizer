# Multi-stage Dockerfile for YouTube Summarizer
# ==============================================
# Chainguard distroless base for minimal attack surface

# Keep the matched Python 3.14 builder/runtime pair from the passing container CI.
# Moving latest tags can advance Python before our dependencies support it.
# Stage 1: Build dependencies in -dev variant (has pip)
FROM cgr.dev/chainguard/python:latest-dev@sha256:de669347e9c1348d3fb952b1ab93738412bd7207769a882701691825741bfce3 AS builder

WORKDIR /app
USER root
RUN python -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip==26.2.2
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: Summarizer service (distroless — no shell)
FROM cgr.dev/chainguard/python:latest@sha256:1f37785e5cdb70151f36aaa15e1e3cef4571424dbefbf4b0d8a9222535cb13ff AS summarizer

WORKDIR /app
COPY --from=builder /app/venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

COPY src/ ./src/
COPY process_videos.py .
COPY start_summarizer.py .

ENTRYPOINT ["python", "start_summarizer.py"]

# Stage 3: Web service (distroless — no shell)
FROM cgr.dev/chainguard/python:latest@sha256:1f37785e5cdb70151f36aaa15e1e3cef4571424dbefbf4b0d8a9222535cb13ff AS web

WORKDIR /app
COPY --from=builder /app/venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

COPY src/ ./src/
COPY main.py .
COPY process_videos.py .

EXPOSE 8000

ENTRYPOINT ["python", "main.py"]
