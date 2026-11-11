# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato

from freecad.PartReview.domain.i18n import Translator
from freecad.PartReview.domain.materials import material_notes
from freecad.PartReview.domain.mesh_texts import material_note_text
from freecad.PartReview.domain.models import Material, material_family
from freecad.PartReview.domain.units import Quantity


def mat(name, e_mpa, nu):
    return Material(name=name, youngs_modulus=Quantity(e_mpa, "MPa"), poisson_ratio=nu,
                    family=material_family(e_mpa))


def kinds(materials):
    return [(n.kind, n.material.name) for n in material_notes(materials)]


def test_steel_has_no_note():
    assert kinds([mat("Steel", 210000, 0.30)]) == []


def test_printed_plastic_is_a_possibility():
    assert kinds([mat("PLA", 3600, 0.36)]) == [("maybe_printed", "PLA")]


def test_nearly_incompressible_from_045():
    assert kinds([mat("Rubber", 5, 0.49)]) == [("incompressible", "Rubber")]
    assert kinds([mat("Edge", 50000, 0.45)]) == [("incompressible", "Edge")]
    assert kinds([mat("Below", 50000, 0.449)]) == []


def test_tpu_gets_both_notes_and_missing_nu_is_no_note():
    assert kinds([mat("TPU", 200, 0.48)]) == [("incompressible", "TPU"),
                                              ("maybe_printed", "TPU")]
    assert kinds([Material(name="Unknown")]) == []


def test_texts_in_both_languages():
    for language in ("pt_BR", "en"):
        tr = Translator(language)
        for note in material_notes([mat("TPU", 200, 0.48)]):
            text = material_note_text(note, tr)
            assert "TPU" in text and "{" not in text
    pt = Translator("pt_BR")
    texts = [material_note_text(n, pt) for n in material_notes([mat("TPU", 200, 0.48)])]
    assert "0,48" in texts[0] and "200 MPa" in texts[1]
