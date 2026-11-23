#!/usr/bin/env bash
# CycloneDX SBOMs (Syft) and a vulnerability report (Grype) for local images. Online only for the Grype DB.
#   offline/sbom.sh <out dir> <image ref>...
# Output: images/<ref>.cdx.json (all packages), python/<ref>.python.cdx.json (Python packages only, for
# images that contain any), vulns/<ref>.grype.json, vuln-summary.md (counts per severity, DB build date).
set -euo pipefail
SYFT=docker.io/anchore/syft:v1.56.0@sha256:697ae864af1299cfa43c54b161cea3dd65c6d54de82e3dba66ea3dccb3acc313
GRYPE=docker.io/anchore/grype:v0.121.1@sha256:6b06708b036f74b2cd70e94b706b4586af96d1932e6ac46255940b2e39dd44a9
OUT=$(mkdir -p "$1" && cd "$1" && pwd); shift
CACHE=${SBOM_CACHE:-$(dirname "$0")/dist/.sbom-cache}; mkdir -p "$CACHE/tmp" "$CACHE/grype"; CACHE=$(cd "$CACHE" && pwd)
mkdir -p "$OUT/images" "$OUT/python" "$OUT/vulns"
safe() { echo "$1" | sed 's|^docker\.io/||; s|[/:@]|_|g'; }
tool() { # tool <image> <args...>: runs as the caller, with docker socket access, host network for proxies
  local img=$1; shift
  docker run --rm --network host --user "$(id -u):$(id -g)" --group-add "$(stat -c %g /var/run/docker.sock)" \
    -e HTTP_PROXY -e HTTPS_PROXY -e NO_PROXY -e TMPDIR=/cache/tmp -e GRYPE_DB_CACHE_DIR=/cache/grype \
    -e SYFT_CHECK_FOR_APP_UPDATE=false -e GRYPE_CHECK_FOR_APP_UPDATE=false \
    -v /var/run/docker.sock:/var/run/docker.sock -v "$OUT:/out" -v "$CACHE:/cache" "$img" "$@"
}

tool "$GRYPE" db update >&2
db_built=$(tool "$GRYPE" db status -o json 2>/dev/null | jq -r '.built // .Built // "unknown"')

for ref in "$@"; do
  n=$(safe "$ref")
  echo "[sbom] $ref" >&2
  tool "$SYFT" scan -q "docker:$ref" -o "cyclonedx-json=/out/images/$n.cdx.json"
  if jq -e '[.components[]? | select(.purl? // "" | startswith("pkg:pypi/"))] | length > 0' \
       "$OUT/images/$n.cdx.json" >/dev/null; then
    tool "$SYFT" scan -q "docker:$ref" --select-catalogers python -o "cyclonedx-json=/out/python/$n.python.cdx.json"
  fi
  tool "$GRYPE" -q "sbom:/out/images/$n.cdx.json" -o json --file "/out/vulns/$n.grype.json"
done

{ echo "# Vulnerability summary (Grype)"
  echo
  echo "Scanner: \`${GRYPE%@*}\`, vulnerability DB built $db_built, scanned $(date -u +%F). Counts are matches"
  echo "(package x vulnerability); *fixable* = Critical/High with a fixed version upstream. Full JSON: \`vulns/\`."
  echo
  echo "| Image | Critical | High | Medium | Low | Other | Fixable C/H |"
  echo "|---|---:|---:|---:|---:|---:|---:|"
  for ref in "$@"; do
    jq -r --arg ref "$ref" '[.matches[]] as $m
      | def c(s): [$m[] | select(.vulnerability.severity == s)] | length;
      "| `\($ref)` | \(c("Critical")) | \(c("High")) | \(c("Medium")) | \(c("Low")) | \(($m|length) - c("Critical") - c("High") - c("Medium") - c("Low")) | \([$m[] | select((.vulnerability.severity == "Critical" or .vulnerability.severity == "High") and .vulnerability.fix.state == "fixed")] | length) |"' \
      "$OUT/vulns/$(safe "$ref").grype.json"
  done; } > "$OUT/vuln-summary.md"
echo "[sbom] wrote $OUT" >&2
