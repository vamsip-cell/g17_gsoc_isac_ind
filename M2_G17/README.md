# M2_G17 — Milestone 2: GNU Radio contributions (GSoC category)

**Project:** G17 — Design and Implementation of an OFDM-Based Communication and Sensing Framework Using GNU Radio (individual)
**Category:** GSoC — open-source contribution to GNU Radio

## Contributions in this milestone

| # | Upstream item | Type | Status |
|---|---|---|---|
| 1 | [gnuradio/gnuradio#8231](https://github.com/gnuradio/gnuradio/pull/8231) — *grc: rewrite Options block documentation to match current parameters* (closes [#7064](https://github.com/gnuradio/gnuradio/issues/7064)) | Pull request | Open, awaiting review |
| 2 | [gnuradio/gnuradio#7997](https://github.com/gnuradio/gnuradio/issues/7997) — *Complete OFDM flowgraph freeze after inserting Channel block* | Issue investigation / reproduction | Findings posted on the issue |

### 1. PR #8231 (issue #7064)
The Options block documentation shown in GRC (`grc/core/blocks/options.py`) predated GRC's
workflow system. It described mode-specific parameters without saying which mode they apply to,
described *Window size* as controlling the GRC editor (it actually sets the Bokeh web page size),
left nine parameters undocumented, and had a truncated sentence. The PR rewrites the
documentation grouped by *Generate Options* mode, with Bokeh-only parameters marked. Each
description was checked against `grc/blocks/*.workflow.yml` and the code that uses the parameter.
The exact change is in `Code/pr_8231_options_docs.patch` (1 file, +37/−8).

### 2. Investigation of issue #7997
The issue reports that inserting a Channel Model into an OFDM TX/RX flowgraph freezes the whole
graph. `Code/src/repro_7997.py` runs a set of flowgraphs with a timeout each:

- Stock `ofdm_tx` → Channel Model → `ofdm_rx` (configured like `ofdm_loopback.grc`): **no freeze**,
  with and without the channel, including timing offset (epsilon ≠ 1).
- A custom `gr.basic_block` pilot inserter (`general_work()` + `consume_each()` on vector ports)
  → IFFT → Channel → FFT: **no freeze**.
- The same total-freeze symptom **was** reproduced in two channel-independent ways:
  1. `ofdm_rx` using the same length-tag key as `ofdm_tx` while TX tags reach it —
     `header_payload_demux` fails with `Buffer too small for min_noutput_items`, its thread stops,
     and backpressure stalls every upstream block.
  2. A `general_work()` block that waits for more input than its `forecast()` declares.

Results: `Results/repro_7997_results_ubuntu.txt` (Ubuntu 24.04, GNU Radio 3.10.9.2), plus macOS
screenshots of the GRC `ofdm_loopback` example.

## Contents

```
M2_G17/
├── README.md                          <- this file
├── Report/M2_G17_Report.pdf           <- M2 report
├── Video/README.md                    <- link to the walkthrough video
├── Code/
│   ├── README.md                      <- how to run / apply
│   ├── src/repro_7997.py              <- reproduction script for issue #7997
│   └── pr_8231_options_docs.patch     <- exact change submitted in PR #8231
├── Data/README.md                     <- no external dataset (simulation only)
└── Results/                           <- script output + screenshots of PR, issues, GRC runs
```

## Next planned contribution
The tag-key collision in finding 2.1 freezes the whole receiver with only a cryptic
`Buffer too small` error. A follow-up could document in `ofdm_rx` that the receiver's
length-tag key must differ from the transmitter's, or improve the error message — to be
proposed on the issue first. This leads into the main project goal: an OFDM sensing block that
attaches to GNU Radio's OFDM receiver and reuses the same frames for range-Doppler estimation.
