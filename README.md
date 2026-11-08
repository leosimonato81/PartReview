# PartReview

**PT-BR** — Workbench do FreeCAD para análises FEM (CalculiX, estática linear)
do começo ao fim, sem travar o seu computador:

1. **Assistente de malha** — analisa a peça, avisa sobre detalhes que atrapalham
   a malha, testa malhas de várias finuras **medindo o seu computador** e cria a
   malha recomendada (ou a melhor para um objetivo de memória ou de tempo).
2. **Otimizar malha pelo erro** — roda o seu cálculo, mede o erro estimado e
   refina a malha só onde ele é alto, até a meta (ex.: 5 %) ou o limite do PC.
3. **Relatório FEM** — relatório para quem não fez a análise: vistas
   automáticas que nunca escondem o ponto mais crítico, forma deformada, tensão
   fora de apoios e cantos vivos com fator de segurança próprio, erro estimado
   em cada ponto, critério certo para metais e polímeros (PLA, ABS, PETG),
   reações nos apoios, estudo de convergência; PDF, HTML e CSV.

**EN** — FreeCAD workbench for FEM analyses (CalculiX, linear static) from start
to finish, without freezing your computer:

1. **Mesh assistant** — analyses the part, warns about details that hurt the
   mesh, tries meshes of several sizes **measuring your computer**, and creates
   the recommended mesh (or the best one for a memory or time objective).
2. **Optimise mesh by the error** — solves your analysis, measures the
   estimated error and refines the mesh only where it is high, up to the target
   (e.g. 5 %) or the computer's limit.
3. **FEM report** — a report for readers who did not run the analysis:
   automatic views that never hide the most critical point, deformed shape,
   stress away from supports and sharp corners with its own safety factor,
   estimated error at each point, the right criterion for metals and polymers
   (PLA, ABS, PETG), support reactions, convergence study; PDF, HTML and CSV.

## Instalação / Installation

**Repositório / Repository:** https://github.com/leosimonato81/PartReview
(ramo / branch `main`)

**Requisitos / Requirements:** FreeCAD 1.1 ou mais novo, com o Workbench FEM e
o CalculiX que já vêm com ele. Nada mais para instalar. / FreeCAD 1.1 or newer
with its bundled FEM workbench and CalculiX. Nothing else to install.

### 1. Descubra a pasta `Mod` do FreeCAD / Find FreeCAD's `Mod` folder

No FreeCAD, abra **Exibir → Painéis → Console Python** e rode:
In FreeCAD, open **View → Panels → Python console** and run:

```python
import os; print(os.path.join(App.getUserAppDataDir(), "Mod"))
```

Caminhos usuais no FreeCAD 1.1 / Usual paths in FreeCAD 1.1:

| Sistema / System | Pasta `Mod` / `Mod` folder |
|---|---|
| Linux (Flatpak) | `~/.var/app/org.freecad.FreeCAD/data/FreeCAD/v1-1/Mod` |
| Linux (AppImage, pacote / package) | `~/.local/share/FreeCAD/v1-1/Mod` |
| Windows | `%APPDATA%\FreeCAD\v1-1\Mod` |
| macOS | `~/Library/Application Support/FreeCAD/v1-1/Mod` |

Se a pasta `Mod` não existir, crie-a. / Create the `Mod` folder if it does not exist.

### 2a. Com git / With git

```bash
cd "<pasta Mod / Mod folder>"
git clone -b main https://github.com/leosimonato81/PartReview.git
```

Para atualizar / To update: `git pull` dentro da pasta / inside the folder `PartReview`.

### 2c. Pelo Addon Manager (repositório personalizado) / Via the Addon Manager (custom repository)

Em **Editar → Preferências → Addon Manager → Repositórios personalizados**,
adicione / In **Edit → Preferences → Addon Manager → Custom repositories**, add:

- URL: `https://github.com/leosimonato81/PartReview`
- Branch: `main`

Depois abra **Ferramentas → Addon Manager**, instale o PartReview e reinicie.
Atualizações aparecem como "atualização disponível", com o número da versão.
A versão instalada também aparece na dica do workbench.
/ Then open **Tools → Addon Manager**, install PartReview and restart. Updates
show up as "update available", with the version number. The installed
version is also shown in the workbench tooltip.

