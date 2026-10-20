import re
import pytest
from fastapi import HTTPException
import main
from models import Fiche
from services.soil_materials import describe_material, split_description
from services.soil_diagram import comparison_svg
from test_operations import operations
from test_site_pours import setup


def test_material_descriptions_are_optional_reversible_and_bounded():
    text = describe_material("ciottoli grossi", "grossolano", "50_100", "assenti")
    assert split_description(text) == ("ciottoli grossi", "grossolano", "50_100", "assenti")
    assert main._translate_fiche_technical_text(text) == "Gros cailloux · Grossier · 50-100 mm · Sans fines"
    assert main._normalize_stratigrafia_materials([text]) == [text]
    assert main._normalize_stratigrafia_materials([text], [], [""], [""], [""]) == ["ciottoli grossi"]
    assert split_description("Autre: terrain fin et humide")[0] == "Autre: terrain fin et humide"
    for args in [("ghiaia", "inventato", "", ""), ("", "fine", "", ""), ("x" * 100, "fine", "", "")]:
        with pytest.raises(ValueError):
            describe_material(*args)
    with pytest.raises(HTTPException):
        main._normalize_stratigrafia_materials(["sabbia"], [], ["fine", "grossolano"])


def test_roundtrip_edit_and_validation_keep_descriptions_on_the_correct_layer(operations):
    o = operations
    setup(o, ("P1",))
    data = dict(cantiere_id=o["site"].id, numero_pannello=1, data_scavo="2026-10-20",
                operatore="Squadra", tipologia_scavo="paratia", profondita_totale="3", larghezza_pannello="5", altezza_pannello=".5",
                strato_da=["0", "1"], strato_a=["1", "3"], strato_materiale=["sabbia", "altro"],
                strato_materiale_altro=["", "Gros cailloux"], strato_granulometria=["fine", "grossolano"],
                strato_pezzatura=["", "oltre_100"], strato_fini=["", "assenti"])
    response = o["client"].post("/manager/fiches/nuova", data=data, follow_redirects=False)
    assert response.status_code == 303, response.text[-2000:]
    o["db"].expire_all()
    fiche = o["db"].query(Fiche).one()
    layers = sorted(fiche.stratigrafie, key=lambda item: item.da_profondita)
    assert [layer.materiale for layer in layers] == ["sabbia · fine", "Autre: Gros cailloux · grossolano · >100 mm · senza frazione fine"]
    edit = o["client"].get(f"/manager/fiches/{fiche.id}/modifica")
    assert 'value="assenti" selected' in edit.text
    assert 'value="oltre_100" selected' in edit.text
    bad = {**data, "strato_pezzatura": ["", "inventato"]}
    assert o["client"].post(f"/manager/fiches/{fiche.id}/modifica", data=bad).status_code == 400
    o["db"].expire_all()
    assert layers[1].materiale.endswith("senza frazione fine")
    data.update(strato_materiale=["sabbia", "ciottoli grossi"], strato_materiale_altro=["", ""],
                strato_granulometria=["", ""], strato_pezzatura=["", ""], strato_fini=["", ""])
    response = o["client"].post(f"/manager/fiches/{fiche.id}/modifica", data=data, follow_redirects=False)
    assert response.status_code == 303, re.findall(r'<div[^>]*role="alert"[^>]*>(.*?)</div>', response.text, re.S)
    o["db"].expire_all()
    assert [layer.materiale for layer in sorted(fiche.stratigrafie, key=lambda item: item.da_profondita)] == ["sabbia", "ciottoli grossi"]


def test_diagram_uses_one_depth_scale_and_preserves_zero_negative_and_missing_elevations():
    rows = [dict(da=0, a=1, materiale="Riporto"), dict(da=1, a=2, materiale="Ghiaia")]
    theory = [dict(da=0, a=3, materiale="Sable")]
    svg = comparison_svg(rows, theory, 0, "NGF", 2)
    for value in ("0,00", "-1,00", "-2,00", "-3,00"):
        assert value in svg
    assert 'height="194.00"' in svg  # one metre on the shared three-metre scale
    assert "—" in comparison_svg(rows, theory, None)
    assert "&lt;script&gt;" in comparison_svg(rows, theory, 0, "<script>")
