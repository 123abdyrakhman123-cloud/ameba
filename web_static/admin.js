const root = document.getElementById('view');
const notice = document.getElementById('notice');
let accounts = [];

async function api(method, path, data) {
    const options = { method, credentials: 'same-origin', headers: {} };
    if (data !== undefined) {
        options.headers['Content-Type'] = 'application/json';
        options.body = JSON.stringify(data);
    }
    const response = await fetch(path, options);
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Ошибка запроса');
    return result;
}

function message(text, error = false) {
    notice.textContent = text;
    notice.classList.toggle('error', error);
    notice.style.display = text ? 'block' : 'none';
    if (text) window.setTimeout(() => { notice.style.display = 'none'; }, 4500);
}

function esc(value) {
    return String(value ?? '').replace(/[&<>"']/g, char => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[char]));
}

function field(label, name, value = '', wide = false, type = 'text') {
    return `<label class="label${wide ? ' wide' : ''}">${label}<input class="field" name="${name}" type="${type}" value="${esc(value)}"></label>`;
}

async function show(view = 'questions') {
    document.querySelectorAll('.tab').forEach(tab => tab.classList.toggle('active', tab.dataset.view === view));
    try {
        if (view === 'questions') await showQuestions();
        if (view === 'stats') await showStats();
        if (view === 'support') await showSupport();
        if (view === 'content') await showContent();
        if (view === 'accounts') await showAccounts();
    } catch (error) { message(error.message, true); }
}

async function showQuestions(search = '') {
    root.innerHTML = `<div class="view-head"><div><h1>Вопросы</h1><p>Поиск и редактирование банка вопросов</p></div></div>
      <div class="toolbar"><input id="questionSearch" class="field search" placeholder="Поиск по тексту или объяснению" value="${esc(search)}"><button id="searchQuestions" class="button primary">Найти</button></div><div id="questionList" class="data-list"></div>`;
    const load = async () => {
        const query = document.getElementById('questionSearch').value.trim();
        const data = await api('GET', `/api/admin/questions?q=${encodeURIComponent(query)}`);
        const list = document.getElementById('questionList');
        list.innerHTML = data.questions.map(q => `<article class="row"><div><div class="row-title">${esc(q.question)}</div><div class="row-meta">${esc(q.subject)} · #${q.id}</div></div><div class="row-actions"><button class="button" data-edit="${q.id}">Изменить</button><button class="button danger" data-delete="${q.id}">Удалить</button></div></article>`).join('') || '<div class="empty-state">Ничего не найдено</div>';
        data.questions.forEach(q => {
            list.querySelector(`[data-edit="${q.id}"]`).onclick = () => editQuestion(q);
            list.querySelector(`[data-delete="${q.id}"]`).onclick = async () => {
                if (!window.confirm('Удалить вопрос из банка?')) return;
                try { await api('POST', `/api/admin/question/${q.id}/delete`, {}); message('Вопрос удалён'); await load(); }
                catch (error) { message(error.message, true); }
            };
        });
    };
    document.getElementById('searchQuestions').onclick = load;
    document.getElementById('questionSearch').onkeydown = event => { if (event.key === 'Enter') load(); };
    await load();
}

function editQuestion(q) {
    const list = document.getElementById('questionList');
    const options = [q.option1, q.option2, q.option3, q.option4, q.option5];
    list.innerHTML = `<form id="questionForm" class="form-block"><h2>Вопрос #${q.id} · ${esc(q.subject)}</h2><div class="form-grid">
      ${field('Текст вопроса', 'question', q.question, true)}
      ${options.map((value, index) => field(`Вариант ${index + 1}`, `option${index + 1}`, value || '')).join('')}
      ${field('Номер правильного ответа', 'correct_option', q.correct_option, false, 'number')}
      <label class="label wide">Объяснение<textarea class="field" name="explanation" rows="4">${esc(q.explanation)}</textarea></label>
      </div><div class="toolbar" style="margin-top:12px"><button class="button primary">Сохранить</button><button type="button" id="cancelEdit" class="button">Назад к списку</button></div></form>`;
    document.getElementById('cancelEdit').onclick = () => showQuestions(document.getElementById('questionSearch')?.value || '');
    document.getElementById('questionForm').onsubmit = async event => {
        event.preventDefault();
        const form = new FormData(event.currentTarget);
        const data = Object.fromEntries(form.entries());
        try { await api('POST', `/api/admin/question/${q.id}`, data); message('Изменения сохранены'); await showQuestions(); }
        catch (error) { message(error.message, true); }
    };
}

async function showStats() {
    const s = await api('GET', '/api/admin/stats');
    root.innerHTML = `<div class="view-head"><div><h1>Статистика</h1><p>Сводка учебной платформы</p></div><button class="button" onclick="show('stats')">Обновить</button></div>
      <div class="stats-grid">${[['Пользователи',s.total_users],['Ответы',s.total_answers],['Покупки',s.total_purchases],['Вопросы',s.total_questions],['Экзамены',s.total_exams],['Рефералы',s.total_referrals]].map(([label,value])=>`<div class="stat"><strong>${Number(value)||0}</strong><span>${label}</span></div>`).join('')}</div>
      <h2>Вопросы по предметам</h2><div class="data-list">${(s.questions_by_subject||[]).map(row=>`<div class="row"><span>${esc(row.subject)}</span><strong>${row.count}</strong></div>`).join('')}</div>`;
}

async function showSupport() {
    const data = await api('GET', '/api/admin/support');
    root.innerHTML = `<div class="view-head"><div><h1>Поддержка</h1><p>Обращения пользователей</p></div><button class="button" onclick="show('support')">Обновить</button></div><div class="split"><div id="ticketList" class="data-list"></div><section id="ticketDetail" class="detail empty-state">Выберите обращение</section></div>`;
    const list = document.getElementById('ticketList');
    list.innerHTML = data.tickets.map(ticket => `<button class="row ticket-row" data-ticket="${ticket.id}"><span><span class="row-title">${esc(ticket.message.slice(0,100))}</span><span class="row-meta">${esc(ticket.provider)}:${esc(ticket.account_key)} · ${esc(ticket.status)} · ${esc(ticket.created_at)}</span></span></button>`).join('') || '<div class="empty-state">Обращений нет</div>';
    data.tickets.forEach(ticket => list.querySelector(`[data-ticket="${ticket.id}"]`).onclick = () => {
        const detail = document.getElementById('ticketDetail');
        detail.classList.remove('empty-state');
        detail.innerHTML = `<h2>Обращение #${ticket.id}</h2><p class="row-meta">${esc(ticket.provider)}:${esc(ticket.account_key)} · ${esc(ticket.created_at)}</p><div class="ticket-message">${esc(ticket.message)}</div>${ticket.replies.map(reply=>`<div class="reply"><div class="row-meta">${esc(reply.author_provider)} · ${esc(reply.created_at)}</div>${esc(reply.message)}</div>`).join('')}<form id="replyForm" class="form-block"><label class="label">Ответ<textarea class="field" name="message" rows="4" required></textarea></label><button class="button primary" style="margin-top:10px">Отправить ответ</button></form>`;
        document.getElementById('replyForm').onsubmit = async event => { event.preventDefault(); const value = new FormData(event.currentTarget).get('message'); try { await api('POST', `/api/admin/support/${ticket.id}/reply`, {message:value}); message('Ответ отправлен'); await showSupport(); } catch(error) { message(error.message,true); } };
    });
}

async function showContent() {
    const [promo, announcements] = await Promise.all([api('GET','/api/promo'), api('GET','/api/announcements')]);
    root.innerHTML = `<div class="view-head"><div><h1>Объявления и промо</h1><p>Контент, который увидят пользователи веб-приложения</p></div></div>
      <form id="promoForm" class="form-block"><h2>Промо-текст</h2><label class="label">Текст<textarea class="field" name="text" rows="3">${esc(promo.text)}</textarea></label><div class="toolbar"><button class="button primary">Сохранить промо</button><button id="clearPromo" type="button" class="button">Очистить</button></div></form>
      <form id="announcementForm" class="form-block"><h2>Новое объявление</h2><div class="form-grid">${field('Заголовок','title','',true)}<label class="label wide">Текст<textarea class="field" name="body" rows="4" required></textarea></label></div><button class="button primary" style="margin-top:10px">Опубликовать</button></form>
      <div class="form-block"><h2>Активные объявления</h2><div class="data-list">${announcements.announcements.map(item=>`<article class="row"><div><div class="row-title">${esc(item.title)}</div><div>${esc(item.body)}</div><div class="row-meta">${esc(item.created_at)}</div></div></article>`).join('')||'<div class="empty-state">Объявлений нет</div>'}</div></div>`;
    document.getElementById('promoForm').onsubmit = async event => { event.preventDefault(); const text = new FormData(event.currentTarget).get('text'); try { await api('POST','/api/admin/promo',{text}); message('Промо сохранено'); } catch(error) { message(error.message,true); } };
    document.getElementById('clearPromo').onclick = async () => { try { await api('POST','/api/admin/promo',{text:''}); message('Промо очищено'); showContent(); } catch(error) { message(error.message,true); } };
    document.getElementById('announcementForm').onsubmit = async event => { event.preventDefault(); const data = Object.fromEntries(new FormData(event.currentTarget).entries()); try { await api('POST','/api/admin/announcements',data); message('Объявление опубликовано'); showContent(); } catch(error) { message(error.message,true); } };
}

async function showAccounts() {
    const catalog = await api('GET', '/api/config');
    const subjects = Object.values(catalog.faculties || {}).flatMap(faculty =>
        Object.values(faculty.subjects || {}).flat().map(subject => [subject.key, subject.name])
    );
    const uniqueSubjects = [...new Map(subjects).entries()];
    root.innerHTML = `<div class="view-head"><div><h1>Пользователи и доступ</h1><p>Поиск по Telegram ID, имени, username, Google subject или почте</p></div></div>
      <div class="toolbar"><input id="accountSearch" class="field search" placeholder="Введите идентификатор или имя"><button id="findAccounts" class="button primary">Найти</button></div><div id="accountList" class="data-list"></div>
      <form id="accessForm" class="form-block"><h2>Выдать или отозвать доступ</h2><div class="form-grid"><label class="label">Провайдер<select class="field" name="provider"><option value="telegram">Telegram</option><option value="google">Google</option></select></label>${field('ID / Google subject','account_key')}<label class="label">Предмет<select class="field" name="subject" id="subject">${uniqueSubjects.map(([key,name])=>`<option value="${esc(key)}">${esc(name)}</option>`).join('')}</select></label><label class="label">Истекает (необязательно)<input class="field" name="expires_at" type="date"></label></div><div class="toolbar"><button class="button primary" name="action" value="grant">Выдать доступ</button><button class="button danger" name="action" value="revoke">Отозвать доступ</button></div></form>`;
    const find = async () => {
        const q = document.getElementById('accountSearch').value.trim();
        const data = await api('GET', `/api/admin/accounts?q=${encodeURIComponent(q)}`);
        accounts = data.accounts;
        document.getElementById('accountList').innerHTML = accounts.map((account,index)=>`<button class="row" data-account="${index}"><span><span class="pill">${esc(account.provider)}</span> <span class="row-title">${esc(account.label||account.username||account.account_key)}</span><span class="row-meta">${esc(account.account_key)} · ${esc(account.username)}</span></span></button>`).join('')||'<div class="empty-state">Аккаунты не найдены</div>';
        accounts.forEach((account,index)=>document.querySelector(`[data-account="${index}"]`).onclick=()=>{
            document.querySelector('#accessForm [name="provider"]').value=account.provider;
            document.querySelector('#accessForm [name="account_key"]').value=account.account_key;
        });
    };
    document.getElementById('findAccounts').onclick = find;
    document.getElementById('accountSearch').onkeydown = event => { if(event.key==='Enter') find(); };
    document.getElementById('accessForm').onsubmit = async event => {
        event.preventDefault();
        const form = event.currentTarget;
        const data = Object.fromEntries(new FormData(form).entries());
        data.action = event.submitter.value;
        if (data.expires_at) data.expires_at = `${data.expires_at} 23:59:59`;
        try { await api('POST','/api/admin/access',data); message(data.action==='grant'?'Доступ выдан':'Доступ отозван'); }
        catch(error) { message(error.message,true); }
    };
}

document.querySelectorAll('.tab').forEach(tab => tab.addEventListener('click', () => show(tab.dataset.view)));
document.getElementById('signOut').onclick = async () => { await api('POST','/api/session/logout',{}); window.location.href='/'; };

(async () => {
    try {
        const session = await api('GET','/api/session');
        const permission = await api('GET','/api/admin/check');
        if (!session.authenticated || !permission.is_admin) {
            document.getElementById('authState').innerHTML = 'Нет доступа. <a href="/">Войдите в веб-приложение</a> аккаунтом администратора Telegram.';
            return;
        }
        document.getElementById('authState').hidden = true;
        document.getElementById('adminAccount').hidden = false;
        document.getElementById('adminName').textContent = session.display_name || session.account_key;
        document.getElementById('adminApp').hidden = false;
        await show();
    } catch (error) {
        document.getElementById('authState').innerHTML = 'Нет активной сессии. <a href="/">Войдите в веб-приложение</a> аккаунтом администратора Telegram.';
    }
})();
