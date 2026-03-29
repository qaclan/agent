FROM python:3.11-slim

WORKDIR /app

# Install system deps needed by Playwright
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 libgbm1 \
    libpango-1.0-0 libcairo2 libasound2 libxshmfence1 libx11-xcb1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    playwright install --with-deps chromium

COPY . .

EXPOSE 7823

CMD ["python", "qaclan.py", "serve", "--port", "7823", "--host", "0.0.0.0", "--no-browser"]
