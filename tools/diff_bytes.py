#!/usr/bin/env python3
"""Fase 4-5 do playbook: analise diferencial entre dois arquivos quase
identicos (ex.: mesma base do editor, so um campo alterado).

Agrupa bytes diferentes consecutivos em "runs" (uma mudanca de int32 ou
string aparece como varios bytes diferentes seguidos, e olhar um por um
so atrapalha), e tenta decodificar cada run como inteiro LE/BE quando o
tamanho bate com 1/2/4/8 bytes.

Uso:
    python3 tools/diff_bytes.py arquivo_A.fmf arquivo_B.fmf [--context 8]
"""
import argparse


def find_diff_runs(a: bytes, b: bytes):
    n = min(len(a), len(b))
    runs = []
    i = 0
    while i < n:
        if a[i] != b[i]:
            start = i
            while i < n and a[i] != b[i]:
                i += 1
            runs.append((start, i - start))
        else:
            i += 1
    return runs


def try_decode_int(chunk: bytes) -> str:
    if len(chunk) not in (1, 2, 4, 8):
        return ""
    le = int.from_bytes(chunk, "little")
    be = int.from_bytes(chunk, "big")
    sle = int.from_bytes(chunk, "little", signed=True)
    sbe = int.from_bytes(chunk, "big", signed=True)
    return f"uLE={le} uBE={be} sLE={sle} sBE={sbe}"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("file_a")
    ap.add_argument("file_b")
    ap.add_argument("--context", type=int, default=8, help="bytes de contexto ao redor de cada run")
    args = ap.parse_args()

    with open(args.file_a, "rb") as f:
        a = f.read()
    with open(args.file_b, "rb") as f:
        b = f.read()

    print(f"A: {args.file_a} ({len(a)} bytes)")
    print(f"B: {args.file_b} ({len(b)} bytes)")
    if len(a) != len(b):
        print(f"AVISO: tamanhos diferentes (diff de {abs(len(a) - len(b))} bytes)."
              " Comparando so o prefixo comum -- se o formato usa"
              " tamanho variavel (ex.: strings), isso pode desalinhar tudo"
              " a partir do primeiro campo de tamanho variavel.")
    print()

    runs = find_diff_runs(a, b)
    if not runs:
        print("Nenhuma diferenca de byte encontrada no prefixo comum.")
        return

    print(f"== {len(runs)} regiao(oes) diferente(s) ==\n")
    ctx = args.context
    for start, length in runs:
        old = a[start : start + length]
        new = b[start : start + length]
        print(f"offset {start:#08x} ({start}), {length} byte(s)")
        print(f"  A: {old.hex(' ')}")
        print(f"  B: {new.hex(' ')}")
        decoded = try_decode_int(old)
        if decoded:
            print(f"  A como inteiro -> {decoded}")
            print(f"  B como inteiro -> {try_decode_int(new)}")
        lo = max(0, start - ctx)
        hi = min(len(a), start + length + ctx)
        print(f"  contexto A [{lo:#x}:{hi:#x}]: {a[lo:hi].hex(' ')}")
        print(f"  contexto B [{lo:#x}:{hi:#x}]: {b[lo:hi].hex(' ')}")
        print()


if __name__ == "__main__":
    main()
