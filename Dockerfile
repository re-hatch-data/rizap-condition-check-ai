FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

ENV PYTHONUNBUFFERED=1

# Cloud Run Jobs はコンテナ起動 = ジョブ実行。1回走って終了する。
CMD ["python", "-m", "src.main"]
