// 제목과 날짜가 일치하는 활용사례 카드를 찾아 클릭하고 클릭 결과를 반환한다.
const item = arguments[0];
const typeWords = arguments[1];
const dateRe = /^20\d{2}-\d{2}-\d{2}$/;
const anyDateRe = /\b20\d{2}-\d{2}-\d{2}\b/g;

// 전용 카드 구조에서는 제목과 날짜를 모두 대조해 클릭 대상을 정한다.
const modernCard = [...document.querySelectorAll('.card-wrap > .item')].find(card =>
    (card.querySelector('.card-title')?.innerText || '').trim() === item.title &&
    (card.querySelector('.card-date')?.innerText || '').trim() === item.date
);
if (modernCard) {
    const link = modernCard.querySelector('a.card-txt');
    if (link) {
        link.click();
        return {clicked: true, layout: 'card-wrap'};
    }
}

// 요소의 본문을 공백과 빈 줄이 정리된 문자열 배열로 변환한다.
function linesOf(el) {
    return (el.innerText || '').split(/\n+/).map(v => v.trim()).filter(Boolean);
}

// 전용 구조가 없는 화면에서 날짜 요소의 상위 영역을 따라가며 제목이 일치하는 카드를 찾는다.
function findCard() {
    const everyElement = [...document.querySelectorAll('body *')];
    const dateElements = everyElement.filter(el => {
        const text = (el.innerText || '').trim();
        return text === item.date &&
            ![...el.children].some(child => (child.innerText || '').trim() === item.date);
    });

    for (const dateEl of dateElements) {
        let node = dateEl.parentElement;
        while (node && node !== document.body) {
            const text = (node.innerText || '').trim();
            if (text.length > 6000) break;
            const lines = linesOf(node);
            const dateIndex = lines.findIndex(line => line === item.date || line.includes(item.date));
            const typeIndex = lines.findIndex(line => typeWords.some(word => line.includes(word)));
            const dates = (text.match(anyDateRe) || []);
            if (
                dateIndex >= 0 && typeIndex >= 0 && typeIndex < dateIndex &&
                dates.length === 1 && text.includes(item.title)
            ) {
                return node;
            }
            node = node.parentElement;
        }
    }
    return null;
}

const card = findCard();
if (!card) return {clicked: false, reason: 'card-not-found'};
card.scrollIntoView({block: 'center', inline: 'nearest'});

// 화면에 표시된 클릭 후보 중 첨부파일 다운로드 요소는 제외한다.
const clickables = [...card.querySelectorAll('a, button, [onclick], [role="button"], [tabindex]')]
    .filter(el => {
        const raw = `${el.getAttribute('href') || ''} ${el.getAttribute('onclick') || ''}`;
        const style = window.getComputedStyle(el);
        return style.display !== 'none' && style.visibility !== 'hidden' &&
            !/fileDownload|atchFileId|fileDetailSn|download/i.test(raw);
    });

// 제목 일치 정도와 상세 페이지 단서에 따라 클릭 후보의 우선순위를 점수로 반환한다.
function score(el) {
    const text = (el.innerText || '').trim();
    const raw = `${el.getAttribute('href') || ''} ${el.getAttribute('onclick') || ''}`;
    let value = 0;
    if (text === item.title) value += 1000;
    else if (text.includes(item.title)) value += 500;
    if (/selectPublicUseCaseView|prcuseCaseSn|detail|view/i.test(raw)) value += 400;
    if (el.tagName === 'A') value += 30;
    return value;
}

clickables.sort((a, b) => score(b) - score(a));
let target = clickables[0] || null;

if (!target) {
    const exactTitle = [...card.querySelectorAll('*')]
        .filter(el => (el.innerText || '').trim() === item.title)
        .sort((a, b) => a.children.length - b.children.length)[0];
    target = exactTitle?.closest('a, button, [onclick], [role="button"]') || exactTitle || card;
}

const before = location.href;
target.dispatchEvent(new MouseEvent('mouseover', {bubbles: true, cancelable: true, view: window}));
target.dispatchEvent(new MouseEvent('mousedown', {bubbles: true, cancelable: true, view: window}));
target.dispatchEvent(new MouseEvent('mouseup', {bubbles: true, cancelable: true, view: window}));
target.click();

return {
    clicked: true,
    before,
    targetTag: target.tagName,
    targetText: (target.innerText || '').trim().slice(0, 120),
    href: target.getAttribute?.('href') || '',
    onclick: target.getAttribute?.('onclick') || '',
};
