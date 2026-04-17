#!/usr/bin/env bash
set -u

ports=(8080 8000 4000 1234)

echo "== Listener Check =="
(ss -ltnp 2>/dev/null || netstat -ltnp 2>/dev/null || true) | awk 'NR==1 || /:8080|:8000|:4000|:1234/'

echo
echo "== HTTP Probe Matrix =="
for p in "${ports[@]}"; do
  echo "-- Port $p --"

  for path in /v1/models /models /health /v1/chat/completions; do
    if [[ "$path" == "/v1/chat/completions" ]]; then
      body='{"model":"test","messages":[{"role":"user","content":"ping"}],"max_tokens":8}'
      out=$(curl -sS -m 4 -o /tmp/pantheon_probe.out -w "%{http_code}" -H "Content-Type: application/json" -d "$body" "http://127.0.0.1:${p}${path}" 2>/dev/null || true)
    else
      out=$(curl -sS -m 4 -o /tmp/pantheon_probe.out -w "%{http_code}" "http://127.0.0.1:${p}${path}" 2>/dev/null || true)
    fi

    if [[ -z "$out" ]]; then
      echo "  $path -> no response"
      continue
    fi

    preview=$(head -c 140 /tmp/pantheon_probe.out | tr '\n' ' ')
    echo "  $path -> HTTP $out | $preview"
  done
  echo
done

echo "Tip: if /v1/models fails but /models works, use the correct base URL/path in .env"
