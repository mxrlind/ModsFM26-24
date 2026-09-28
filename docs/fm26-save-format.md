# Formato do save do FM26 (`.fm`) — já reverse-engineered, com fonte

> **TL;DR:** não precisamos reverse-engenheirar o save do zero. O projeto
> open-source **[fmsave](https://github.com/rhiever/fmsave)** (MIT License,
> Randal S. Olson) já fez isso — e melhor: os *test fixtures* do próprio
> repositório constroem os bytes do formato manualmente (sem usar o parser),
> byte a byte, exatamente pra garantir que o parser real bate com o formato
> observado. Isso funciona como uma especificação executável do formato.
>
> Achado em 2026-09-28, direto do GitHub (`raw.githubusercontent.com`, que é
> um dos poucos domínios que este ambiente consegue acessar). Todo o conteúdo
> abaixo é extraído/resumido de código-fonte real do `fmsave`, não é
> especulação nossa.

## Onde isso vem

- `src/fmsave/_container.py` — leitor real do container (produção).
- `tests/fixtures/container.py` — constrói o container **manualmente**, sem
  importar `fmsave`, exatamente pra testar o leitor real contra bytes
  conhecidos. **Nunca importa o próprio fmsave** — comentário no código:
  *"a wrong offset inside fmsave has to fail tests built here"*.
- `tests/fixtures/game_db.py` — mesma ideia, mas para os registros de
  jogador, clube, contrato, etc. dentro da seção `game_db`.
- Licença: **MIT** (`Copyright (c) 2026 Randal S. Olson`) — uso, cópia,
  modificação e redistribuição livres, com atribuição.

## 1. Container (nível de arquivo)

> *"A save is a 26-byte header, a run of Zstandard frames, and a trailer
> holding one frame whose payload lists the named frames (the directory)."*
> — `src/fmsave/_container.py`

```
FILE_MAGIC  = b"\x02\x01fmf."     # 6 bytes — repare: contem literalmente "fmf."
HEADER_SIZE = 26 bytes
```

**Header (26 bytes):**

```
FILE_MAGIC (6 bytes)
+ struct "<HBQQB":
    u16  = 8            # versao? constante observada
    u8   = 0
    u64  = trailer_offset - 9
    u64  = 17           # constante observada
    u8   = 3            # constante observada
```

**Corpo:** uma sequência de *frames* comprimidos com **Zstandard (zstd)**,
um atrás do outro, sem cabeçalho próprio por frame (o offset/tamanho de cada
um só existe no diretório, no final do arquivo). Cada frame corresponde a
uma "seção" nomeada (`game_info`, `save_game_summary`, `game_db`, `humans`,
etc.) ou a um "anexo" (ex.: `.apm`, `.scm` — arquivos por partida).

Também podem existir **frames "não listados"** intercalados no meio do
stream — inclusive *skippable frames* do próprio Zstandard (magic
`0x184D2A50`–`0x184D2A5F`, do spec oficial do zstd), que o diretório não
referencia diretamente.

**Trailer (rodapé, não cabeçalho!):** um marcador de 9 bytes
(`FILE_MAGIC + u16(8) + u8(0)`) seguido por **um frame zstd** cujo payload
descomprimido é o **diretório**:

```
length_prefixed(save_name)      # u32 tamanho + utf-8, sem terminador nulo
u32 (campo ainda nao identificado)
para cada entrada (em ordem REVERSA de escrita):
    u32 len(nome) + nome (ascii)
    u32(4) + extensao (4 chars ascii, ex.: ".dat", ".cmt", ".apm")
    u64 offset_relativo   (relativo ao fim do header, 26 bytes)
    u64 tamanho_comprimido
    u64 tamanho_descomprimido
    u64 0   (nao identificado)
    u64 0   (nao identificado)
16 bytes de padding no final
```

**"Seções" conhecidas** (vistas no fixture `default_sections()`):

| Nome | Extensão | Conteúdo |
|---|---|---|
| `game_info` | `.dat` | versão do banco (`"26.2.0+0"`), 3 build numbers, data in-game (dia do ano + slot de tempo + ano), lista de "migration names" (patches aplicados) |
| `memory_pools` | `.dat` | interno do engine, não modelado pelo fmsave |
| `save_game_summary` | `.dat` | nome do manager, liga, versão do save, nome do clube — o que aparece na tela de "load game" |
| `game_db` | `.dat` | **o banco de dados propriamente dito**: clubes, jogadores, competições, etc. (ver seção 2) |
| `non_pl_hist_ls` | `.dat` | histórico de entidades não jogáveis; tem frames zstd extras "não listados" logo depois |
| `humans` | `.dat` | contagem de "humanos" (managers controlados por jogador) + seletor |
| `tc_history_dt` | `.cmt` | histórico (extensão diferente — `.cmt`, não `.dat`) |

Cada corpo de seção, antes de comprimir, tem esse envelope:

```
b"\x03\x01" + extensao_invertida (ex.: ".dat" -> "tad.") + u16 schema + payload
```

## 2. Dentro do `game_db` — jogadores, clubes e mais

Layout geral: `64 bytes zero` + registros de clube + `gap` de zeros (tamanho
variável) + registros de status de clube + pares de ID de competição +
"tagged stream" + tabela de estágios (perto do fim do arquivo).

### Registro de jogador (`player_record_bytes`)

Cabeçalho (26 bytes) + corpo (300 bytes). Offsets do **corpo**:

