# Blindfold

Run AI on computers you don’t trust: they never see your input, and they get caught if they cheat.
Example: a doctor’s note processed on rented servers without any of them reading it.
Built for HACK1984 by Viraj Pandey and Apollo-1955.

## Run

Python 3.10+, standard library only. No GPU, download or internet needed.

```sh
git clone https://github.com/virajpandey/hackathon.git
cd hackathon
python3 run.py              # 3 servers; --servers N for any N >= 2, --port to change 8765
```

Open **http://127.0.0.1:8765/**: `/demo.html` is the live demo, `/slides.html` the slides
(arrows, F for fullscreen), `/whiteboard.html` the diagram, `/` the recording outline.
Everything is served locally; prompts are not logged.

## How it works

Your computer splits the input into one random-looking piece per server (additive shares mod `2^61 − 1`).
Each server runs the same public model on its piece. The model only adds, multiplies and squares,
which is the math that works on pieces; the square takes one round trip through your computer,
so each character costs two round trips. Every answer piece carries a MAC tag, so a server that
changes a single number is caught before its answer is used.

No group missing even one piece can read the input. That assumes different people run the servers;
in the demo they all run on one desk. Your computer makes the random helper values, and it also
re-runs the model in plain form, only to show the private output matches exactly.

The demo model has **19,295 parameters**, trained on made-up doctor-note templates (no real patient
data): last 10 characters → embed → linear → square → linear.

The quality slide is a separate experiment (`web/data/quality.json`): a 6.2M-parameter model rebuilt
to use only add, multiply and square scored 2.48% worse perplexity than a normal one after the same
14,336,000 training tokens.

Not built yet: real-size models, servers run by different people, servers making their own helper
values and talking directly, encrypted transport, a security review.

## Chips and separate computers

`hardware/espnode/` is the ESP32 server firmware with the same public model. Mix any endpoints:

```sh
python3 run.py --nodes local serial:/dev/cu.usbmodem101 serial:/dev/cu.usbmodem2101
python3 -m engine.node 9101 --host 0.0.0.0          # on another computer (trusted network only)
python3 run.py --nodes local tcp:SERVER_ADDRESS:9101 local
```

## Tests

```sh
python3 -m unittest discover -s tests
```

Covers exact output, fresh shares, tampering at every server for 2–7 servers, the wire format and
the web API. `tools/build_evidence.py` and `tools/record_demo.py` regenerate the slide numbers and
the recorded run. `node tools/check_browser.mjs` checks every page state and renders `web/slides.pdf`; it
needs headless Chrome started with `--remote-debugging-port=0 --user-data-dir=qa/chrome` and
`BLINDFOLD_URL` set to the running server.
