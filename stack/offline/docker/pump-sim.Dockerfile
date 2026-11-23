# Offline build of stack/plant-sim/Dockerfile.sim (keep the two in sync): Python packages come only from the
# vendored, hash-locked wheels in the build context. Built by bundle.sh with --network none.
ARG BASE=docker.io/library/python:3.11-slim-bookworm
FROM ${BASE} AS deps
COPY wheels /wheels
COPY requirements.lock.txt /wheels/
RUN pip install --no-cache-dir --no-index --find-links /wheels --require-hashes --prefix /install \
      -r /wheels/requirements.lock.txt

FROM ${BASE}
COPY --from=deps /install /usr/local
COPY pump_set_opcua_sim.py /app/
USER nobody
EXPOSE 4840
CMD ["python", "-u", "/app/pump_set_opcua_sim.py"]
