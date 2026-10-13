/* Local appearance preferences. No network requests or research-data writes. */
(() => {
  'use strict';
  // Start the requested white appearance once; later explicit choices persist.
  const key = 'kw-appearance-v2';
  const modes = ['light', 'dark', 'system'];
  const accents = ['blue', 'graphite', 'teal'];
  const media = window.matchMedia('(prefers-color-scheme: dark)');
  const subscribers = new Set();
  let preference = { mode: 'light', accent: 'blue' };
  const normalize = value => ({
    mode: modes.includes(value?.mode) ? value.mode : 'light',
    accent: accents.includes(value?.accent) ? value.accent : 'blue'
  });
  try {
    const saved = localStorage.getItem(key);
    preference = saved === null
      ? normalize({ ...JSON.parse(localStorage.getItem('kw-appearance-v1')), mode: 'light' })
      : normalize(JSON.parse(saved));
  } catch {}
  function apply() {
    const theme = preference.mode === 'system' ? (media.matches ? 'dark' : 'light') : preference.mode;
    document.documentElement.dataset.theme = theme;
    document.documentElement.dataset.accent = preference.accent;
    document.documentElement.style.colorScheme = theme;
    subscribers.forEach(update => update());
  }
  function change(field, value) {
    preference = normalize({ ...preference, [field]: value });
    try { localStorage.setItem(key, JSON.stringify(preference)); } catch {}
    apply();
  }
  apply();
  media.addEventListener('change', () => { if (preference.mode === 'system') apply(); });
  window.addEventListener('storage', event => {
    if (event.key === key || event.key === null) {
      try { preference = normalize(event.newValue ? JSON.parse(event.newValue) : null); } catch { preference = normalize(null); }
      apply();
    }
  });
  let sequence = 0;
  class Appearance extends HTMLElement {
    static get observedAttributes() { return ['locale', 'compact']; }
    connectedCallback() {
      this.instance = this.instance || ++sequence;
      this.update = () => this.sync();
      subscribers.add(this.update);
      this.render();
      this.onOutside = event => {
        const details = this.querySelector('details');
        if (details?.open && !this.contains(event.target)) details.open = false;
      };
      document.addEventListener('pointerdown', this.onOutside);
      this.onEscape = event => {
        const details = this.querySelector('details');
        if (event.key === 'Escape' && details?.open) {
          details.open = false;
          details.querySelector('summary').focus();
          event.stopPropagation();
        }
      };
      this.addEventListener('keydown', this.onEscape);
    }
    disconnectedCallback() {
      subscribers.delete(this.update);
      document.removeEventListener('pointerdown', this.onOutside);
      this.removeEventListener('keydown', this.onEscape);
    }
    attributeChangedCallback() { if (this.isConnected && this.instance) this.render(); }
    render() {
      const zh = this.getAttribute('locale') !== 'en';
      const compact = this.hasAttribute('compact');
      const names = zh ? ['浅色', '深色', '跟随系统'] : ['Light', 'Dark', 'System'];
      const colors = zh ? ['蓝色', '石墨', '青绿'] : ['Blue', 'Graphite', 'Teal'];
      const icon = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><circle cx="12" cy="12" r="8.5"/><path d="M12 3.5a8.5 8.5 0 0 1 0 17z" fill="currentColor" stroke="none"/></svg>';
      const content = `<div class="appearance-heading"><h3>${zh ? '外观' : 'Appearance'}</h3><span>${zh ? '让专注更舒适' : 'Make room for focus'}</span></div>
        <fieldset class="appearance-modes"><legend class="appearance-sr">${zh ? '界面主题' : 'Interface theme'}</legend>${modes.map((mode, index) => `<label class="appearance-choice"><input type="radio" name="appearance-mode-${this.instance}" data-field="mode" value="${mode}"><span class="appearance-preview preview-${mode}" aria-hidden="true"><i></i><b></b><em></em></span><span class="appearance-label">${names[index]}<span class="appearance-check" aria-hidden="true">✓</span></span></label>`).join('')}</fieldset>
        <fieldset class="appearance-accents"><legend>${zh ? '强调色' : 'Accent color'}</legend><div>${accents.map((accent, index) => `<label class="accent-choice" title="${colors[index]}"><input type="radio" name="appearance-accent-${this.instance}" data-field="accent" value="${accent}" aria-label="${colors[index]}"><span class="accent-dot accent-${accent}" aria-hidden="true"></span><span>${colors[index]}</span></label>`).join('')}</div></fieldset>
        <p class="appearance-note">${zh ? '默认浅色 · 自动记住你的选择' : 'Light by default · Your choice is saved automatically'}</p>`;
      this.innerHTML = compact ? `<details class="appearance-menu"><summary aria-label="${zh ? '切换外观' : 'Change appearance'}" title="${zh ? '切换外观' : 'Change appearance'}">${icon}</summary><div class="appearance-popover">${content}</div></details>` : `<section class="settings-section appearance-section">${content}</section>`;
      this.querySelectorAll('input').forEach(input => input.addEventListener('change', () => {
        if (input.checked) change(input.dataset.field, input.value);
      }));
      this.sync();
    }
    sync() {
      this.querySelectorAll('input[data-field]').forEach(input => { input.checked = preference[input.dataset.field] === input.value; });
    }
  }
  customElements.define('knowline-appearance', Appearance);
})();
