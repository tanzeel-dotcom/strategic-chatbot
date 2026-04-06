FROM python:3.11-slim

# System deps (ffmpeg only if your app truly needs it)
RUN apt-get update \
  && apt-get install -y --no-install-recommends ffmpeg \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
  && pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

RUN chmod +x /app/start.sh

# Railway sets PORT; start.sh avoids Railway UI eating ${PORT} in custom commands
CMD ["/app/start.sh"]
