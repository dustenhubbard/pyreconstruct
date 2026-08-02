#!/usr/bin/env python
"""Rank hotspots by SELF time from a py-spy speedscope file.

Self time is the sample weight attributed to the *leaf* frame of each stack, so
this answers "where is the interpreter actually spending cycles", which is the
question the Phase 2 Rust decision gate asks. py-spy reports a leaf per source
line, so lines belonging to one function are folded back together here.

Usage:
    python rank_hotspots.py session.speedscope.json [--top 20] [--by-line]
"""
import argparse, collections, json, sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("speedscope")
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--by-line", action="store_true",
                    help="do not fold source lines into their function")
    ap.add_argument("--strip", default="",
                    help="strip this path prefix from displayed filenames")
    args = ap.parse_args()

    with open(args.speedscope) as f:
        d = json.load(f)
    frames = d["shared"]["frames"]

    self_w = collections.Counter()
    total = 0.0
    for p in d["profiles"]:
        samples = p["samples"]
        weights = p.get("weights") or [1.0] * len(samples)
        for stack, w in zip(samples, weights):
            total += w
            if stack:
                self_w[stack[-1]] += w

    if not total:
        print("no samples", file=sys.stderr)
        return 1

    def key_of(idx):
        fr = frames[idx]
        fn = fr.get("file") or "?"
        if args.strip and fn.startswith(args.strip):
            fn = fn[len(args.strip):]
        elif "/PyReconstruct/" in fn:
            fn = "PyReconstruct/" + fn.split("/PyReconstruct/", 1)[1]
        name = fr.get("name") or "?"
        return (name, fn, fr.get("line")) if args.by_line else (name, fn)

    folded = collections.Counter()
    for idx, w in self_w.items():
        folded[key_of(idx)] += w

    native = sum(w for k, w in folded.items()
                 if not (k[1].endswith(".py") or ".py:" in k[1]))
    print(f"total samples weight: {total:.2f}s   "
          f"leaf-in-native/extension frames: {native / total * 100:.1f}%")
    print()
    print(f"{'rank':>4s} {'self%':>7s} {'cum%':>7s}  {'function':38s} location")
    print("-" * 108)
    cum = 0.0
    for i, (k, w) in enumerate(folded.most_common(args.top), 1):
        cum += w
        loc = k[1] if len(k) == 2 else f"{k[1]}:{k[2]}"
        print(f"{i:>4d} {w / total * 100:6.2f}% {cum / total * 100:6.2f}%  "
              f"{k[0][:38]:38s} {loc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
