# Changelog

All notable changes to PartReview. / Mudanças importantes do PartReview.

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
