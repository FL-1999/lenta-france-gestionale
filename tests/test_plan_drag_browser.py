"""Precise dragging must follow the pointer, including at neighbouring edges."""
import copy
import json
import os

import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy.orm import Session

from models import SitePlan
from test_operations_live import live_operations
from test_plan_corners import layout
from test_site_plans import vector_pdf
from services.site_plan_import import import_pdf

pytestmark = pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS') != '1', reason='Browser checks opt-in')


def test_precise_drag_across_neighbour_and_back(live_operations):
    origin, engine, ids, password, _ = live_operations
    data = layout()
    for index, panel in enumerate(data['panels']):
        panel.pop('corner_group')
        panel['label'] = f'P{index + 1}'
        panel['points'] = [[x + index * 100.5, y] for x, y in [[100, 130], [200, 130], [200, 150], [100, 150]]]
        panel['reference_points'] = copy.deepcopy(panel['points'])
    data['width'] = 500
    _, preview = import_pdf(vector_pdf())
    with Session(engine) as db:
        db.add(SitePlan(site_id=ids['site'], filename='adjacent.pdf', pdf_data=vector_pdf(), preview_data=preview, draft=json.dumps(data)))
        db.commit()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        page = browser.new_page(viewport={'width': 1680, 'height': 1100})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('dialog', lambda dialog: dialog.accept())
        page.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin + '/') else route.abort())
        page.goto(origin + '/login')
        page.locator('#email').fill('smoke-manager@example.com')
        page.locator('#password').fill(password)
        page.locator('#login-form button[type=submit]').click()
        page.wait_for_url('**/manager/dashboard')
        url = origin + f'/manager/cantieri/{ids["site"]}/pianta'
        page.goto(url)
        expect(page.locator('[data-geometry-tools]')).to_be_visible()
        page.locator('[data-original-toggle]').click()

        def points(key):
            return page.locator(f'[data-clean-shapes] polygon[data-key="{key}"]').evaluate('(e)=>[...e.points].map(p=>[p.x,p.y])')

        svg = page.locator('[data-clean-svg]')
        for zoom in [False, True]:
            page.locator('[data-zoom]' if zoom else '[data-fit]').click()
            svg.scroll_into_view_if_needed()
            initial, neighbour = points('a'), points('b')
            # Grab inside the body, clear of its edge handles.
            screen = svg.evaluate('''e=>{const m=e.getScreenCTM(),p=new DOMPoint(170,140).matrixTransform(m);
                return {x:p.x,y:p.y,scale:m.a};}''')
            page.mouse.move(screen['x'], screen['y'])
            page.mouse.down()
            # Close a sub-point gap, cross the other panel and return to the start.
            for dx in [0.25, 0.5, 1.25, 20, 40, 45, 0.5, 0]:
                page.mouse.move(screen['x'] + dx * screen['scale'], screen['y'])
                actual = points('a')
                for before, after in zip(initial, actual):
                    assert after == pytest.approx([before[0] + dx, before[1]], abs=0.05), (zoom, dx, actual)
                assert points('b') == neighbour
            page.mouse.up()
            assert points('a') == initial
            expect(page.locator('[data-select]')).to_have_value('a')
        # Edge handles allow the same fine alignment, without resizing a locked panel.
        handle = page.locator('[data-clean-shapes] [data-edge-handle=end]').bounding_box()
        x, y = handle['x'] + handle['width'] / 2, handle['y'] + handle['height'] / 2
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x + 0.5 * screen['scale'], y)
        page.mouse.up()
        aligned = points('a')
        assert aligned[1][0] == pytest.approx(neighbour[0][0], abs=0.05)
        assert aligned[1][0] - aligned[0][0] == pytest.approx(100)
        expect(page.locator('[name=width_m]')).to_have_value('2.5')
        page.locator('[data-undo-edit]').click()
        assert points('a') == initial
        # Releasing outside the drawing still finishes the gesture and can be undone.
        svg.scroll_into_view_if_needed()
        screen = svg.evaluate('''e=>{const p=new DOMPoint(170,140).matrixTransform(e.getScreenCTM());return {x:p.x,y:p.y};}''')
        page.mouse.move(screen['x'], screen['y'])
        page.mouse.down()
        page.mouse.move(screen['x'], svg.bounding_box()['y'] - 15, steps=5)
        page.mouse.up()
        expect(page.locator('#site-plan-app')).not_to_have_attribute('data-dragging', 'true')
        moved = points('a')
        assert moved != initial
        assert points('b') == neighbour
        with page.expect_response(lambda response: response.url.endswith('/bozza') and response.request.method == 'PUT') as saved:
            page.locator('[data-save]').click()
        assert saved.value.ok
        expect(page.locator('[data-message]')).to_contain_text('Bozza salvata')
        page.reload()
        expect(page.locator('[data-geometry-tools]')).to_be_visible()
        for before, after in zip(moved, points('a')):
            assert after == pytest.approx(before, abs=0.05)
        assert points('b') == neighbour
        assert not errors, errors
        browser.close()
