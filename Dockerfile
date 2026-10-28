FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY . .
ENV STATIC_ROOT=/srv/static
RUN python manage.py collectstatic --noinput
RUN useradd --create-home --uid 1000 app
USER app
EXPOSE 8000
CMD ["./entrypoint.sh"]
