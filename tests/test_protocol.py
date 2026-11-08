import contextlib
import io
import json
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))
from device import Device, centered, shares
from node import Node, P, frame, read_frame

MODEL = json.loads((Path(__file__).resolve().parents[1] / "engine/private_lm_model.json").read_text())


class LocalLink:
    def __init__(self, tamper_opening=False):
        self.node = Node(MODEL)
        self.tamper_opening = tamper_opening
        self.sent = []

    def write(self, data):
        kind, values = read_frame(io.BytesIO(data).read)
        self.sent.append(kind)
        with contextlib.redirect_stdout(io.StringIO()):
            self.response = self.node.handle(kind, values)
        if kind == b"X" and self.tamper_opening:
            kind, values = read_frame(io.BytesIO(self.response).read)
            values[0] = (values[0] + 1) % P
            self.response = frame(kind, values)

    def recv(self, expected):
        kind, values = read_frame(io.BytesIO(self.response).read)
        if kind != expected:
            raise ValueError("Unexpected response")
        return values


class ProtocolTests(unittest.TestCase):
    def test_sharing_signed_values(self):
        for value in [-100, 0, 1, 100, P // 2]:
            parts = shares(value)
            self.assertEqual(centered(sum(parts)), value)
            self.assertTrue(all(0 <= v < P for v in parts))
        self.assertNotEqual(shares(123), shares(123))

    def test_honest_logits_match_plaintext(self):
        for prompt in ["patient reports chest", "patient reports knee", "patient reports a"]:
            with self.subTest(prompt=prompt):
                device = Device([LocalLink() for _ in range(3)], MODEL)
                result = device.run(prompt, echo=False)
                self.assertTrue(result["exact"])
                self.assertFalse(result["caught"])
                self.assertEqual(result["text"], device.plain_text(prompt))
                self.assertEqual(len(result["steps"]), len(result["text"]) - len(prompt))

    def test_each_workers_injected_lie_is_rejected_before_output(self):
        for node in "ABC":
            with self.subTest(node=node):
                device = Device([LocalLink() for _ in range(3)], MODEL)
                result = device.run("patient reports chest", lie=f"{node}@0", echo=False)
                self.assertTrue(result["caught"])
                self.assertEqual(result["steps"], [])
                self.assertEqual(result["text"], "patient reports chest")

    def test_failed_opening_is_not_broadcast(self):
        links = [LocalLink(tamper_opening=i == 1) for i in range(3)]
        result = Device(links, MODEL).run("patient reports chest", echo=False)
        self.assertTrue(result["caught"])
        self.assertTrue(all(b"O" not in link.sent for link in links))

    def test_fresh_randomness_same_answer(self):
        device = Device([LocalLink() for _ in range(3)], MODEL)
        a = device.run("patient reports chest", echo=False)
        b = device.run("patient reports chest", echo=False)
        self.assertEqual(a["text"], b["text"])
        self.assertNotEqual(a["steps"][0]["view"], b["steps"][0]["view"])

    def test_wire_roundtrip(self):
        kind, values = read_frame(io.BytesIO(frame(b"D", [0, 42, P - 1])).read)
        self.assertEqual((kind, values), (b"D", [0, 42, P - 1]))

    def test_invalid_wire_frames_are_rejected(self):
        with self.assertRaises(EOFError):
            read_frame(io.BytesIO(b"").read)
        with self.assertRaises(ValueError):
            read_frame(io.BytesIO(struct.pack("<BcI", 0xB1, b"X", 10001)).read)
        with self.assertRaises(ValueError):
            Node(MODEL).handle(b"X", [0])
        with self.assertRaises(ValueError):
            Node(MODEL).handle(b"S", [3, 0, 0])


if __name__ == "__main__":
    unittest.main()
