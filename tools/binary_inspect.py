#!/usr/bin/env python3
"""Fase 1-4 do playbook de engenharia reversa: identificar formato,
inspecionar cabecalho, procurar strings legiveis e estimar se o arquivo
esta comprimido/criptografado (via entropia).

Uso:
    python3 tools/binary_inspect.py <arquivo> [--hexlen 128] [--strings-min 4] [--out strings.txt]
"""
import argparse
import math
import string
from collections import Counter

MAGIC_SIGNATURES = {
    b"PK\x03\x04": "ZIP (PKZIP local file header)",
    b"PK\x05\x06": "ZIP (empty archive)",
    b"7z\xbc\xaf\x27\x1c": "7-Zip",
    b"\x1f\x8b": "GZIP",
    b"BZh": "BZIP2",
    b"\x78\x01": "ZLIB (no/low compression)",
    b"\x78\x9c": "ZLIB (default compression)",
    b"\x78\xda": "ZLIB (best compression)",
    b"FMF": "Possivel header proprio 'FMF'",
    b"\x89PNG\r\n\x1a\n": "PNG",
    b"RIFF": "RIFF container (WAV/AVI/...)",
}


def hexdump(data: bytes, length: int) -> str:
    chunk = data[:length]
    lines = []
    for i in range(0, len(chunk), 16):
        row = chunk[i : i + 16]
        hex_part = " ".join(f"{b:02x}" for b in row)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in row)
        lines.append(f"{i:08x}  {hex_part:<47}  {ascii_part}")
    return "\n".join(lines)


def guess_magic(data: bytes) -> list[str]:
    hits = []
    for sig, desc in MAGIC_SIGNATURES.items():
        if data.startswith(sig):
            hits.append(f"{sig!r} -> {desc}")
    return hits


def shannon_entropy(data: bytes) -> float:
    if not data:
        return 0.0
    counts = Counter(data)
    total = len(data)
    return -sum((c / total) * math.log2(c / total) for c in counts.values())


def extract_strings(data: bytes, min_len: int) -> list[str]:
    printable = set(bytes(string.printable, "ascii"))
    out = []
    current = bytearray()
    for b in data:
        if b in printable and b not in (9, 10, 11, 12, 13):
            current.append(b)
        else:
            if len(current) >= min_len:
                out.append(current.decode("ascii", errors="replace"))
            current = bytearray()
    if len(current) >= min_len:
        out.append(current.decode("ascii", errors="replace"))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("path")
    ap.add_argument("--hexlen", type=int, default=128, help="bytes to hexdump do inicio do arquivo")
    ap.add_argument("--strings-min", type=int, default=4, help="tamanho minimo de string ASCII")
    ap.add_argument("--out", help="salva a lista de strings encontradas neste arquivo")
    ap.add_argument("--entropy-window", type=int, default=4096, help="tamanho da janela p/ entropia por blocos")
    args = ap.parse_args()

    with open(args.path, "rb") as f:
        data = f.read()

    print(f"Arquivo: {args.path}")
    print(f"Tamanho: {len(data)} bytes")
    print()

    print("== Cabecalho (hexdump) ==")
    print(hexdump(data, args.hexlen))
    print()

    print("== Magic number ==")
    hits = guess_magic(data)
    if hits:
        for h in hits:
            print(f"  MATCH: {h}")
    else:
        print(f"  Nenhuma assinatura conhecida. Primeiros bytes: {data[:8].hex(' ')}")
    print()

    print("== Entropia (Shannon, 0=totalmente previsivel, 8=totalmente aleatorio) ==")
    overall = shannon_entropy(data)
    print(f"  Arquivo inteiro: {overall:.3f} bits/byte")
    w = args.entropy_window
    if len(data) > w:
        print(f"  Por blocos de {w} bytes (primeiros 10 blocos):")
        for i in range(0, min(len(data), w * 10), w):
            block = data[i : i + w]
            e = shannon_entropy(block)
            tag = ""
            if e > 7.5:
                tag = "  <- alta entropia (comprimido/criptografado/binario denso)"
            elif e < 4:
                tag = "  <- baixa entropia (texto/estrutura repetitiva)"
            print(f"    offset {i:#08x}: {e:.3f}{tag}")
    print()

    print(f"== Strings ASCII (min {args.strings_min} chars) ==")
    strs = extract_strings(data, args.strings_min)
    print(f"  Total encontrado: {len(strs)}")
    for s in strs[:40]:
        print(f"    {s!r}")
    if len(strs) > 40:
        print(f"    ... (+{len(strs) - 40} strings, use --out para salvar todas)")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write("\n".join(strs))
        print(f"  Strings completas salvas em: {args.out}")


if __name__ == "__main__":
    main()
