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

**Bloqueado na fase 0 (ambiente de testes):** o sandbox de desenvolvimento
não tem o FM26 instalado (é um container Linux headless; o jogo só roda em
Windows/Mac via Steam/Epic/MS Store) e não veio nenhum arquivo `.fmf`,
`.xml` de editor data ou save (`.fm`) junto com o repositório. Ferramentas
como HxD e Ghidra também não existem aqui (GUI/Windows).

O que **está disponível** neste ambiente: `python3`, `file`, `strings` —
suficiente para as fases 1 a 6 do fluxo acima, todas scriptáveis.

### O que falta pra destravar

Subir pra dentro da sessão (anexando no chat) pelo menos um par de arquivos
com uma mudança controlada isolada, por ex.:

- Dois `.fmf`/`.xml` de editor data (Pre-Game Editor), a única diferença
  sendo um campo só (ex.: idade de um jogador) —
  `Documents/Sports Interactive/Football Manager 26/editor data/`
- E/ou dois saves `.fm`, mesma ideia —
  `Documents/Sports Interactive/Football Manager 26/games/`

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

## Tabela de hipóteses

Preencher conforme formos descobrindo (padrão sugerido: offset, bytes
observados, hipótese, confiança, como foi validada).

| Offset | Bytes | Hipótese | Confiança | Validação |
|---|---|---|---|---|
| — | — | — | — | — |

## Achados confirmados

_(nada ainda — preencher conforme a investigação avançar)_