### 2b. Sem git (ZIP) / Without git (ZIP)

1. Baixe / Download: https://github.com/leosimonato81/PartReview/archive/refs/heads/main.zip
2. Extraia dentro da pasta `Mod`. Vai surgir a pasta `PartReview-main` (o nome
   não importa). / Extract it inside the `Mod` folder. It creates
   `PartReview-main` (the name does not matter).

### 3. Confira / Check

Reinicie o FreeCAD. Na lista de workbenches deve aparecer **PartReview**, com
o botão **Relatório FEM**. Para testar, abra `examples/viga_em_balanco.FCStd`
(dentro da pasta instalada) e gere um relatório.
Restart FreeCAD. **PartReview** should appear in the workbench list, with the
**FEM report** button. To try it, open `examples/viga_em_balanco.FCStd` (inside
the installed folder) and create a report.

Para desinstalar, apague a pasta do PartReview dentro de `Mod`.
To uninstall, delete the PartReview folder inside `Mod`.

> Testado / Tested: FreeCAD 1.1.4 no Linux (Flatpak), com a pasta chamada
> `PartReview` e `PartReview-main`. Windows e macOS: **ainda não testados** /
> **not tested yet**.

## Desenvolvimento / Development

- FreeCAD 1.1.x, Python ≥ 3.11
- Testes puros / Pure tests: `pytest tests/domain`
- Usar sem instalar / Use without installing: `./tools/link_to_freecad.sh`
- Testes no FreeCAD / FreeCAD tests: `tests/freecad/` (`test_view_state.py`,
  `run_report_headless.py`, `inspect_fem_reader.py`)

## Assistente de malha / Mesh assistant

Use **antes** de calcular, normalmente num modelo que ainda não tem malha.
Use it **before** solving, usually on a model that has no mesh yet.

1. Clique em **Assistente de malha**. O painel abre ao lado, em passos numerados.
2. **1 · Peça:** escolha a peça na lista (as peças finais do documento; se houver
   só uma, ela já vem escolhida, e a selecionada na tela também). O painel mostra
   dimensões, volume e a *espessura característica*
   (t = 2·volume/área; todas as sugestões partem dela, por isso servem para
   peças de qualquer tamanho). **Avisos de geometria:** paredes muito mais finas
   que a peça (provável sobra de modelagem), furos e raios pequenos, e apoios ou
   cargas em arestas ou vértices (tensão teoricamente infinita ali). Clique duas
   vezes num aviso para selecionar a face na tela.
3. **2 · Seu computador:** separa o que foi **lido do sistema** (memória total e
   livre, núcleos), o que foi **medido neste computador** (ensaios do CalculiX) e
   o que é **estimado** a partir dos dois.
4. **3 · Escolha da malha:** se a peça já tem malha, o cartão **Malha atual**
   diz se ela deve caber na memória. Clique em **Testar as opções** (cerca de
   meio minuto a um minuto): o assistente gera as malhas baratas num documento
   oculto — o seu arquivo não muda —, roda o CalculiX em malhas de ensaio
   pequenas **da sua peça, no seu computador** para medir memória e tempo, e só
   gera as malhas finas que têm chance de caber (as outras aparecem como
   "previsto"). Cada opção mostra nós, memória
   e tempo total previstos e um selo ✔ cabe / ⚠ no limite / ✖ não cabe. A
   recomendada leva ★ (normalmente a média: cerca de 2 elementos na espessura).
   Ou escolha um **objetivo** (a malha mais fina que cabe na memória, ou cálculo
   em até ~1, 5 ou 10 minutos) e clique em **Gerar malha automática**.
5. **4 · Criar a malha:** cria um objeto de malha Gmsh **novo** (nada do que já
   existe é alterado; Ctrl+Z desfaz), com refino local nas faces pequenas de
   apoio e carga, gera a malha, seleciona-a na árvore e fecha o painel. Rodar o
   assistente de novo **atualiza** essa mesma malha (não cria outra); malhas
   feitas por você nunca são alteradas.
6. Gere a malha (se ainda não estiver gerada) e calcule pelo Workbench FEM.

