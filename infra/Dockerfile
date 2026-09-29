FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# psycopg2-binary ашигладаг тул gcc/libpq-dev (apt) хэрэггүй.
# pip-ийн cache mount: requirements.txt өөрчлөгдсөн ч өмнө татсан сангууд дахин татагдахгүй.
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

COPY . .

EXPOSE 8000
