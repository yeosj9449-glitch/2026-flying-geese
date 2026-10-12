# 우리집 주식회사 웹앱 이미지. 저장소 루트에서: docker compose -f household_finance/deploy/docker-compose.yml build
ARG BASE=python:3.12-slim
FROM ${BASE}
# TZ=KST-9: 한국 시간 (zoneinfo 파일 없이도 동작하는 POSIX 표기). 날짜 계산(D-day, 월말 결산)이 한국 기준이 된다.
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 TZ=KST-9
WORKDIR /app
COPY requirements.txt requirements-web.txt ./
RUN pip install -r requirements-web.txt
COPY household_finance ./household_finance
RUN useradd --create-home --uid 1000 app && mkdir -p /data && chown app /data
USER app
VOLUME /data
EXPOSE 8000
CMD ["python", "-m", "household_finance", "serve", "--db", "/data/우리집.db", "--host", "0.0.0.0", "--port", "8000", "--https"]
