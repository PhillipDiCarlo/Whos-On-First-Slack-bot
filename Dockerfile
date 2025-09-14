FROM python:3.12-slim

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-client && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY app/app.py /app/app.py
COPY inventory.yml /app/inventory.yml

# SSH key provided via docker secret/volume; set expected path via ENV
ENV INVENTORY_PATH=/config/inventory.yml
ENV SSH_KEY_PATH=/run/secrets/ssh_key
ENV PANEL_STATE_PATH=/data/panel.json

# Ensure data dir exists (will be mounted in compose)
RUN mkdir -p /data
RUN mkdir -p /config

CMD ["python", "-u", "app.py"]
