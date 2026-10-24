/* Shared reader: no administration, writes, model calls or private diagnostics. */
(() => {
  'use strict';
  const $ = selector => document.querySelector(selector);
  const $$ = selector => [...document.querySelectorAll(selector)];
  const base = window.CERO_PUBLIC.base;
  const form = $('#filters');
  let view = 'radar', preset = 'all', currency = 'EUR', market = 'España', request = 0, debounce;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const money = value => value == null ? 'Por confirmar' : new Intl.NumberFormat('es-ES', {style:'currency',currency}).format(value);
  const when = value => value ? new Date(value).toLocaleString('es-ES', {day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'}) : 'Sin comprobar';
  const labels = {verified:'Verificada',candidate:'Por verificar',unverified:'Sin confirmar',expired:'Sin stock',ended:'Oferta finalizada',removed:'Enlace retirado',blocked:'Sin lectura',conditional:'En revisión',stale:'Pendiente de renovar',in_stock:'En stock',out_of_stock:'Sin stock',preorder:'Bajo pedido',unknown:'Sin confirmar'};
  const safe = value => {
    if (/^\/static\/cache\/[a-f0-9]{64}\.webp$/.test(value || '')) return esc(base + value.slice(1));
    try {const parsed = new URL(value); return ['https:','http:'].includes(parsed.protocol) ? esc(parsed.href) : '';} catch {return '';}
  };
  async function api(path) {
    const response = await fetch(base + path.replace(/^\//, ''), {credentials:'same-origin',headers:{Accept:'application/json'}});
    let data;
    try {data = await response.json();} catch {throw Error('No se pudo leer el radar. Actualiza la página para comprobar tu sesión.');}
    if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : 'El radar no está disponible temporalmente.');
    return data;
  }
  function toast(message) {
    $('#toast').textContent = message; $('#toast').hidden = false;
    clearTimeout(toast.timer); toast.timer = setTimeout(() => $('#toast').hidden = true, 6000);
  }
  function fill(name, rows, placeholder) {
    const field = form.elements[name], selected = field.value;
    field.innerHTML = `<option value="">${esc(placeholder)}</option>` + (rows || []).map(row => `<option value="${esc(row.value)}">${esc(row.value)} (${row.count})</option>`).join('');
    field.value = selected;
  }
  async function loadMeta() {
    const data = await api('api/meta'), totals = data.totals;
    currency = data.market?.currency || 'EUR'; market = data.market?.name || 'España';
    $$('[data-market-name]').forEach(node => node.textContent = market);
    $$('[data-market-code]').forEach(node => node.textContent = data.market?.country || 'ES');
    $$('[data-zero-price]').forEach(node => node.textContent = money(0));
    $$('[data-currency-code]').forEach(node => node.textContent = currency);
    if (data.market?.country) form.elements.country.innerHTML = `<option value="${esc(data.market.country)}">${esc(market)}</option>`;
    $('#stats').innerHTML = [
      ['Ofertas en el radar',totals.deals,'Conservamos las oportunidades interesantes','↗'],
      ['Productos a 0 €',totals.free,`${totals.free_available || 0} con compra activa en la última lectura`,'€'],
      ['Descuentos de ≥90%',totals.extreme,'Sobre la referencia publicada por la tienda','↘'],
      ['Tiendas analizadas',data.coverage?.analyzed || 0,`${data.coverage?.monitored || 0} en seguimiento`,'▦']
    ].map(([label, number, note, icon]) => `<article><span>${label}<i>${icon}</i></span><b>${number || 0}</b><small>${note}</small></article>`).join('');
    $('#nav-count').textContent = totals.deals || 0; $('#restock-count').textContent = data.restocks || 0;
    $('#coverage-label').textContent = (data.coverage?.analyzed >= 500 ? '+500 tiendas analizadas' : `${data.coverage?.analyzed || 0} tiendas analizadas`) + ` · ${data.coverage?.monitored || 0} en seguimiento`;
    fill('store',data.stores,'Todas las tiendas'); fill('category',data.categories,'Todas las categorías');
    fill('subcategory',data.subcategories,'Todas las subcategorías'); fill('product_type',data.types,'Todos los productos');
  }
  function parameters() {
    const values = new URLSearchParams(new FormData(form));
    for (const key of ['free_only','known_only','stock_only']) values.set(key,form.elements[key].checked ? '1' : '0');
    if (!values.get('max_price')) values.delete('max_price');
    values.set('q',$('#search').value); values.set('sort',$('#sort').value); values.set('limit','500');
    values.set('status',['pending','expired'].includes(preset) ? 'all' : 'radar');
    // A zero with no strike-through PVP still belongs in every discount band.
    values.set('min_discount','0');
    if (preset === 'free') values.set('free_only','1');
    if (preset === 'ai') values.set('min_score',Math.max(85,Number(values.get('min_score') || 0)));
    return values;
  }
  function card(deal) {
    const active = deal.status === 'verified', free = deal.price === 0;
    const badge = active ? free ? 'PRODUCTO A 0 €' : `−${Math.round(deal.discount_pct || 0)}%` : free && deal.availability === 'out_of_stock' ? '0 € · SIN STOCK' : labels[deal.status] || 'Por verificar';
    return `<article class="deal-card"><div class="product-image"><img src="${safe(deal.image)}" alt="${esc(deal.title)}" loading="lazy"><span class="badge ${active ? free ? 'free' : '' : 'muted'}">${esc(badge)}</span></div><div class="card-content"><div class="store-row"><b>${esc(deal.store)}</b> · ${esc(market)}</div><h3 class="deal-title" title="${esc(deal.title)}">${esc(deal.title)}</h3><p class="variant">${esc([deal.variant !== 'Default Title' ? deal.variant : '',deal.subcategory || deal.category].filter(Boolean).join(' · '))}</p><div class="price-line"><span class="current-price ${free && active ? 'free' : ''}">${money(deal.price)}</span>${deal.reference_price ? `<span class="old-price">${money(deal.reference_price)}</span>` : ''}</div><p class="shipping">${deal.shipping == null ? 'Gastos de envío por confirmar' : `Envío: ${money(deal.shipping)} · Total: ${money(deal.total_price)}`}</p>${deal.shipping_note ? `<p class="shipping">${esc(deal.shipping_note)}</p>` : ''}<div class="score-row"><span class="score">${deal.under_review ? 'Revisión' : deal.score_kind === 'gemini' ? '✦ Gemini' : '◇ Radar'} ${Math.round(deal.score || 0)}/100</span><span>${esc(labels[active ? deal.availability : deal.status] || 'Por confirmar')}</span></div><p class="card-reason">${esc(deal.reason || deal.conditions || 'Pendiente de revisión.')}</p><div class="card-actions"><a class="btn primary" href="${safe(deal.buy_url || deal.url)}" target="_blank" rel="noopener noreferrer">${active ? 'Ver en tienda ↗' : 'Abrir ficha ↗'}</a><button class="btn secondary" data-detail="${esc(deal.id)}">Detalles</button></div><p class="card-time">${esc(when(deal.checked_at))} · ${active ? 'Precio comprobado' : 'Último precio observado'}</p></div></article>`;
  }
  async function loadDeals() {
    if (view !== 'radar') return;
    const ticket = ++request;
    $('#discount-label').textContent = form.elements.min_discount.value + '%'; $('#score-label').textContent = form.elements.min_score.value;
    const data = await api('api/deals?' + parameters()); if (ticket !== request) return;
    const minimum = preset === 'extreme' ? Math.max(90,+form.elements.min_discount.value) : +form.elements.min_discount.value;
    let rows = data.deals.filter(deal => deal.image_status === 'verified' && deal.image && (deal.price === 0 || Number(deal.discount_pct || 0) >= minimum));
    if (preset === 'free') rows = rows.filter(deal => deal.free_review === 'accepted');
    if (preset === 'ai') rows = rows.filter(deal => deal.score_kind === 'gemini');
    if (preset === 'pending') rows = rows.filter(deal => ['candidate','unverified','blocked','conditional','stale'].includes(deal.status) || (deal.price === 0 && deal.free_review !== 'accepted' && deal.status === 'expired'));
    if (preset === 'expired') rows = rows.filter(deal => ['expired','ended','removed'].includes(deal.status));
    $('#result-count').textContent = rows.length;
    $('#list').innerHTML = rows.length ? rows.map(card).join('') : '<div class="empty"><div class="empty-icon">◎</div><h3>Las buenas oportunidades necesitan paciencia.</h3><p>No hay productos que coincidan con estos filtros en esta lectura. Puedes consultar las ofertas pasadas o revisar los indicios pendientes.</p><button class="btn secondary" data-reset>Restablecer filtros</button></div>';
    $$('#list img').forEach(image => image.addEventListener('error',() => {image.closest('.deal-card')?.remove();$('#result-count').textContent = $$('#list .deal-card').length;}));
  }
  async function detail(key) {
    const {deal,history} = await api('api/deals/' + encodeURIComponent(key));
    $('#detail-content').innerHTML = `<button class="close" data-close aria-label="Cerrar">×</button><p class="eyebrow">LOS DATOS DEL HALLAZGO</p><div class="detail-top"><img src="${safe(deal.image)}" alt="${esc(deal.title)}"><div><p>${esc(deal.store)}</p><h2>${esc(deal.title)}</h2><div class="detail-price">${money(deal.price)}</div></div></div><div class="detail-facts"><div><small>ESTADO</small>${esc(labels[deal.status] || deal.status)}</div><div><small>DISPONIBILIDAD</small>${esc(labels[deal.availability] || 'Por confirmar')}</div><div><small>ENVÍO / TOTAL</small>${deal.shipping == null ? 'Por confirmar' : money(deal.shipping) + ' / ' + money(deal.total_price)}</div><div><small>ÚLTIMA LECTURA</small>${when(deal.checked_at)}</div></div><p>${esc(deal.reason)}</p>${deal.conditions ? `<p>${esc(deal.conditions)}</p>` : ''}${deal.price === 0 ? `<p><b>Revisión del cero:</b> ${esc(deal.free_review_reason || 'Pendiente de confirmar.')}</p>` : ''}<p>El precio final y la aceptación del pedido los confirma la tienda. La referencia tachada corresponde al precio publicado por el comercio.</p><a class="btn primary" href="${safe(deal.buy_url || deal.url)}" target="_blank" rel="noopener noreferrer">Ver en tienda ↗</a><h3>Historial de precios observados</h3><div class="table-wrap"><table class="data-table"><thead><tr><th>Lectura</th><th>Precio</th><th>Estado</th></tr></thead><tbody>${history.slice(0,15).map(item => `<tr><td>${when(item.checked_at)}</td><td>${money(item.price)}</td><td>${esc(labels[item.status] || item.status)}</td></tr>`).join('') || '<tr><td colspan="3">Sin historial previo.</td></tr>'}</tbody></table></div>`;
    $('#detail-dialog').showModal();
  }
  async function renderHistory() {
    const {examples} = await api('api/history');
    $('#extra-view').innerHTML = `<section class="panel"><h2>Ofertas que ya pasaron · ${examples.length} productos</h2><p>Estos precios son históricos. Los enlaces abren el producto a su precio actual.</p><div class="deal-grid">${examples.map(item => `<article class="deal-card history-card"><div class="product-image"><img src="${safe(item.image)}" alt="${esc(item.title)}" loading="lazy"><span class="deal-badge">OFERTA FINALIZADA</span></div><div class="card-body"><p class="store">${esc(item.store)}</p><h3>${esc(item.title)}</h3><p>${esc(item.variant)}</p><small>Precio que tuvo en la oferta</small><div class="price">${money(item.historical_price)} ${item.reference_price ? `<span class="old-price">${money(item.reference_price)}</span>` : ''}</div><p>${esc(item.note)}</p>${item.buy_url ? `<a class="btn secondary" href="${safe(item.buy_url)}" target="_blank" rel="noopener noreferrer">Ver producto al precio actual ↗</a>` : ''}</div></article>`).join('') || '<p>Las ofertas pasadas se incorporarán cuando tengan una fotografía pública del producto.</p>'}</div></section>`;
  }
  async function renderRestocks() {
    const {restocks} = await api('api/restocks');
    const products = new Set(restocks.map(item => item.url.split('?')[0])).size;
    $('#extra-view').innerHTML = `<section class="panel"><h2>${products} productos a cero sin stock</h2><p>${restocks.length} fichas y variantes en vigilancia. Se revisan cada 12 horas: cuando vuelvan, habrá que comprobar de nuevo precio, cesta y condiciones.</p><label class="search"><span>⌕</span><input id="restock-search" type="search" aria-label="Buscar ceros sin stock" placeholder="Buscar producto, tienda o talla…"></label><div class="table-wrap"><table class="data-table"><thead><tr><th>Producto</th><th>Tienda</th><th>Última lectura</th><th>Próxima revisión</th></tr></thead><tbody>${restocks.map(item => `<tr data-restock-row><td><img class="restock-thumb" src="${safe(item.image)}" alt="" loading="lazy"><a href="${safe(item.buy_url || item.url)}" target="_blank" rel="noopener noreferrer">${esc(item.title)}</a><div class="watched-url">${esc(item.variant === 'Default Title' ? '' : item.variant)}</div></td><td>${esc(item.store)}</td><td>${when(item.last_checked)}</td><td>${when(item.next_check)}</td></tr>`).join('') || '<tr><td colspan="4">Todavía no hay ceros agotados en vigilancia.</td></tr>'}</tbody></table></div></section>`;
  }
  async function switchView(next) {
    if (!['radar','history','restocks'].includes(next)) return;
    view = next;
    const titles = {radar:['Radar de ofertas','Un buen precio. Un gran hallazgo.','Ofertas extremas, precios a cero y oportunidades que duran poco.'],history:['Ofertas pasadas','Estos precios ya ocurrieron.','Oportunidades anteriores, claramente separadas de los precios actuales.'],restocks:['Ceros sin stock','Si vuelve el stock, volvemos a comprobar.','Últimos precios observados en productos agotados.']};
    const [breadcrumb,title,description] = titles[view];
    $('#breadcrumb').textContent = breadcrumb; $('#page-title').textContent = title; $('#page-description').textContent = description;
    $$('[data-view]').forEach(button => button.classList.toggle('active',button.dataset.view === view));
    $('#radar-view').hidden = view !== 'radar'; $('#extra-view').hidden = view === 'radar';
    $('#hero').hidden = view !== 'radar'; $('#stats').hidden = view !== 'radar'; $('.public-intro').hidden = view !== 'radar';
    if (view === 'radar') await loadDeals(); else if (view === 'history') await renderHistory(); else await renderRestocks();
  }
  function reset() {form.reset();$('#search').value = '';preset = 'all';updatePresets();loadDeals().catch(error => toast(error.message));}
  function updatePresets() {$$('[data-preset]').forEach(button => {button.classList.toggle('active',button.dataset.preset === preset);button.setAttribute('aria-selected',String(button.dataset.preset === preset));});}
  async function refresh() {await loadMeta();if (view === 'radar') await loadDeals();else if (view === 'restocks') await renderRestocks();}
  const mobile = document.createElement('nav'); mobile.className = 'public-mobile-nav'; mobile.setAttribute('aria-label','Explorar radar');
  mobile.innerHTML = '<button class="btn secondary" data-view="radar">Radar</button><button class="btn secondary" data-view="history">Ofertas pasadas</button><button class="btn secondary" data-view="restocks">Ceros sin stock</button>';
  $('.page-head').insertAdjacentElement('afterend',mobile);
  form.addEventListener('submit',event => event.preventDefault());
  form.addEventListener('input',() => {clearTimeout(debounce);debounce = setTimeout(() => loadDeals().catch(error => toast(error.message)),200);});
  $('#search').addEventListener('input',() => {clearTimeout(debounce);debounce = setTimeout(() => loadDeals().catch(error => toast(error.message)),250);});
  $('#sort').addEventListener('change',() => loadDeals().catch(error => toast(error.message)));
  $('#refresh').addEventListener('click',() => refresh().catch(error => toast(error.message))); $('#reset').addEventListener('click',reset);
  document.addEventListener('click',async event => {
    const button = event.target.closest('button'); if (!button) return;
    try {
      if (button.dataset.view) await switchView(button.dataset.view);
      else if (button.dataset.preset) {preset = button.dataset.preset;updatePresets();await loadDeals();}
      else if (button.dataset.detail) await detail(button.dataset.detail);
      else if (button.hasAttribute('data-close')) $('#detail-dialog').close();
      else if (button.hasAttribute('data-reset')) reset();
    } catch (error) {toast(error.message);}
  });
  document.addEventListener('input',event => {if (event.target.id === 'restock-search') {const query = event.target.value.toLocaleLowerCase('es');$$('[data-restock-row]').forEach(row => row.hidden = !row.textContent.toLocaleLowerCase('es').includes(query));}});
  updatePresets();refresh().catch(error => toast(error.message));
  setInterval(() => {if (!document.hidden) refresh().catch(error => toast(error.message));},30000);
})();
