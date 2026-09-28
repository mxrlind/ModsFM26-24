#!/usr/bin/env python3
"""Extrator completo do formato de container .fmf da Football Manager.

Implementacao PROPRIA em Python do mecanismo descrito em
docs/reverse-engineering-log.md, cuja peca final (AES-CTR + onde a chave
fica guardada) foi descoberta lendo o codigo-fonte aberto do projeto
`JelmerBouma1985/fm-ai-assistent` (sem licenca no repositorio, portanto
codigo NAO copiado -- isto e uma reimplementacao independente a partir do
entendimento do formato, citando a fonte que revelou o mecanismo).

Formato (resumo -- ver docs/fm26-save-format.md e reverse-engineering-log.md
para o detalhamento completo):

    arquivo .fmf
      |- header (26 bytes): magic (6) + u16 + u8 + u64 "trailer_offset-9"
      |                     + u64 constante(17) + u8 "formato" (3 no FM26)
      |- [recursos, um atras do outro, cada um no formato "resource" abaixo]
      |- marcador de 9 bytes (magic "...fmf." + u16 + u8)
      \- catalogo comprimido (zlib no FM19, zstd no FM26): arvore de
         diretorios com nome/extensao/offset/tamanhos de cada recurso

    "resource" (o conteudo de cada arquivo listado no catalogo):
      u32 keyLen(=16) + u32 ivLen(=16) + 16 bytes chave AES + 16 bytes IV
      + ciphertext = AES/CTR/NoPadding(zstd.compress(conteudo_real))

Uso:
    python3 tools/fmf_extract.py arquivo.fmf --list
    python3 tools/fmf_extract.py arquivo.fmf --extract-all --out saida/
    python3 tools/fmf_extract.py arquivo.fmf --extract "3-3-3-1 Morphing System.tac" --out saida/
"""
from __future__ import annotations

import argparse
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path

try:
    import zstandard
except ImportError:
    zstandard = None

try:
    from Crypto.Cipher import AES
    from Crypto.Util import Counter
except ImportError:
    AES = None
    Counter = None

HEADER_SIZE = 26


@dataclass
class CatalogFile:
    directory: str
    base_name: str
    extension: str
    offset: int
    stored_length: int
    raw_length: int

    @property
    def file_name(self) -> str:
        return f"{self.directory}{self.base_name}{self.extension}"


@dataclass
class CatalogDirectory:
    name: str
    files: list[CatalogFile] = field(default_factory=list)
    directories: list["CatalogDirectory"] = field(default_factory=list)

    def all_files(self) -> list[CatalogFile]:
        out = list(self.files)
        for d in self.directories:
            out.extend(d.all_files())
        return out


class _Cursor:
    def __init__(self, data: bytes, offset: int = 0):
        self.data = data
        self.offset = offset

    def u32(self) -> int:
        (v,) = struct.unpack_from("<I", self.data, self.offset)
        self.offset += 4
        return v

    def i64(self) -> int:
        (v,) = struct.unpack_from("<q", self.data, self.offset)
        self.offset += 8
        return v

    def string(self) -> str:
        length = self.u32()
        if not (0 <= length <= 4096):
            raise ValueError(f"tamanho de string implausivel: {length}")
        s = self.data[self.offset : self.offset + length].decode("utf-8")
        self.offset += length
        return s

    def skip(self, n: int) -> None:
        self.offset += n


def _decompress_catalog(payload: bytes) -> bytes:
    """O catalogo pode vir em zlib (FM19) ou zstd (FM26)."""
    try:
        return zlib.decompress(payload)
    except zlib.error:
        pass
    if zstandard is None:
        raise RuntimeError("catalogo parece ser zstd, mas a lib 'zstandard' nao esta instalada")
    return zstandard.ZstdDecompressor().decompress(payload, max_output_size=64 * 1024 * 1024)


