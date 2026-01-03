(() => {
    const input = document.getElementById('list-search');
    if (!input) {
        return;
    }

    const normalize = (value) => value
        .toLowerCase()
        .normalize('NFD')
        .replace(/\p{Diacritic}/gu, '');

    const items = Array.from(document.querySelectorAll('[data-list-item]'));
    const itemText = new Map(
        items.map((item) => [
            item,
            normalize(item.dataset.searchText || item.textContent || ''),
        ]),
    );

    const applyFilter = () => {
        const query = normalize(input.value.trim());
        items.forEach((item) => {
            const matches = !query || (itemText.get(item) || '').includes(query);
            if (item.tagName === 'TR') {
                item.style.display = matches ? 'table-row' : 'none';
            } else {
                item.style.display = matches ? '' : 'none';
            }
        });
    };

    input.addEventListener('input', applyFilter);
})();
