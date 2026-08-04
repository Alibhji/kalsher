#!/usr/bin/env bash
# One-shot: enable global Docker json-file log rotation (requires sudo).
set -euo pipefail
sudo python3 - <<'PY'
import json
from pathlib import Path
p = Path("/etc/docker/daemon.json")
data = json.loads(p.read_text()) if p.exists() else {}
data["log-driver"] = "json-file"
data["log-opts"] = {"max-size": "50m", "max-file": "3"}
p.write_text(json.dumps(data, indent=4) + "\n")
print(p.read_text())
PY
sudo systemctl restart docker
echo "docker restarted with log rotation enabled"
