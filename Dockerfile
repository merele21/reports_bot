ARG PYTHON_VERSION=3.11
FROM python:${PYTHON_VERSION}-slim

# metadata
LABEL maintainer="your_mail@exmpl.com"
LABEL description="Report Bot - Local Image"

# args image
ARG DEBIAN_FRONTEND=noninteractive

# install packages
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    git \
    curl \
    sqlite3 \
    # debug
    vim \
    nano \
    htop \
    netcat-openbsd \
    procps \
    # images
    libjpeg-dev \
    libpng-dev \
    && rm -rf /var/lib/apt/lists/*

# create work dir
WORKDIR /app

# copy requirements
COPY requirements.txt requirements-local.txt ./

# install python packages
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir -r requirements-local.txt && \
    # additional dev tools
    pip install --no-cache-dir \
        debugpy \
        watchdog \
        ipython \
        rich \
        httpie

# make dirs
RUN mkdir -p /app/data /app/logs

# copy code
COPY bot ./bot
COPY migrate_db.py ./

# variables environment
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    LOG_LEVEL=DEBUG \
    ENVIRONMENT=local

# ports
EXPOSE 8000 5678

# healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import sys; sys.exit(0)" || exit 1

# start with debugpy
CMD ["python", "-m", "debugpy", "--listen", "0.0.0.0:5678", "--wait-for-client", "-m", "bot.main"]