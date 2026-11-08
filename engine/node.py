#!/usr/bin/env python3
"""One Blindfold node: computes its share of the tiny note model and never sees the note.

    python3 node.py 9101                 # listen on port 9101 (any computer with Python 3; no installs)

Needs private_lm_model.json next to this file. Arithmetic is mod P = 2^61-1.
Wire format (same for TCP and USB): 0xB1, type byte, uint32 count, count x uint64, little-endian.
"""
import argparse
import json
import socket
import struct
from pathlib import Path

P = 2**61 - 1
MAGIC = 0xB1


def read_frame(rd):
    while True:
        head = rd(1)
        if not head:
            raise EOFError
        if head[0] == MAGIC:
            break
    kind, n = struct.unpack("<cI", rd(5))
    if n > 10000:
        raise ValueError("Frame too large")
    return kind, list(struct.unpack(f"<{n}Q", rd(8 * n)))


def frame(kind, vals):
    return struct.pack(f"<BcI{len(vals)}Q", MAGIC, kind, len(vals), *[v % P for v in vals])


class Node:
    def __init__(self, model, quiet=False):
        self.quiet = quiet
        self.W1, self.b1, self.W2, self.b2 = model["W1"], model["b1"], model["W2"], model["b2"]
        self.n_in, self.hid, self.vocab = len(self.W1), len(self.b1), len(self.b2)
        self.W1T = [list(col) for col in zip(*self.W1)]
        self.W2T = [list(col) for col in zip(*self.W2)]
        self.index, self.alpha, self.lie_at, self.char = 0, 0, -1, 0

    def setup(self, v):
        self.index, self.alpha = v[0], v[1]
        self.lie_at = -1 if v[2] == P - 1 else v[2]
        self.char = 0
        return frame(b"K", [self.index])

    def step_in(self, v):
        n, h = self.n_in, self.hid
        eps, r, rt, a, at, a2, a2t = (v[:n], v[n:2 * n], v[2 * n:3 * n], v[3 * n:3 * n + h],
                                       v[3 * n + h:3 * n + 2 * h], v[3 * n + 2 * h:3 * n + 3 * h], v[3 * n + 3 * h:])
        lead = self.index == 0
        x = [(ri + (e if lead else 0)) % P for ri, e in zip(r, eps)]
        xt = [(ti + self.alpha * e) % P for ti, e in zip(rt, eps)]
        z = [(sum(w * xi for w, xi in zip(col, x)) + (b if lead else 0)) % P for col, b in zip(self.W1T, self.b1)]
        zt = [(sum(w * xi for w, xi in zip(col, xt)) + self.alpha * b) % P for col, b in zip(self.W1T, self.b1)]
        self.a, self.at, self.a2, self.a2t = a, at, a2, a2t
        d, dt = [(zi - ai) % P for zi, ai in zip(z, a)], [(zi - ai) % P for zi, ai in zip(zt, at)]
        self.view = (x[:3], d[:3])
        return frame(b"D", d + dt)

    def step_out(self, d):
        lead = self.index == 0
        y = [(a2 + 2 * di * ai + (di * di if lead else 0)) % P for a2, di, ai in zip(self.a2, d, self.a)]
        yt = [(a2t + 2 * di * ati + self.alpha * di * di) % P for a2t, di, ati in zip(self.a2t, d, self.at)]
        if self.char == self.lie_at:
            y[0] = (y[0] + 1) % P
        l = [(sum(w * yi for w, yi in zip(col, y)) + (b if lead else 0)) % P for col, b in zip(self.W2T, self.b2)]
        lt = [(sum(w * yi for w, yi in zip(col, yt)) + self.alpha * b) % P for col, b in zip(self.W2T, self.b2)]
        got, sent = self.view
        lie = "   <- LYING" if self.char == self.lie_at else ""
        if not self.quiet:
            print(f"char {self.char:3d}  got {' '.join(f'{v:016x}' for v in got)}  sent {l[0]:016x}{lie}", flush=True)
        self.char += 1
        return frame(b"L", l + lt)

    def handle(self, kind, v):
        expected = {b"S": 3, b"X": 3 * self.n_in + 4 * self.hid, b"O": self.hid}
        if kind not in expected or len(v) != expected[kind]:
            raise ValueError("Invalid protocol frame")
        if kind == b"S" and not 0 <= v[0] < 26:  # servers A..Z
            raise ValueError("Invalid node index")
        return {b"S": self.setup, b"X": self.step_in, b"O": self.step_out}[kind](v)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("port", type=int, nargs="?", default=9101)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    model = json.loads((Path(__file__).resolve().parent / "private_lm_model.json").read_text())
    node = Node(model, quiet=args.quiet)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((args.host, args.port))
    srv.listen(1)
    print(json.dumps({"ready": True, "host": args.host, "port": srv.getsockname()[1]}), flush=True)
    while True:
        conn, addr = srv.accept()
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        if not args.quiet:
            print(f"device connected from {addr[0]}", flush=True)
        f = conn.makefile("rwb")

        def rd(n):
            b = f.read(n)
            if len(b) < n:
                raise EOFError
            return b
        try:
            while True:
                kind, v = read_frame(rd)
                f.write(node.handle(kind, v))
                f.flush()
        except (EOFError, ConnectionError, ValueError, struct.error):
            if not args.quiet:
                print("device disconnected", flush=True)
        f.close()
        conn.close()


if __name__ == "__main__":
    main()
