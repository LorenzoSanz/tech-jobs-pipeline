# jobpipe itself, for `jobpipe serve`: the form behind the dashboards' "Add a posting" link.
FROM python:3.13.1-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[db]" \
    && useradd --create-home --uid 1000 jobpipe
USER jobpipe
EXPOSE 8100
CMD ["jobpipe", "serve", "--host", "0.0.0.0", "--port", "8100"]
