(() => {
  const byId = id => document.getElementById(id);
  const results = [];
  let stopped = false;

  function clean(value) {
    return String(value || '')
      .replace(/\b20\d{2}[\s_-]\d{2}[\s_-]\d{2}.*$/i, '')
      .replace(/\b(?:img|image|foto|whatsapp)[-_ ]?\d+\b/ig, '')
      .replace(/\s*\(\d+\)\s*$/g, '')
      .replace(/\s+/g, ' ')
      .trim();
  }

  function junkName(value) {
    const v = clean(value).toLowerCase();
    return !v || /^producto por confirmar/.test(v) ||
      /^(jordan|nike|adidas|puma|new balance|reebok)\s*\d{1,4}$/.test(v) ||
      /^\d+$/.test(v);
  }

  function infer(text, product) {
    const source = `${text} ${product.title || ''} ${product.brand || ''}`.toUpperCase();
    let brand = clean(product.brand), model = '', confidence = 0.35;
    const evidence = [];
    const brandRules = [
      ['Jordan', /\b(JORDAN|JUMPMAN|AIR JORDAN)\b/],
      ['Nike', /\b(NIKE|AIR MAX|SWOOSH)\b/],
      ['Adidas', /\b(ADIDAS|YEEZY|ULTRABOOST|SUPERSTAR)\b/],
      ['New Balance', /\b(NEW BALANCE|NB\s?\d{3})\b/],
      ['Puma', /\bPUMA\b/], ['Reebok', /\bREEBOK\b/],
      ['Hugo Boss', /\b(HUGO|BOSS)\b/],
    ];
    for (const [name, rule] of brandRules) if (rule.test(source)) {
      brand = name; confidence += 0.2; evidence.push(name); break;
    }

    const modelRules = [
      ['Air Jordan 4', /\b(JORDAN\s*4|AJ4|AIR\s*JORDAN\s*IV)\b/],
      ['Air Jordan 1', /\b(JORDAN\s*1|AJ1|AIR\s*JORDAN\s*I)\b/],
      ['Air Jordan 3', /\b(JORDAN\s*3|AJ3|AIR\s*JORDAN\s*III)\b/],
      ['Air Jordan 11', /\b(JORDAN\s*11|AJ11|AIR\s*JORDAN\s*XI)\b/],
      ['Air Max 90', /\bAIR\s*MAX\s*90\b/],
      ['Air Max 270', /\bAIR\s*MAX\s*270\b/],
      ['Air Force 1', /\b(AIR\s*FORCE\s*1|AF1)\b/],
      ['Dunk Low', /\bDUNK\s*LOW\b/],
      ['Yeezy 350', /\bYEEZY\s*350\b/],
      ['New Balance 550', /\b(NB\s*)?550\b/],
      ['New Balance 327', /\b(NB\s*)?327\b/],
    ];
    for (const [name, rule] of modelRules) if (rule.test(source)) {
      model = name; confidence += 0.35; evidence.push(name); break;
    }

    const title = model ? `${brand || 'Nike'} ${model}`.replace(/^Jordan Air Jordan/, 'Air Jordan') : '';
    return {brand, model, title, confidence: Math.min(confidence, .98), evidence: evidence.join(', ') || 'Sin texto concluyente', ocr: clean(text).slice(0,220)};
  }

  function imageUrl(product) { return product.thumbnailUrl || product.catalogUrl || product.imageUrl || ''; }

  async function recognize(url, index, total) {
    if (!window.Tesseract) throw new Error('El motor OCR no pudo cargarse. Revisa la conexión a internet.');
    byId('identifierProgress').textContent = `Leyendo imagen ${index + 1} de ${total}…`;
    const result = await Tesseract.recognize(url, 'eng', {
      workerPath: '/assets/vendor/tesseract/worker.min.js',
      corePath: '/assets/vendor/tesseract/tesseract-core-simd-lstm.wasm.js',
      langPath: '/assets/vendor/tesseract',
      gzip: true,
      logger: m => {
        if (m.status === 'recognizing text') {
          byId('identifierProgress').textContent = `Producto ${index + 1}/${total} · OCR ${Math.round((m.progress || 0) * 100)}%`;
        }
      }
    });
    return result?.data?.text || '';
  }

  function render() {
    const root = byId('identifierResults');
    root.innerHTML = results.length ? results.map((item, i) => `
      <article class="product-row" style="grid-template-columns:64px minmax(0,1fr) auto">
        ${item.image ? `<img class="product-thumb" src="${esc(item.image)}" loading="lazy">` : '<span class="product-thumb placeholder">e</span>'}
        <span><b>${esc(item.product.title || 'Sin nombre')} → ${esc(item.suggestion.title || 'Sin coincidencia')}</b>
        <small>Marca: ${esc(item.suggestion.brand || 'Pendiente')} · Modelo: ${esc(item.suggestion.model || 'Pendiente')}</small>
        <small>Confianza: ${Math.round(item.suggestion.confidence * 100)}% · Evidencia: ${esc(item.suggestion.evidence)}</small>
        <small>OCR: ${esc(item.suggestion.ocr || 'Sin texto visible')}</small></span>
        <span class="actions"><button onclick="window.eleganceApplySuggestion(${i})" ${item.suggestion.title ? '' : 'disabled'}>Aplicar</button>
        <button onclick="window.eleganceSearchSuggestion(${i})">Buscar web</button></span>
      </article>`).join('') : '<p class="empty">Todavía no hay resultados.</p>';
  }

  async function updateProduct(item) {
    const full = await api('/api/admin/catalog/products/' + encodeURIComponent(item.product.id));
    const p = full.product;
    const body = {
      title: item.suggestion.title || p.title,
      brand: item.suggestion.brand || p.brand,
      model: item.suggestion.model || p.model,
      category: p.category || 'Calzado', subcategory: p.subcategory || 'Tenis',
      price: Number(p.price || 0), purchasePrice: Number(p.purchasePrice || 0),
      description: p.description || '', sizes: (p.sizes || []).join(', '),
      colors: (p.colors || []).join(', '), variants: variantsFromProduct(p),
    };
    await api('/api/admin/catalog/products/' + encodeURIComponent(p.id), {method:'PUT', body:JSON.stringify(body)});
    item.applied = true;
  }

  window.eleganceApplySuggestion = async index => {
    const item = results[index];
    try { await updateProduct(item); byId('identifierProgress').textContent = `Nombre actualizado: ${item.suggestion.title}`; render(); await load(); }
    catch (e) { byId('identifierProgress').textContent = e.message; }
  };

  window.eleganceSearchSuggestion = index => {
    const item = results[index];
    const fallback = [item.product.brand, item.product.category, item.product.title]
      .filter(Boolean)
      .join(' ')
      .replace(/\b(jordan|nike|adidas)\s+\d{1,4}\b/ig, '$1 tenis');
    const terms = [item.suggestion.brand,item.suggestion.model,item.suggestion.ocr,fallback,'tenis']
      .filter(Boolean).join(' ');
    window.open('https://www.google.com/search?tbm=isch&q=' + encodeURIComponent(terms), '_blank', 'noopener');
  };

  async function analyzeVisible() {
    stopped = false; results.length = 0; render();
    const candidates = [...state.products].filter(p => imageUrl(p) && (junkName(p.title) || !clean(p.model)));
    const limit = Math.min(candidates.length, 30);
    if (!limit) { byId('identifierProgress').textContent = 'No hay productos visibles que necesiten renombrado.'; return; }
    for (let i = 0; i < limit; i++) {
      if (stopped) break;
      const product = candidates[i];
      try {
        const text = await recognize(imageUrl(product), i, limit);
        results.push({product, image:imageUrl(product), suggestion:infer(text, product)});
      } catch (e) {
        results.push({product, image:imageUrl(product), suggestion:{brand:clean(product.brand),model:'',title:'',confidence:0,evidence:e.message,ocr:''}});
      }
      render();
    }
    byId('identifierProgress').textContent = stopped ? `Proceso detenido. ${results.length} producto(s) analizados.` : `Análisis terminado: ${results.length} producto(s).`;
  }

  async function applySafe() {
    const safe = results.filter(x => !x.applied && x.suggestion.title && x.suggestion.confidence >= .78);
    if (!safe.length) { byId('identifierProgress').textContent = 'No hay sugerencias con confianza alta para aplicar.'; return; }
    let done = 0;
    for (const item of safe) {
      if (stopped) break;
      byId('identifierProgress').textContent = `Actualizando ${done + 1} de ${safe.length}…`;
      try { await updateProduct(item); done++; } catch {}
    }
    render(); await load();
    byId('identifierProgress').textContent = `${done} nombre(s) actualizados de forma segura.`;
  }

  document.addEventListener('DOMContentLoaded', () => {
    byId('identifyProducts')?.addEventListener('click', () => { byId('identifierPanel').classList.add('open'); render(); });
    byId('identifyProductsShortcut')?.addEventListener('click', () => {
      byId('identifierPanel').classList.add('open');
      render();
    });
    byId('closeIdentifier')?.addEventListener('click', () => { stopped = true; byId('identifierPanel').classList.remove('open'); });
    byId('identifyVisible')?.addEventListener('click', analyzeVisible);
    byId('applySafeNames')?.addEventListener('click', applySafe);
    byId('stopIdentification')?.addEventListener('click', () => { stopped = true; byId('identifierProgress').textContent = 'Deteniendo después del producto actual…'; });
  });
})();