def _parse_directory(cursor: _Cursor, name: str, path: str) -> CatalogDirectory:
    file_count = cursor.u32()
    files = []
    for _ in range(file_count):
        base_name = cursor.string()
        extension = cursor.string()
        offset = cursor.i64()
        stored_length = cursor.i64()
        raw_length = cursor.i64()
        cursor.skip(16)  # dois campos de 8 bytes (timestamps / sentinela)
        files.append(CatalogFile(path, base_name, extension, offset, stored_length, raw_length))
    dir_count = cursor.u32()
    directories = []
    for _ in range(dir_count):
        child_name = cursor.string()
        directories.append(_parse_directory(cursor, child_name, f"{path}{child_name}/"))
    return CatalogDirectory(name, files, directories)


def read_catalog(data: bytes) -> CatalogDirectory:
    trailer_ptr = struct.unpack_from("<Q", data, 9)[0]
    trailer_offset = trailer_ptr + 9
    marker = data[trailer_offset : trailer_offset + 9]
    if marker[:2] != b"\x02\x01" or marker[2:6] != b"fmf.":
        raise ValueError(f"marcador de catalogo inesperado em {trailer_offset:#x}: {marker!r}")
    payload = data[trailer_offset + 9 :]
    catalog_bytes = _decompress_catalog(payload)
    cursor = _Cursor(catalog_bytes)
    root_name = cursor.string()
    return _parse_directory(cursor, root_name, "")


def decrypt_resource(data: bytes, catalog_file: CatalogFile) -> bytes:
    """Extrai e decodifica o conteudo real de um recurso do catalogo.

    Layout do recurso (bytes a partir de HEADER_SIZE + catalog_file.offset):
        u32 key_len (sempre 16) + u32 iv_len (sempre 16)
        + 16 bytes de chave AES + 16 bytes de IV
        + o resto = ciphertext AES/CTR/NoPadding de um blob zstd
    """
    if AES is None or Counter is None:
        raise RuntimeError("pycryptodome nao esta instalado (pip install pycryptodome)")
    if zstandard is None:
        raise RuntimeError("a lib 'zstandard' nao esta instalada (pip install zstandard)")

    abs_offset = HEADER_SIZE + catalog_file.offset
    raw = data[abs_offset : abs_offset + catalog_file.stored_length]
    key_len, iv_len = struct.unpack_from("<II", raw, 0)
    if key_len != 16 or iv_len != 16:
        raise ValueError(f"tamanho de chave/IV inesperado: {key_len}/{iv_len}")
    key = raw[8:24]
    iv = raw[24:40]
    ciphertext = raw[40:]

    counter = Counter.new(128, initial_value=int.from_bytes(iv, "big"))
    cipher = AES.new(key, AES.MODE_CTR, counter=counter)
    compressed = cipher.decrypt(ciphertext)

    dctx = zstandard.ZstdDecompressor()
    plaintext = dctx.decompress(compressed, max_output_size=max(catalog_file.raw_length, 1024))
    if len(plaintext) != catalog_file.raw_length:
        raise ValueError(
            f"tamanho descomprimido nao bate: esperado {catalog_file.raw_length}, obtido {len(plaintext)}"
        )
    return plaintext


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path")
    ap.add_argument("--list", action="store_true", help="lista os recursos do catalogo")
    ap.add_argument("--extract", metavar="FILENAME", help="extrai um recurso especifico (nome completo, ex.: '3-3-3-1 Morphing System.tac')")
    ap.add_argument("--extract-all", action="store_true", help="extrai todos os recursos")
    ap.add_argument("--out", default=".", help="diretorio de saida para extracao")
    args = ap.parse_args()

    data = open(args.path, "rb").read()
    root = read_catalog(data)
    files = root.all_files()

    if args.list or not (args.extract or args.extract_all):
        print(f"catalogo: {root.name!r}")
        for f in files:
            print(f"  {f.file_name:40s} offset_abs={HEADER_SIZE + f.offset:#x} "
                  f"armazenado={f.stored_length:6d} bytes  real={f.raw_length:6d} bytes")

    out_dir = Path(args.out)
    targets = files if args.extract_all else [f for f in files if args.extract and f.file_name == args.extract]
    for f in targets:
        plaintext = decrypt_resource(data, f)
        out_path = out_dir / f.file_name
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(plaintext)
        print(f"extraido: {f.file_name} -> {out_path} ({len(plaintext)} bytes)")


if __name__ == "__main__":
    main()
