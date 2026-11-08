# Changelog

All notable changes to PartReview. / Mudanças importantes do PartReview.

## Próxima versão / Next version (não publicada / unreleased)

- **Optimise mesh by the error / Otimizar malha pelo erro** (new command,
  decision 008): solves the user's analysis with the FEM workbench's CalculiX,
  estimates the error per element (ZZ) and refines only the CAD faces where it is
  high, until the target error, the memory or time limit, or stagnation
  (singularities); every refined mesh is tried in a hidden document before it is
  applied; old results stay until the new solve succeeds. / Novo comando: refino
  adaptativo pelo erro, seguro e com explicação de por que parou.
- **Report: supports and loads figure (beta) / Relatório: figura de apoios e
  cargas (beta).** Optional, off by default (check box in the report dialog,
  remembered; never in the quick summary): the part in gray with the held
  regions painted purple and the loaded regions orange, colors only; the
  caption names each support and load with its value. A second view is added
  only for supports or loads hidden in the first. Result images keep only the
  result balloons, and the numbered points are results only. / Opcional e
  desmarcada por padrão: peça em cinza, apoios em roxo, cargas em laranja.
- The report no longer prints its level ("Report level") on the cover or in
  the traceability table. / O relatório não mostra mais o "nível do relatório". / A figura 1 mostra a
  peça em cinza, apoios em roxo, cargas em laranja e setas na direção das
  forças, sem balões; as imagens de resultado ficam só com os balões de
  resultado.

## 1.5.1 — 2026-11-08

- Running the assistant again updates its own mesh of the part instead of
  adding another (no remove button needed); "Your computer" separates what was
  read from the system, measured on this computer and estimated. / Rodar de
  novo atualiza a malha do assistente; o passo 2 separa lido / medido / estimado.

## 1.5.0 — 2026-11-08

**Mesh assistant / Assistente de malha** (new command):
- Analyses the solid before any mesh exists: size, volume, characteristic
  thickness (t = 2V/A), and warnings for walls much thinner than the part
  (likely modelling leftovers), small radii, and supports or loads on edges or
  vertices. / Analisa a peça antes de existir malha e avisa sobre detalhes que
  atrapalham (paredes finíssimas, raios pequenos, apoios em arestas).
- Five mesh options relative to the part (very coarse to very fine), always
  2nd order with curvature sizing; recommendation with the reason (about
  2 elements across the wall by default); local refinement on small support
  and load faces. / Cinco opções de malha e recomendação justificada.
- "Try the options": real Gmsh runs in a hidden document and CalculiX trials
  on small meshes of the part, to measure memory and solve time on THIS
  computer (nothing assumed from another machine; each computer keeps its own
  measurements). Fit status ✔/⚠/✖ against the free memory; objectives: finest
  mesh that fits, or solve within ~1, 5 or 10 minutes. / Mede o seu
  computador na sua peça; objetivos de memória ou tempo.
- Gmsh and CalculiX always run as separate, watched processes (time limit,
  memory watchdog, progress with elapsed/remaining time, Cancel). Creates a
  new Gmsh mesh object (undoable); removes only what it created. / Sempre em
  processos vigiados, com cancelar; cria uma malha nova, desfazível.

- Part chosen from a list of the document's final solids; a mesh the part
  already has is judged too ("Current mesh" card). Expensive fine meshes are
  generated only when the measured law says they may fit; the panel closes and
  selects the new mesh when it is created. / Peça escolhida numa lista; cartão
  "Malha atual"; ensaio mais curto; o painel fecha ao criar a malha.

**Report / Relatório:**
- Balloons rebuilt: anchored on the part (never in the air), one per visible
  face or edge, placed on the image background without covering the result or
  crossing leaders; black = result, orange = load, purple = support. / Balões
  refeitos: na peça, um por face, no fundo da imagem, sem cruzar.
- Supports and loads on edges or vertices are flagged as singular (the report
  used to say "no alerts" with the maximum stress sitting on an edge support).
  / Apoios e cargas em arestas/vértices geram alerta de singularidade.
- FreeCAD's logo is the default cover logo the first time; an empty field means
  no logo; the fields of the last report are remembered in PartReview's own
  file, also after FreeCAD is closed. / Logo do FreeCAD como padrão; campos
  lembrados entre sessões.

## 1.4.0 — 2026-11-07

- Equilibrium check: loads applied on nodes that are also fixed are added back
  to the CalculiX reactions (they go straight into the support and are missing
  from the reaction totals). Removes a false "does not close" alert when a load
  face touches a fixed face. / Checagem de equilíbrio: cargas em nós que também
  estão engastados são somadas de volta às reações do CalculiX. Acaba com o
  falso alerta "não fecha" quando a face de carga encosta num apoio fixo.
- Accent color stays legible: with light colors, titles use a darker shade of
  the same color (WCAG contrast 4.5:1 for text, 3:1 for lines and bars), in PDF
  and HTML; the dialog warns when this happens. Default color is now black. /
  Cor de destaque sempre legível (regra de contraste WCAG) no PDF e no HTML,
  com aviso no diálogo. A cor padrão agora é preta.
- Logo: SVG drawn sharp at print resolution; preview and print-sharpness note
  in the dialog; a logo that does not open is reported instead of silently
  dropped; the last logo used is remembered; the logo now sits centered at the
  bottom of the cover, larger. / Logo: SVG nítido, prévia e aviso de nitidez,
  aviso quando o arquivo não abre, último logo lembrado, logo centralizado
  embaixo da capa e maior.
- Report dialog scrolls; the Generate and Cancel buttons are always visible,
  also on small screens. / O diálogo do relatório rola e os botões Gerar e
  Cancelar ficam sempre visíveis, também em telas pequenas.

## 1.3.1 — 2026-11-07

- The workbench tooltip shows the installed version. / A dica do workbench
  mostra a versão instalada.
- Test that the example models carry no personal paths or names. / Teste que
  garante que os modelos de exemplo não levam caminhos nem nomes pessoais.
- README: installation from GitHub (git clone, ZIP, or the Addon Manager with
  a custom repository). / README: instalação pelo GitHub (git clone, ZIP ou
  Addon Manager com repositório personalizado).

## 1.3.0 — 2026-11-07

First public release: professional reports of FreeCAD FEM results (CalculiX,
linear static). / Primeira versão pública: relatórios profissionais de
resultados FEM do FreeCAD (CalculiX, estática linear).

- Automatic views of the critical points with numbered balloons and legend.
- Executive summary, analysis summary, main results, points of interest.
- Mesh quality, equilibrium check (applied loads vs reactions) and
  Zienkiewicz–Zhu estimated error with an error map.
- Assumptions and limitations, traceability (versions, file SHA-256, solver
  and mesher settings).
- Three report sizes, user templates, PDF, HTML and CSV, Portuguese and English.