**Segurança / Safety:** o Gmsh e o CalculiX sempre rodam como processos
separados, com tempo limite, vigia de memória, barra de progresso com tempo
decorrido e restante, e botão Cancelar. Nada é previsto a partir de outro
computador: a memória do CalculiX depende da malha (antes de medir aparece como
faixa) e o tempo depende do computador (aparece "a medir" até o primeiro ensaio).
Cada computador guarda o que mediu em `<dados do usuário>/PartReview/` e começa
a próxima peça já com uma estimativa. / Gmsh and CalculiX always run as separate
processes with a time limit, a memory watchdog, progress (elapsed and remaining
time) and Cancel. Nothing is predicted from another computer: CalculiX memory
depends on the mesh (a band before measuring) and time depends on the computer
("to be measured" until the first trial). Each computer keeps what it measured.

## Otimizar malha pelo erro / Optimise mesh by the error

Depois de criar a malha com o assistente (ela fica na análise), clique em
**Otimizar malha pelo erro**, escolha a meta de erro estimado (10, **5** ou 2 %)
e o tempo máximo, e clique em **Otimizar a malha**. Cada rodada: o seu cálculo
com o CalculiX do Workbench FEM (seus apoios, cargas e material) → erro estimado
(Zienkiewicz–Zhu) por elemento → tamanho menor só nas faces onde o erro é alto
(regra clássica h·(e_perm/e)^(1/2), no máximo metade por rodada) → a malha nova
é ensaiada num documento oculto e só é aplicada se couber na memória e no tempo.
Para quando atinge a meta, quando a próxima malha não cabe, quando o tempo acaba
ou quando o erro para de cair — o sinal típico de singularidade (apoio ou carga
em aresta, canto vivo), que o painel explica. Faces junto a apoios/cargas em
arestas não são refinadas, e a tabela mostra a tensão máxima fora das regiões
singulares. Na viga de exemplo: 2,25 % → 1,85 % (meta 2 %) em 9 s.
Depois do primeiro cálculo, o painel mostra **quais metas cabem neste
computador**: para 10, 5 e 2 %, quantos nós seriam necessários (taxa teórica de
convergência dos elementos quadráticos, erro ∝ N^(−2/3), estimativa do lado
seguro), com memória e tempo medidos nesta peça. Num computador com mais memória
livre, metas mais exigentes cabem. Com várias peças no documento, escolha a peça
no próprio painel. As rodadas ficam gravadas na malha e viram o **estudo de
convergência** do relatório.
/ After creating the mesh with the assistant, pick a target error and a time
limit; each pass solves, estimates the error per element and refines only the
faces where it is high, trying every new mesh first and stopping at the target,
the computer's limits or stagnation (singularities).

## Como gerar o relatório FEM

1. Abra o documento com um resultado FEM já calculado (CalculiX).
2. Ative o workbench **PartReview** e clique em **Relatório FEM**.
3. Escolha o **tamanho do relatório** nos cartões: *Resumo rápido* (~3 páginas),
   *Intermediário* (~8) ou *Completo* (~10).
4. Preencha resultado, idioma (PT-BR ou EN), unidades (MPa/mm/N ou as do
   FreeCAD), título, autor, empresa, logo e, se quiser, o limite de escoamento
   (ex.: `250 MPa`) para obter o fator de segurança. O logo (SVG, PNG ou JPG)
   aparece centralizado embaixo da capa; o diálogo mostra uma prévia e avisa se
   uma imagem pequena pode sair borrada na impressão (SVG sai sempre nítido). Na
   primeira vez o campo vem com o logo do FreeCAD (o botão **Padrão** volta a
   ele); deixe-o vazio para um relatório sem logo. Os campos do último
   relatório (empresa, autor, aparência, nível, idioma, unidades, limite de
   escoamento, exportações) voltam enquanto o FreeCAD fica aberto; o logo
   escolhido é lembrado também depois de fechar.
5. Opcional: em **Aparência e textos fixos**, escolha a cor de destaque (padrão:
   preto) e os textos de abertura e de responsabilidade. Com cores claras, os
   títulos usam automaticamente um tom mais escuro da mesma cor, para manter o
   contraste mínimo de leitura da WCAG (4,5:1); o diálogo avisa quando isso
   acontece. Salve tudo como **template**, que
   fica numa pasta própria do PartReview, para reaproveitar depois.
