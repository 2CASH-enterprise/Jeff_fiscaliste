FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --create-home jeff \
    && mkdir -p /data/documents \
    && chown jeff:jeff /data/documents
USER jeff

# Lot 17 : derrière nginx, l'adresse réelle du visiteur et le https viennent des en-têtes du proxy.
# Le port n'est publié que sur 127.0.0.1 : seuls nginx et le tunnel SSH peuvent les poser.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
