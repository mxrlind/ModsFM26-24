#!/usr/bin/env python3
"""Fase 6 do playbook: dado um punhado de bytes (hex), mostra todas as
interpretacoes plausiveis (inteiro LE/BE, signed/unsigned, float, string
ascii/utf-16) para ajudar a decidir qual bateu com o valor esperado.

Uso:
    python3 tools/endian_check.py "40 e2 01 00"
    python3 tools/endian_check.py 40e20100
"""
import argparse
import struct


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("hexbytes", help="bytes em hex, com ou sem espacos (ex.: '40 e2 01 00')")
    args = ap.parse_args()

    raw = args.hexbytes.replace(" ", "").replace("0x", "")
    data = bytes.fromhex(raw)
    print(f"Bytes: {data.hex(' ')} ({len(data)} bytes)\n")

    for width in (1, 2, 4, 8):
        if len(data) < width:
            continue
        chunk = data[:width]
        le_u = int.from_bytes(chunk, "little")
        be_u = int.from_bytes(chunk, "big")
        le_s = int.from_bytes(chunk, "little", signed=True)
        be_s = int.from_bytes(chunk, "big", signed=True)
        print(f"-- {width} byte(s): {chunk.hex(' ')} --")
        print(f"   unsigned little-endian: {le_u}")
        print(f"   unsigned big-endian:    {be_u}")
        print(f"   signed little-endian:   {le_s}")
        print(f"   signed big-endian:      {be_s}")

    if len(data) == 4:
        print(f"\n   float32 little-endian: {struct.unpack('<f', data)[0]}")
        print(f"   float32 big-endian:    {struct.unpack('>f', data)[0]}")
    if len(data) == 8:
        print(f"\n   float64 little-endian: {struct.unpack('<d', data)[0]}")
        print(f"   float64 big-endian:    {struct.unpack('>d', data)[0]}")

    print(f"\n   como ascii:   {data.decode('ascii', errors='replace')!r}")
    try:
        print(f"   como utf-16le: {data.decode('utf-16-le', errors='replace')!r}")
    except Exception:
        pass


if __name__ == "__main__":
    main()
