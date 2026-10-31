# Agnostos CLI image.
#   docker build -t agnostos .
#   docker run --rm -it --env-file .env -v "$PWD/data:/data" agnostos stats
# Mount a folder at /data holding your .env, resume and workbook; all output
# (drafts, logs, send history) is written to /data/output so it survives.
FROM python:3.12-slim AS build
WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY outreach ./outreach
RUN pip wheel --no-cache-dir --wheel-dir /wheels ".[calendar]"

FROM python:3.12-slim
LABEL org.opencontainers.image.title="Agnostos" \
      org.opencontainers.image.description="Resume-driven academic outreach CLI" \
      org.opencontainers.image.source="https://github.com/Avinashistoocool/Agnostos-v2" \
      org.opencontainers.image.licenses="MIT"
ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    OUTPUT_DIR=/data/output
COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels \
 && useradd --create-home --uid 1000 agnostos \
 && mkdir -p /data/output && chown -R agnostos /data
USER agnostos
WORKDIR /data
ENTRYPOINT ["agnostos"]
CMD ["--help"]
