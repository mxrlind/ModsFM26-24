#!/usr/bin/env python3
"""Escreve um .fmf de TATICA a partir de uma base real + uma modificacao
validada por analise diferencial (ver docs/reverse-engineering-log.md).

Diferente de shortlist (tools/fmf_write.py), nao mapeamos o esquema
INTERNO completo de uma tatica (formacao, papeis, instrucoes por fase)
-- so decifiamos a camada externa (AES-CTR + zstd). O que dá pra fazer com
seguranca e o que este modulo faz: comparar duas taticas reais que so
diferem por um ajuste conhecido ("High Press"), confirmar que a diferenca
se resume a 2 bytes isolados (depois de realinhar pelo campo de nome, que
tem tamanho variavel), e usar essa transformacao *validada* pra gerar uma
tatica nova a partir de uma base real -- ao inves de compor uma tatica do
zero campo a campo, o que exigiria o esquema completo que ainda nao
temos.

Achado (analise diferencial entre "3-3-3-1 Morphing System.fmf" e
"3-3-3-1 Morphing System High Press.fmf", ambas de Glawster/fmsat):
depois do campo de nome (que tem tamanho variavel), os proximos 5077
bytes sao IDENTICOS exceto em 2 offsets:

    offset relativo (pos-nome) 23: 0x54 -> 0x94  (XOR 0xC0, 2 bits: 01->10,
                                    provavel enum de 2 bits "intensidade
                                    de pressao": normal -> alta)
    offset relativo (pos-nome) 27: 0x80 -> 0x90  (XOR 0x10, 1 bit: flag
                                    booleana ligada)

Validado: aplicar XOR 0xC0 e XOR 0x10 nesses 2 offsets da tatica base
reproduz BYTE A BYTE o conteudo da tatica "High Press" real (descontado
o campo de nome, que nao alteramos).

O restante do arquivo (details.aom com a descricao, image.img) e
recriado com o mesmo layout observado num details.aom real de tatica
(TACTICS_TYPE_HANDLER), mas com nome/descricao/autor proprios.

Uso:
    python3 tools/fmf_write_tactic.py base.fmf --high-press --out saida.fmf
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

from fmf_extract import HEADER_SIZE, read_catalog, decrypt_resource
from fmf_write import (
    _build_resource,
    _string,
    _u32,
    _i64,
    AFE_MAGIC,
    CATALOG_MAGIC,
    ARCHIVE_FORMAT,
    EMPTY_RESOURCE_TIMESTAMP,
)
import zstandard

DETAILS_MAGIC = bytes([3, 1]) + b"moa." + bytes([4, 0])
# Sufixo estrutural de 22 bytes visto em todo details.aom de TATICA real
# (constante de formato / provavel GUID de tipo, nao expressao criativa).
TACTIC_DETAILS_SUFFIX = bytes([
    0x02, 0x00, 0x01, 0x00, 0x02, 0x80, 0x81, 0xA8, 0x00, 0x01, 0x00,
    0x10, 0x01, 0x0B, 0xB2, 0x54, 0x0C, 0x91, 0x30, 0xBB, 0x6E, 0x51,
])

# Offsets relativos (contados a partir do fim do campo de nome dentro do
# .tac descomprimido) onde a analise diferencial encontrou o ajuste de
# "High Press", e as mascaras de XOR que reproduzem a mudanca real.
HIGH_PRESS_OFFSET_1 = 23
HIGH_PRESS_XOR_1 = 0xC0
HIGH_PRESS_OFFSET_2 = 27
HIGH_PRESS_XOR_2 = 0x10


def _tac_name_span(tac_plain: bytes) -> tuple[int, int]:
    """Retorna (inicio, fim) do campo de nome dentro do .tac descomprimido."""
    if tac_plain[:6] != bytes([3, 1]) + b"cat.":
        raise ValueError("conteudo nao parece um .tac valido (tag ausente)")
    name_len = struct.unpack_from("<I", tac_plain, 16)[0]
    start = 20
    return start, start + name_len


def apply_high_press(tac_plain: bytes) -> bytes:
    """Aplica a transformacao 'High Press' validada por analise diferencial."""
    _, name_end = _tac_name_span(tac_plain)
    out = bytearray(tac_plain)
    out[name_end + HIGH_PRESS_OFFSET_1] ^= HIGH_PRESS_XOR_1
    out[name_end + HIGH_PRESS_OFFSET_2] ^= HIGH_PRESS_XOR_2
    return bytes(out)


def _build_tactic_details_content(name: str, description: str, author: str) -> bytes:
    out = bytearray()
    out += DETAILS_MAGIC
    out += _string("TACTICS_TYPE_HANDLER")
    out += _string(name)
    out += _string(description)
    out += bytes(6)
    out += bytes([0xFF] * 16)
    out += _string(author)
    out += TACTIC_DETAILS_SUFFIX
    return bytes(out)


IMAGE_PLACEHOLDER = bytes([1, 0, 0, 0, 0, 0, 0, 0, 0, 0])


def _catalog_file_entry(resource) -> bytes:
    out = bytearray()
    out += _string(resource.base_name)
    out += _string(resource.extension)
    out += _i64(resource.offset)
    out += _i64(len(resource.stored_bytes))
    out += _i64(resource.raw_length)
    out += _i64(EMPTY_RESOURCE_TIMESTAMP)
    out += _i64(EMPTY_RESOURCE_TIMESTAMP)
    return bytes(out)


def write_tactic_fmf(name: str, tac_plain: bytes, description: str, author: str) -> bytes:
    details = _build_resource("_data/", "details", ".aom",
                               _build_tactic_details_content(name, description, author))
    image = _build_resource("", "image", ".img", IMAGE_PLACEHOLDER)
    tactic = _build_resource("", name, ".tac", tac_plain)

    offset = 0
    for resource in (details, image, tactic):
        resource.offset = offset
        offset += len(resource.stored_bytes)

    catalog_bytes = bytearray()
    catalog_bytes += _string(name)
    catalog_bytes += _u32(2)
    catalog_bytes += _catalog_file_entry(image)
    catalog_bytes += _catalog_file_entry(tactic)
    catalog_bytes += _u32(1)
    catalog_bytes += _string("_data")
    catalog_bytes += _u32(1)
    catalog_bytes += _catalog_file_entry(details)
    catalog_bytes += _u32(0)

    catalog = zstandard.ZstdCompressor().compress(bytes(catalog_bytes))
    catalog_offset = HEADER_SIZE + offset

    header = bytearray(HEADER_SIZE)
    header[0 : len(AFE_MAGIC)] = AFE_MAGIC
    struct.pack_into("<Q", header, 9, catalog_offset - 9)
    header[17] = 0x11
    header[25] = ARCHIVE_FORMAT

    archive = bytearray()
    archive += header
    for resource in (details, image, tactic):
        archive += resource.stored_bytes
    archive += CATALOG_MAGIC
    archive += catalog
    return bytes(archive)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("base_fmf", help="arquivo .fmf de tatica real, usado como base")
    ap.add_argument("--high-press", action="store_true",
                     help="aplica a transformacao 'High Press' validada")
    ap.add_argument("--name", help="novo nome (padrao: mesmo da base)")
    ap.add_argument("--description", default="Variante gerada por tools/fmf_write_tactic.py")
    ap.add_argument("--author", default="ModsFM26-24")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    base_data = open(args.base_fmf, "rb").read()
    root = read_catalog(base_data)
    tac_file = next((f for f in root.all_files() if f.extension == ".tac"), None)
    if tac_file is None:
        sys.exit("o arquivo base nao contem um recurso .tac")
    tac_plain = decrypt_resource(base_data, tac_file)

    if args.high_press:
        tac_plain = apply_high_press(tac_plain)

    name = args.name or Path(tac_file.base_name).stem or tac_file.base_name
    result = write_tactic_fmf(name, tac_plain, args.description, args.author)
    Path(args.out).write_bytes(result)
    print(f"escrito: {args.out} ({len(result)} bytes)")


if __name__ == "__main__":
    main()
