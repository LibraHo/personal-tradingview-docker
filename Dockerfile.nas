# This NAS already has the moomoo Python SDK in its local OpenD image.
# The default runs charts; the trade Compose overlay runs charts + TLS trading together.
FROM moomoo-opend:local
WORKDIR /srv/market
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN python3 -m pip install --no-cache-dir --index-url https://pypi.tuna.tsinghua.edu.cn/simple \
    fastapi==0.115.12 'uvicorn[standard]==0.34.2' tzdata==2026.1
COPY app/ ./app/
EXPOSE 8000 8443
ENTRYPOINT ["python3", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
