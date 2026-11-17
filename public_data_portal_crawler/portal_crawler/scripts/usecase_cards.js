// 브라우저의 활용사례 목록을 읽어 카드 정보와 탐색 진단을 반환한다.
const typeWords = arguments[0];
const dateRe = /^20\d{2}-\d{2}-\d{2}$/;
const anyDateRe = /\b20\d{2}-\d{2}-\d{2}\b/g;

// 제목·날짜 전용 요소에서 카드 정보를 추출한다. 찾지 못하면 아래의 날짜 기반 탐색을 사용한다.
const modern = [...document.querySelectorAll('.card-wrap > .item')].map(card => {
    const title = (card.querySelector('.card-title')?.innerText || '').trim();
    const date = (card.querySelector('.card-date')?.innerText || '').trim();
    const link = card.querySelector('a.card-txt');
    const raw = `${link?.getAttribute('href') || ''} ${link?.getAttribute('onclick') || ''}`;
    const sn = raw.match(/(?:fn_view|prcuseCaseSn)[^0-9]*(\d+)/)?.[1] || '';
    const href = link?.getAttribute('href') || '';
    return {key: sn || `${title}|${date}`, sn, title, date,
            cardText: (card.innerText || '').trim(),
            detailUrl: /selectPublicUseCaseView\.do/i.test(href) ? link.href : ''};
}).filter(item => item.title && dateRe.test(item.date));
if (modern.length) {
    return {items: modern, diagnostics: {layout: 'card-wrap', count: modern.length}};
}

// 요소의 본문을 줄 단위로 정리하고 빈 줄을 제외한 배열을 반환한다.
function linesOf(el) {
    return (el.innerText || '')
        .split(/\n+/)
        .map(v => v.trim())
        .filter(Boolean);
}

// 개발유형·제목·날짜 배치로 단일 카드 여부를 판단하고, 유효한 카드의 제목을 반환한다.
function itemFromCandidate(card, dateText) {
    const lines = linesOf(card);
    if (lines.length < 3) return null;

    const dateIndex = lines.findIndex(line => line === dateText || line.includes(dateText));
    const typeIndex = lines.findIndex(line => typeWords.some(word => line.includes(word)));
    if (dateIndex < 0 || typeIndex < 0 || typeIndex >= dateIndex) return null;

    let title = '';
    for (let i = typeIndex + 1; i < dateIndex; i++) {
        const line = lines[i];
        if (!dateRe.test(line) && !typeWords.includes(line) && line.length <= 200) {
            title = line;
            break;
        }
    }
    if (!title) return null;

    // 카드 한 개에 날짜가 여러 개 들어가면 상위 목록 컨테이너일 가능성이 높다.
    const dates = ((card.innerText || '').match(anyDateRe) || []);
    if (dates.length !== 1) return null;

    return {lines, title};
}

// 상세 주소·일련번호 탐색에 쓸 속성을 모으며 첨부파일 다운로드 관련 속성은 제외한다.
function relevantAttributes(card) {
    const values = [];
    const nodes = [card, ...card.querySelectorAll('*')];
    for (const node of nodes) {
        const raw = [
            node.getAttribute?.('href') || '',
            node.getAttribute?.('onclick') || '',
            node.getAttribute?.('value') || '',
            node.getAttribute?.('data-id') || '',
            node.getAttribute?.('data-sn') || '',
            node.getAttribute?.('data-prcuse-case-sn') || '',
        ].join(' ');
        if (!raw || /fileDownload|atchFileId|fileDetailSn/i.test(raw)) continue;
        values.push(raw);
    }
    return values.join(' ');
}

const everyElement = [...document.querySelectorAll('body *')];
// 날짜 문자열이 직접 표시된 가장 안쪽 요소만 탐색의 시작점으로 사용한다.
const dateElements = everyElement.filter(el => {
    const text = (el.innerText || '').trim();
    if (!dateRe.test(text)) return false;
    // 같은 날짜 텍스트를 가진 더 안쪽 자식이 있으면 바깥 요소는 제외한다.
    return ![...el.children].some(child => dateRe.test((child.innerText || '').trim()));
});

const results = [];
const seen = new Set();

for (const dateEl of dateElements) {
    const dateText = (dateEl.innerText || '').trim();
    let node = dateEl.parentElement;
    let selected = null;
    let parsed = null;

    while (node && node !== document.body) {
        const text = (node.innerText || '').trim();
        if (text.length > 6000) break;

        const attempt = itemFromCandidate(node, dateText);
        if (attempt) {
            selected = node;
            parsed = attempt;
            break;
        }
        node = node.parentElement;
    }

    if (!selected || !parsed) continue;

    const attributeText = relevantAttributes(selected);
    let sn = '';
    let detailUrl = '';

    const snPatterns = [
        /prcuseCaseSn(?:%3D|=|\s*[:]\s*|[^0-9]{0,30})(\d{5,12})/i,
        /selectPublicUseCaseView\.do[^\s"']*?(\d{5,12})/i,
        /(?:detail|view|select|go)[^(]{0,40}\(\s*["']?(\d{5,12})/i,
    ];
    for (const pattern of snPatterns) {
        const match = attributeText.match(pattern);
        if (match) {
            sn = match[1];
            break;
        }
    }

    const links = [...selected.querySelectorAll('a')];
    for (const link of links) {
        const href = link.href || link.getAttribute('href') || '';
        if (/selectPublicUseCaseView\.do/i.test(href)) {
            detailUrl = href;
            break;
        }
    }

    const key = sn || `${parsed.title}|${dateText}`;
    if (seen.has(key)) continue;
    seen.add(key);

    results.push({
        key,
        sn,
        title: parsed.title,
        date: dateText,
        cardText: (selected.innerText || '').trim(),
        detailUrl,
    });
}

return {
    items: results,
    diagnostics: {
        bodyTextLength: (document.body?.innerText || '').length,
        dateElementCount: dateElements.length,
        totalText: ([...(document.body?.innerText || '').matchAll(/총\s*[\d,]+건/g)]
            .map(m => m[0])[0] || ''),
    },
};
