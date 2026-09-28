# Football Manager 26 — Game Editor: formato de arquivo e uso para mods

> Pesquisa feita em 2026-09-28. A rede usada para pesquisar bloqueava a maioria
> dos fóruns da comunidade (sortitoutsi, fmscout, fm-base, fmrte.com,
> steamcommunity), então grande parte veio de snippets de busca + repositórios
> open-source no GitHub. Não existe SDK/documentação oficial da Sports
> Interactive/SEGA — tudo aqui é conhecimento comunitário reverse-engineered e
> pode quebrar entre patches/versões do jogo.

## 1. Dois "editores" oficiais — não são a mesma coisa

| | **Pre-Game Editor** | **In-Game Editor** |
|---|---|---|
| Preço | Grátis (Steam/Epic/MS Store, em "Tools") | Pago (~US$8.99 na Steam) |
| Quando edita | Antes de começar um save novo | Durante um save já em andamento (tempo real) |
| O que afeta | O **banco de dados mestre** do jogo (todo save novo criado a partir dele já nasce com as mudanças) | Só **aquele save específico** |
| Saída | Gera um arquivo de "editor data" | Aplica direto no save, sem gerar arquivo separado pra distribuir |

Se o objetivo é criar um **mod pra distribuir** (elenco retrô, liga fictícia,
correção de atributos, etc.), o caminho é o **Pre-Game Editor** — é ele quem
gera o arquivo de banco de dados que outras pessoas instalam.

## 2. O arquivo final: `.fmf` (binário) vs `.xml` (texto)

Os arquivos de "editor data" ficam em:

```
Documents/Sports Interactive/Football Manager 26/editor data/
```

e podem ser de dois tipos:

- **`.fmf`** — formato binário **proprietário e fechado**. É o mesmo
  container usado pra skins, motor de partida (`simatch.fmf`) etc. Não existe
  parser open-source funcional pra ele. A única forma de mexer nele é através
  do **Resource Archiver** (ferramenta oficial que vem junto nas "Tools" da
  Steam), que faz extração/compilação `.fmf ↔ XML`.
- **`.xml`** — formato de texto, o **"db_changes"**. É o que dá pra ler,
  gerar e versionar em Git. É o caminho realista pra automação/mod pipeline.

**Conclusão prática:** não vale a pena tentar reverter o `.fmf` — o próprio
editor já aceita `.xml` diretamente na pasta `editor data` (marcando na tela
de "New Game"). Trabalhar em XML e, se quiser, compilar pra `.fmf` no final
(via Resource Archiver) só por questão de ofuscação/performance de
carregamento.

## 3. Estrutura do XML `db_changes`

Pela análise de projetos reais que geram esse XML programaticamente (ex.:
`imdoamaral/football-manager-xml-converter`, que converteu uma base retrô
inteira de FM21→FM24), o esqueleto é:

```xml
<record>
  ... cabeçalho (varia por versão do jogo) ...
  <list id="db_changes">
    <record>
      <integer id="rtype" value="1"/>           <!-- tipo do registro -->
      <large id="db_unique_id" value="..."/>    <!-- ID único codificado -->
      <list id="data">
        <record>
          <string id="Pnti" value="..."/>       <!-- código FourCC da propriedade -->
          <string id="old_value" value="..."/>
          <string id="new_value" value="..."/>  <!-- ou <null id="new_value"/> pra "apagar" -->
        </record>
      </list>
    </record>
  </list>
</record>
```

Pontos-chave confirmados:

- **`rtype`** define o tipo de entidade que o registro altera. Exemplos
  mapeados: `0` = histórico de prêmios, `1` = pessoas (jogadores/staff),
  `3` = clubes e competições, `9` = registros financeiros/nações,
  `25` = histórico de competições, `55` = referências cruzadas.
- **`db_unique_id`** é o UID "interno" do XML, e se relaciona ao UID exibido
  no jogo por uma fórmula de codificação (ex.: no caso da conversão
  FM21→FM24 documentada, `db_unique_id = player_id × (2³² + 1)` — dá pra ir
  e voltar entre o ID exibido no editor e o ID interno do XML).
- **Códigos FourCC** (4 letras, tipo `Pcti`, `Pnti`, `Plhs`, `Cdvi`)
  identificam **qual campo** está sendo alterado (nome, clube contratual,
  etc.). Esses códigos **mudam de versão pra versão** do jogo — não dá pra
  copiar de um FM24 pra um FM26 sem validar.
- Cada `record` guarda **valor antigo e novo** (`old_value`/`new_value`), e
  uma remoção é representada como `<null id="new_value"/>`.
- O cabeçalho (linhas antes de `<list id="db_changes">`) e o **número de
  versão de cada tipo de registro** também variam por edição do jogo e
  precisam ser extraídos de um XML de exemplo daquela versão específica.

### Como descobrir os códigos certos pro FM26

Fazer **uma edição pequena e isolada** manualmente no Pre-Game Editor do
FM26 (ex.: mudar só o nome de um jogador), exportar o XML, e usar esse
arquivo como referência ("Rosetta Stone") pra descobrir o FourCC, a versão
do record e o formato do cabeçalho daquele campo específico naquela versão.
Depois generalizar pra outros campos, um de cada vez.

