# The tool server. Small on purpose: it answers Vapi during a live call and does nothing
# else — no workers, no schedulers, no third-party clients (invariant I1).
FROM python:3.12-slim

WORKDIR /app
RUN pip install --no-cache-dir uv

COPY pyproject.toml README.md ./
COPY src ./src
RUN uv pip install --system --no-cache .

COPY platform/postgres/migrations ./platform/postgres/migrations

EXPOSE 8080
# One worker: a single tenant at ~45 calls/day does not need more, and more workers would
# each hold their own rate-limit and breaker state.
CMD ["uvicorn", "grace_api.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
