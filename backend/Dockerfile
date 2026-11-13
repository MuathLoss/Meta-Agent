FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
COPY requirements.txt .
# The pip bundled with the base image has known security issues; replace it first.
RUN pip install --no-cache-dir --upgrade pip==26.3 \
    && pip install --no-cache-dir -r requirements.txt
COPY . .
# Run as an unprivileged user. Only the uploads folder is writable.
RUN useradd --system --uid 10001 --user-group --home-dir /app --shell /usr/sbin/nologin app \
    && mkdir -p /app/uploads \
    && chown -R app:app /app/uploads
USER app
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
