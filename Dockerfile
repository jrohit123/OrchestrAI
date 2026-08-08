FROM python:3.13-slim

# Install WeasyPrint system dependencies via apt
# These land in /usr/lib/... which cffi/dlopen can find
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libpangocairo-1.0-0 \
    libcairo2 \
    libfontconfig1 \
    libharfbuzz0b \
    fonts-noto \
    && ldconfig \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create non-root user
RUN useradd -m -u 1000 appuser
USER appuser

# Copy the entire project
COPY --chown=appuser:appuser . .

# Use PORT from environment (Railway sets this)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "${PORT}"]
