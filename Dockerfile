FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# 系统依赖（chromadb 需要的）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY .env.example ./.env.example

# 数据目录（挂载卷）
RUN mkdir -p /app/data/uploads /app/data/chroma

EXPOSE 8001

# 生产用 uvicorn 单进程（embedding 模型常驻内存，多进程会重复加载）
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
