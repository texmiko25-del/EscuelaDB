(function () {
    const form = document.querySelector('[data-registry-search]');
    if (!form) return;

    const searchField = form.querySelector('input[name="q"]');
    const resultsSection = document.getElementById('filter-results');
    const resultsTitle = document.getElementById('filter-results-title');
    const resultsBody = document.getElementById('filter-results-body');
    const defaultList = document.getElementById('registry-default-list')
        || document.getElementById('student-default-list');
    const resultsPagination = resultsSection.querySelector('.admin-pagination');
    const matchCount = document.querySelector('[data-registry-match-count]');
    const matchPercent = document.querySelector('[data-registry-match-percent]');
    const matchTrack = document.querySelector('[data-registry-match-track]');
    const resultsKey = form.dataset.resultsKey;
    const resultsUrl = form.dataset.resultsUrl;
    const fields = resultsBody.dataset.searchFields.split(',');
    let searchTimer;
    let activeRequest;

    function renderResults(query, data) {
        if (!Array.isArray(data[resultsKey]) || typeof data.total !== 'number') {
            throw new Error('La búsqueda devolvió datos no válidos.');
        }

        const totalRegistered = Number(matchTrack.dataset.total);
        const percentage = totalRegistered
            ? Math.round((data.total / totalRegistered) * 100)
            : 0;
        matchCount.textContent = String(data.total);
        matchPercent.textContent = String(percentage);
        matchTrack.setAttribute('aria-label', `${percentage} por ciento del total`);
        matchTrack.firstElementChild.style.width = `${percentage}%`;
        resultsTitle.textContent = `Resultados para «${query}» (${data.total})`;
        resultsBody.replaceChildren();

        if (!data[resultsKey].length) {
            const row = document.createElement('tr');
            const cell = document.createElement('td');
            cell.colSpan = fields.length;
            cell.textContent = resultsBody.dataset.emptyMessage;
            row.append(cell);
            resultsBody.append(row);
        } else {
            data[resultsKey].forEach((record) => {
                const row = document.createElement('tr');
                fields.forEach((field) => {
                    const cell = document.createElement('td');
                    cell.textContent = record[field] == null ? '' : String(record[field]);
                    row.append(cell);
                });
                resultsBody.append(row);
            });
        }

        resultsSection.hidden = false;
        resultsSection.removeAttribute('aria-busy');
        if (resultsPagination) resultsPagination.hidden = true;
    }

    function showSearchError() {
        resultsTitle.textContent = 'No se pudo completar la búsqueda. Intenta de nuevo.';
        resultsBody.replaceChildren();
        resultsSection.hidden = false;
        resultsSection.removeAttribute('aria-busy');
    }

    async function searchRecords(query) {
        if (activeRequest) activeRequest.abort();
        defaultList.hidden = Boolean(query);

        if (!query) {
            resultsSection.hidden = true;
            resultsSection.removeAttribute('aria-busy');
            const totalRegistered = Number(matchTrack.dataset.total);
            matchCount.textContent = String(totalRegistered);
            matchPercent.textContent = totalRegistered ? '100' : '0';
            matchTrack.setAttribute(
                'aria-label',
                `${totalRegistered ? 100 : 0} por ciento del total`,
            );
            matchTrack.firstElementChild.style.width = totalRegistered ? '100%' : '0%';
            const url = new URL(window.location.href);
            url.searchParams.delete('q');
            url.searchParams.delete('page');
            url.searchParams.delete('format');
            window.history.replaceState(null, '', url);
            return;
        }

        activeRequest = new AbortController();
        resultsSection.hidden = false;
        resultsSection.setAttribute('aria-busy', 'true');
        resultsTitle.textContent = 'Buscando...';

        const url = new URL(resultsUrl, window.location.origin);
        url.searchParams.set('q', query);
        url.searchParams.set('format', 'json');
        window.history.replaceState(null, '', `${url.pathname}?${url.searchParams}`);

        try {
            const response = await fetch(url, {signal: activeRequest.signal});
            if (!response.ok) throw new Error('La búsqueda respondió con un error.');
            renderResults(query, await response.json());
        } catch (error) {
            if (error.name !== 'AbortError') showSearchError();
        }
    }

    searchField.addEventListener('input', () => {
        window.clearTimeout(searchTimer);
        const query = searchField.value.trim();
        searchTimer = window.setTimeout(() => searchRecords(query), 200);
    });

    form.addEventListener('submit', (event) => {
        event.preventDefault();
        window.clearTimeout(searchTimer);
        searchRecords(searchField.value.trim());
    });

    if (searchField.value.trim()) searchRecords(searchField.value.trim());
})();
