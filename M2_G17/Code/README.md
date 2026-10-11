# Code

## `src/repro_7997.py` — reproduction for gnuradio/gnuradio#7997
Requires GNU Radio 3.10.x with its Python bindings.

```bash
# macOS (conda):  conda create -n gr310 -c conda-forge gnuradio=3.10 -y && conda activate gr310
# Ubuntu 24.04:   sudo apt install gnuradio
python repro_7997.py 2>&1 | tee results.txt     # all cases, ~2 min (30 s timeout each)
python repro_7997.py stock_channel_eps1         # a single case
```

Each case runs in its own subprocess with a 30 s timeout and is reported as `OK`, `HANG`
(no completion) or `STALL` (running, but no data in the last 3 s).

| Case | What it tests |
|---|---|
| `stock_no_channel` | `ofdm_tx` → `ofdm_rx`, baseline |
| `stock_channel_eps1`, `stock_channel_eps1.0001` | with Channel Model, without/with timing offset |
| `stock_channel_tags_pass` | channel passes stream tags through |
| `stock_channel_same_key` | receiver uses the transmitter's tag key, channel blocks tags |
| `stock_nochan_same_key`, `stock_chan_tagspass_same_key` | receiver uses the transmitter's tag key and the tags reach it (expected STALL) |
| `custom_*` | custom `gr.basic_block` pilot inserter → IFFT → (channel) → FFT |
| `fragile_*` | deliberately broken block: waits for more input than its forecast declares |

## `pr_8231_options_docs.patch`
The exact change submitted upstream in PR #8231. Applies to GNU Radio `main`:
`git apply pr_8231_options_docs.patch`
