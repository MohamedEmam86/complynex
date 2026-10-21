# ComplyNex application image (web, workers and scheduled jobs share it).
# For a client server the recommended path is deploy/install_server.sh (bare metal / VM);
# this image is for container platforms and evaluation set-ups.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/.cache/huggingface OMP_NUM_THREADS=1
RUN apt-get update && apt-get install -y --no-install-recommends \
      libpango-1.0-0 libpangoft2-1.0-0 libcairo2 libgl1 libglib2.0-0 libmagic1 curl \
    && rm -rf /var/lib/apt/lists/* && useradd --system --home /app complynex
WORKDIR /app
COPY requirements.txt .
RUN grep -E '^(torch|torchvision)==' requirements.txt | sed 's/+cpu//' > /tmp/torch.txt \
 && pip install -r /tmp/torch.txt --index-url https://download.pytorch.org/whl/cpu \
 && grep -vE '^(torch|torchvision)==' requirements.txt > /tmp/req.txt && pip install -r /tmp/req.txt \
 && python -c "from sentence_transformers import SentenceTransformer as S; S('paraphrase-multilingual-MiniLM-L12-v2')"
COPY . .
RUN mkdir -p logs uploads ekyc_storage && chown -R complynex:complynex /app
USER complynex
ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
EXPOSE 8000
CMD ["gunicorn", "-c", "gunicorn.conf.py", "--bind", "0.0.0.0:8000", "app:create_app()"]
