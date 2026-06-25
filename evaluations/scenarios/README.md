# Evaluation Scenarios

Scenario files are JSON contracts consumed by the backend evaluation runner.

Each scenario defines:

- Input EDI file.
- Expected workflow status.
- Expected policy decision.
- Expected validation status.
- Whether an ERP update should execute.
- Whether the workflow should be detected as a duplicate.

The suite covers exact matches, policy-allowed small delivery delays, risky commercial changes, unsupported EDI qualifiers, and alternate delimiter handling.
