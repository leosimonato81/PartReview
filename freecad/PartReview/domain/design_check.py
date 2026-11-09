# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""Design safety factor of the report's conclusion (pure, no FreeCAD).

One number decides: the smallest safety factor among the failure criteria that
apply to the material, each computed with the DESIGN stress, i.e. the highest
stress away from supports, loads and sharp re-entrant corners (Saint-Venant;
Williams 1952). Peaks on idealised supports are modelling artefacts that grow
with refinement: they are reported, never used for the conclusion.

Criteria:
- von Mises against the material limit (yield strength, or the tensile
  strength when the card gives a lower one): ductile yielding;
- polymers also Rankine (largest principal stress against the tensile
  strength): less ductile, they tend to break in tension.

"Meets / does not meet" only against a safety factor typed by the user (no
published threshold is assumed); without it, FS < 1 still says that the linear
analysis exceeds the material limit, which is a physical statement.
"""

from dataclasses import dataclass

from .models import Quantity

VON_MISES, RANKINE = "von_mises", "rankine"


@dataclass(frozen=True)
class Criterion:
    key: str  # VON_MISES or RANKINE
    limit: Quantity  # allowable stress of the criterion
    limit_source: str  # "user", "material", "material_uts" (i18n suffix)
    design_stress: Quantity  # away from supports, loads and sharp corners
    peak_stress: Quantity  # highest in the whole part (may be singular)
    design_is_regular: bool  # False: no regular point known, the peak is used

    @property
    def fs_design(self) -> float:
        return self.limit.value / self.design_stress.value

    @property
    def fs_peak(self) -> float:
        return self.limit.value / self.peak_stress.value


@dataclass(frozen=True)
class DesignCheck:
    criteria: tuple[Criterion, ...]
    required: float | None = None  # safety factor required by the user

    @property
    def governing(self) -> Criterion:
        return min(self.criteria, key=lambda c: c.fs_design)

    @property
    def fs(self) -> float:
        return self.governing.fs_design

    @property
    def status(self) -> str:
        """'meets', 'fails' (below the required FS), 'exceeds' (FS < 1: the
        material limit is passed, no requirement needed) or 'number' (only the
        value: no requirement typed)."""
        if self.fs < 1.0:
            return "exceeds"
        if self.required is None:
            return "number"
        return "meets" if self.fs >= self.required else "fails"


def _criterion(key, limit, source, design, peak):
    if limit is None or peak is None or peak.value <= 0 or limit.value <= 0:
        return None
    if peak.unit != limit.unit or (design is not None and design.unit != limit.unit):
        return None
    regular = design is not None and 0 < design.value <= peak.value
    return Criterion(key, limit, source, design if regular else peak, peak, regular)


def design_check(limit: Quantity | None, limit_source: str, vm_design: Quantity | None,
                 vm_peak: Quantity | None, family: str = "other",
                 ultimate: Quantity | None = None, s1_design: Quantity | None = None,
                 s1_peak: Quantity | None = None,
                 required: float | None = None) -> DesignCheck | None:
    """None when no criterion can be evaluated (no material limit)."""
    criteria = [_criterion(VON_MISES, limit, limit_source, vm_design, vm_peak)]
    if family == "polymer":
        criteria.append(_criterion(RANKINE, ultimate, "material", s1_design, s1_peak))
    criteria = tuple(c for c in criteria if c is not None)
    if not criteria:
        return None
    return DesignCheck(criteria, required if required and required > 0 else None)


def parse_required(text: str) -> float | None:
    """Safety factor typed by the user ("2", "1,5", "1.5"); None when empty.
    Raises ValueError on anything else or a value below 1."""
    text = (text or "").strip()
    if not text:
        return None
    value = float(text.replace(",", "."))
    if not value >= 1.0:
        raise ValueError("required safety factor below 1: %r" % text)
    return value
