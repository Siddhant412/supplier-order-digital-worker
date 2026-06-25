# Evaluation Scenarios

Initial vertical-slice scenarios:

| File | Expected Behavior |
| --- | --- |
| `sample-data/edi/exact-match.edi` | Automatically confirms and updates the mock ERP. |
| `sample-data/edi/risky-change.edi` | Pauses for approval because quantity, price, date, and stockout risk exceed policy. |
| `sample-data/edi/unsupported-qualifier.edi` | Routes to manual review because the date qualifier is unsupported by the partner profile. |
| `sample-data/edi/alternate-delimiters.edi` | Parses successfully by detecting delimiters from the envelope. |
