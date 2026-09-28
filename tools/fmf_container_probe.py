#!/usr/bin/env python3
"""Reproduz a analise do estudo de caso em docs/reverse-engineering-log.md:
le o cabecalho de 26 bytes no formato observado (FM19/FM26), localiza o
trailer pelo ponteiro "trailer_offset - 9", tenta descomprimir o trailer
com zlib e, se der certo, lista o diretorio de entradas (nome, extensao,
offset, tamanhos).

Nao inclui nenhuma amostra de arquivo -- baixe a sua (ex.: um .fmf real de
`quarterback/FM-Files` no GitHub, ou um .fmf/.fm seu) e aponte o caminho.

Uso:
    python3 tools/fmf_container_probe.py caminho/para/arquivo.fmf
"""
import argparse
import struct
import sys
import zlib

HEADER_SIZE = 26


def parse_header(data: bytes):
    magic6 = data[:6]
    u16_a, u8_a = struct.unpack_from("<HB", data, 6)
    trailer_ptr = struct.unpack_from("<Q", data, 9)[0]
    const17 = struct.unpack_from("<Q", data, 17)[0]
    u8_b = data[25]
    return {
        "magic6": magic6,
        "u16@6": u16_a,
        "u8@8": u8_a,
        "trailer_offset_minus_9": trailer_ptr,
        "trailer_offset_guess": trailer_ptr + 9,
        "const@17": const17,
        "u8@25": u8_b,
    }


def try_decompress_trailer(data: bytes, trailer_offset: int):
    marker = data[trailer_offset : trailer_offset + 9]
    payload = data[trailer_offset + 9 :]
    try:
        return marker, zlib.decompress(payload)
    except zlib.error as e:
        return marker, f"zlib falhou: {e}"


def parse_directory(directory: bytes):
    """Formato observado no FM19: length_prefixed(save_name), u32
    desconhecido, depois entradas de (nome, extensao, offset, tam.
    comprimido, tam. descomprimido, 2 campos extras)."""
    off = 0

    def read_u32():
        nonlocal off
        (v,) = struct.unpack_from("<I", directory, off)
        off += 4
        return v

    def read_str(length):
        nonlocal off
        s = directory[off : off + length]
        off += length
        return s

    entries = []
    name_len = read_u32()
    save_name = read_str(name_len).decode("utf-8", errors="replace")
    unknown_count = read_u32()
    while off + 4 <= len(directory):
        try:
            entry_name_len = read_u32()
            if not (0 < entry_name_len < 256):
                break
            entry_name = read_str(entry_name_len).decode("utf-8", errors="replace")
            ext_len = read_u32()
            ext = read_str(ext_len).decode("ascii", errors="replace")
            if off + 40 > len(directory):
                break
            rel_offset, comp_size, decomp_size, extra1, extra2 = struct.unpack_from(
                "<5Q", directory, off
            )
            off += 40
            entries.append(
                {
                    "name": entry_name,
                    "ext": ext,
                    "relative_offset": rel_offset,
                    "absolute_offset": HEADER_SIZE + rel_offset,
                    "compressed_size": comp_size,
                    "decompressed_size": decomp_size,
                    "extra1": extra1,
                    "extra2": extra2,
                }
            )
        except struct.error:
            break
    return save_name, unknown_count, entries


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("path")
    args = ap.parse_args()

    with open(args.path, "rb") as f:
        data = f.read()

    print(f"Arquivo: {args.path} ({len(data)} bytes)\n")

    header = parse_header(data)
    print("== Cabecalho (26 bytes) ==")
    for k, v in header.items():
        print(f"  {k}: {v!r}")
    print()

    trailer_offset = header["trailer_offset_guess"]
    if trailer_offset >= len(data):
        print(f"trailer_offset_guess ({trailer_offset}) fora do arquivo -- formato diferente do esperado.")
        sys.exit(1)

    marker, result = try_decompress_trailer(data, trailer_offset)
    print(f"== Trailer no offset {trailer_offset:#x} ({trailer_offset}) ==")
    print(f"  marcador (9 bytes): {marker.hex(' ')}")
    if isinstance(result, str):
        print(f"  {result}")
        print("  (tente adaptar este script para zstd -- ver docs/fm26-save-format.md)")
        return
    print(f"  descomprimido com zlib: {len(result)} bytes\n")

    save_name, unknown_count, entries = parse_directory(result)
    print(f"== Diretorio ==")
    print(f"  nome do save/export: {save_name!r}")
    print(f"  campo u32 nao identificado: {unknown_count}")
    print(f"  {len(entries)} entrada(s):\n")
    for e in entries:
        print(
            f"    {e['name']}{e['ext']}  offset_abs={e['absolute_offset']:#x}"
            f"  comprimido={e['compressed_size']}  descomprimido={e['decompressed_size']}"
            f"  extra=({e['extra1']}, {e['extra2']})"
        )


if __name__ == "__main__":
    main()
