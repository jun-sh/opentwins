# Offline build of stack/phm/Dockerfile (keep the two in sync): same runtime layout, but Python packages come
# only from the vendored, hash-locked wheels in the build context. Built by bundle.sh with --network none.
ARG BASE=docker.io/library/python:3.11-slim-bookworm
FROM ${BASE} AS deps
COPY wheels /wheels
COPY requirements.lock.txt /wheels/
RUN pip install --no-cache-dir --no-index --find-links /wheels --require-hashes --prefix /install \
      -r /wheels/requirements.lock.txt

FROM ${BASE}
RUN useradd -r -u 10001 phm
COPY --from=deps /install /usr/local
COPY phm_worker.py thermal_model.py /app/
USER phm
WORKDIR /app
ENV PYTHONUNBUFFERED=1 MPLCONFIGDIR=/tmp
ENTRYPOINT ["python", "/app/phm_worker.py"]
