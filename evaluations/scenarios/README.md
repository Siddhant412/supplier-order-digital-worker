# Evaluation Scenarios

Scenario files are JSON contracts consumed by the backend evaluation runner.

Each scenario defines:

- Input EDI file.
- Expected workflow status.
- Expected policy decision.
- Expected validation status.
- Whether an ERP update should execute.
- Whether the workflow should be detected as a duplicate.
- Whether transient ERP lookup or notification retry behavior should be simulated.

The suite covers exact matches, policy-allowed small delivery delays, risky commercial changes, unsupported EDI qualifiers, unknown acknowledgment codes, missing profiles, alternate delimiter handling, duplicate replay, malformed input, supported and unsupported unit handling, currency changes, repeated ACK split quantities, unknown parts, part substitutions, temporary ERP lookup retry, and notification retry after ERP update.
