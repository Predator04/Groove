FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py layout.html setup.html ./
COPY assets/ assets/

# Persistent config/data lives in /data (mount a volume here)
ENV GROOVE_DATA_DIR=/data
VOLUME /data

EXPOSE 8813

CMD ["python", "app.py"]
