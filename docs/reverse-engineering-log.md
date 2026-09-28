# Log de engenharia reversa — arquivos do FM26

Acompanha a investigação descrita em `docs/fm26-editor-format.md`, seguindo
o fluxo:

```
arquivo FM26
  -> [1] identificar formato
  -> [2] analisar bytes
  -> [3] descobrir cabecalho
  -> [4] descobrir compressao/criptografia
  -> [5] localizar estruturas
  -> [6] identificar tipos de dados
  -> [7] criar parser
  -> [8] exportar JSON/CSV
```

## Status atual

O sandbox de desenvolvimento não tem o FM26 instalado (é um container Linux
headless; o jogo só roda em Windows/Mac via Steam/Epic/MS Store) e ninguém
subiu ainda um `.fmf`/`.xml` de editor data ou um save (`.fm`) **do FM26**
pra dentro da sessão. Ferramentas como HxD e Ghidra também não existem aqui
(GUI/Windows).

O que **está disponível** neste ambiente: `python3`, `file`, `strings`, e
acesso de rede a `github.com`/`raw.githubusercontent.com` — suficiente para
as fases 1 a 6 do fluxo acima, todas scriptáveis, **e** para achar amostras
reais publicadas por outros projetos (ver fases 1 e 2 abaixo, já feitas).

### Duas fontes externas já exploradas (2026-09-28)

