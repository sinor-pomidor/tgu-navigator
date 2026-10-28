# Образ приложения «ТГУ: Навигатор возможностей».
# Базовый образ: Python 3.11 (соответствует требованиям проекта).
FROM python:3.11-slim

# Не писать .pyc, логировать без буферизации stdout.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv/app

# Сначала зависимости — слой кэшируется отдельно от кода.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Код приложения и сид-каталог.
COPY app ./app
COPY seed ./seed
COPY frontend ./frontend

# Непривилегированный пользователь для запуска.
RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /srv/app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
