# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""Material logic of PartReview (one place, CLAUDE.md architecture rule 4).

For now: warnings about what the linear static analysis cannot represent for the
materials of the analysis, read before the calculation (mesh assistant).

- Poisson ratio >= 0.45 (rubber, TPU, other elastomers): nearly incompressible
  material. The analysis is linear elastic, valid only for small strains;
  elastomers usually work at large strains, which need a hyperelastic model that
  PartReview does not cover (out of scope, PLANO.md).
- Young's modulus in the polymer range (models.material_family, Ashby charts):
  the part may be 3D printed. The mesh is a solid part with the same properties
  in every direction: infill, perimeters and layers are not represented and the
  strength between layers is not checked. Said as a possibility ("if the part is
  printed"): E alone does not tell the process.
"""

from dataclasses import dataclass

from .models import Material

NEARLY_INCOMPRESSIBLE_NU = 0.45


@dataclass(frozen=True)
class MaterialNote:
    kind: str  # "incompressible" or "maybe_printed"
    material: Material


def material_notes(materials) -> list:
    """MaterialNote list for ``materials`` (domain Material), in their order."""
    notes = []
    for mat in materials:
        if mat.poisson_ratio is not None and mat.poisson_ratio >= NEARLY_INCOMPRESSIBLE_NU:
            notes.append(MaterialNote("incompressible", mat))
        if mat.family == "polymer":
            notes.append(MaterialNote("maybe_printed", mat))
    return notes
