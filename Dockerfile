FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py layout.html setup.html ./
COPY assets/ assets/

# Persistent config/data lives in /data (mount a volume here)
ENV PRISMLUME_DATA_DIR=/data
VOLUME /data

EXPOSE 8813
EXPOSE 4001/udp 4002/udp 4003/udp

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8813/ping', timeout=3)" || exit 1

CMD ["python", "app.py"]
