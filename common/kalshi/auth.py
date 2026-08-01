from __future__ import annotations

import base64
import time
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


class KalshiAuth:
    def __init__(self, key_id: str, private_key_path: str) -> None:
        self.key_id = key_id
        pem = Path(private_key_path).read_bytes()
        self._private_key = serialization.load_pem_private_key(pem, password=None)

    def sign(self, method: str, path: str) -> dict[str, str]:
        timestamp = str(int(time.time() * 1000))
        path_only = path.split("?")[0]
        message = f"{timestamp}{method.upper()}{path_only}".encode()
        signature = self._private_key.sign(
            message,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256(),
        )
        return {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode(),
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "Content-Type": "application/json",
        }

    def ws_headers(self, ws_path: str) -> dict[str, str]:
        headers = self.sign("GET", ws_path)
        headers.pop("Content-Type", None)
        return headers
