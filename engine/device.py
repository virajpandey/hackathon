#!/usr/bin/env python3
"""The patient's device: holds the note, talks to 3 nodes it doesn't trust, and checks every answer.

    python3 device.py tcp:127.0.0.1:9101 tcp:127.0.0.1:9102 serial:/dev/cu.usbmodem101 "patient reports chest"
    ... --lie=C@5            node C lies on character 5 (the device must catch it)
    ... --pace=0.15          seconds per character, for filming
    ... --trace=FILE         honest run + lying run, written in the demo page's trace format (private_lm_trace.json)

The device makes the helper numbers itself (random masks, square pairs, MAC key), so no third party is trusted.
Each node gets only its share of each value. The device sends masked input once per character and checks the MAC
tags on everything the nodes send back. Any change to a share is caught except with probability 1/P.
"""
import json
import os
import secrets
import select
import socket
import sys
import time
from pathlib import Path

if __package__:
    from .node import P, frame, read_frame
else:
    from node import P, frame, read_frame

HERE = Path(__file__).resolve().parent
NAMES = "ABC"
HEX = lambda vals: [f"{v:016x}" for v in vals[:4]]


class Link:
    def __init__(self, spec):
        kind, addr = spec.split(":", 1)
        self.name = spec
        if kind == "tcp":
            host, port = addr.rsplit(":", 1)
            s = socket.create_connection((host, int(port)), timeout=10)
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            s.settimeout(10)
            self.socket = s
            self.f = s.makefile("rwb")
            self.write = lambda b: (self.f.write(b), self.f.flush())
            self.rd = self._rd_file
        elif kind == "serial":
            import tty

            self.fd = os.open(addr, os.O_RDWR | os.O_NOCTTY)
            tty.setraw(self.fd)
            self.buf = b""
            self.write = self._write_fd
            self.rd = self._rd_fd
        else:
            raise ValueError("Use tcp:host:port or serial:device")

    def close(self):
        if hasattr(self, "f"):
            self.f.close()
            self.socket.close()
        else:
            os.close(self.fd)

    def _rd_file(self, n):
        b = self.f.read(n)
        if len(b) < n:
            raise EOFError(self.name)
        return b

    def _write_fd(self, data):
        view = memoryview(data)
        while view:
            view = view[os.write(self.fd, view):]

    def _rd_fd(self, n):
        while len(self.buf) < n:
            if not select.select([self.fd], [], [], 10)[0]:
                raise TimeoutError(self.name)
            self.buf += os.read(self.fd, 65536)
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def recv(self, want):
        kind, v = read_frame(self.rd)
        if kind != want:
            raise ValueError(f"Expected {want!r}, received {kind!r}")
        return v


def rand():
    return secrets.randbelow(P)


def shares(v):
    a, b = rand(), rand()
    return [a, b, (v - a - b) % P]


def centered(v):
    v %= P
    return v - P if v > P // 2 else v


