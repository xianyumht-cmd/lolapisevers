from __future__ import annotations

import base64
import hashlib
import io
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHUNK_ROOT = ROOT / ".deployment-package" / "full-bug-repair-20260801"
EXPECTED_SHA256 = "30266c26bc21b4600d7e2cf63a27978f486958fa7c1e65a11e19484587a54237"
ANCHOR = (
    '$ready = Invoke-JsonRequest -Uri "$BaseUrl/readyz"\n'
    'Assert-True ($ready.StatusCode -eq 200) "readyz failed."\n'
    'Add-Check "readyz" "pass" "HTTP 200"'
)


class V3ReadyzAnchorDiagnostic(unittest.TestCase):
    def test_print_reconstructed_readyz_anchor_facts(self) -> None:
        chunks = sorted(CHUNK_ROOT.glob("chunk-*.txt"))
        self.assertEqual(4, len(chunks))
        encoded = "".join(path.read_text(encoding="ascii").strip() for path in chunks)
        archive = base64.b64decode(encoded, validate=True)
        self.assertEqual(EXPECTED_SHA256, hashlib.sha256(archive).hexdigest())

        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            raw = bundle.read("ops/Verify-FullBugRepairProduction.ps1")
        text = raw.decode("utf-8-sig").replace("\r\n", "\n")
        indices: list[int] = []
        start = 0
        while True:
            index = text.find(ANCHOR, start)
            if index < 0:
                break
            indices.append(index)
            start = index + 1
        marker_indices: list[int] = []
        start = 0
        marker = '$BaseUrl/readyz'
        while True:
            index = text.find(marker, start)
            if index < 0:
                break
            marker_indices.append(index)
            start = index + 1
        contexts = [repr(text[max(0, i - 80): i + len(ANCHOR) + 80]) for i in marker_indices]
        self.fail(
            "RECONSTRUCTED_READYZ_FACTS="
            + repr(
                {
                    "anchor_count": len(indices),
                    "anchor_indices": indices,
                    "marker_count": len(marker_indices),
                    "marker_indices": marker_indices,
                    "anchor_repr": repr(ANCHOR),
                    "contexts": contexts,
                    "raw_has_crlf": b"\r\n" in raw,
                    "raw_has_lf": b"\n" in raw,
                }
            )
        )


if __name__ == "__main__":
    unittest.main()
