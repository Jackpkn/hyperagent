FROM node:22-bookworm-slim AS web
WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web/ ./
RUN npm run build

FROM python:3.13-slim-bookworm AS engine
WORKDIR /app
ENV PYTHONUNBUFFERED=1 HEADLESS=1 WEB_DIST=/app/web PLAYWRIGHT_BROWSERS_PATH=/opt/browsers
COPY pyproject.toml README.md LICENSE ./
COPY hyperagent/ ./hyperagent/
RUN pip install --no-cache-dir . && python -m playwright install --with-deps chromium
COPY --from=web /web/out /app/web
RUN useradd --create-home --uid 10001 hyperagent && chmod -R a+rX /opt/browsers \
    && mkdir -p /app/.hyperagent && chown hyperagent /app/.hyperagent
USER hyperagent
EXPOSE 8766
CMD ["hyperagent-server"]