class Device:
    def __init__(self, links, model):
        self.links, self.m = links, model
        self.vocab, self.K = model["vocab"], model["K"]
        self.idx = {c: i for i, c in enumerate(self.vocab)}

    def plain(self, ctx):
        m = self.m
        x = [v for c in ctx for v in m["E"][c]]
        z = [sum(w * xi for w, xi in zip(col, x)) + b for col, b in zip(zip(*m["W1"]), m["b1"])]
        a = [v * v for v in z]
        return [sum(w * ai for w, ai in zip(col, a)) + b for col, b in zip(zip(*m["W2"]), m["b2"])]

    def ctx(self, text):
        return [self.idx[c] for c in (" " * self.K + text)[-self.K:]]

    def plain_text(self, prompt):
        text = prompt
        for _ in range(90):
            logits = self.plain(self.ctx(text))
            text += self.vocab[max(range(len(logits)), key=lambda k: logits[k])]
            if text[-1] == "\n":
                break
        return text

    def run(self, prompt, lie=None, pace=0.0, echo=True):
        """One private generation. Returns dict(text, steps, exact, caught, at)."""
        alpha = rand()
        al = shares(alpha)
        for i, l in enumerate(self.links):
            lie_at = int(lie.split("@")[1]) if lie and lie.split("@")[0] == NAMES[i] else P - 1
            l.write(frame(b"S", [i, al[i], lie_at]))
            l.recv(b"K")
        text, exact, steps, h, V = prompt, True, [], len(self.m["b1"]), len(self.vocab)
        phases = 0
        if echo:
            sys.stdout.write(text)
            sys.stdout.flush()
        for step in range(90):
            ctx = self.ctx(text)
            x = [v for c in ctx for v in self.m["E"][c]]
            r = [rand() for _ in x]
            a = [rand() for _ in range(h)]
            eps = [(xi - ri) % P for xi, ri in zip(x, r)]
            per = [[] for _ in self.links]
            rsh = None
            for vec in (r, [alpha * v % P for v in r], a, [alpha * v % P for v in a],
                        [v * v % P for v in a], [alpha * v * v % P for v in a]):
                sh = [shares(v) for v in vec]
                rsh = rsh or sh
                for i in range(3):
                    per[i].extend(s[i] for s in sh)
            for i, l in enumerate(self.links):
                l.write(frame(b"X", eps + per[i]))
            got = [l.recv(b"D") for l in self.links]
            phases += 1
            if any(len(g) != 2 * h for g in got):
                raise ValueError("Invalid opening response")
            d = [sum(g[k] for g in got) % P for k in range(h)]
            ok = all(sum(g[h + k] for g in got) % P == alpha * d[k] % P for k in range(h))
            # What each node actually received for the first input numbers: node A's share includes eps.
            seen = {NAMES[i]: HEX([(s[i] + (e if i == 0 else 0)) % P for s, e in zip(rsh, eps)]) for i in range(3)}
            view = dict(device_sends=HEX(eps), node_shares=seen, opened_square_mask=HEX(d))
            if not ok:
                return dict(text=text, steps=steps, exact=exact, caught=True, at=step,
                            failed_phase="opening", client_exchange_phases=phases, rejected_view=view)
            for l in self.links:
                l.write(frame(b"O", d))
            got = [l.recv(b"L") for l in self.links]
            phases += 1
            if any(len(g) != 2 * V for g in got):
                raise ValueError("Invalid output response")
            logits = [sum(g[k] for g in got) % P for k in range(V)]
            ok = ok and all(sum(g[V + k] for g in got) % P == alpha * logits[k] % P for k in range(V))
            if not ok:
                if echo:
                    print(f"\n\nCHECK FAILED at character {step}: a node changed its numbers. "
                          "Session stopped; nothing was accepted.")
                return dict(text=text, steps=steps, exact=exact, caught=True, at=step,
                            failed_phase="output", client_exchange_phases=phases, rejected_view=view)
            logits = [centered(v) for v in logits]
            exact = exact and logits == self.plain(ctx)
            ch = self.vocab[max(range(V), key=lambda k: logits[k])]
            steps.append(dict(char=ch, view=view))
            text += ch
            if echo:
                sys.stdout.write(ch)
                sys.stdout.flush()
            time.sleep(pace)
            if ch == "\n":
                break
        return dict(text=text, steps=steps, exact=exact, caught=False, at=None,
                    client_exchange_phases=phases)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    opt = {a.split("=")[0][2:]: a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--") and "=" in a}
    specs = args[:3]
    m = json.loads((HERE / "private_lm_model.json").read_text())
    dev = Device([Link(s) for s in specs], m)
    prompt = "".join(c for c in (args[3] if len(args) > 3 else "patient reports ").lower() if c in dev.idx)
    pace = float(opt.get("pace", 0))
    print("connected to 3 nodes: " + ", ".join(f"{NAMES[i]}={s}" for i, s in enumerate(specs)))
    if "trace" not in opt:
        t0 = time.time()
        res = dev.run(prompt, lie=opt.get("lie"), pace=pace)
        if not res["caught"]:
            n, secs = len(res["text"]) - len(prompt), time.time() - t0
            print(f"bit-exact with the normal model: {res['exact']}   every answer checked: True   "
                  f"{n} chars in {secs:.2f}s ({n / secs:.0f} chars/s), 2 client exchange phases per char")
        return
    lie = opt.get("lie", "C@5")
    honest = dev.run(prompt, pace=pace, echo=False)
    lying = dev.run(prompt, lie=lie, pace=pace, echo=False)
    normal = dev.plain_text(prompt)
    exact = honest["exact"] and honest["text"] == normal
    trace = dict(
        prompt=prompt, normal_text=normal, private_text=honest["text"], bit_exact=exact,
        device_trips_per_char=2, node_exchanges_per_char=0, nodes=list(NAMES), prime="2^61-1",
        hardware={NAMES[i]: s for i, s in enumerate(specs)},
        steps=honest["steps"],
        cheat=dict(node=lie.split("@")[0], at_char=int(lie.split("@")[1]), caught=lying["caught"],
                   stopped_text=lying["text"], miss_probability="1 in 2,305,843,009,213,693,951"),
        model=dict(params=sum(len(m[k]) * (len(m[k][0]) if isinstance(m[k][0], list) else 1)
                              for k in ("E", "W1", "b1", "W2", "b2")),
                   architecture="last 10 chars -> embed -> linear -> square -> linear",
                   corpus="synthetic patient notes from templates (no real data)"),
        label=("Three node programs over TCP or USB. The client creates fresh helper values and relays the masked "
               "square opening; two client exchange phases per character. A tiny synthetic-note model, not an LLM."),
    )
    Path(opt["trace"]).write_text(json.dumps(trace, indent=1))
    print(f"honest: {honest['text'].strip()}\nbit-exact: {exact}   lie by {lie}: caught={lying['caught']}\nwrote {opt['trace']}")


if __name__ == "__main__":
    main()
