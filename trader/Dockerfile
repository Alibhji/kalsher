FROM python:3.12-slim

WORKDIR /app

RUN useradd -m -u 1000 appuser

COPY trader/requirements.txt /app/trader/requirements.txt
RUN pip install --no-cache-dir -r /app/trader/requirements.txt

COPY common /app/common
COPY storage /app/storage
COPY trader /app/trader

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

USER appuser

WORKDIR /app/trader

EXPOSE 8091

CMD ["python", "-m", "app.main"]
