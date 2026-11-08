

def test_measured_run_never_shows_zero():
    from freecad.PartReview.domain import mesh_texts as mt
    from freecad.PartReview.domain.i18n import Translator
    tr = Translator("pt_BR", strict=True)
    assert mt.measured(tr, 0.3, 0.0) == "< 1 s · —"
    assert mt.measured(tr, 4.2, 85.0) == "4 s · 85 MB"
