FROM python:3.12-slim
WORKDIR /app
COPY services/plugin/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && \
    useradd --uid 1000 --create-home plugin && mkdir -p /app/data/plugin && chown plugin:plugin /app/data/plugin
COPY services/plugin/*.py /app/services/plugin/
USER 1000:1000
ENV PLUGIN_BIND_HOST=0.0.0.0 PLUGIN_PORT=8787 PLUGIN_DATA_DIR=/app/data/plugin PYTHONDONTWRITEBYTECODE=1
EXPOSE 8787
CMD ["python", "-m", "services.plugin"]
