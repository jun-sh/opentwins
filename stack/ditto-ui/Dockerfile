# eclipse/ditto-ui 3.9.9 is the newest upstream release (2026-11); all of its Critical/High CVEs are in Alpine
# OS packages (curl, openssl, expat, ...), not in the UI. Same UI files, OS packages upgraded at build time.
# Drop this image once upstream ships a release on a patched base. Pinned base digest: offline/images.lock.
ARG BASE=docker.io/eclipse/ditto-ui:3.9.9
FROM ${BASE}
USER root
RUN apk upgrade --no-cache
USER 101
