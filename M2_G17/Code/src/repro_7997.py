#!/usr/bin/env python3
"""
Reproduction attempt for gnuradio/gnuradio#7997:
"Complete OFDM Flowgraph Freeze After Inserting Channel Block".

Each case runs in its own subprocess with a 30 s timeout, so a hang is
detected instead of blocking the harness.

- stock_*  : GNU Radio's own ofdm_tx -> [Channel Model] -> ofdm_rx, configured like
             gr-digital's examples/ofdm/ofdm_loopback.grc. The OFDM receiver never
             signals "done", so each case runs for 6 s and reports how many packets
             were decoded correctly, and STALL if no data arrived in the last 3 s.
- custom_* : a hand-written gr.basic_block pilot inserter (general_work() +
             consume_each() on vector ports, as described in the issue) -> IFFT ->
             [Channel Model] -> FFT, with a finite source. OK if tb.run() returns.
- fragile_*: the same chain, but the pilot inserter waits for 1000 input vectors
             while its forecast() still declares 1:1 -- expected to HANG.

Usage:  python3 repro_7997.py            # run all cases
        python3 repro_7997.py <case>     # run one case in-process
"""
import subprocess
import sys
import time

import numpy as np

FFT_LEN = 64
CP_LEN = 16
N_DATA = 48          # data carriers fed to the custom pilot inserter
N_VECS = 2000        # OFDM symbols for the custom-chain cases
TIMEOUT_S = 30


# --------------------------------------------------------------------------
# Custom pilot inserter, written the way the issue describes:
# gr.basic_block, vector ports, general_work() + explicit consume_each(n).
# --------------------------------------------------------------------------
def make_pilot_inserter(chunk=1):
    from gnuradio import gr

    data_idx = np.r_[1:7, 8:21, 22:27, 38:43, 44:57, 58:64]   # 48 carriers
    pilot_idx = np.array([7, 21, 43, 57])
    assert len(data_idx) == N_DATA

    class pilot_inserter(gr.basic_block):
        """Maps N_DATA-carrier vectors onto FFT_LEN vectors with 4 pilots.

        chunk=1  -> well-behaved: process whatever is available.
        chunk>1  -> deliberately fragile: refuses to work until `chunk`
                    input vectors are available, but keeps the default 1:1
                    forecast, so the scheduler is never told it needs more.
        """

        def __init__(self):
            gr.basic_block.__init__(
                self, name="pilot_inserter",
                in_sig=[(np.complex64, N_DATA)],
                out_sig=[(np.complex64, FFT_LEN)])

        def general_work(self, input_items, output_items):
            inp, out = input_items[0], output_items[0]
            n = min(len(inp), len(out))
            if chunk > 1:
                if n < chunk:
                    return 0          # wait for more, consume nothing
                n -= n % chunk
            frame = np.zeros((n, FFT_LEN), dtype=np.complex64)
            frame[:, data_idx] = inp[:n]
            frame[:, pilot_idx] = 1.0
            out[:n] = frame
            self.consume_each(n)
            return n

    return pilot_inserter()


def make_channel(eps):
    from gnuradio import channels
    return channels.channel_model(
        noise_voltage=0.01, frequency_offset=0.0, epsilon=eps,
        taps=[1.0 + 0j], noise_seed=0, block_tags=False)


# --------------------------------------------------------------------------
# Case 1: stock ofdm_tx -> [channel] -> ofdm_rx
# --------------------------------------------------------------------------
def run_stock(channel, eps=1.0, block_tags=True, rx_key="rx_len"):
    """Mirrors gr-digital's bundled examples/ofdm/ofdm_loopback.grc
    (fft_len 64, cp 16, 8 data + 4 pilot carriers, 50-byte packets,
    repeating source, throttle at 100 kS/s), minus the GUI sinks."""
    from gnuradio import gr, blocks, digital, channels

    pkt_len = 50
    occ = ((-4, -3, -2, -1, 1, 2, 3, 4),)
    pil = ((-6, -5, 5, 6),)
    pil_sym = ((-1, 1, -1, 1),)

    tb = gr.top_block()
    src = blocks.vector_source_b(list(range(pkt_len)), True)
    s2ts = blocks.stream_to_tagged_stream(gr.sizeof_char, 1, pkt_len, "packet_len")
    tx = digital.ofdm_tx(fft_len=FFT_LEN, cp_len=CP_LEN, packet_length_tag_key="packet_len",
                         occupied_carriers=occ, pilot_carriers=pil, pilot_symbols=pil_sym,
                         bps_header=1, bps_payload=2, rolloff=0)
    rx = digital.ofdm_rx(fft_len=FFT_LEN, cp_len=CP_LEN, frame_length_tag_key="frame_length",
                         packet_length_tag_key=rx_key,
                         occupied_carriers=occ, pilot_carriers=pil, pilot_symbols=pil_sym,
                         bps_header=1, bps_payload=2)
    thr = blocks.throttle(gr.sizeof_gr_complex, 100000, True)
    sink = blocks.vector_sink_b()

    tb.connect(src, s2ts, tx)
    if channel:
        ch = channels.channel_model(noise_voltage=0.0, frequency_offset=0.0, epsilon=eps,
                                    taps=[1.0 + 1.0j], noise_seed=0, block_tags=block_tags)
        tb.connect(tx, ch, thr, rx, sink)
    else:
        tb.connect(tx, thr, rx, sink)

    # The stock OFDM receiver never reports "done" after a finite source ends,
    # so tb.run() would block forever even WITHOUT a channel. Instead, run for
    # a fixed time and check how much data made it through, and whether the
    # flowgraph was still making progress (a freeze stops progress early).
    tb.start()
    counts = []
    for _ in range(6):
        time.sleep(1.0)
        counts.append(len(sink.data()))
    tb.stop()
    tb.wait()
    print(f"PROGRESS bytes_out_per_second={counts}")

    data = np.array(sink.data(), dtype=np.uint8)
    n = len(data) // pkt_len
    ok = int(sum(np.array_equal(data[i*pkt_len:(i+1)*pkt_len], np.arange(pkt_len))
                 for i in range(n)))
    stalled = counts[-1] == counts[2]          # no progress over the last 3 s
    print(f"RESULT packets_decoded={n} packets_correct={ok} "
          f"{'STALLED' if stalled else 'still-running'}")


