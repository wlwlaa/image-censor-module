# Demo Scenarios

| Scenario | Input | Expected result |
|---|---|---|
| Safe generation | Prompt `draw a safe corporate illustration` | `ALLOW`, passport, verified download |
| Prompt rule | Prompt containing `fake passport` | `BLOCK` before generation |
| Suspicious bypass | Prompt containing `ignore safety` | `REVIEW`, no release |
| Input PII | Image uploaded as `passport.png` | `BLOCK` before generation |
| Unsafe supplied output | Generated image uploaded as `unsafe-violence.png` | Quarantine then `BLOCK`, no release |
| Detector failure | Generated image uploaded as `detector_error.png` | Fail-closed `BLOCK` |
| TOCTOU attempt | Modify released bytes after `ALLOW` | Download returns HTTP `409` |