## 4. Isso é diferente do arquivo de **save** (`.fm`)

Vale separar dois mundos:

- **Editor data (`.fmf`/`.xml`)** = altera o **banco de dados** (usado antes
  ou durante um save), é o que vira "mod".
- **Save game (`.fm`)** = o arquivo do save salvo (carreira em andamento).
  Formato binário completamente diferente, também não documentado
  oficialmente, mas com reverse-engineering ativo da comunidade:
  - **[fmsave](https://github.com/rhiever/fmsave)** — biblioteca Python
    open-source, **já compatível com FM26**, somente leitura, decodifica
    ~26 tipos de tabela (jogadores, clubes, finanças, competições, lesões,
    contratos, tática, etc.) pra DataFrame/CSV/JSON. Ótima se o objetivo for
    **extrair informação** de um save existente (ex.: relatório de scout,
    dashboard, estatísticas).
  - **FMRTE** — ferramenta paga, edição em tempo real (lê/escreve o estado
    do jogo rodando, não o arquivo `.fmf`).

Se a ideia for "puxar dados do save pra analisar/gerar conteúdo", `fmsave` é
o caminho certo. Se a ideia for "criar um mod de banco de dados pra
distribuir", é o XML `db_changes` do Pre-Game Editor.

## 5. Workflow prático sugerido

1. Baixar o **Pre-Game Editor FM26** (Steam Tools) e o **Resource Archiver**
   (mesma seção).
2. Fazer uma alteração mínima e isolada no editor, exportar como XML, e usar
   isso como referência de schema real da versão 26 (cabeçalho + FourCC +
   versão de record).
3. Construir um pipeline (Python) que gera XML `db_changes` a partir de
   CSV/JSON — inspirado no padrão do `Retro-FM-Workbench` / FMME (normaliza
   dados → mapeia campo→FourCC via uma tabela tipo `attributes.yaml` por
   versão → gera XML).
4. Testar carregando o `.xml` direto na pasta `editor data` (não precisa
   compilar pra `.fmf` durante o desenvolvimento — só se quiser distribuir
   de forma mais "fechada"/performática no final).
5. Se algum mod depender de ler dados de saves já existentes (não da base),
   usar `fmsave` em vez de tentar reimplementar o parser do `.fmf`.

## 6. Limitações importantes

- Não existe SDK/documentação oficial da Sports Interactive/SEGA — tudo isso
  é conhecimento comunitário reverse-engineered, então quebra facilmente
  entre patches/versões e precisa revalidação a cada atualização do FM26.
- O `.fmf` binário continua uma caixa-preta sem parser aberto conhecido —
  não vale investir tempo tentando decodificá-lo do zero.
- Se pretendem redistribuir um mod publicamente, atenção a direitos autorais
  dos dados de jogadores/licenças (isso é uma questão de ToS da comunidade,
  não técnica).

## Fontes

- [How to find & download the official FM26 Pre-Game Editor – FM Scout](https://www.fmscout.com/a-fm26-official-pre-game-editor.html)
- [Football Manager 26 In-Game Editor Guide – Deltia's Gaming](https://deltiasgaming.com/football-manager-26-in-game-editor-guide/)
- [How to Install FM26 Pre-Game Editor (PGE) – sortitoutsi](https://sortitoutsi.net/content/74982/how-to-install-fm26-pre-game-editor-pge)
- [Any (un)official SDK/API or docs for creating FM database updates programmatically? – sortitoutsi](https://sortitoutsi.net/content/75156/any-unofficial-sdkapi-or-docs-for-creating-fm-database-updates-programmatically)
- [FM24 Guide: How to use the Football Manager 2024 Resource Archiver to open .fmf files – sortitoutsi](https://sortitoutsi.net/content/68097/fm24-guide-how-to-use-the-football-manager-2024-resource-archiver-to-open-fmf-files)
- [How to install FMF and XML Editor Data files in Football Manager – sortitoutsi](https://sortitoutsi.net/installation-instructions/4/how-to-install-fmf-and-xml-editor-data-files-in-football-manager)
- [github.com/rhiever/fmsave](https://github.com/rhiever/fmsave)
- [github.com/imdoamaral/football-manager-xml-converter](https://github.com/imdoamaral/football-manager-xml-converter)
- [github.com/awesomeaidan76/Retro-FM-Workbench-V0.2](https://github.com/awesomeaidan76/Retro-FM-Workbench-V0.2)
- [github.com/Glawster/fmsat](https://github.com/Glawster/fmsat)
- [github.com/robeady/fm-explorer](https://github.com/robeady/fm-explorer)
- [FM Resource Archiver – FM Scout Q&A](https://www.fmscout.com/q-24284-FM-Resource-Archiver.html)
- [What's the difference between Editor and In-Game Editor? – FM Base](https://fm-base.co.uk/threads/whats-the-difference-between-editor-and-in-game-editor.139334/)
- [Diferencias entre el editor externo (pre-game) y editor in-game – FMSite.net](https://www.fmsite.net/articulos/football-manager/diferencias-entre-el-editor-externo-pre-game-y-editor-in-game-del-football-manager-r1145/)
