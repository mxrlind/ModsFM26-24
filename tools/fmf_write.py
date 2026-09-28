#!/usr/bin/env python3
"""Escreve um arquivo .fmf de shortlist do zero (formato FM26).

Implementacao PROPRIA em Python do mecanismo descrito em
docs/reverse-engineering-log.md (secao "FORMATO RESOLVIDO"). O layout de
bytes (magic numbers, offsets, a constante GUID em DETAILS_SUFFIX) foi
entendido lendo o codigo-fonte aberto do projeto
`JelmerBouma1985/fm-ai-assistent` (sem licenca no repositorio -- este
modulo NAO copia o codigo Java, e uma reescrita a partir do entendimento
do formato de arquivo, que e o objeto legitimo de engenharia reversa pra
interoperabilidade).

Escolhemos "shortlist" como primeiro alvo de escrita porque, dos tipos de
`.fmf` que decifiamos, e o unico cujo esquema INTERNO completo (o que vai
dentro do recurso .slf: nome + lista de IDs de jogador) tambem esta
mapeado -- outros tipos como tatica (.tac) so tiveram a camada externa
(zstd+AES) decifrada, nao a estrutura interna dos atributos/instrucoes.

Uso:
    python3 tools/fmf_write.py "Minha Shortlist" 1001 1002 1003 --out saida.fmf
"""
from __future__ import annotations

import argparse
import struct
from dataclasses import dataclass
from pathlib import Path

import zstandard
from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes
from Crypto.Util import Counter

from fmf_extract import HEADER_SIZE, read_catalog, decrypt_resource

AFE_MAGIC = bytes([2, 1]) + b"afe." + bytes([8, 0, 0])
CATALOG_MAGIC = bytes([2, 1]) + b"fmf." + bytes([8, 0, 0])
SHORTLIST_MAGIC = bytes([3, 1]) + b"fls."
DETAILS_MAGIC = bytes([3, 1]) + b"moa." + bytes([4, 0])
IMAGE_PLACEHOLDER = bytes([1, 0, 0, 0, 0, 0, 0, 0, 0, 0])
ARCHIVE_FORMAT = 3
# Constante estrutural (parece um GUID/CLSID interno do "Application Object
# Model" da SI) exigida logo apos o nome da ferramenta no recurso "details".
# Reproduzida aqui por ser um valor fixo de formato, nao expressao criativa.
DETAILS_SUFFIX = bytes([
    2, 0, 1, 0, 2, 0xCD, 0xC7, 0xD3, 0x11, 1, 0,
    0x10, 1, 0x0B, 0x6D, 7, 0x2E, 1, 0xB6, 0x64, 0x0B, 0x5E,
])
FM26_DATABASE_VERSION = 0x006281A3
EMPTY_RESOURCE_TIMESTAMP = -62_135_596_800  # sentinela ("data vazia"), visto em amostras reais
TOOL_NAME = "ModsFM26-24 fmf_write.py"


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _i64(value: int) -> bytes:
    return struct.pack("<q", value)


def _string(value: str) -> bytes:
    encoded = value.encode("utf-8")
    return _u32(len(encoded)) + encoded


@dataclass
class _Resource:
    directory: str
    base_name: str
    extension: str
    raw_length: int
    stored_bytes: bytes
    offset: int = 0

    def file_name(self) -> str:
        return f"{self.directory}{self.base_name}{self.extension}"


def _encrypt_resource(raw_bytes: bytes) -> bytes:
    """Espelha decrypt_resource() de fmf_extract.py, na direcao inversa."""
    key = get_random_bytes(16)
    iv = get_random_bytes(16)
    compressed = zstandard.ZstdCompressor().compress(raw_bytes)
    counter = Counter.new(128, initial_value=int.from_bytes(iv, "big"))
    cipher = AES.new(key, AES.MODE_CTR, counter=counter)
    ciphertext = cipher.encrypt(compressed)
    return _u32(16) + _u32(16) + key + iv + ciphertext