| Offset | Campo | Tipo |
|---|---|---|
| 0 | Current Ability (CA) | u16 |
| 2 | Potential Ability (PA) | i16 (**signed**) |
| 8 | "bucket" | u8 |
| 16 | `team_id` | u32 |
| 24 | ratings (bloco bruto) | bytes |
| **39** | **atributos crus (raw_attributes)** | bytes — aqui começam os atributos técnicos/mentais/físicos |
| 93 | valor de transferência (cru) | u32 |
| 98 | data de contratação (join_date) | date4 |
| 102 | marcador de registro válido (`01 00 6c 07`) | 4 bytes |
| 106 | sharpness | u16 |
| 110 | condition | u16 |
| 121 | altura (cm) | u8 |

O UID do jogador aparece **duplicado** no cabeçalho (padrão comum no
formato — vale testar em outros registros também).

### Bloco de pessoa (`person_block_bytes`) — nome, nação, personalidade

Contém: bits de traço (u64), 3 IDs de nome (referenciando pools — ver
abaixo) para primeiro nome / sobrenome / nome comum, nome legal
(string com tamanho prefixado), data de nascimento (`date4`), nação (u16),
bytes de personalidade (bloco bruto), e uma lista de "relações" (16 bytes
cada: valor referenciado + tipo + papel + qualificador).

### Pools de nomes (`name_pools_bytes`)

Três pools (nomes, sobrenomes, "nomes comuns"), cada um:
`u32 count` + N × (`u32 id`, `u32 tamanho`, nome em UTF-8).

### Registro de clube (`club_record_bytes`)

```
u32 club_index-1, u32 uid-1, u32 uid-1 (duplicado)
u8  0
u32 nation_id
4 bytes  FF FF FF FF   <- "ancora" no offset 17, usada pra localizar o registro
u32 fa_nation_id, u32 nation_id (de novo), u32 city_id
6 bytes zero
string com tamanho prefixado: nome completo
string com tamanho prefixado: nome curto
16 bytes zero
[bloco de lista de times: datas, floats, ids dos times do clube + afiliados]
[opcional: listas de staff]
[bytes finais: cadeias de financas/patrocinio]
```

### Data (`date4`) — formato usado em todo lugar

```python
def packed_date(day_of_year, year, time_slot=0):
    return struct.pack("<HH", day_of_year | (time_slot << 9), year)
```
4 bytes: `u16` (dia-do-ano combinado com um "time slot" nos bits altos) +
`u16` (ano).

### Outras estruturas mapeadas (menos críticas pra scouting, mas documentadas)

- **Registro de status de clube** (86 bytes) — posição na liga, reputação.
- **Tabela de estágios de competição** (linhas de 33 bytes) — fases/rodadas.
- **Pares de ID de competição** (registro de 30+ bytes com marcador `FF×16 + 01`).
- **Cadeia de contrato** — salário, datas, cláusulas de bônus por competição/prêmio.
- **Registro de partida por jogador** — 15 bytes se não jogou, 43 bytes se
  jogou (posição, papel, gols, assistências, minutos, nota×10, passes).
- **Suspensão** — registro fixo de 20 bytes.

## 3. Isso é o SAVE, não o mod

Repetindo o ponto já levantado em `docs/fm26-editor-format.md`: isso é o
formato do **save** (carreira em andamento) — perfeito pra construir uma
ferramenta de **scouting/análise** (ler o save e extrair dados). **Não** é o
formato de **editor data** (`.fmf`/XML `db_changes`) usado para criar e
distribuir mods de banco de dados — esse continua sem uma fonte equivalente
confirmada.

**Hipótese em aberto, ainda não testada:** o `FILE_MAGIC` do save contém
literalmente `"fmf."`. É bem possível que os arquivos `.fmf` do editor usem
o **mesmo envelope de container** (header + frames zstd + trailer com
diretório) e só troquem os *nomes de seção* e os *schemas* internos. Se
conseguirmos uma amostra real de `.fmf` do Pre-Game Editor, o primeiro teste
óbvio é rodar `tools/binary_inspect.py` nela e conferir se os 6 primeiros
bytes batem com `02 01 66 6d 66 2e`.

## 4. Recomendação prática

Para **extrair dados de saves** (scouting, dashboards, assistente de
análise): **não vale reimplementar isso do zero.** Instalar e usar o
`fmsave` diretamente é mais rápido e mais confiável do que reconstruir o
parser via engenharia reversa manual — ele já trata os casos extremos
(managers de seleção sem clube, registros sem "marker", UUIDs duplicados,
etc.) que só aparecem depois de muito teste.

```bash
pip install fmsave
```

```python
import fmsave

with fmsave.open("career.fm") as save:
    squad = save.players().where(club_uid=meu_clube.club_uid)
    squad.write_csv("squad.csv")
```

Se precisarmos ler **campos que o fmsave ainda não expõe**, dá pra usar
`src/fmsave/_container.py` como referência de baixo nível (ele é MIT, então
também podemos vendorizar/adaptar trechos citando a fonte) em vez de
redescobrir o container do zero.

## Fontes

- [github.com/rhiever/fmsave](https://github.com/rhiever/fmsave) (MIT License)
- [`src/fmsave/_container.py`](https://raw.githubusercontent.com/rhiever/fmsave/main/src/fmsave/_container.py)
- [`tests/fixtures/container.py`](https://raw.githubusercontent.com/rhiever/fmsave/main/tests/fixtures/container.py)
- [`tests/fixtures/game_db.py`](https://raw.githubusercontent.com/rhiever/fmsave/main/tests/fixtures/game_db.py)
- [`fuzz/README.md`](https://raw.githubusercontent.com/rhiever/fmsave/main/fuzz/README.md)
