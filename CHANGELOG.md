# Changelog

All notable changes to PartReview. / Mudanças importantes do PartReview.

## 1.6.0 — 2026-11-08

Improvement release: a report written for professionals who did not run the
analysis. / Versão de melhoria: relatório para profissionais que não fizeram a
análise.

**Optimise mesh by the error / Otimizar malha pelo erro** (new command, **beta**:
marked as such in the menu and in its panel):
- Solves the analysis with the FEM workbench's CalculiX, estimates the error
  per element (ZZ) and refines only the CAD faces where it is high, aiming at
  the error away from supports (Saint-Venant), until the target, the memory or
  time limit, or stagnation. Every refined mesh is tried in a hidden document
  first; old results stay until the new solve succeeds. Its passes are kept on
  the mesh and become the report's convergence study. / Refino adaptativo pelo
  erro, seguro, com estudo de convergência no relatório.

**Report: honest by design / Relatório imparcial:**
- The overview never hides the most critical point to show lesser ones, and
  lists the points it could not show with the figure where they are. Figures
  read overview → its close-ups → next quantity. / A visão geral nunca esconde
  o ponto mais crítico; ordem: visão geral → aproximações.
- **Stress away from supports, loads and sharp inner corners**, with its own
  safety factor; the summary says which factor governs. Sharp re-entrant
  corners are flagged as singular (Williams 1952). / Tensão fora de apoios,
  cargas e cantos vivos, com fator de segurança próprio.
- **Estimated local error at each point** (ZZ), and computed results printed
  with significant digits that match the estimated error. / Erro local em cada
  ponto e algarismos coerentes com o erro.
- **Materials:** family from Young's modulus (metals, polymers). The lower of
  yield and tensile strength is used (generic PLA and ABS cards break before
  they yield). Polymers (PLA, ABS, PETG...) also get the maximum principal
  stress vs tensile strength (Rankine) and notes on 3D printing, creep and
  temperature. / Materiais: menor limite; Rankine e notas de impressão 3D para
  polímeros.
- **Deformed shape** (magnified, over the unloaded outline) replaces the
  displacement overview; no redundant displacement close-up, so the standard
  level spends its figures on stress. / Forma deformada; figuras melhor usadas.
- **Support reactions** (force per support), **share of the volume above
  50/80/100 % of the material limit**, **mesh convergence study**. / Reações
  por apoio, volume acima do limite, estudo de convergência.
- Every figure has an XYZ axes triad and a scale bar; close-ups fill the frame.
  / Eixos XYZ e barra de escala; aproximações bem enquadradas.
- **Supports and loads figure (beta)**, optional and off by default: gray part,
  supports purple, loads orange, painted up to the real CAD edges. / Figura de
  apoios e cargas (beta), desmarcada por padrão.
- The report level is no longer printed. / O nível do relatório não aparece
  mais.

**Mesh tools / Ferramentas de malha:**
- The optimiser shows, after its first solve, which targets (10/5/2 %) fit this
  computer (nodes from the a priori convergence rate, memory and time measured
  on the part); a part choice appears when several parts have an assistant
  mesh. / O otimizador mostra quais metas cabem neste computador e deixa
  escolher a peça.
- Fixed: a CalculiX run too short to be sampled (peak 0 MB) broke the memory
  model and was saved to the machine calibration; very short runs no longer set
  the computer's speed. / Corrigido: cálculo curto demais para medir quebrava
  o modelo de memória.
- Fixed: updating the assistant's mesh kept extra refinement regions from the
  optimiser, so the created mesh differed from the tested one. / Corrigido:
  ao atualizar, a malha criada agora é igual à testada.
- The assistant gives total solve times everywhere and shows "< 1 s · —" for
  runs too short to measure. / Tempos coerentes e medições curtas legíveis.

**Report dialog / Diálogo do relatório:**
- Fields of the last report (now also the yield strength) come back only while
  FreeCAD stays open; a logo changed from the default (also "no logo") is
  remembered after a restart. "Default" button restores FreeCAD's logo, read
  from FreeCAD itself on every system; an empty field makes a report without a
  logo. / Campos lembrados durante a sessão; logo lembrado sempre; botão
  "Padrão"; campo vazio = sem logo.

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
