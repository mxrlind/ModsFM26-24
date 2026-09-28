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

## 🔓 FORMATO RESOLVIDO (2026-09-28)

Depois de descartar experimentalmente zlib, zstd puro, zstd "magicless",
LZ4 (frame/legacy/block), brotli e XOR (chave única, repetida de 1 a 64
bytes, fixa ou como keystream contínuo) para o conteúdo das entradas do
`.fmf`, a resposta certa apareceu ao pesquisar o projeto open-source
**[JelmerBouma1985/fm-ai-assistent](https://github.com/JelmerBouma1985/fm-ai-assistent)**
(sem arquivo de licença no repositório — código **não copiado**, apenas
estudado; a implementação abaixo em `tools/fmf_extract.py` é nossa,
reescrita do zero a partir do entendimento do mecanismo, o que é prática
padrão e legítima de engenharia reversa pra interoperabilidade — formatos e
algoritmos não são protegidos por direito autoral, só a expressão de código
específica é). O arquivo-chave foi
`src/main/java/com/github/fmaiassistent/shortlist/FmfShortlistFile.java`.

### O mecanismo real

Cada recurso listado no catálogo (o que a gente vinha chamando de
"entrada") não é só comprimido — é **comprimido com zstd e depois
criptografado com AES-128 em modo CTR**, com uma peça crucial: **a chave
AES e o IV são gerados aleatoriamente por recurso e guardados em texto
puro, sem nenhuma proteção, logo no início do próprio recurso**:

```
u32 tamanho_da_chave (sempre 16)
u32 tamanho_do_IV (sempre 16)
16 bytes: chave AES-128, em claro
16 bytes: IV (usado como contador inicial do modo CTR), em claro
resto: ciphertext = AES/CTR/NoPadding(zstd.compress(conteúdo_real))
```

**Isso explica tudo que a gente vinha vendo e não conseguia decifrar:**

- O misterioso prefixo constante `10 00 00 00 10 00 00 00` que aparecia
  antes de toda entrada, em todo arquivo testado (FM19 e FM26)? Não é um
  "mini-header" nem uma seção de tipo — é literalmente
  `u32(16) + u32(16)`, os tamanhos de chave e IV, que são **sempre 16**
  (AES-128), por isso pareciam uma constante universal.
- Por que todo teste de XOR (1 byte, chave repetida de qualquer tamanho,
  por índice, com ou sem reinício por entrada) falhava de forma
  consistente e sem nenhum padrão? Porque a gente estava tentando
  descriptografar byte a byte a partir do offset errado — os 32 bytes
  logo depois do prefixo de 16/16 **são a própria chave e o IV, gerados
  aleatoriamente a cada recurso**, não o início do conteúdo cifrado. Não
  existe XOR fixo porque não é XOR: é AES de verdade, com chave nova a
  cada arquivo — só que essa chave está a poucos bytes de distância, sem
  nenhuma proteção.
- Por que zstd/LZ4/brotli "quase batiam" (o "magicless" chegou a passar da
  checagem inicial) mas nunca fechavam? Porque o zstd real só começa
  *depois* de descriptografar com AES — sem a chave (que está bem ali do
  lado, só não estávamos olhando pra ela do jeito certo), qualquer tentativa
  de descomprimir direto o ciphertext é, na prática, tentar descomprimir
  ruído aleatório.

### Testado e confirmado, com decriptografia real

Implementei o mecanismo em `tools/fmf_extract.py` (Python puro, usa
`pycryptodome` pro AES-CTR e `zstandard` pro zstd) e rodei contra o mesmo
arquivo real do FM26 que já vínhamos usando
(`3-3-3-1 Morphing System.fmf`, de `Glawster/fmsat`). Resultado —
**as 3 entradas descriptografam com sucesso**, incluindo a que estava
"escondida" numa subpasta que nosso parser antigo (plano, sem recursão)
nem alcançava:

- `image.img` → 10 bytes, batendo exatamente com o placeholder de "sem
  imagem" que o código-fonte usa (`{1,0,0,0,0,0,0,0,0,0}`).
- `3-3-3-1 Morphing System.tac` → 5120 bytes de conteúdo estruturado de
  baixa entropia (contra ~7.8 bits/byte antes de descriptografar), com a
  string `"CustomLLUNB"` e o nome da tática em claro.
- `_data/details.aom` → 348 bytes **totalmente legíveis em inglês**:
  `"TACTICS_TYPE_HANDLER"`, o nome da tática, a descrição completa —
  *"Attack in a 3-2-5 with width from Advanced Wing-Backs and Inside
  Forwards attacking the half-spaces. Defend in a compact 5-2-2-1 with two
  Defensive Midfielders screening the back three. Counter quickly after
  regaining possession."* — e o nome do autor, **"Glawster"**, batendo
  exatamente com o dono do repositório de onde veio o arquivo.

Isso valida o mecanismo de ponta a ponta: container → catálogo (zstd/zlib)
→ recurso individual (AES-CTR + zstd). Também explica a entrada universal
`_data/details.aom` vista em toda amostra (FM19 e FM26): é um descritor de
tipo padrão do formato (`"..._TYPE_HANDLER"`), presente em qualquer `.fmf`
independente do conteúdo (tática, shortlist, banco de dados teria seu
próprio `"..._TYPE_HANDLER"`, provavelmente algo como
`EDITOR_DATA_TYPE_HANDLER`).

### O que isso destrava

Como a "proteção" é só o algoritmo (real, mas com a chave exposta ao lado
do dado), **dá pra ler qualquer `.fmf`** com `tools/fmf_extract.py`, e
também **dá pra escrever um `.fmf` válido do zero** — que é exatamente o
objetivo original do projeto: criar mods programaticamente em vez de só
usar o editor manualmente.

### Escrita confirmada: `tools/fmf_write.py`

Implementado e testado. Escolhemos **shortlist** como primeiro tipo de
conteúdo pra escrever porque é o único cujo esquema *interno* completo (o
que vai dentro do recurso, não só o container) também está mapeado: nome
da shortlist + lista de FM Unique IDs de jogador.

**Teste de round-trip completo**, sem depender do jogo nem de nenhum
arquivo de terceiros — geramos o `.fmf` do zero e lemos de volta só com
nossas próprias ferramentas:

```
python3 tools/fmf_write.py "Zagueiros Jovens" 123456 789012 555555 --out teste.fmf
python3 tools/fmf_extract.py teste.fmf --extract-all --out saida/
```

Resultado: os 3 recursos (`image.img`, `Zagueiros Jovens.slf`,
`_data/details.aom`) descriptografam com sucesso, e o conteúdo do `.slf`
decodificado bate **exatamente** com o que foi escrito — nome
`"Zagueiros Jovens"`, versão de banco `0x6281a3`, e os 3 IDs
`[123456, 789012, 555555]` na ordem certa (curiosidade: `123456` aparece
codificado como `40 e2 01 00`, o mesmíssimo exemplo de little-endian do
passo a passo original desta investigação). O `_data/details.aom` também
decodifica de volta com o texto `"PLAYER_SHORTLIST_TYPE_HANDLER"` e o
nome da ferramenta.

**Ressalva importante:** isso confirma que nossa leitura e escrita são
**consistentes entre si** (a estrutura de bytes está correta e
implementada fielmente) — não confirma que o **FM26 de verdade aceitaria**
esse arquivo, já que não temos o jogo neste ambiente pra testar
carregando-o de fato. Se alguém com FM26 instalado colocar esse arquivo em
`Documents/Sports Interactive/Football Manager 26/shortlists/` e tentar
importar, isso seria a validação final que falta.

## Escrevendo uma TÁTICA do zero — `tools/fmf_write_tactic.py`

Diferente da shortlist, não mapeamos o esquema *interno* completo de uma
tática (formação, papéis, instruções por fase) — só a camada externa
(zstd+AES). Mas agora que decifrar deixou de ser o problema, a análise
diferencial do passo a passo original finalmente ficou viável **no
conteúdo já descomprimido**, não mais no ciphertext (que não alinha por
ser comprimido).

### Achado: o campo de "intensidade de pressão"

Comparando `3-3-3-1 Morphing System.fmf` com
`3-3-3-1 Morphing System High Press.fmf` (mesmíssima tática-base, só essa
diferença), depois de descriptografar os dois `.tac`:

1. O `.tac` descomprimido começa com `03 01` + `"cat."` invertido (a
   mesma tag `section_body` do `fmsave`), depois um cabeçalho fixo, e no
   **offset 16** um `u32` = tamanho do nome (`23` vs `34` — bate exato com
   `"3-3-3-1 Morphing System"` vs `"...System High Press"`, 23 e 34
   caracteres). O nome em si começa no offset 20.
2. Como o nome tem tamanho variável, tudo depois dele desalinha entre os
   dois arquivos por causa da diferença de 11 bytes no nome — exatamente
   o aviso que o próprio `diff_bytes.py` imprime. Realinhando (comparando
   `A[20+23:]` com `B[20+34:]`), os **5077 bytes restantes são idênticos
   exceto em exatamente 2 offsets**:

   | Offset (pós-nome) | Base | High Press | XOR | Interpretação |
   |---|---|---|---|---|
   | 23 | `0x54` (`0101 0100`) | `0x94` (`1001 0100`) | `0xC0` | 2 bits (6-7) mudam de `01`→`10`: provável enum de intensidade de pressão (normal→alta) |
   | 27 | `0x80` (`1000 0000`) | `0x90` (`1001 0000`) | `0x10` | 1 bit (4) liga: provável flag booleana associada |

3. **Validado:** aplicar XOR `0xC0` e XOR `0x10` nesses 2 offsets na
   tática base reproduz **byte a byte** (exceto o campo de nome, que não
   alteramos) o conteúdo real da tática "High Press" exportada pelo
   próprio jogo.

### Tática nova, escrita do zero, com conteúdo validado

Como ainda não temos o esquema completo pra compor uma tática do nada
(formação/papéis do zero seria só um chute), o caminho honesto foi:
pegar o conteúdo **real e validado** de uma tática (a base, decifrada do
arquivo original), aplicar a transformação **validada** acima, e escrever
tudo através do nosso próprio pipeline de container do zero (chave/IV AES
novos, catálogo remontado, header novo) — nenhum byte do container ou da
criptografia original é reaproveitado, só o conteúdo tático em si (que já
sabemos que é válido porque bate com o que o próprio FM26 gerou).

```bash
python3 tools/fmf_write_tactic.py base.fmf --high-press \
  --name "Minha Variante" --description "..." --author "..." \
  --out nova.fmf
```

Testado e confirmado: o `.tac` de dentro do arquivo gerado, depois de
descriptografado com nosso próprio leitor, bate **100%** com o conteúdo
da tática "High Press" real (exceto o nome, que é o nosso). O
`_data/details.aom` também decodifica corretamente com
`"TACTICS_TYPE_HANDLER"` e o nome/descrição/autor escolhidos — o layout
desse recurso (magic `moa.`, string do tipo, nome, descrição, 6 bytes
zero, 16 bytes `0xFF`, autor, e um sufixo estrutural de 22 bytes que
parece um GUID de tipo) foi extraído com precisão via código direto do
`details.aom` real, não de cabeça.

**Mesma ressalva da shortlist:** validado contra nosso próprio
leitor/análise, não contra o FM26 de verdade (que não temos aqui pra
testar). O campo de "pressão" é o único que mapeamos com confiança — o
resto da tática (formação, papéis, instruções por jogador) continua
sendo uma caixa-preta de bytes que só sabemos copiar de uma base real,
não compor do zero.

## Status atual (contexto histórico da investigação abaixo)

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

3. **[Glawster/fmsat](https://github.com/Glawster/fmsat)**, pasta
   `samples/` — quatro `.fmf` **reais do FM26** (confirmado: o README do
   projeto cita `config/tacticExtraction.yaml` calibrado pro "default FM26
   skin"), só que são exports de **tática**, não de banco de dados. Dois
   pares pensados pelo próprio autor pra análise diferencial: `3-3-3-1
   Morphing System.fmf` vs `...High Press.fmf`, e `my 3-3-3-1 1DM.fmf` vs
   `...2DM.fmf`. Baixados, analisados e enviados ao usuário — ver estudo de
   caso 2 abaixo. **Essa é a primeira confirmação byte-a-byte do formato
   `.fmf` na geração do FM26** (as duas fontes anteriores eram: uma spec de
   *save*, não editor data; e um `.fmf` de 2018).

### O que ainda falta pra fechar o ciclo

- Um `.fmf` ou `.xml` de editor data **do FM26 especificamente de banco de
  dados** (jogadores/clubes, não tática) — pra validar se as seções
  `game_db`-like realmente aparecem do mesmo jeito num export do Pre-Game
  Editor. Se alguém subir um pro chat, já temos ferramenta pronta.
- Decifrar o conteúdo das entradas individuais (ver "ainda em aberto" no
  estudo de caso 2) — provavelmente precisa ou de mais amostras, ou de
  olhar o executável do jogo (fase 10 do fluxo original, fora do escopo
  deste sandbox).

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

## Estudo de caso 2: `.fmf` de tática, real e **do FM26** (`Glawster/fmsat`)

Quatro arquivos baixados de `Glawster/fmsat/samples/` (repositório sem
licença explícita — analisados e enviados ao usuário via chat, não
versionados neste repo). O README do projeto confirma calibração pro
"default FM26 skin", ou seja: **primeira amostra `.fmf` genuinamente do
FM26** que conseguimos testar nesta investigação (as anteriores eram save
FM26 via spec, ou `.fmf` de editor de 2018/FM19). São exports de **tática**
(`3-3-3-1 Morphing System.fmf` etc.), não de banco de dados — mas usam o
mesmo container genérico `.fmf`.

### Confirmado ✅

- **Mesmo cabeçalho de 26 bytes**, com um detalhe novo: `u8@25 = 3` neste
  arquivo real do FM26 — bate **exatamente** com o valor que o fixture
  sintético do `fmsave` usa pro FM26 (`struct.pack("<HBQQB", 8, 0,
  trailer_offset-9, 17, 3)`). No FM19 esse byte era `0`. Mais uma
  confirmação cruzada entre uma spec (fmsave) e um arquivo real e
  independente (fmsat).
- **O trailer é zstd de verdade**, pela primeira vez confirmado num `.fmf`:
  o marcador de 9 bytes (`02 01 66 6d 66 2e 08 00 00`) é seguido
  imediatamente pelo **magic number oficial do Zstandard** (`28 B5 2F FD`)
  — e só existe essa **uma** ocorrência do magic zstd no arquivo inteiro.
  `zstandard.decompress()` funciona de primeira, sem ajuste de offset.
- Diretório decodificado, 100% legível: nome do export
  (`"3-3-3-1 Morphing System"`), e 2 entradas: `image.img` e `3-3-3-1
  Morphing System.tac` (a tática de verdade). Os bytes que sobram depois
  (não interpretados por não seguirem o padrão de 40 bytes fixos) mostram
  mais 2 nomes de entrada em texto puro: `_data` e `details` com extensão
  `.aom` — **exatamente os mesmos nomes/extensão vistos no FM19**, 7 anos
  antes. Forte indício de que `_data`/`details.aom` é uma seção-padrão
  presente em todo export `.fmf`, independente do conteúdo (tática, banco
  de dados, etc.).
- **O mesmo prefixo de 8 bytes** (`10 00 00 00 10 00 00 00`) aparece antes
  do conteúdo de cada entrada listada (`image.img`, `.tac`) — igual ao
  visto no FM19. Confirma que não é coincidência de uma amostra só: é uma
  mini-estrutura real do formato, presente em pelo menos 2 gerações do
  jogo e em pelo menos 2 tipos de conteúdo (tática e banco de dados).

### Ainda em aberto ❓ (igual ao FM19, agora confirmado também no FM26)

- **zstd não decodifica o conteúdo das entradas** (`image.img`, `.tac`)
  mesmo com offset exato: só existe **uma** ocorrência do magic zstd no
  arquivo inteiro (a do trailer). Ou seja, mesmo no FM26 — onde já
  confirmamos que o trailer usa zstd puro, sem criptografia — as entradas
  de conteúdo continuam ilegíveis com as ferramentas padrão.
- **Conclusão que já dá pra tirar com confiança:** o design da SI parece
  ser deliberado — o **diretório/trailer** (só metadados: nomes, tamanhos,
  offsets) fica em compressão padrão, sem proteção extra, mas o
  **conteúdo de cada seção** (tática, banco de dados) tem alguma camada
  adicional (criptografia, ofuscação, ou um dialeto de compressão sem
  magic bytes público) que nenhuma das duas amostras reais (FM19 e FM26)
  revelou até agora. Resolver isso provavelmente exige olhar o executável
  do jogo (Ghidra) ou achar mais amostras pra análise diferencial dentro
  do próprio conteúdo da entrada, não só do container externo.

### XOR simples: testado e descartado (na entrada `.tac`, FM26)

Testes feitos sobre a entrada `3-3-3-1 Morphing System.tac` (940 bytes,
`3-3-3-1 Morphing System.fmf`), com e sem pular o prefixo constante de 8
bytes:

1. **XOR de 1 byte, força bruta nas 256 chaves.** A entropia de Shannon é
   matematicamente invariante sob XOR de 1 byte (é só uma permutação da
   distribuição de valores), então essa métrica não serve pra distinguir
   chaves aqui — usamos só como registro de que a entropia continua ~7.82
   em qualquer chave, sem exceção. Nenhuma chave produziu o magic do zstd
   nem um "run" longo de ASCII imprimível no início.
2. **XOR de chave repetida, derivada pra forçar o magic do zstd.** Pra cada
   tamanho de chave de 1 a 16 bytes e cada offset inicial de 0 a 16,
   calculamos qual seria a chave necessária pra que os primeiros 4 bytes
   descriptografados batessem com `28 B5 2F FD`, aplicamos essa chave
   (repetida) no resto dos 940 bytes e tentamos `zstd.decompress`. Zero
   sucessos em toda a varredura (256 combinações de offset×tamanho).
3. **XOR por índice de posição** (`byte[i] ^ (i & 0xFF)`, variantes com
   multiplicador e com índice invertido), **subtração por índice**, e
   **complemento de bits** (`NOT`) — nenhum reproduziu o magic do zstd.
4. **Comparação por XOR entre duas entradas `.tac` de arquivos irmãos**
   (`Morphing System` vs `...High Press`, mesma base tática): se fosse
   XOR de chave fixa por arquivo, bytes de conteúdo idêntico entre os dois
   deveriam virar `0x00` no XOR de um contra o outro. Resultado: só os 8
   bytes do prefixo constante (que já sabíamos ser texto puro) zeraram;
   nos ~932 bytes restantes, só 14/940 bytes (1,5%) ficaram zero — dentro
   do esperado por acaso (`940/256 ≈ 3,7` já seria a base aleatória; 14 é
   um pouco acima, mas nada como o "zeramento em massa" que uma chave XOR
   fixa produziria se o conteúdo por trás fosse texto/dados brutos
   idênticos). **Ressalva importante:** esse teste não é conclusivo contra
   XOR em geral — se o conteúdo por trás da criptografia já é ele mesmo
   comprimido (zstd, por ex.), duas táticas quase iguais produzem fluxos
   comprimidos completamente diferentes byte a byte mesmo sem nenhuma
   criptografia por cima, então a ausência de zeros em massa não descarta
   "comprime então criptografa", só descarta "XOR direto sobre dados
   brutos/estruturados idênticos".
5. **zstd "magicless"** (frame sem os 4 bytes de magic, recurso real do
   protocolo zstd, exposto em Python como
   `zstandard.FORMAT_ZSTD1_MAGICLESS`) — testado sem XOR, em vários
   offsets. `skip=8` (pulando o prefixo constante) chegou a passar da
   checagem inicial de framing e falhar com "Unsupported frame parameter"
   em vez de "Data corruption detected" — sinal fraco de que o byte ali
   tem *alguma* estrutura parecida com um frame header válido, mas não
   fechou. Não teve sucesso completo em nenhum offset testado.

**Conclusão desta rodada:** XOR simples (de qualquer chave curta, fixa ou
posicional) está descartado como única camada de proteção da entrada
`.tac`. Combinado com o teste de zstd "magicless" (quase bateu, mas não
fechou), a hipótese que ganha força é "compressão real (zstd ou algo
próprio) por trás de uma camada de ofuscação/criptografia mais estruturada
que XOR simples" — ou um dialeto de zstd com parâmetros não padrão que a
lib Python não reconhece.

### Chave XOR mais longa (16-64 bytes) com plaintext conhecido melhor: também descartada

Ideia: em vez de usar só os 4 bytes do magic do zstd como "plaintext
conhecido" pra derivar a chave, usar o **cabeçalho real do frame zstd do
trailer** (que não tem criptografia nenhuma) como modelo exato de como o
encoder da SI escreve um frame — isso dá 6 bytes conhecidos em vez de 4:
`28 B5 2F FD 04 50` (magic + Frame_Header_Descriptor `0x04` +
Window_Descriptor `0x50`, decodificado conforme o spec do zstd: descriptor
`0x04` = sem tamanho de conteúdo no header, sem dicionário, com checksum;
window descriptor `0x50` = janela de 1 MB). Confirmado que esse cabeçalho
de 6 bytes é **idêntico** nos dois trailers testados (`tac1.fmf` e
`tac2.fmf`), reforçando que é mesmo o padrão fixo do encoder.

Com esses 6 bytes conhecidos, testamos duas hipóteses de "onde a chave
começa a se repetir", usando as 8 entradas disponíveis (`.img` + `.tac` de
`tac1.fmf` a `tac4.fmf`):

1. **Reinicia em cada entrada** (o byte 0 do payload de cada entrada usa
   sempre o byte 0 da chave): derivamos um fragmento de 6 bytes por
   entrada — **as 8 chaves derivadas são todas diferentes entre si**, sem
   nenhum par batendo. Se a chave fosse fixa e reiniciasse por entrada,
   todas deveriam ser idênticas. Descartado.
2. **Keystream contínuo pelo corpo do arquivo** (a chave não reinicia por
   entrada; a posição usada é `offset_absoluto - 26`, ou seja, um único
   fluxo de chave cobrindo o arquivo inteiro, com período `L`): testamos
   `L` = 8, 16, 24, **32**, 40, 48, 64, alinhando os fragmentos das 8
   entradas por `posição mod L` e conferindo se batem nas posições onde se
   sobrepõem. Resultado: **conflito em quase toda posição coberta, em
   todos os tamanhos testados** (ex.: `L=32` → 12 posições cobertas, 11
   com valores conflitantes). Nenhum tamanho de chave testado (incluindo os
   32 bytes sugeridos) é consistente com os dados.

**Conclusão:** não existe uma chave XOR fixa e repetida — nem reiniciando
por entrada, nem como fluxo contínuo — de nenhum tamanho entre 1 e 64 bytes
que explique os dados. Isso deixa duas explicações prováveis: **(a)** cada
entrada/arquivo usa uma chave ou IV **único** (criptografia de verdade, ou
um nonce derivado de algo que não vemos de fora — timestamp, hash do
conteúdo, id interno), o que torna esse ataque de plaintext-conhecido
inviável sem mais informação; ou **(b)** a suposição-base ("por trás da
criptografia tem um frame zstd padrão") está errada, e o formato real por
trás não é zstd — nesse caso todo o exercício de derivar "chave" a partir
do magic simplesmente produziu ruído sem sentido, o que também explicaria
a total inconsistência observada. Não temos como distinguir (a) de (b) só
com XOR e as amostras atuais — os próximos passos que poderiam desempatar
são: (i) testar outras famílias de compressão sobre o conteúdo bruto (LZ4,
Oodle, brotli, RLE simples) em vez de assumir zstd; ou (ii) obter mais
amostras `.fmf` (idealmente uma sequência de saves/exports do mesmo
usuário, pra ver se alguma chave/IV se repete ao longo do tempo); ou (iii)
olhar o executável do jogo.

### LZ4 testado (item "i" acima): também descartado

Testado sobre as duas entradas de `3-3-3-1 Morphing System.fmf`
(`image.img`, 63 bytes / decomprime pra 10; `.tac`, 940 bytes / decomprime
pra 5120), com a lib `lz4` (bindings oficiais do LZ4):

- **Magic do formato "frame"** (`04 22 4D 18`), **"legacy"** (`02 21 4C
  18`) e **"skippable frame"** (`184D2A5X`, mesma família do zstd) — zero
  ocorrências em qualquer lugar do arquivo inteiro.
- **`lz4.frame.decompress`** direto na entrada — falha (`ERROR_frameType_
  unknown`, ou seja, nem reconhece como frame LZ4 válido).
- **`lz4.block.decompress`** (formato "block" raw, sem cabeçalho nenhum —
  o mais provável de um engine de jogo usar internamente), testado em
  todos os offsets de 0 a 23 bytes, informando o tamanho descomprimido
  exato que já conhecíamos pelo diretório (10 e 5120 respectivamente) —
  **zero sucessos** em ambas as entradas, em todos os offsets.

**Conclusão:** LZ4 (frame, legacy ou block cru) está descartado como o
formato por trás da criptografia/ofuscação dessas entradas, do mesmo jeito
que zlib, zstd puro e deflate cru já tinham sido. Sobra Oodle (formato
proprietário usado por várias engines AAA, sem biblioteca Python livre
pra testar facilmente) e brotli como famílias de compressão ainda não
testadas, além da possibilidade de ser criptografia de verdade (não
compressão) por cima de qualquer coisa.

### Brotli testado: também descartado

Testado com a lib `Brotli` (bindings oficiais do Google) sobre as mesmas
duas entradas (`image.img` e `.tac`). O formato brotli (RFC 7932) **não
tem magic number** — é um bitstream que começa direto nos dados
codificados, então não dá pra "procurar assinatura" como nos outros
formatos; a única forma de testar é tentar descomprimir mesmo.

- `brotli.decompress()` (one-shot) em todos os offsets de 0 a 23 bytes —
  zero sucessos nas duas entradas.
- `brotli.Decompressor()` incremental (que às vezes consegue devolver
  output parcial antes de detectar erro, útil pra pegar sinais fracos como
  o que vimos no teste de zstd "magicless") — também zero bytes de saída
  em qualquer offset, nas duas entradas.

**Conclusão:** brotli descartado. Com isso, já eliminamos experimentalmente
zlib, zstd (padrão e "magicless"), LZ4 (frame/legacy/block) e brotli — as
famílias de compressão sem-encriptação mais comuns em engines de jogos.
Continua de pé: Oodle (não testável sem SDK/binding), ou uma camada de
criptografia real por cima de qualquer uma dessas compressões (o que
tornaria inútil testar mais formatos de compressão sem antes achar a
chave/algoritmo de decriptação).

## Tabela de hipóteses

| Offset | Bytes | Hipótese | Confiança | Validação |
|---|---|---|---|---|
| 0-5 | `02 01` + 4 bytes | "magic" do container; os 4 bytes finais variam (`afe.` no início do arquivo FM19, `fmf.` no marcador do trailer) — não é uma string fixa universal | Alta (estrutura) / Média (significado exato dos 4 bytes) | Confirmado em `Neloxia_FM19.fmf` e cruzado com `fmsave` (FM26) |
| 9 (u64) | — | `trailer_offset - 9` | Alta | Bateu exato em `Neloxia_FM19.fmf` (138706 = 138715-9) e é a fórmula documentada no `fmsave` |
| 17 (u64) | `11 00 00 00 00 00 00 00` | Constante `17`, significado desconhecido | Média | Valor idêntico em FM19 e no fixture do FM26 |
| corpo, +0 de cada frame | `10 00 00 00 10 00 00 00` | Mini-header de 8 bytes (2× u32) antes do payload comprimido de cada seção/entrada | Baixa | Visto repetido em 2 posições diferentes do mesmo arquivo; significado não decifrado |
| trailer | zlib (FM19) / zstd (FM26) | Codec de compressão do trailer mudou por versão | **Alta (confirmado nos dois)** | zlib decodificado em `Neloxia_FM19.fmf`; zstd decodificado em `3-3-3-1 Morphing System.fmf` (real, FM26) |
| corpo das entradas (FM19) | alta entropia, sem magic | Não é zstd | Alta (descartado) | `zstandard` rejeita em todos os offsets testados; zero ocorrências do magic `28 B5 2F FD` no arquivo inteiro |
| corpo das entradas (FM26) | alta entropia, sem magic | Não é zstd puro (mesmo com o trailer do mesmo arquivo sendo zstd) | Alta (descartado) | Só 1 ocorrência do magic `28 B5 2F FD` no arquivo inteiro (a do trailer); entradas `image.img`/`.tac` não decodificam |
| diretório, 2 últimos `u64` de cada entrada | ex.: `1560165027` (FM19) / `0xFFFFFFF188066E09` (FM26) | Timestamps Unix no FM19; no FM26 parecem ser um valor-sentinela/"não definido" (`f1 ff ff ff` sugere placeholder, não timestamp real) | Alta (FM19) / Média (FM26, campo existe mas com outro significado/estado) | FM19: decodificados batem com junho/2019. FM26: valor idêntico e repetido nas duas entradas do mesmo arquivo, sugerindo "vazio", não uma data real |
| 25 (u8) | `3` no FM26 real, `0` no FM19 | Byte de versão/flag que mudou entre gerações | Média-Alta | `u8@25=3` bate exatamente com a constante usada no fixture sintético do `fmsave` para FM26 |
| conteúdo da entrada `.tac` (FM26) | alta entropia após qualquer XOR (invariante) | Não é XOR simples (1 byte, chave repetida ≤16 bytes, por índice, subtração ou NOT) | Alta (descartado) | Nenhuma das 256+256 combinações testadas produziu o magic zstd nem reduziu a entropia (que é matematicamente invariante sob XOR de 1 byte) |
| conteúdo de todas as 8 entradas testadas (FM26, 4 arquivos) | chaves de 6 bytes derivadas via cabeçalho zstd real | Não é chave XOR fixa/repetida, nem reiniciando por entrada nem como keystream contínuo, em nenhum tamanho de 8 a 64 bytes (incluindo 32) | Alta (descartado) | 8 chaves derivadas todas diferentes (hipótese "reinicia por entrada"); alinhamento por `posição mod L` gera conflito em quase toda posição pra `L` ∈ {8,16,24,32,40,48,64} |
| conteúdo da entrada `.tac`/`.img` (FM26) | sem magic LZ4, `lz4.block.decompress` falha em todos os offsets | Não é LZ4 (frame, legacy ou block cru) | Alta (descartado) | Zero ocorrências dos magics de frame/legacy/skippable; `lz4.block.decompress` com tamanho exato conhecido falha em offsets 0-23 nas duas entradas testadas |
| conteúdo da entrada `.tac`/`.img` (FM26) | `brotli.decompress`/`Decompressor` incremental falham em todos os offsets | Não é brotli | Alta (descartado) | Zero sucessos e zero output parcial em offsets 0-23, nas duas entradas testadas (brotli não tem magic pra buscar diretamente) |

## Achados confirmados

- Estrutura de cabeçalho de 26 bytes e esquema de trailer-no-final são
  compartilhados entre o save do FM26 (via `fmsave`), um `.fmf` de editor
  real do FM19 **e um `.fmf` de tática real do FM26** — confirmado em 3
  fontes independentes (uma spec + duas amostras reais de gerações e tipos
  de conteúdo diferentes). É a mesma "camada de container" da SI,
  reaproveitada entre save, tática e editor data, e entre gerações do jogo.
- Conseguimos extrair um diretório real e legível (nomes/extensões/offsets)
  de dentro de `.fmf` sem nenhuma ferramenta oficial, só com Python +
  stdlib (`zlib`) e a lib `zstandard` — validado tanto em zlib (FM19)
  quanto em zstd de verdade (FM26, com o magic number oficial do
  Zstandard).
- O conteúdo de cada entrada individual (a "carne" — tática ou banco de
  dados) permanece protegido por algo além de zlib/zstd simples, em ambas
  as gerações testadas — não é força bruta de offset errado, é uma camada
  a mais que ainda não identificamos.
