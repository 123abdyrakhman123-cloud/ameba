from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    content = path.read_text(encoding="utf-8")
    occurrences = content.count(old)
    if occurrences != 1:
        raise RuntimeError(f"Expected one patch target in {path}, found {occurrences}")
    path.write_text(content.replace(old, new, 1), encoding="utf-8")


replace_once(
    Path("/app/webapp_analytics.py"),
    '''    source_users = {}
    source_event_users = {}
    for row in selected:
        actor = row["actor"]
        source = first_touch.get(actor, {}).get("source") or "direct_or_unknown"
        source_users.setdefault(source, set()).add(actor)
        source_event_users.setdefault((source, row["event_name"]), set()).add(actor)
    sources = []
    for source in sorted(source_users):
        sources.append({
            "source": source,
            "landing_users": len(source_event_users.get((source, "landing_view"), set())),
            "authenticated_users": len(source_event_users.get((source, "auth_succeeded"), set())),
            "practice_users": len(source_event_users.get((source, "practice_started"), set())),
''',
    '''    first_touch_sources = {}
    source_event_users = {}
    for row in selected:
        actor = row["actor"]
        source = first_touch.get(actor, {}).get("source") or "direct_or_unknown"
        first_touch_sources.setdefault(source, set()).add(actor)
        source_event_users.setdefault((source, row["event_name"]), set()).add(actor)
    landing_users_by_source = {}
    for row in normalized:
        if row["event_name"] != "landing_view":
            continue
        source = row["dimensions"].get("source") or "direct_or_unknown"
        landing_users_by_source.setdefault(source, set()).add(row["actor"])
    source_names = set(first_touch_sources) | set(landing_users_by_source)
    if "source" in clean_filters:
        source_names.intersection_update({clean_filters["source"]})
    sources = []
    for source in sorted(source_names):
        sources.append({
            "source": source,
            "landing_users": len(landing_users_by_source.get(source, set())),
            "authenticated_users": len(source_event_users.get((source, "auth_succeeded"), set())),
            "practice_users": len(source_event_users.get((source, "practice_started"), set())),
''',
)

replace_once(
    Path("/app/web_static/admin.js"),
    '''    const funnelRows = (report.funnel || []).map(item => `<div class="row analytics-row"><span>${esc(item.event_name.replaceAll('_', ' '))}</span><strong>${Number(item.users) || 0} польз.</strong><span>${item.previous_stage_users ? `${item.step_users}/${item.previous_stage_users} · ${item.step_conversion_percent}%` : 'начальный этап'}</span></div>`).join('');
''',
    '''    const funnelRows = (report.funnel || []).map(item => `<div class="row analytics-row"><span>${esc(item.event_name.replaceAll('_', ' '))}</span><strong>${Number(item.users) || 0} польз.</strong><span>${item.previous_stage_users ? `${item.step_users}/${item.previous_stage_users} · ${item.step_conversion_percent}%` : 'начальный этап'}</span></div>`).join('');
    const sourceLabel = source => ({ instagram: 'Instagram', telegram: 'Telegram', qr: 'Листовки · QR', direct_or_unknown: 'Без метки' })[source] || source;
    const sourceRows = (report.sources || []).map(item => `<div class="row analytics-row"><strong>${esc(sourceLabel(item.source))}</strong><span>Перешли: ${Number(item.landing_users) || 0}</span><span>Вошли: ${Number(item.authenticated_users) || 0}</span><span>Начали: ${Number(item.practice_users) || 0}</span><span>Покупки: ${Number(item.verified_purchases) || 0}</span></div>`).join('');
''',
)

replace_once(
    Path("/app/web_static/admin.js"),
    '''      <div class="analytics-columns"><section class="analytics-section"><h2>Источники · первое касание</h2><div class="data-list">${(report.sources || []).map(item => `<div class="row analytics-row"><strong>${esc(item.source)}</strong><span>Входы ${item.authenticated_users}</span><span>Начали ${item.practice_users}</span><span>Выдачи ${item.verified_purchases}</span></div>`).join('') || '<div class="empty-state">Нет данных за выбранный период</div>'}</div></section>
''',
    '''      <div class="analytics-columns"><section class="analytics-section"><h2>Переходы и конверсии по каналам</h2><div class="data-list">${sourceRows || '<div class="empty-state">Нет данных за выбранный период</div>'}</div><p class="muted">Переходы считаются по метке каждой ссылки; конверсии — по первому источнику пользователя.</p></section>
''',
)
