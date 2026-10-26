document.addEventListener("DOMContentLoaded", function () {
    const root = document.querySelector("[data-courbe-beton-form]");
    if (!root) return;
    const form = root.closest("form");
    const checkbox = form.querySelector("input[type=checkbox][name=courbe_beton_active]");
    const tr = (it, fr) => document.documentElement.lang === "fr" ? fr : it;
    const panel = root.querySelector("[data-courbe-beton-panel]");
    const canvas = root.querySelector("[data-courbe-chart]");
    const ctx = canvas?.getContext("2d");

    function parseValue(input) {
        const value = (input?.value || "").trim().replace(/,/g, ".");
        if (!value) return null;
        const parsed = Number(value);
        return Number.isFinite(parsed) ? parsed : null;
    }
    function readSeries(tableName) {
        const table = root.querySelector(`[data-courbe-table="${tableName}"]`);
        return Array.from(table?.querySelectorAll(".courbe-row") || [])
            .map(row => ({ volume: parseValue(row.querySelector("[data-courbe-volume]")), hauteur: parseValue(row.querySelector("[data-courbe-hauteur]")) }))
            .filter(point => point.volume !== null && point.hauteur !== null)
            .sort((a, b) => a.volume - b.volume);
    }
    const volumeInput = root.querySelector('[data-courbe-theoretical-volume]');
    const startInput = root.querySelector('[data-courbe-theoretical-start]');
    function defaults() {
        const read = name => parseValue(form.querySelector(`[name="${name}"]`));
        let depth = read('profondita_totale');
        if (depth === null) {
            const origin = read('quota_partenza'), bottom = read('quota_ngf_fondo');
            if (origin !== null && bottom !== null) depth = origin - bottom;
        }
        const kind = form.querySelector('[name=tipologia_scavo]')?.value || root.dataset.ficheKind;
        const width = read('larghezza_pannello'), thickness = read('altezza_pannello');
        const cm = read('diametro_palo_cm');
        const diameter = cm !== null ? cm / 100 : read('diametro_palo') ?? parseValue({value:root.dataset.ficheDiameter});
        let section = null;
        if (kind === 'paratia' && width > 0 && thickness > 0) section = width * thickness;
        if (kind === 'palo' && diameter > 0) section = Math.PI * (diameter / 2) ** 2;
        return {volume:section !== null && depth > 0 ? section * depth : null, start:depth > 0 ? depth : null};
    }
    const automatic = new Map();
    const initial = defaults();
    [[volumeInput,'volume'],[startInput,'start']].forEach(([input,key]) => {
        automatic.set(input, parseValue(input) === null || (initial[key] !== null && Math.abs(parseValue(input)-initial[key]) < .0051));
        input.addEventListener('input', () => automatic.set(input, parseValue(input) === null));
    });
    function fillDefaults(force = false) {
        const values = defaults();
        [[volumeInput,'volume'],[startInput,'start']].forEach(([input,key]) => {
            if (force) automatic.set(input,true);
            if (automatic.get(input)) input.value = values[key] === null ? '' : values[key].toFixed(2);
        });
        root.querySelector('[data-courbe-theoretical-end]').value = '0';
    }
    root.querySelector('[data-courbe-reset]')?.addEventListener('click', () => {fillDefaults(true);drawChart();});
    form.addEventListener('input', event => {if (!root.contains(event.target)) {fillDefaults();drawChart();}});
    form.addEventListener('change', () => {fillDefaults();drawChart();});
    function theoreticalSeries() {
        const volume = parseValue(root.querySelector("[data-courbe-theoretical-volume]"));
        const start = parseValue(root.querySelector("[data-courbe-theoretical-start]"));
        return volume !== null && start !== null ? [{ volume: 0, hauteur: start }, { volume, hauteur: 0 }] : [];
    }
    const number = value => value.toLocaleString(document.documentElement.lang === 'fr' ? 'fr-FR' : 'it-IT', {maximumFractionDigits:2});
    const measuredTable = root.querySelector('[data-courbe-table=realisee]');
    const notice = document.createElement('div');
    notice.className = 'courbe-direction-warning';
    notice.hidden = true;
    notice.innerHTML = `<p role="alert" data-courbe-direction-message></p><button type="button" class="btn btn-secondary btn-sm" data-courbe-review-volumes>${tr('Rivedi abbinamento volumi', 'Revoir les volumes associés')}</button><div data-courbe-volume-proposal hidden></div>`;
    measuredTable.appendChild(notice);
    const proposal = notice.querySelector('[data-courbe-volume-proposal]');
    const correctionStatus = document.createElement('p');
    correctionStatus.setAttribute('role','status');
    correctionStatus.dataset.courbeCorrectionStatus = '';
    measuredTable.appendChild(correctionStatus);
    function updateDirectionNotice(points) {
        const inverted = points.some((point,index) => index && point.volume > points[index-1].volume && point.hauteur > points[index-1].hauteur + 1e-6);
        notice.hidden = !inverted;
        notice.querySelector('[data-courbe-direction-message]').textContent = tr(
            'Controlla gli abbinamenti: il volume cumulato aumenta mentre anche la profondità residua aumenta. Durante il riempimento la profondità residua normalmente diminuisce.',
            'Vérifiez les associations : le volume cumulé augmente et la profondeur restante augmente aussi. Pendant le remplissage, la profondeur restante diminue normalement.');
        // Only propose reversal for an entirely reversed sequence, never for isolated anomalies.
        const entirelyReversed = points.length > 1 && points.every((point,index) => !index || (point.volume > points[index-1].volume && point.hauteur > points[index-1].hauteur));
        const incomplete = Array.from(measuredTable.querySelectorAll('.courbe-row')).some(row => {
            const v = parseValue(row.querySelector('[data-courbe-volume]')), h = parseValue(row.querySelector('[data-courbe-hauteur]'));
            return (v === null) !== (h === null);
        });
        notice.querySelector('[data-courbe-review-volumes]').hidden = !entirelyReversed || incomplete;
        if (!inverted || !entirelyReversed || incomplete) proposal.hidden = true;
    }
    notice.querySelector('[data-courbe-review-volumes]').addEventListener('click', () => {
        const rows = Array.from(measuredTable.querySelectorAll('.courbe-row'))
            .map(row => ({row, volume:parseValue(row.querySelector('[data-courbe-volume]')), depth:parseValue(row.querySelector('[data-courbe-hauteur]'))}))
            .filter(p => p.volume !== null && p.depth !== null).sort((a,b) => a.depth-b.depth);
        const volumes = rows.map(p => p.volume).reverse();
        proposal.replaceChildren();
        const explanation = document.createElement('p');
        explanation.textContent = tr('Proposta di inversione dei volumi tra le righe. Verifica ogni abbinamento con i rilievi di cantiere prima di applicarla.', 'Proposition d’inversion des volumes entre les lignes. Vérifiez chaque association avec les relevés du chantier avant de l’appliquer.');
        proposal.appendChild(explanation);
        const comparison = document.createElement('div');
        comparison.className = 'courbe-volume-comparison';
        [tr('Profondità (m)','Profondeur (m)'),tr('Volume attuale (m³)','Volume actuel (m³)'),tr('Proposta (m³)','Proposition (m³)')].forEach(label => {
            const cell = document.createElement('strong');cell.textContent = label;comparison.appendChild(cell);
        });
        rows.forEach((point,index) => [point.depth,point.volume,volumes[index]].forEach(value => {
            const cell = document.createElement('span');cell.textContent=number(value);comparison.appendChild(cell);
        }));
        proposal.appendChild(comparison);
        const apply = document.createElement('button');apply.type='button';apply.className='btn btn-primary btn-sm';
        apply.dataset.courbeApplyVolumes='';apply.textContent=tr('Usa questi abbinamenti nell’anteprima','Utiliser ces associations dans l’aperçu');
        apply.addEventListener('click', () => {
            rows.forEach((point,index) => {point.row.querySelector('[data-courbe-volume]').value=String(volumes[index]);});
            sortRows(measuredTable);proposal.hidden=true;drawChart();
            correctionStatus.textContent=tr('Abbinamenti modificati nell’anteprima. Controlla la curva e salva i dati per aggiornare la fiche e il PDF.', 'Associations modifiées dans l’aperçu. Vérifiez la courbe puis enregistrez les données pour mettre à jour la fiche et le PDF.');
        });
        proposal.appendChild(apply);proposal.hidden=false;
    });
    function drawSeries(points, { color, dashed = false, markers = false }) {
        if (!ctx || points.length === 0) return;
        ctx.save();
        ctx.strokeStyle = color;
        ctx.fillStyle = color;
        ctx.lineWidth = 3;
        ctx.setLineDash(dashed ? [10, 6] : []);
        ctx.beginPath();
        points.forEach((point, index) => {
            const x = mapX(point.volume);
            const y = mapY(point.hauteur);
            if (index === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        });
        ctx.stroke();
        ctx.setLineDash([]);
        if (markers) {
            points.forEach(point => {
                const x = mapX(point.volume);
                const y = mapY(point.hauteur);
                ctx.beginPath();
                ctx.arc(x, y, 4.5, 0, Math.PI * 2);
                ctx.fill();
                ctx.strokeStyle = "#ffffff";
                ctx.lineWidth = 1.5;
                ctx.stroke();
                ctx.strokeStyle = color;
            });
        }
        ctx.restore();
    }
    let bounds = { minX: 0, maxX: 1, minY: 0, maxY: 1 };
    const plot = { left: 70, right: 24, top: 54, bottom: 58 };
    function mapX(value) { return plot.left + ((value - bounds.minX) / (bounds.maxX - bounds.minX || 1)) * (canvas.width - plot.left - plot.right); }
    function mapY(value) { return plot.top + ((value - bounds.minY) / (bounds.maxY - bounds.minY || 1)) * (canvas.height - plot.top - plot.bottom); }
    function drawChart() {
        if (!ctx || !canvas) return;
        const realised = readSeries("realisee");
        const theoretical = theoreticalSeries();
        const tube = readSeries("tube");
        const all = realised.concat(theoretical, tube);
        updateDirectionNotice(realised);
        const example = root.querySelector('[data-courbe-example]');
        const initialDepth = parseValue(startInput);
        if (example) example.textContent = initialDepth === null ? '' : tr(
            `Inizio getto: 0 m³ / ${number(initialDepth)} m residui. Fine getto al riferimento 0: volume totale gettato / 0 m residui.`,
            `Début du coulage : 0 m³ / ${number(initialDepth)} m restants. Fin du coulage au repère 0 : volume total coulé / 0 m restant.`);
        const status = root.querySelector('[data-courbe-status]');
        if (status) status.textContent = !theoretical.length
            ? tr('Completa le dimensioni della fiche o inserisci volume teorico e altezza iniziale per vedere la curva.', 'Complétez les dimensions de la fiche ou saisissez le volume théorique et la hauteur initiale pour afficher la courbe.')
            : realised.length < 2 ? tr('Curva teorica pronta. Inserisci almeno due rilievi per tracciare la curva reale. Salva per includerla nella fiche e nel PDF.', 'Courbe théorique prête. Saisissez au moins deux relevés pour tracer la courbe réelle. Enregistrez pour l’inclure dans la fiche et le PDF.')
            : tr('Anteprima aggiornata. Salva per aggiornare la fiche e il PDF.', 'Aperçu actualisé. Enregistrez pour mettre à jour la fiche et le PDF.');
        const maxX = Math.max(1, ...all.map(point => point.volume));
        const maxY = Math.max(1, ...all.map(point => point.hauteur));
        bounds = { minX: 0, maxX: maxX * 1.08, minY: 0, maxY: maxY * 1.08 };
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = "#ffffff";
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = "#0f172a";
        ctx.font = "bold 20px Arial, sans-serif";
        ctx.textAlign = "center";
        ctx.fillText("COURBE DE BÉTONNAGE", canvas.width / 2, 30);
        ctx.strokeStyle = "#d9d9d9";
        ctx.lineWidth = 1;
        ctx.font = "12px Arial, sans-serif";
        ctx.fillStyle = "#475569";
        ctx.textAlign = "right";
        for (let i = 0; i <= 5; i++) {
            const x = plot.left + ((canvas.width - plot.left - plot.right) / 5) * i;
            const y = plot.top + ((canvas.height - plot.top - plot.bottom) / 5) * i;
            ctx.beginPath(); ctx.moveTo(x, plot.top); ctx.lineTo(x, canvas.height - plot.bottom); ctx.stroke();
            ctx.beginPath(); ctx.moveTo(plot.left, y); ctx.lineTo(canvas.width - plot.right, y); ctx.stroke();
            ctx.fillText((bounds.minY + ((bounds.maxY - bounds.minY) / 5) * i).toFixed(1), plot.left - 8, y + 4);
            ctx.textAlign = "center";
            ctx.fillText((bounds.maxX / 5 * i).toFixed(1), x, canvas.height - plot.bottom + 20);
            ctx.textAlign = "right";
        }
        ctx.strokeStyle = "#000000"; ctx.lineWidth = 1;
        ctx.strokeRect(plot.left, plot.top, canvas.width - plot.left - plot.right, canvas.height - plot.top - plot.bottom);
        ctx.fillStyle = "#0f172a"; ctx.font = "bold 13px Arial, sans-serif"; ctx.textAlign = "center";
        ctx.fillText(tr('Volume cumulato (m³)', 'Volume cumulé (m³)'), (canvas.width + plot.left - plot.right) / 2, canvas.height - 12);
        ctx.save(); ctx.translate(18, canvas.height / 2); ctx.rotate(-Math.PI / 2); ctx.fillText(tr('Profondità residua (m)', 'Profondeur restante (m)'), 0, 0); ctx.restore();
        drawSeries(realised, { color: "#2563eb", markers: true });
        drawSeries(theoretical, { color: "#dc2626", dashed: true });
        drawSeries(tube, { color: "#16a34a", dashed: true, markers: true });
    }
    let rowCounter = 0;
    function ensureStableRowIds() {
        root.querySelectorAll(".courbe-row").forEach(row => {
            if (!row.dataset.courbeRowId) {
                row.dataset.courbeRowId = `row-${rowCounter++}`;
            }
        });
    }
    function sortRows(table) {
        const rowsContainer = table.querySelector("[data-courbe-rows]");
        Array.from(rowsContainer.querySelectorAll(".courbe-row"))
            .sort((a, b) => (parseValue(b.querySelector("[data-courbe-volume]")) ?? -Infinity) - (parseValue(a.querySelector("[data-courbe-volume]")) ?? -Infinity))
            .forEach(row => rowsContainer.appendChild(row));
    }
    function addRow(tableName) {
        const table = root.querySelector(`[data-courbe-table="${tableName}"]`);
        const rows = table.querySelector("[data-courbe-rows]");
        const prefix = tableName === "tube" ? "courbe_tube" : "courbe_realisee";
        const row = document.createElement("div");
        row.className = "courbe-row";
        row.dataset.courbeRowId = `row-${rowCounter++}`;
        row.innerHTML = `<input class="form-control" name="${prefix}_volume" type="number" step="0.01" min="0" data-courbe-volume><input class="form-control" name="${prefix}_hauteur" type="number" step="0.01" data-courbe-hauteur><button type="button" class="btn btn-secondary btn-sm" data-remove-courbe-row>Supprimer</button>`;
        rows.appendChild(row);
        row.querySelector("input")?.focus();
        drawChart();
    }
    root.addEventListener("click", event => {
        const add = event.target.closest("[data-add-courbe-row]");
        if (add) { proposal.hidden=true; addRow(add.dataset.addCourbeRow); }
        const remove = event.target.closest("[data-remove-courbe-row]");
        if (remove) { proposal.hidden=true; remove.closest(".courbe-row")?.remove(); drawChart(); }
    });
    root.addEventListener("input", event => {
        proposal.hidden=true;correctionStatus.textContent='';
        drawChart();
    });
    root.querySelectorAll('[data-courbe-table]').forEach(table => {
        const order = document.createElement('button');order.type='button';order.className='btn btn-secondary btn-sm';
        order.dataset.courbeOrder='';order.textContent=tr('Ordina volumi ↓','Trier les volumes ↓');
        order.addEventListener('click', () => {sortRows(table);proposal.hidden=true;});
        table.querySelector('[data-add-courbe-row]').after(order);
        sortRows(table);
    });
    checkbox?.addEventListener("change", () => { panel.hidden = !checkbox.checked; fillDefaults(); drawChart(); });
    ensureStableRowIds();
    fillDefaults();
    drawChart();
});
