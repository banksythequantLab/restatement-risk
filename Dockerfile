# Web app / orchestrator. Holds the inference key (env_file), NOT the docker socket.
FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY rr ./rr
COPY app ./app
COPY data ./data
ENV RR_ROOT=/var/lib/rr RR_CACHE=/var/lib/rr/cache PYTHONUNBUFFERED=1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
