"""Agentic Irrigation Workflow — objective: save water.

Phase 1 (this module): the data plumbing before any physical hardware —
stubbed sensor / rain-gauge reads (``hardware``), a real NWS forecast +
observations client (``weather``), the moisture-sensor map (``sensors``), and
a rainfall forecast-accuracy log (``forecast_log``). No HTTP routes yet; the
deliberation engine and the daily roll trigger land in Phase 2.
"""