6. Opcional: marque **HTML** (relatório num arquivo único) e/ou **CSV** (valores
   por nó), e a **figura de apoios e cargas (beta)**.
7. **Gerar relatório.** O PDF abre ao final. O documento volta exatamente como
   estava: visibilidade, câmera, cores e o sinal de "modificado".

O que o relatório traz: capa com logo; sumário; **resumo executivo** com o
veredito montado a partir dos dados (quando a tensão máxima cai sobre um apoio,
uma carga ou um canto vivo, ele mostra os dois fatores de segurança e diz qual
governa); vistas automáticas (visão geral → aproximações de cada grandeza),
com balões que nunca escondem o ponto mais crítico, eixos XYZ e barra de
escala; **forma deformada** ampliada sobre o contorno da peça sem carga;
resultados com unidade e local, incluindo a **tensão máxima fora de apoios,
cargas e cantos vivos** (princípio de Saint-Venant; Williams, 1952) e a tensão
principal máxima; **reações em cada apoio**; parte do volume acima de 50/80/100 %
do limite do material; pontos de interesse com o **erro estimado em cada
ponto**; **qualidade da malha, checagem de equilíbrio e erro estimado**
(Zienkiewicz–Zhu, com mapa do erro local) e, quando a malha veio de "Otimizar
malha pelo erro", o **estudo de convergência**; premissas e limitações
conforme o material (metais: von Mises; polímeros como PLA, ABS e PETG: também
a tensão principal contra a resistência à tração, com notas sobre impressão 3D,
fluência e temperatura; quando o cartão do material traz resistência à tração
menor que o escoamento, vale a menor); **rastreabilidade** (versões, SHA-256 do
arquivo, configurações do solver e da malha). Os valores calculados saem com
algarismos coerentes com o erro estimado. A checagem de equilíbrio e o erro
estimado foram validados contra a solução analítica da viga em balanço do
FreeCAD (teoria de vigas): o equilíbrio fecha exatamente, e o erro estimado
acompanha o erro verdadeiro, subestimando-o por um fator de 1,2 a 1,9 nesse
caso.

## Modelos de exemplo / Example models

A pasta `examples/` traz modelos prontos, todos feitos a partir do exemplo
nativo do FreeCAD "viga em balanço" (`ccx_cantilever_faceload`, aço,
8000 mm × 1000 mm × 1000 mm, 9 MN na ponta), já resolvidos com o CalculiX:

| Arquivo | Para quê |
|---|---|
| `viga_em_balanco.FCStd` | Primeiro teste: abra, clique em **Relatório FEM** e gere. Resultados próximos da teoria de vigas (≈ 88 mm de flecha, ≈ 430 MPa na raiz). |
| `teste_app_part.FCStd` | A mesma viga dentro de um `App::Part` deslocado e girado. |
| `teste_duas_analises.FCStd` | Duas análises no mesmo arquivo (a segunda com metade da carga). |
| `teste_sem_resultado.FCStd` | Análise montada mas não resolvida: a ferramenta deve avisar com clareza. |

Como usar: abra o arquivo no FreeCAD, ative o workbench **PartReview** e clique
em **Relatório FEM**. Para recriar os modelos: rode `tools/build_examples.py`
com o `freecadcmd` (instruções no próprio arquivo).

*EN — `examples/` holds ready, solved models built from FreeCAD's native
cantilever example. Open one, activate **PartReview** and click **FEM report**.
Rebuild them with `tools/build_examples.py`.*

## Compatibilidade e limitações conhecidas

> **Status:** beta. A ferramenta foi desenvolvida e testada com um único
> modelo de referência do autor e com os modelos de `examples/`. Os itens abaixo são pontos de atenção
> levantados na revisão do projeto. Cada um precisa ser confirmado com
> modelos reais antes de ser considerado suportado.

### O que a ferramenta lê

Resultados de **análise estática linear** feitos com o Workbench FEM nativo
do FreeCAD, usando o solver **CalculiX**: deslocamento (magnitude) e
tensão de von Mises, lidos das propriedades do objeto de resultado.

### Pontos críticos de revisão