1. **[rhiever/fmsave](https://github.com/rhiever/fmsave)** (MIT) — não é
   uma amostra de arquivo, é uma **especificação executável** do formato do
   *save* do FM26 (`.fm`), extraída dos "test fixtures" do próprio projeto
   (construtores de bytes escritos manualmente, sem usar o parser, pra
   validar o parser real). Detalhes completos em
   `docs/fm26-save-format.md`. Resolve as fases 1-6 inteiras pro `.fm`, sem
   precisarmos ter o jogo.
2. **[quarterback/FM-Files](https://github.com/quarterback/FM-Files)** —
   tem um `.fmf` real de verdade (`Neloxia_FM19.fmf`, 138.860 bytes), só que
   do **FM19** (2018), não do FM26. Usamos ele como cobaia — ver estudo de
   caso abaixo. Não achamos (ainda) nenhum `.fmf`/`.xml` de editor data
   específico do FM26 em repositório público.

### O que ainda falta pra fechar o ciclo

- Um `.fmf` ou `.xml` de editor data **do FM26** (Pre-Game Editor). Se
  alguém subir um pro chat, ou linkar um repositório público que tenha um,
  já temos ferramenta pronta pra atacar.
- Idealmente dois arquivos quase idênticos, com uma mudança controlada só
  (ex.: idade de um jogador), pra rodar `diff_bytes.py` — mas mesmo um
  arquivo único já ajuda bastante (dá pra testar a hipótese do envelope
  compartilhado, ver abaixo).

## Ferramentas prontas em `tools/`

| Script | Fase do fluxo | O que faz |
|---|---|---|
| `tools/binary_inspect.py` | 1, 2, 3, 4 | Hexdump do início do arquivo, checa magic numbers conhecidos (ZIP/7z/GZIP/ZLIB/etc.), calcula entropia de Shannon (alta entropia ⇒ provável compressão/criptografia) e extrai strings ASCII legíveis. |
| `tools/diff_bytes.py` | 4, 5 | Análise diferencial entre dois arquivos: agrupa bytes divergentes em "runs" (não byte a byte solto) e tenta decodificar cada run como inteiro LE/BE, signed/unsigned. |
| `tools/endian_check.py` | 6 | Dado um hex qualquer, mostra todas as interpretações plausíveis (int 1/2/4/8 bytes, LE/BE, signed/unsigned, float32/64, ASCII, UTF-16LE) pra bater com o valor esperado. |

Uso típico assim que os arquivos chegarem:

```bash
python3 tools/binary_inspect.py exemplo.fmf --out strings.txt
python3 tools/diff_bytes.py base_A.fmf base_B.fmf
python3 tools/endian_check.py "40 e2 01 00"
```

## Estudo de caso: `Neloxia_FM19.fmf` (real, mas de FM19)

Baixado de `quarterback/FM-Files` e analisado com `tools/binary_inspect.py`
+ scripts Python ad-hoc, comparando contra a spec do container do FM26
(`docs/fm26-save-format.md`). Objetivo: testar a hipótese de que o `.fmf`
do editor usa o **mesmo envelope de container** que o `.fm` de save.

### Confirmado ✅

- **Cabeçalho de 26 bytes**, exatamente como no FM26: `magic(6) + u16 + u8 +
  u64 + u64 + u8`. Os dois campos `u64` bateram em posição e um deles
  (offset 17, valor `17`) é **idêntico** ao valor constante visto na spec
  do FM26 — mesmo formato, 7 anos de distância entre os jogos.
- O primeiro `u64` do cabeçalho (offset 9) é de novo `trailer_offset - 9`,
  igual ao FM26: `138706 = 138715 - 9`, e o trailer realmente começa em
  `138715` (bytes finais do arquivo).
- **Achamos e decodificamos o trailer**: no offset calculado (`138715`)
  existe o marcador de 9 bytes esperado, seguido por dados **zlib**
  (`78 9c`, cabeçalho clássico de zlib "default compression" — diferente
  do FM26, que usa zstd). Descomprimimos com sucesso e o resultado é um
  **diretório 100% legível**: nome do arquivo (`Neloxia_FM19`), e entradas
  com nome + extensão + offset + tamanho comprimido + tamanho
  descomprimido + dois campos extras que parecem timestamps (não zero,
  diferente do que o fixture do FM26 assume pra esses campos).
- Extensões internas encontradas: `.dbc` (o banco de dados em si, ~121 KB),
  `.jpg` (uma imagem, provavelmente escudo de time), `.aom` (desconhecido),
  e entradas chamadas `_data`/`details` sem offset claro.
- Os "dois campos extras" de cada entrada do diretório **são timestamps
  Unix**: decodificados dão `2019-06-02` a `2019-06-10`, exatamente a época
  em que esse mod de FM19 teria sido feito. Confirma que não são zero/lixo
  (como o fixture de teste do FM26 assume por simplicidade), e sim
  metadados reais de criação/modificação por entrada.
- **Conclusão prática:** o "envelope" de container (header pequeno com
  magic + ponteiro pro trailer, corpo com frames comprimidos, trailer no
  final com um diretório nomeado) parece ser uma peça de infraestrutura
  estável da Sports Interactive, reusada desde pelo menos FM19 até FM26,
  tanto pra saves quanto (aparentemente) pra exports do editor. O que muda
  entre versões é o **codec de compressão** (zlib no FM19 → zstd no FM26)
  e o conteúdo interno de cada seção.

### Ainda em aberto ❓

- O **conteúdo comprimido de cada entrada individual** (`.dbc`, `.jpg`)
  não abre com `zlib.decompress` nem com deflate raw nos offsets
  calculados (`HEADER_SIZE + relative_offset`), mesmo variando o start em
  alguns bytes. As duas entradas testadas começam com o mesmo prefixo de 8
  bytes (`10 00 00 00 10 00 00 00`), que também aparece bit-a-bit idêntico
  logo no início do corpo do arquivo (offset 26) — provavelmente uma
  mini-estrutura fixa (2× `u32`) antes do fluxo comprimido de verdade, cujo
  significado não identificamos ainda.
- Depois desse prefixo os bytes têm entropia máxima e não batem com
  nenhuma assinatura conhecida — consistente com o que a comunidade sempre
  falou sobre o `.fmf`: "proprietário, não dá pra abrir com editor de
  texto". Pode ser criptografia real (não só compressão), ou um dialeto de
  compressão sem magic bytes que não testamos ainda.
- **zstd testado e descartado** para o conteúdo das entradas deste arquivo
  FM19: nenhuma ocorrência do magic real do zstd (`28 B5 2F FD`) em lugar
  nenhum do arquivo, e a lib `zstandard` rejeita os bytes em todos os
  offsets testados (`skip` 0/8/16) com "Unknown frame descriptor" — não é
  um frame zstd válido, nem com deslocamento. Faz sentido: esse `.fmf` é de
  2018/2019, e o zstd só aparece confirmado no formato de *save* do FM26
  (via `fmsave`). Pra um `.fmf` do FM26 de verdade, ainda vale testar zstd
  primeiro (é a hipótese mais forte pra essa geração do jogo) — só não se
  aplica a esta amostra antiga.

## Tabela de hipóteses

| Offset | Bytes | Hipótese | Confiança | Validação |
|---|---|---|---|---|
| 0-5 | `02 01` + 4 bytes | "magic" do container; os 4 bytes finais variam (`afe.` no início do arquivo FM19, `fmf.` no marcador do trailer) — não é uma string fixa universal | Alta (estrutura) / Média (significado exato dos 4 bytes) | Confirmado em `Neloxia_FM19.fmf` e cruzado com `fmsave` (FM26) |
| 9 (u64) | — | `trailer_offset - 9` | Alta | Bateu exato em `Neloxia_FM19.fmf` (138706 = 138715-9) e é a fórmula documentada no `fmsave` |
| 17 (u64) | `11 00 00 00 00 00 00 00` | Constante `17`, significado desconhecido | Média | Valor idêntico em FM19 e no fixture do FM26 |
| corpo, +0 de cada frame | `10 00 00 00 10 00 00 00` | Mini-header de 8 bytes (2× u32) antes do payload comprimido de cada seção/entrada | Baixa | Visto repetido em 2 posições diferentes do mesmo arquivo; significado não decifrado |
| trailer | zlib (`78 9c`) no FM19 | Codec de compressão do trailer/corpo mudou por versão (zlib → zstd) | Média-Alta | Confirmado no FM19 via decompressão bem-sucedida; extrapolado pro FM26 via `fmsave` |
| corpo das entradas (FM19) | alta entropia, sem magic | Não é zstd | Alta (descartado) | `zstandard` rejeita em todos os offsets testados; zero ocorrências do magic `28 B5 2F FD` no arquivo inteiro |
| diretório, 2 últimos `u64` de cada entrada | ex.: `1560165027` | Timestamps Unix (criação/modificação da entrada) | Alta | Decodificados batem com junho/2019, época real do mod testado |

## Achados confirmados

- Estrutura de cabeçalho de 26 bytes e esquema de trailer-no-final são
  compartilhados entre o save do FM26 (via `fmsave`) e um `.fmf` de editor
  real do FM19 — forte indício de que é a mesma "camada de container" da
  SI, reaproveitada entre save e editor data, e entre gerações do jogo.
- Conseguimos extrair um diretório real e legível (nomes/extensões/offsets)
  de dentro de um `.fmf` sem nenhuma ferramenta oficial, só com Python +
  zlib da standard library.
