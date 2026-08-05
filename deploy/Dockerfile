# Shared image for the twin core and the publisher (they differ only by command).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install dependencies first for better layer caching.
COPY pyproject.toml README.md ./
COPY src ./src
COPY examples ./examples
# CSV dataset uploads (/api/validation/upload) work out of the box. Parsing .mat
# files (NASA / Oxford) is opt-in -- add the `validate` extra (pulls in SciPy) if
# you need it: pip install ".[server,connect,validate]".
RUN pip install --no-cache-dir ".[server,connect]"

EXPOSE 8000

CMD ["uvicorn", "celltwin.twincore.main:app", "--host", "0.0.0.0", "--port", "8000"]