A coluna "Como está hoje" descreve o comportamento atual do código, verificado
no modelo de referência do autor (FreeCAD 1.1.4, CalculiX, malha de tetraedros de 2ª ordem com
40 349 nós).

| # | Ponto | Risco | Como está hoje | Status |
|---|---|---|---|---|
| 1 | **Outros solvers** (Elmer, Mystran, Z88) | Podem não preencher as mesmas propriedades de resultado do CalculiX. | O leitor só aceita objetos `Fem::FemResultObject` com `ResultType = Fem::ResultMechanical`. Solvers que gravam o resultado só no pipeline (caso do Elmer, até onde sabemos) não aparecem na lista de resultados. | Não testado |
| 2 | **Outros tipos de análise** (térmica, modal, flambagem, não linear) | Resultados diferentes dos suportados. A ferramenta não os interpreta. | Resultados que não são de análise estática são **recusados com mensagem clara**, inclusive os modos de vibração e de flambagem do CalculiX, que o FreeCAD também guarda como "resultado mecânico". Verificado com o exemplo nativo `frequency_beamsimple`: os 10 modos foram recusados. | Não suportado (bloqueado) |
| 3 | **Vários resultados ou passos de tempo** no mesmo documento | Hoje o relatório trata um resultado por vez. | O diálogo lista todos os resultados mecânicos e o usuário escolhe um. Cada PDF cobre um resultado. | Limitado |
| 4 | **Elementos de casca ou viga** | O cálculo de câmera e de normais foi pensado para peças sólidas. | A superfície, as normais, os pontos de interesse e a visibilidade só funcionam com tetraedros (4 ou 10 nós). Com outros elementos (casca, viga, hexaedro), o PDF sai só com as visões gerais e um aviso. | Parcial |
| 5 | **Modelos dentro de `App::Part`** ou com vários corpos | Enquadramento da câmera e mapeamento da geometria podem errar com `Placement`. | A posição de apoios e cargas vem da face do CAD (`Shape` do objeto), **sem** somar o `Placement` de um `App::Part` que o contenha. Se o contêiner estiver deslocado, os marcadores de apoio/carga e o aviso de singularidade podem sair no lugar errado. As vistas de tensão e deslocamento usam só a malha e não são afetadas. | Risco conhecido |
| 6 | **Objeto que desenha o mapa de cores** | A captura depende de qual objeto (`Pipeline_*`, malha de resultados) está presente no documento. Documentos montados de outra forma podem precisar de outro caminho. | **Resolvido para resultados mecânicos:** a ferramenta não depende do estado da tela nem do pipeline. Ela pinta a própria malha de resultados (`result.Mesh`) com a escala azul→vermelho, esconde todo o resto e restaura tudo no fim. | Resolvido |
| 7 | **Singularidades de tensão** | Apoios fixos e cargas pontuais geram picos que não representam a tensão real e crescem com o refino da malha. Os pontos próximos a eles são sinalizados no relatório, mas a decisão é do engenheiro. | Um ponto de tensão alta é sinalizado como "possível singularidade" quando fica a menos de 1,5× o tamanho médio do elemento (ou 1% do tamanho da peça) de uma face de apoio ou de carga. Na viga de `examples/teste_app_part.FCStd`, o canto do engaste é sinalizado. Cargas em arestas ou vértices ainda não entram nessa verificação. | Sinalizado |
| 8 | **Critério de falha** | O relatório só calcula fator de segurança se o usuário informar o limite de escoamento. Sem isso, não afirma que a peça passa ou falha. | O limite vem do diálogo (ex.: `250 MPa`, convertido para a unidade do relatório) ou, se houver, do `YieldStrength` do material. Fator de segurança < 1 gera aviso. O critério é só de escoamento por von Mises: não cobre fadiga, flambagem nem fratura. | Por projeto |
| 9 | **Unidades** | Devem ser lidas do documento. Conferir em modelos com unidades diferentes de mm e MPa. | O FreeCAD guarda os resultados mecânicos em mm/MPa (convenção do próprio FreeCAD). O relatório mostra em MPa/mm/N ou no sistema de unidades das preferências, conforme a escolha no diálogo. Material e cargas são convertidos pela API de unidades do FreeCAD. Verificado nos 10 sistemas de unidades do FreeCAD 1.1: quando um sistema não define unidade legível para uma grandeza, usa MPa/N/mm nela. As reações do CalculiX estão em N, o que foi confirmado com o exemplo da viga em balanço. | Verificado (Linux) |
| 10 | **Interface gráfica** | A geração de relatório depende do FreeCAD com interface aberta. Não roda em modo sem interface. | Precisa do FreeCAD com interface, porque a captura usa a vista 3D. Funciona também com a interface **invisível** (`QT_QPA_PLATFORM=offscreen`), que é como os testes automáticos rodam. Não funciona no `freecadcmd`. | Por projeto |
| 11 | **Desempenho** | Modelos grandes podem travar a interface. | No modelo de referência (40 mil nós), o relatório completo leva de 5 a 15 s, com barra de progresso e botão de cancelar. Ainda não foi testado com malhas muito maiores. | A verificar |
| 12 | **Tensão máxima no interior** | As imagens só mostram a superfície. | Se o nó de tensão máxima estiver dentro da peça, o PDF avisa. | Sinalizado |
| 13 | **Equilíbrio** | Cargas e reações podem não fechar (modelo errado ou arquivo de reações antigo). | Compara a soma das forças com as reações do `ccx_dat_file` (resíduo relativo). Fica "não verificável" quando há pressão, peso próprio, deslocamento imposto ou outras cargas que ainda não somamos. Momentos não são verificados. Na viga de exemplo, o resíduo é da ordem de 10⁻¹². Quando uma face de carga encosta num apoio fixo, a carga nos nós compartilhados vai direto ao apoio e o CalculiX não a inclui no total de reações; a ferramenta recalcula essa parcela (com as mesmas funções do FreeCAD que escrevem a entrada do CalculiX), soma de volta e explica no relatório. | Implementado |
| 14 | **Erro estimado (ZZ)** | Uma malha só não mostra o erro real. | Estimador de Zienkiewicz–Zhu validado contra a viga em balanço: acompanha o erro verdadeiro, mas o subestima (fator 1,2 a 1,9). Exige um único material isotrópico e tetraedros. É um erro global em energia, não o erro da tensão máxima. | Validado em 1 caso |

