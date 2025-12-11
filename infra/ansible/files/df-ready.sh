#!/usr/bin/env bash
set -euo pipefail

# Wait for DFHack RPC listener to be ready
for i in {1..120}; do
  if ss -lnt | grep -q "127.0.0.1:5000"; then
    echo "[df-ready] DFHack RPC listener detected on port 5000"
    break
  fi
  sleep 0.5
done

# Verify listener is actually up
if ! ss -lnt | grep -q "127.0.0.1:5000"; then
  echo "[df-ready] WARNING: Port 5000 not listening after 60s timeout"
  exit 0
fi

# Optional: Load region1 save if it exists
if [ -d /opt/dwarf-fortress/data/save/region1 ]; then
  echo "[df-ready] region1 save detected, attempting to load..."
  for i in {1..10}; do
    if /opt/dwarf-fortress/dfhack-run load-save region1 2>&1 | tee -a /opt/dwarf-fortress/dfhack-ready.log; then
      echo "[df-ready] region1 loaded successfully"
      break
    fi
    sleep 1
  done

  # Verify save path
  /opt/dwarf-fortress/dfhack-run lua -e 'print("savePath=", dfhack.getSavePath())' 2>&1 | tee -a /opt/dwarf-fortress/dfhack-ready.log || true
else
  echo "[df-ready] No region1 save found, skipping autoload"
fi

echo "[df-ready] Readiness check complete"
exit 0
