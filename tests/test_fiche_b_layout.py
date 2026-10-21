import xml.etree.ElementTree as ET
from services.soil_diagram import panel_report_svg, soils_need_annex
from services.fiche_curve import compact_courbe_svg


def test_b_wall_geometry_is_identical_and_logs_share_its_scale():
    rows = [{'da':0, 'a':10.7, 'materiale':'Ghiaia · senza frazione fine', 'texture_class':'soil-layer--ghiaia'}]
    args = (rows, rows, 13.5, 'NGF', 10.7, 14.5, '6,30 m', '0,42 m', 4.8, 2.8)
    old, new = [ET.fromstring(panel_report_svg(*args, compact=compact)) for compact in (False, True)]
    ns = {'s':'http://www.w3.org/2000/svg'}
    for cls in ('panel-guide-back', 'panel-guide-front'):
        assert ET.tostring(old.find(f'.//s:g[@class="{cls}"]', ns)) == ET.tostring(new.find(f'.//s:g[@class="{cls}"]', ns))
    assert old.find('.//s:rect[@class="panel-front-face"]', ns).attrib == new.find('.//s:rect[@class="panel-front-face"]', ns).attrib
    assert len(new.findall('.//s:rect[@class="soil-column-frame"]', ns)) == 2
    for frame in new.findall('.//s:rect[@class="soil-column-frame"]', ns):
        assert frame.attrib['y'] == '147' and frame.attrib['height'] == '753'
        assert frame.attrib['width'] == '74'
    text = ''.join(new.itertext())
    assert '13,50 → 2,80 m NGF' in text
    assert 'Longueur forée' not in text
    assert 'Sans fines' in text


def test_dense_long_and_outside_soils_require_complete_annex():
    assert not soils_need_annex([{'da':0, 'a':10, 'materiale':'Sabbia'}], [], 10)
    for row in ({'da':0, 'a':.1, 'materiale':'Ghiaia'}, {'da':0, 'a':11, 'materiale':'Sabbia'},
                {'da':0, 'a':10, 'materiale':'Descrizione molto lunga '*40}):
        assert soils_need_annex([row], [], 10)


def test_curve_uses_origin_minus_depth_for_every_point_and_does_not_mutate_payload():
    data = {'theorique':[{'volume':0, 'hauteur':11}, {'volume':29.11, 'hauteur':0}],
            'realisee':[{'volume':0, 'hauteur':11}, {'volume':38, 'hauteur':0}], 'tube':[]}
    svg = compact_courbe_svg(data, 13.8)
    assert '>13.80<' in svg and '>2.80<' in svg and 'NGF' in svg
    root=ET.fromstring(svg); ns={'s':'http://www.w3.org/2000/svg'}
    assert len(root.findall('s:circle',ns)) == 4
    assert data['theorique'][0]['hauteur'] == 11
    assert 'NGF' in compact_courbe_svg(data, None)
