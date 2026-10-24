Ticket: https://example.atlassian.net/browse/PAY-142
Spec: PAY-142

## Summary

The roster page gets an Export button that downloads the visible rows as CSV, with a header row and commas quoted.

## Acceptance criteria and how they were checked

- the export writes a header row: automated, `tests/test_export.py` › `test_export_writes_a_header_row`, run with `pytest tests/test_export.py`: passed
- commas inside a name are quoted: automated, `tests/test_export.py` › `test_commas_are_quoted`: passed
- the button shows only to coordinators: checked by hand, signed in as a coordinator and as a member: shown only to the coordinator

## Review

One adversarial pass on the diff, verdict CLEAN: one NOTE (the button's label could name the file type), fixed.
