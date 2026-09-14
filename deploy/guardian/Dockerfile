# Base indexes verified against registry-1.docker.io on 2026-09-12.
FROM node:24.21.0-bookworm-slim@sha256:2fe369e969550cde8e867afc3fe370b260140cab4a23d467074295b42163d553 AS frontend
WORKDIR /build
COPY apps/guardian/frontend/package.json apps/guardian/frontend/package-lock.json ./
RUN npm ci --include=dev
COPY apps/guardian/frontend/craco.config.js apps/guardian/frontend/jsconfig.json apps/guardian/frontend/postcss.config.js apps/guardian/frontend/tailwind.config.js ./
COPY apps/guardian/frontend/src ./src
COPY apps/guardian/frontend/public/index.html ./public/index.html
COPY apps/guardian/frontend/public/favicon.svg apps/guardian/frontend/public/favicon.ico apps/guardian/frontend/public/apple-touch-icon.png apps/guardian/frontend/public/manifest.json apps/guardian/frontend/public/HankenGrotesk-OFL.txt apps/guardian/frontend/public/IBMPlexMono-OFL.txt ./public/
ENV CI=true NODE_ENV=production REACT_APP_GUARDIAN_URL=/ GENERATE_SOURCEMAP=false \
    DISABLE_HOT_RELOAD=true REACT_APP_ENABLE_VISUAL_EDITS=false ENABLE_HEALTH_CHECK=false
RUN npm run build

FROM python:3.13.15-slim-bookworm@sha256:ed86c82274b3c69b52fb5820f358f0bd7df0b603332063cb5c6e32bd220c3e6e AS dependencies
WORKDIR /build
COPY apps/guardian/backend/requirements.txt apps/guardian/backend/requirements.constraints.txt ./
RUN python -m pip install --no-cache-dir --prefix=/install -r requirements.txt -c requirements.constraints.txt

FROM python:3.13.15-slim-bookworm@sha256:ed86c82274b3c69b52fb5820f358f0bd7df0b603332063cb5c6e32bd220c3e6e AS python_integration
WORKDIR /build
ENV SOURCE_DATE_EPOCH=1789257600 PYTHONHASHSEED=0
COPY packages/sillage-python/pyproject.toml packages/sillage-python/README.md ./
COPY packages/sillage-python/src ./src
RUN python -m pip wheel --no-cache-dir --no-deps --wheel-dir=/wheel .

FROM python:3.13.15-slim-bookworm@sha256:ed86c82274b3c69b52fb5820f358f0bd7df0b603332063cb5c6e32bd220c3e6e AS application
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHON_DOTENV_DISABLED=1 \
    GUARDIAN_STATIC_DIR=/opt/guardian/ui GUARDIAN_INTEGRATIONS_DIR=/opt/guardian/integrations GUARDIAN_BIND_HOST=0.0.0.0 GUARDIAN_PORT=8001
RUN groupadd --gid 10001 guardian && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin guardian
COPY --from=dependencies /install /usr/local
WORKDIR /opt/guardian/backend
COPY apps/guardian/backend/*.py ./
COPY apps/guardian/backend/api ./api
COPY apps/guardian/backend/capture ./capture
COPY apps/guardian/backend/deployment ./deployment
COPY apps/guardian/backend/guardian ./guardian
COPY apps/guardian/backend/identity ./identity
COPY apps/guardian/backend/notifications ./notifications
COPY apps/guardian/backend/policies ./policies
COPY examples/native-capture/guardian_capture.py examples/native-capture/guardian_exporter.py examples/native-capture/guardian_openai.py /opt/guardian/integrations/
COPY examples/native-capture/guardian_capture.mjs examples/native-capture/guardian_exporter.mjs examples/native-capture/guardian_openai.mjs /opt/guardian/integrations/
COPY --from=python_integration /wheel/sillage_observe-0.2.0-py3-none-any.whl /opt/guardian/integrations/
COPY --from=frontend /build/build /opt/guardian/ui
USER 10001:10001
EXPOSE 8001
ENTRYPOINT ["python", "-m", "deployment"]
CMD ["--help"]
