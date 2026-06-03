FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY frontend/ ./frontend/

RUN mkdir -p /app/data
ENV AIRFARE_DB_PATH=/app/data/airfare.db

EXPOSE 8100

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8100"]
