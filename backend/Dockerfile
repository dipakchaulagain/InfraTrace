FROM python:3.12-slim

WORKDIR /app

# Install system deps needed by psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Default: run the API server. Override CMD for the scheduler container.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
