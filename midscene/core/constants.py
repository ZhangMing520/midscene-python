"""Build-time constants (upstream core/src/constants.ts).

The upstream Report Viewer build replaces the __MIDSCENE_REPORT_BUILD__ flag
with true; the Python SDK has no separate report build, so the value is fixed.
"""

IS_REPORT_BUILD = False