def _build_resource(directory: str, base_name: str, extension: str, raw_bytes: bytes) -> _Resource:
    stored = _encrypt_resource(raw_bytes)
    return _Resource(directory, base_name, extension, len(raw_bytes), stored)


def _build_shortlist_content(name: str, unique_ids: list[int]) -> bytes:
    out = bytearray()
    out += SHORTLIST_MAGIC
    out += bytes([2, 0, 1])
    out += _u32(FM26_DATABASE_VERSION)
    out += _string(name)
    out += _u32(len(unique_ids))
    for uid in unique_ids:
        out += _u32(uid)
    out += bytes([0])
    return bytes(out)


def _build_details_content(type_handler: str, name: str) -> bytes:
    out = bytearray()
    out += DETAILS_MAGIC
    out += _string(type_handler)
    out += _string(name)
    out += bytes(10)
    out += bytes(16)
    # os ultimos 16 bytes escritos ate aqui viram 0xFF (visto em amostras reais)
    out[-16:] = bytes([0xFF] * 16)
    out += _string(TOOL_NAME)
    out += DETAILS_SUFFIX
    return bytes(out)


def _catalog_file_entry(resource: _Resource) -> bytes:
    out = bytearray()
    out += _string(resource.base_name)
    out += _string(resource.extension)
    out += _i64(resource.offset)
    out += _i64(len(resource.stored_bytes))
    out += _i64(resource.raw_length)
    out += _i64(EMPTY_RESOURCE_TIMESTAMP)
    out += _i64(EMPTY_RESOURCE_TIMESTAMP)
    return bytes(out)


def _build_catalog(root_name: str, image: _Resource, shortlist: _Resource, details: _Resource) -> bytes:
    out = bytearray()
    out += _string(root_name)
    out += _u32(2)  # arquivos na raiz: image, shortlist
    out += _catalog_file_entry(image)
    out += _catalog_file_entry(shortlist)
    out += _u32(1)  # 1 subdiretorio: "_data"
    out += _string("_data")
    out += _u32(1)  # 1 arquivo dentro de "_data": details
    out += _catalog_file_entry(details)
    out += _u32(0)  # "_data" nao tem subdiretorios
    return bytes(out)


def write_fmf(shortlist_name: str, player_unique_ids: list[int]) -> bytes:
    if not shortlist_name.strip():
        raise ValueError("shortlist_name nao pode ser vazio")
    if not player_unique_ids:
        raise ValueError("informe pelo menos um ID de jogador")

    details = _build_resource("_data/", "details", ".aom", _build_details_content(
        "PLAYER_SHORTLIST_TYPE_HANDLER", shortlist_name))
    image = _build_resource("", "image", ".img", IMAGE_PLACEHOLDER)
    shortlist = _build_resource("", shortlist_name, ".slf",
                                 _build_shortlist_content(shortlist_name, player_unique_ids))

    # ordem fisica no arquivo: details, image, shortlist (como no formato real)
    offset = 0
    for resource in (details, image, shortlist):
        resource.offset = offset
        offset += len(resource.stored_bytes)

    catalog = zstandard.ZstdCompressor().compress(_build_catalog(shortlist_name, image, shortlist, details))
    catalog_offset = HEADER_SIZE + offset

    header = bytearray(HEADER_SIZE)
    header[0 : len(AFE_MAGIC)] = AFE_MAGIC
    struct.pack_into("<Q", header, 9, catalog_offset - 9)
    header[17] = 0x11
    header[25] = ARCHIVE_FORMAT

    archive = bytearray()
    archive += header
    for resource in (details, image, shortlist):
        archive += resource.stored_bytes
    archive += CATALOG_MAGIC
    archive += catalog
    return bytes(archive)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name", help="nome da shortlist")
    ap.add_argument("player_ids", nargs="+", type=int, help="FM Unique IDs dos jogadores")
    ap.add_argument("--out", required=True, help="arquivo .fmf de saida")
    args = ap.parse_args()

    data = write_fmf(args.name, args.player_ids)
    Path(args.out).write_bytes(data)
    print(f"escrito: {args.out} ({len(data)} bytes)")


if __name__ == "__main__":
    main()
