FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr poppler-utils && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# /data is the persistent disk. On first start it is filled from the copy shipped in the image.
ENV EVAL_DATA_DIR=/data
EXPOSE 8501 8000
CMD ["sh", "deploy/start.sh"]