# --------------------------------------------------------------------------
# Case 2: hand-built chain like the issue:
#   symbols -> pilot_inserter (gr.basic_block) -> IFFT -> [channel] -> FFT
# --------------------------------------------------------------------------
def run_custom(channel, eps=1.0, chunk=1):
    from gnuradio import gr, blocks, fft
    from gnuradio.fft import window

    rng = np.random.default_rng(1)
    qpsk = (rng.choice([-1, 1], N_VECS * N_DATA)
            + 1j * rng.choice([-1, 1], N_VECS * N_DATA)) / np.sqrt(2)

    tb = gr.top_block()
    src = blocks.vector_source_c(qpsk.astype(np.complex64).tolist(), False, N_DATA)
    pil = make_pilot_inserter(chunk)
    ifft = fft.fft_vcc(FFT_LEN, False, window.rectangular(FFT_LEN), True)
    v2s = blocks.vector_to_stream(gr.sizeof_gr_complex, FFT_LEN)
    s2v = blocks.stream_to_vector(gr.sizeof_gr_complex, FFT_LEN)
    fwd = fft.fft_vcc(FFT_LEN, True, window.rectangular(FFT_LEN), True)
    sink = blocks.vector_sink_c(FFT_LEN)

    tb.connect(src, pil, ifft, v2s)
    if channel:
        tb.connect(v2s, make_channel(eps), s2v)
    else:
        tb.connect(v2s, s2v)
    tb.connect(s2v, fwd, sink)
    tb.run()

    got = len(sink.data()) // FFT_LEN
    print(f"RESULT vectors_out={got} vectors_in={N_VECS}")


CASES = {
    "stock_no_channel":         lambda: run_stock(False),
    "stock_channel_eps1":       lambda: run_stock(True, 1.0),
    "stock_channel_eps1.0001":  lambda: run_stock(True, 1.0001),
    "stock_channel_tags_pass":  lambda: run_stock(True, 1.0, block_tags=False),
    "stock_channel_same_key":   lambda: run_stock(True, 1.0, rx_key="packet_len"),
    "stock_nochan_same_key":    lambda: run_stock(False, rx_key="packet_len"),
    "stock_chan_tagspass_same_key": lambda: run_stock(True, 1.0, block_tags=False, rx_key="packet_len"),
    "custom_no_channel":        lambda: run_custom(False),
    "custom_channel_eps1":      lambda: run_custom(True, 1.0),
    "custom_channel_eps1.0001": lambda: run_custom(True, 1.0001),
    "fragile_no_channel":       lambda: run_custom(False, chunk=1000),
    "fragile_channel_eps1":     lambda: run_custom(True, 1.0, chunk=1000),
}


def main():
    if len(sys.argv) > 1:
        CASES[sys.argv[1]]()
        return

    from gnuradio import gr
    print(f"GNU Radio {gr.version()}  |  timeout {TIMEOUT_S}s per case\n")
    for name in CASES:
        t0 = time.time()
        try:
            p = subprocess.run([sys.executable, __file__, name],
                               capture_output=True, text=True, timeout=TIMEOUT_S)
            res = [l for l in p.stdout.splitlines() if l.startswith("RESULT")]
            if p.returncode == 0 and res:
                status = "STALL" if "STALLED" in res[0] else "OK   "
            else:
                status = f"ERR({p.returncode})"
            detail = res[0][7:] if res else p.stderr.strip().splitlines()[-1:]
            errs = [l for l in (p.stdout + p.stderr).splitlines() if "ERROR" in l]
            if errs:
                detail = f"{detail}  | {errs[0].split(']:')[-1].strip()}"
        except subprocess.TimeoutExpired:
            status, detail = "HANG ", f"no completion within {TIMEOUT_S}s"
        print(f"{status}  {name:29s} {time.time()-t0:5.1f}s  {detail}")


if __name__ == "__main__":
    main()
