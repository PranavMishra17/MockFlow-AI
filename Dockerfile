# MockFlow-AI — container image for Fly.io (or any container host).
#
# Why a container and not a buildpack: the web process spawns agent_worker.py
# as a SUBPROCESS per interview (worker_manager.spawn_worker). That needs a real
# OS with a Python on PATH and room for N concurrent child processes — not a
# serverless/isolate runtime. See docs/DEPLOYMENT.md for why Cloudflare Workers
# cannot host this app.

FROM python:3.12-slim

# Silero VAD is ONNX-on-CPU inside each worker subprocess; onnxruntime wants
# libgomp. curl is here so the Fly health check / debugging can hit /health.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 curl \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /app

# Dependency layer first so app-code edits don't reinstall the (slow) wheels.
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

# Fail the BUILD, not the first interview, if the VAD model isn't importable.
# livekit-plugins-silero vendors silero_vad.onnx (~2.2 MB) inside the package,
# so there is no runtime model download and no network dependency at spawn time.
RUN python -c "import importlib.resources as r; \
p = r.files('livekit.plugins.silero') / 'resources' / 'silero_vad.onnx'; \
assert p.is_file(), 'silero_vad.onnx missing from image'; \
print('silero vad ok')"

EXPOSE 8080

# Mirrors the Procfile. gthread + 8 threads (NOT sync): a single sync worker got
# blocked for the 15-30 s verdict LLM call and adjacent /api/feedback/save and
# /api/user/insights requests 503'd. Keep --workers 1 — see docs/DEPLOYMENT.md
# ("Why this app pins to one machine"): active workers live in an in-process
# dict, so a second process/machine cannot see them.
CMD ["gunicorn", "app:app", \
     "--worker-class", "gthread", \
     "--workers", "1", \
     "--threads", "8", \
     "--timeout", "120", \
     "--graceful-timeout", "30", \
     "--access-logfile", "-", \
     "--bind", "0.0.0.0:8080"]
