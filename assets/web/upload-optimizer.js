(() => {
  'use strict';

  const MAX_EDGE = 1800;
  const JPEG_QUALITY = 0.82;
  const BATCH_SIZE = 6;
  const PARALLEL_BATCHES = 2;
  const RETRIES = 2;

  const $ = (id) => document.getElementById(id);
  const wait = (ms) => new Promise(resolve => setTimeout(resolve, ms));

  async function canvasBlob(canvas, type, quality) {
    return new Promise((resolve, reject) => {
      canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('No se pudo comprimir la imagen.')), type, quality);
    });
  }

  async function optimizeImage(file) {
    if (!file.type.startsWith('image/')) return file;
    if (file.type === 'image/gif') return file;

    let bitmap;
    try {
      bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' });
    } catch {
      return file;
    }

    const scale = Math.min(1, MAX_EDGE / Math.max(bitmap.width, bitmap.height));
    const width = Math.max(1, Math.round(bitmap.width * scale));
    const height = Math.max(1, Math.round(bitmap.height * scale));
    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext('2d', { alpha: false });
    context.drawImage(bitmap, 0, 0, width, height);
    bitmap.close?.();

    const blob = await canvasBlob(canvas, 'image/jpeg', JPEG_QUALITY);
    if (blob.size >= file.size * 0.95 && scale === 1) return file;
    const base = file.name.replace(/\.[^.]+$/, '') || 'producto';
    return new File([blob], `${base}.jpg`, { type: 'image/jpeg', lastModified: file.lastModified });
  }

  async function postBatch(productId, variantId, files, attempt = 0) {
    const form = new FormData();
    files.forEach(file => form.append('files', file, file.name));
    form.append('variant_id', variantId || '');
    try {
      const response = await fetch(`/api/admin/catalog/products/${encodeURIComponent(productId)}/images/batch`, {
        method: 'POST',
        body: form,
      });
      const data = await response.json().catch(() => ({ detail: 'Respuesta invÃ¡lida del servidor.' }));
      if (!response.ok) throw new Error(data.detail || `Error HTTP ${response.status}`);
      return data;
    } catch (error) {
      if (attempt >= RETRIES) throw error;
      await wait(700 * (attempt + 1));
      return postBatch(productId, variantId, files, attempt + 1);
    }
  }

  async function runPool(tasks, concurrency, onDone) {
    let cursor = 0;
    async function worker() {
      while (cursor < tasks.length) {
        const index = cursor++;
        try {
          const value = await tasks[index]();
          onDone(index, null, value);
        } catch (error) {
          onDone(index, error, null);
        }
      }
    }
    await Promise.all(Array.from({ length: Math.min(concurrency, tasks.length) }, worker));
  }

  function installImageRecovery(root = document) {
    root.querySelectorAll('img:not([data-elegance-recovery])').forEach(img => {
      img.dataset.eleganceRecovery = '1';
      img.loading = 'lazy';
      img.decoding = 'async';
      img.referrerPolicy = 'no-referrer';
      const original = img.src;
      img.addEventListener('error', () => {
        if (img.dataset.retry !== '1') {
          img.dataset.retry = '1';
          const join = original.includes('?') ? '&' : '?';
          img.src = `${original}${join}retry=${Date.now()}`;
          return;
        }
        img.onerror = null;
        img.src = '/assets/web/elegance-hero.png';
      });
    });
  }

  function installUploadButton() {
    const oldButton = $('uploadMedia');
    if (!oldButton || oldButton.dataset.optimized === '1') return;

    const button = oldButton.cloneNode(true);
    button.dataset.optimized = '1';
    oldButton.replaceWith(button);

    button.addEventListener('click', async () => {
      const productId = $('productId')?.value;
      const input = $('mediaFiles');
      const variantId = $('mediaVariant')?.value || '';
      const status = $('mediaStatus');
      const notice = $('notice');
      const sourceFiles = [...(input?.files || [])];

      if (!productId) {
        if (notice) notice.textContent = 'Guarda primero el producto.';
        return;
      }
      if (!sourceFiles.length) {
        if (notice) notice.textContent = 'Selecciona una o mÃ¡s imÃ¡genes.';
        return;
      }

      button.disabled = true;
      let optimized = [];
      try {
        if (status) status.textContent = `Preparando 0 de ${sourceFiles.length}â€¦`;
        for (let i = 0; i < sourceFiles.length; i += 1) {
          optimized.push(await optimizeImage(sourceFiles[i]));
          if (status) status.textContent = `Preparando ${i + 1} de ${sourceFiles.length}â€¦`;
          await wait(0);
        }

        const batches = [];
        for (let i = 0; i < optimized.length; i += BATCH_SIZE) batches.push(optimized.slice(i, i + BATCH_SIZE));
        let completedFiles = 0;
        let accepted = 0;
        let duplicates = 0;
        let failed = 0;

        const tasks = batches.map(batch => async () => postBatch(productId, variantId, batch));
        await runPool(tasks, PARALLEL_BATCHES, (_index, error, data) => {
          const count = batches[_index].length;
          completedFiles += count;
          if (error) failed += count;
          else {
            accepted += Number(data?.summary?.accepted || 0);
            duplicates += Number(data?.summary?.duplicates || 0);
            failed += Number(data?.summary?.failed || 0);
          }
          if (status) status.textContent = `Subidas ${Math.min(completedFiles, sourceFiles.length)} de ${sourceFiles.length}â€¦`;
        });

        if (notice) notice.textContent = `${accepted} guardadas, ${duplicates} repetidas y ${failed} fallidas.`;
        if (input) input.value = '';
        if (typeof window.loadMedia === 'function') await window.loadMedia(productId);
        if (typeof window.load === 'function') await window.load();
        installImageRecovery();
      } catch (error) {
        if (notice) notice.textContent = error.message || 'No se pudo completar la carga.';
        if (status) status.textContent = 'Carga interrumpida';
      } finally {
        button.disabled = false;
        optimized = [];
      }
    });
  }

  const observer = new MutationObserver(() => installImageRecovery());
  window.addEventListener('DOMContentLoaded', () => {
    installUploadButton();
    installImageRecovery();
    observer.observe(document.body, { childList: true, subtree: true });
  });
})();
