# syntax=docker/dockerfile:1

FROM python:3.12-slim AS build
WORKDIR /src
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir .

FROM python:3.12-slim
WORKDIR /app
RUN useradd --system --create-home --uid 10001 chimp
COPY --from=build /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    CHIMP_CONFIG=/app/config.yaml \
    PYTHONUNBUFFERED=1
COPY config.docker.yaml /app/config.example.yaml
USER chimp
EXPOSE 8787
# Mount your real config at /app/config.yaml (see compose.yaml).
CMD ["chimp"]
