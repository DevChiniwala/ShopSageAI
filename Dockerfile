# ─── Stage 1: Builder ───────────────────────────────────────────────────
# Use python slim as the base for building wheels
FROM python:3.12-slim AS builder

# Prevent python from writing pyc files to disc
ENV PYTHONDONTWRITEBYTECODE=1
# Prevent python from buffering stdout and stderr
ENV PYTHONUNBUFFERED=1

WORKDIR /build

# Install build dependencies
# (gcc, python3-dev, etc. are needed for building packages like asyncpg, uvloop, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies into a wheelhouse
COPY requirements.txt .
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /build/wheels -r requirements.txt


# ─── Stage 2: Runner ────────────────────────────────────────────────────
# The final image, strictly for running the application
FROM python:3.12-slim AS runner

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Create a non-root user 'shopsage'
RUN addgroup --system shopsage && adduser --system --ingroup shopsage shopsage

WORKDIR /app

# Install runtime dependencies required for psycopg2/asyncpg
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy the built wheels from the builder stage
COPY --from=builder /build/wheels /wheels
COPY --from=builder /build/requirements.txt .

# Install packages using the built wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

# Copy the actual application source code
COPY ./shopsage /app/shopsage
COPY ./app.py /app/app.py
COPY ./gunicorn.conf.py /app/gunicorn.conf.py
COPY ./static /app/static
COPY ./templates /app/templates

# Ensure data directory exists and is writable by non-root user
RUN mkdir -p /app/data && chown -R shopsage:shopsage /app/data

# Switch to non-root user
USER shopsage

EXPOSE 8000

# Start Gunicorn with Uvicorn worker class using the config file
ENTRYPOINT ["gunicorn", "-c", "gunicorn.conf.py", "app:app"]