### Como reportar um caso que não funcionou

Abra uma issue com: versão do FreeCAD, solver usado, tipo de análise,
a mensagem do Console Python (menu Exibir > Painéis) e, se possível, um
modelo reduzido que reproduza o problema. Cada caso confirmado vira um teste
automatizado e uma linha nesta tabela.

### Aviso

Este software gera relatórios a partir de resultados calculados pelo usuário.
Ele não substitui a validação por um profissional habilitado, e os valores
dependem da qualidade do modelo, da malha e das condições de contorno
definidas no FreeCAD. Software fornecido sem garantia (ver `LICENSE`).

## Licença / License

LGPL-2.1-or-later. Veja / See `LICENSE` e/and `NOTICE`.

## Créditos / Credits

**PT-BR** — O PartReview foi concebido a partir do
[FreeCAD-DFM-Workbench](https://github.com/ryankembrey/FreeCAD-DFM-Workbench),
de Ryan Kembrey (LGPL-2.1-or-later). Esta versão não contém código desse
projeto. Quando as análises de DFM forem incorporadas, os arquivos herdados
manterão o aviso de copyright do autor original e serão listados em `NOTICE`.

**EN** — PartReview was conceived from
[FreeCAD-DFM-Workbench](https://github.com/ryankembrey/FreeCAD-DFM-Workbench)
by Ryan Kembrey (LGPL-2.1-or-later). This version contains no code from that
project. When the DFM analyses are brought in, inherited files will keep the
original author's copyright notice and will be listed in `NOTICE`.

**Desenvolvimento / Development** — PT-BR: PartReview é desenvolvido por
Leonardo Simonato, com o apoio do Claude (Anthropic), assistente de IA usado no
planejamento, na implementação, nos testes e na validação técnica. Os commits
feitos com essa ajuda registram `Co-Authored-By: Claude`. EN: PartReview is
developed by Leonardo Simonato with the help of Claude (Anthropic), an AI
assistant used for planning, implementation, testing and technical validation.
Commits made with its help carry `Co-Authored-By: Claude`.
