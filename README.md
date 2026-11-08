# Blindfold

Private, checked inference on computers you do not have to trust with your input.
Built for HACK1984 by Viraj Pandey and Apollo-1955.

## Run

Python 3.10 or newer. No Python packages, account, model download, GPU, or internet connection required.

```sh
git clone https://github.com/virajpandey/hackathon.git
cd hackathon
python3 run.py
```

Open **http://127.0.0.1:8765/**. The launcher starts three independent Python server
processes on loopback TCP ports by default; `python3 run.py --servers 5` starts five.
Any number from 2 up works. Ctrl-C stops them and the web server.
Use `python3 run.py --port 8766` if the default port is occupied.

| Page | Purpose |
| --- | --- |
| `/` | Recording desk: links and speaking sequence |
| `/whiteboard.html` | Diagram to draw by hand, plus drawing order |
| `/slides.html` | Supporting evidence slides; arrows to move, F for fullscreen |
| `/demo.html` | Live inference, plaintext comparison, and a real tampering run |

Everything the browser needs, including fonts, is served locally. No analytics or
external APIs. The server does not log prompts or save live traces.

## The demonstration

1. Open the demo and run `patient reports chest`.
2. Watch the actual shares from the computation play back. Playback is paced for
   recording; it is not a real-time throughput measurement.
3. Compare the generated text with the normal integer model. The client also
   checks every output logit against the reference.
4. Choose a server and run again with an injected change. The protocol rejects
   the first altered character before accepting it.
5. If needed, use **Play recorded**. The page labels recorded evidence explicitly
   and never silently substitutes it for a failed live run.

The demonstration uses a bundled **19,295-parameter character model**, trained on
synthetic note templates. Its path is embedding → linear → square → linear.
It is not a general-purpose language model.

## What is implemented

The client splits input into one additive share per server, modulo `2^61 − 1`.
The number of servers is a setting, not a limit: the tests run 2, 3, 5 and 7.
Each server holds public model weights and one share. Multiplication uses fresh
square pairs, and opened values and outputs are checked with MAC tags. The client
generates preprocessing material and relays the masked square opening.

There are **two client exchange phases per generated character**, plus session
setup. This is not yet a direct server-to-server mesh. The reference computation
is intentionally retained for demonstrating exactness, not for benchmarking a
production client.

Any set of shares missing even one does not reconstruct the input; all of them together do.
That privacy argument assumes independent servers and fresh preprocessing. The
default processes on one laptop demonstrate the arithmetic, not independent
trust domains. The client knows the input and preprocessing by design.
The check detects a bad computation; the highlighted server is the one the demo
deliberately changed, not an identity discovered by the check.

This prototype is not an audited deployment or a complete malicious-secure MPC
stack. Server TCP transport is unencrypted and unauthenticated. Distributed
preprocessing, secure transport, independent operators, and useful-model private
inference are next-stage work.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

Tests cover exact output, fresh shares, tampering at each server, fail-closed
masked openings, the wire format, and the web API. No training runs.

To regenerate the bundled evidence:

```sh
python3 tools/build_evidence.py
python3 tools/record_demo.py
```

The second command records only the fixed synthetic prompt in its source.
Optional browser QA uses Node.js and an installed Chrome with remote debugging:
start this server on port 8876, start a disposable Chrome profile at `qa/chrome`
with `--headless --remote-debugging-port=0`, then run
`node tools/check_browser.mjs`. It checks the live, tampered, recorded and failure
states; renders both PDFs; and saves local screenshots in ignored `qa/screens/`.
Use `BLINDFOLD_URL` to point it at a different local port.

## Hardware and separate computers

The original ESP32 sketch and public integer weights are in `hardware/espnode/`.
This cleanup does not reflash or test your chips.

Any mix of local processes, TCP servers and chips works, two or more in total.
For one already-flashed chip on macOS or Linux:

```sh
python3 run.py --nodes local local serial:/dev/cu.usbmodem101
```

Replace the serial path with the actual device. Serial support uses POSIX APIs;
the all-Python TCP demo does not.

A server can also run separately:

```sh
python3 -m engine.node 9101 --host 0.0.0.0
python3 run.py --nodes local tcp:SERVER_ADDRESS:9101 local
```

Use this raw TCP mode only on a trusted test network. The web server always stays
on localhost. Node labels in the demo distinguish local processes, TCP servers,
and USB chips.

## Files

```text
run.py                  local server and launcher
engine/                 client, server, session lifecycle, bundled public model
hardware/espnode/        existing USB server firmware and matching model
tests/                  standard-library regression and integration tests
web/                    recording desk, diagram, helper slides, demo
web/data/               historical quality result and explicitly recorded demo
web/assets/             shared visual style, local fonts, vector figures
tools/                  evidence generation and browser verification
```

The quality slide is a **separate historical training experiment**, not this
private demo: `web/data/quality.json` records the standard and private-friendly
model losses after 14,336,000 unique training tokens. It does not establish
large-model private throughput. The slide's figures are derived by
`python3 tools/build_evidence.py`; no figures are invented or trained at startup.

Research scratch files, local model caches, flash backups, agent handoffs, machine
paths, and environment files are not part of this submission.
