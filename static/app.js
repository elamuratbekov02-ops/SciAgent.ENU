/* SciAgent.ENU интерфейсі. Құрастыру қадамы жоқ: Vue 3 тікелей браузерде жұмыс істейді. */
const { createApp, reactive, ref, computed, watch, onMounted, nextTick } = Vue;

const store = {
  get(key, fallback) { try { return localStorage.getItem(key) || fallback; } catch (e) { return fallback; } },
  set(key, value) { try { localStorage.setItem(key, value); } catch (e) { /* жеке режимде сақталмауы мүмкін */ } },
};

const S = reactive({
  pos: store.get('sa_pos', 'head'), boot: null, view: 'home', refresh: 0,
  drawerId: null, newRecord: null, toast: null, chatOpen: false, posOpen: false, sideOpen: false, notifOpen: false, q: '',
});

function toast(text, bad) {
  S.toast = { text, bad };
  clearTimeout(toast.t);
  toast.t = setTimeout(() => { S.toast = null; }, bad ? 6000 : 3200);
}

async function api(path, opts = {}) {
  const headers = { 'X-Position': S.pos };
  const init = { method: opts.method || 'GET', headers };
  if (opts.body !== undefined) {
    if (opts.body instanceof FormData) init.body = opts.body;
    else { headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(opts.body); }
  }
  const res = await fetch(path, init);
  let data = null;
  try { data = await res.json(); } catch (e) { /* JSON емес жауап */ }
  if (!res.ok && !(opts.allow || []).includes(res.status)) {
    const detail = data && (data.detail || data.error);
    const message = typeof detail === 'string' ? detail : (detail && detail.message) || 'Запрос не выполнен';
    toast(message, true);
    throw new Error(message);
  }
  return opts.allow ? { status: res.status, data } : data;
}

const STATUS_CLASS = { 'создано': 'info', 'на согласовании': 'violet', 'на подписании': 'blue', 'согласовано': 'good', 'принято': 'good', 'на доработке': 'warn' };
const ROLE_NAME = { teacher: 'Преподаватель', doctoral: 'Докторант', master: 'Магистрант', student: 'Студент', external: 'Внешний автор' };
const can = (...roles) => S.boot && roles.includes(S.boot.position.role);
const fmt = (v) => (v === null || v === undefined || v === '' ? '–' : v);
const go = (view) => { S.view = view; S.sideOpen = false; window.scrollTo(0, 0); };
const bump = () => { S.refresh += 1; };
const dl = (path) => { window.location.href = path + (path.includes('?') ? '&' : '?') + 'pos=' + S.pos; };

function useLoad(fn) {
  const data = ref(null);
  const loading = ref(true);
  const load = async () => {
    loading.value = true;
    try { data.value = await fn(); } finally { loading.value = false; }
  };
  onMounted(load);
  watch(() => [S.refresh, S.pos], load);
  return { data, loading, load };
}

/* ---------- Шағын құрамдастар ---------- */
const Tag = {
  props: ['status'],
  setup(p) { return { cls: computed(() => STATUS_CLASS[p.status] || '') }; },
  template: `<span class="tag" :class="cls">{{ status }}</span>`,
};
const IssueLine = {
  props: ['issue', 'fixes', 'canAct'],
  emits: ['fix', 'dismiss'],
  setup() {
    const icon = { error: 'fa-circle-xmark lv-error', warn: 'fa-triangle-exclamation lv-warn', info: 'fa-circle-info lv-info' };
    const level = { error: 'Ошибка', warn: 'Обратите внимание', info: 'Примечание' };
    return { icon, level };
  },
  template: `<div class="issue"><i class="fa-solid" :class="icon[issue.level]"></i>
    <div><span class="small muted">{{ level[issue.level] }}: </span>{{ issue.text }}</div>
    <div class="act" v-if="canAct">
      <button v-if="fixes && fixes[issue.code]" class="btn sm outline" @click="$emit('fix', issue.code)">{{ fixes[issue.code] }}</button>
      <button v-if="issue.level !== 'info'" class="btn sm" @click="$emit('dismiss', issue.code)">Верно</button>
    </div></div>`,
};

/* ---------- Ғылыми жұмыстар ---------- */
const Records = {
  components: { Tag },
  setup() {
    const filters = reactive({ type: '', confirmed: '', mine: can('author') });
    const { data, load } = useLoad(() => {
      const p = new URLSearchParams();
      if (S.q) p.set('q', S.q);
      if (filters.type) p.set('type', filters.type);
      if (filters.confirmed) p.set('confirmed', filters.confirmed);
      if (filters.mine) p.set('mine', 'true');
      return api('/api/records?' + p.toString());
    });
    const addOpen = ref(false);
    const kok = ref(false);
    const journal = reactive({ open: false, issn: '', name: '', result: null });
    watch(filters, load);
    watch(() => S.q, load);
    const page = ref(0);
    const size = 25;
    const paged = computed(() => (data.value ? data.value.items.slice(page.value * size, (page.value + 1) * size) : []));
    watch(data, () => { page.value = 0; });
    const importFrom = async (name) => {
      addOpen.value = false;
      const r = await api(`/api/integrations/${name}/import`, { method: 'POST' });
      toast(r.text);
      bump();
    };
    const checkJournal = async () => {
      journal.result = await api(`/api/journal/check?issn=${encodeURIComponent(journal.issn)}&name=${encodeURIComponent(journal.name)}`);
    };
    return { S, can, data, filters, addOpen, kok, journal, paged, page, size, importFrom, checkJournal, dl, ROLE_NAME };
  },
  template: `<div>
    <div class="page-title"><h1>Научные работы</h1></div>
    <div class="card toolbar">
      <div class="dropdown">
        <button class="tbtn" @click="addOpen = !addOpen"><i class="fa-solid fa-plus"></i> Добавить научную работу <i class="fa-solid fa-chevron-down small"></i></button>
        <div class="menu" v-if="addOpen" @mouseleave="addOpen = false">
          <button @click="addOpen = false; S.newRecord = {}"><i class="fa-regular fa-file"></i> Добавить новую</button>
          <button @click="addOpen = false; S.chatOpen = true"><i class="fa-regular fa-comment-dots"></i> Отправить файл в чат</button>
          <div class="sep">Импорт</div>
          <button @click="importFrom('platonus')"><i class="fa-solid fa-right-to-bracket"></i> Platonus</button>
          <button @click="importFrom('scopus')"><i class="fa-solid fa-right-to-bracket"></i> Scopus</button>
        </div>
      </div>
      <button class="tbtn" @click="dl('/api/export/person/' + S.boot.position.person)"><i class="fa-solid fa-print"></i> Список научных работ</button>
      <div class="dropdown">
        <button class="tbtn" @click="journal.open = !journal.open"><i class="fa-solid fa-shield-halved"></i> Проверить журнал</button>
        <div class="menu" v-if="journal.open" style="padding:10px;width:300px">
          <label class="f">ISSN<input class="inp" v-model="journal.issn" placeholder="2146-4553"></label>
          <label class="f" style="margin-top:6px">Название журнала<input class="inp" v-model="journal.name"></label>
          <button class="btn sm primary" style="margin-top:8px;width:auto" @click="checkJournal">Проверить</button>
          <div v-if="journal.result" class="small" style="margin-top:8px">
            <div v-if="journal.result.issn_valid === false" class="lv-error">Неверная контрольная цифра ISSN</div>
            <div v-if="journal.result.issn_valid === true">Формат ISSN верный</div>
            <div v-if="journal.result.risk" class="lv-error"><i class="fa-solid fa-triangle-exclamation"></i> {{ journal.result.risk.reason }}</div>
            <div v-if="journal.result.index">{{ S.boot.labels.index[journal.result.index.index] }}: {{ journal.result.index.basis }}</div>
            <div v-if="!journal.result.risk && !journal.result.index" class="muted">Этого журнала нет в базе. Проверьте его индексацию по официальному списку.</div>
          </div>
        </div>
      </div>
      <span style="flex:1"></span>
      <select class="inp" style="width:auto;margin:0" v-model="filters.type"><option value="">Все типы</option><option v-for="(t,k) in S.boot.types" :key="k" :value="k">{{ t.label }}</option></select>
      <select class="inp" style="width:auto;margin:0" v-model="filters.confirmed"><option value="">Все</option><option value="false">Не подтверждено</option><option value="true">Подтверждено</option></select>
      <label v-if="!can('author')" class="small nowrap"><input type="checkbox" v-model="filters.mine"> Моя</label>
    </div>
    <div class="card" v-if="data">
      <div class="table-wrap"><table>
        <thead><tr><th style="width:42%"><i class="fa-solid fa-align-left"></i> Название публикации</th><th>Тип</th><th>Автор</th><th class="num">Год</th><th>Раздел</th><th>Статус</th></tr></thead>
        <tbody>
          <tr v-for="r in paged" :key="r.id">
            <td><button class="link" @click="S.drawerId = r.id">{{ r.title }}</button>
              <div class="small muted" v-if="r.source_text">{{ r.source_text.slice(0,90) }}</div></td>
            <td class="small">{{ r.index ? S.boot.labels.index[r.index] : r.type_label }}</td>
            <td class="small">{{ r.authors.slice(0,3).join(', ') }}<span v-if="r.authors.length > 3" class="faint"> +{{ r.authors.length - 3 }}</span></td>
            <td class="num">{{ r.year }}</td>
            <td class="nowrap"><span v-for="s in r.sections" :key="s" class="section-badge">{{ s }}</span></td>
            <td><Tag :status="r.status"/><div v-if="!r.confirmed" style="margin-top:3px"><span class="tag warn">не подтверждено</span></div><div v-if="r.in_press" style="margin-top:3px"><span class="tag">в печати</span></div></td>
          </tr>
        </tbody>
      </table></div>
      <div v-if="!data.items.length" class="empty">Записи не найдены.</div>
      <div class="card-head" style="border-top:1px solid var(--border-soft);border-bottom:0" v-if="data.items.length > size">
        <span class="muted small">Записи {{ page*size+1 }}–{{ Math.min((page+1)*size, data.total) }} из {{ data.total }}</span><span class="spacer"></span>
        <button class="btn sm" :disabled="page === 0" @click="page--"><i class="fa-solid fa-chevron-left"></i></button>
        <button class="btn sm" :disabled="(page+1)*size >= data.total" @click="page++"><i class="fa-solid fa-chevron-right"></i></button>
      </div>
    </div>
  </div>`,
};

/* ---------- Жазба панелі ---------- */
const RecordDrawer = {
  components: { IssueLine, Tag },
  setup() {
    const data = ref(null);
    const edit = reactive({ fields: {}, attrs: {} });
    const load = async () => {
      data.value = await api('/api/records/' + S.drawerId);
      edit.fields = { ...data.value.record.fields };
      edit.attrs = { ...data.value.record.attrs };
    };
    onMounted(load);
    const spec = computed(() => (data.value ? S.boot.types[data.value.record.type] : null));
    const save = async () => {
      await api('/api/records/' + S.drawerId, { method: 'PATCH', body: { fields: edit.fields, attrs: edit.attrs } });
      toast('Сохранено');
      bump();
      await load();
    };
    const confirm = async () => { await api(`/api/records/${S.drawerId}/confirm`, { method: 'POST' }); toast('Подтверждено'); bump(); await load(); };
    const fix = async (code) => { await api(`/api/records/${S.drawerId}/fix`, { method: 'POST', body: { code } }); toast('Раздел исправлен'); bump(); await load(); };
    const dismiss = async (code) => { await api(`/api/records/${S.drawerId}/dismiss`, { method: 'POST', body: { code } }); bump(); await load(); };
    const upload = async (e) => {
      const f = e.target.files[0];
      if (!f) return;
      const form = new FormData();
      form.append('file', f);
      await api(`/api/records/${S.drawerId}/evidence`, { method: 'POST', body: form });
      toast('Подтверждающий документ добавлен');
      bump();
      await load();
    };
    const checkPublished = async () => {
      const r = await api(`/api/records/${S.drawerId}/check-published`, { method: 'POST' });
      toast(r.text, !r.found);
      if (r.found) {
        for (const k of Object.keys(r.fields)) if (r.fields[k] && spec.value.fields.some((x) => x.key === k)) edit.fields[k] = r.fields[k];
      }
    };
    const conf = (k) => { const c = data.value.record.ai && data.value.record.ai.confidence; return c ? c[k] : null; };
    const proof = (k) => { const c = data.value.record.ai && data.value.record.ai.evidence; return c ? c[k] : null; };
    return { S, can, data, edit, spec, save, confirm, fix, dismiss, upload, checkPublished, conf, proof, ROLE_NAME, load };
  },
  template: `<div class="overlay" @click.self="S.drawerId = null"><div class="drawer" v-if="data">
    <div class="drawer-head">
      <div><div class="small muted">{{ spec.label }} · {{ data.record.year }}</div><h2 style="font-size:16px">{{ data.title }}</h2>
        <div style="margin-top:5px"><span v-for="s in data.record.sections" :key="s" class="section-badge">{{ s }}</span><Tag :status="data.record.status"/>
          <span v-if="!data.record.confirmed" class="tag warn" style="margin-left:4px">не подтверждено</span>
          <span v-if="data.record.in_press" class="tag" style="margin-left:4px">в печати</span>
          <span v-if="data.record.merged_from" class="tag good" style="margin-left:4px">объединено строк: {{ data.record.merged_from.length + 1 }}</span></div></div>
      <span class="spacer"></span><button class="icon-btn" aria-label="Закрыть" @click="S.drawerId = null"><i class="fa-solid fa-xmark"></i></button>
    </div>
    <div class="drawer-body">
      <RecordFlow :flow="data.flow" :rid="data.record.id" :key="data.flow.status + data.flow.stage" @changed="load"/>
      <div v-if="data.issues.length" class="card" style="margin-bottom:14px"><div class="card-body" style="padding:6px 12px">
        <IssueLine v-for="i in data.issues" :key="i.code" :issue="i" :fixes="data.fixes" :can-act="can('responsible','head')" @fix="fix" @dismiss="dismiss"/>
      </div></div>
      <h3 style="margin-bottom:6px">Авторы</h3>
      <span v-for="a in data.authors" :key="a.id" class="chip">{{ a.name }} <span class="faint small">{{ ROLE_NAME[a.role] }}</span></span>
      <span v-for="a in data.record.external_authors" :key="a" class="chip">{{ a }} <span class="faint small">внешний</span></span>
      <div v-if="data.supervisors.length" class="small muted" style="margin-top:4px">Научный руководитель: {{ data.supervisors.map(s => s.name).join(', ') }}</div>
      <h3 style="margin:14px 0 6px">Сведения</h3>
      <div class="form-grid">
        <label v-for="f in spec.fields" :key="f.key" class="f" :class="{wide: f.wide}">{{ f.label }}<span v-if="f.required" class="req"> *</span>
          <span v-if="conf(f.key) !== null && conf(f.key) !== undefined" class="tag" :class="conf(f.key) < 0.7 ? 'warn' : 'good'" style="margin-left:5px">ИИ {{ Math.round(conf(f.key)*100) }}%</span>
          <input class="inp" v-model="edit.fields[f.key]" :disabled="!data.can_edit || edit.fields[f.key] === '•••'">
          <span v-if="proof(f.key)" class="small faint">«{{ proof(f.key).quote }}»<span v-if="proof(f.key).page">, с. {{ proof(f.key).page }}</span></span>
        </label>
        <label v-for="a in spec.attrs" :key="a.key" class="f">{{ a.label }}
          <select class="inp" v-model="edit.attrs[a.key]" :disabled="!data.can_edit"><option v-for="(v,k) in a.options" :key="k" :value="k">{{ v }}</option></select>
        </label>
      </div>
      <div style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap" v-if="data.can_edit">
        <button class="btn primary" @click="save"><i class="fa-regular fa-floppy-disk"></i> Сохранить</button>
        <button v-if="!data.record.confirmed" class="btn outline" @click="confirm"><i class="fa-solid fa-check"></i> Подтвердить</button>
        <button v-if="data.record.in_press" class="btn" @click="checkPublished"><i class="fa-solid fa-magnifying-glass"></i> Проверить выход статьи</button>
      </div>
      <h3 style="margin:18px 0 6px">Подтверждающие документы</h3>
      <div v-if="data.evidence_needed.length" class="small muted">Требуется по форме: {{ data.evidence_needed.join(', ') }}</div>
      <div v-for="e in data.record.evidence" :key="e.stored" class="small" style="margin-top:4px"><i class="fa-regular fa-file"></i>
        <a :href="'/api/records/' + data.record.id + '/evidence/' + e.stored + '?pos=' + S.pos">{{ e.filename }}</a></div>
      <label v-if="data.can_edit" class="btn sm" style="margin-top:8px"><i class="fa-solid fa-paperclip"></i> Добавить файл<input type="file" accept=".pdf,.png,.jpg,.jpeg,.webp" hidden @change="upload"></label>
      <details class="more"><summary>Данные в формате Smart.ENU</summary><pre class="code">{{ JSON.stringify(data.smartenu, null, 2) }}</pre></details>
      <div v-if="data.record.source_ref" class="small faint" style="margin-top:8px">Источник: отчёт, «{{ data.record.source_ref.sheet }}», строка {{ data.record.source_ref.row }}</div>
    </div>
  </div></div>`,
};

/* ---------- Жаңа жазба ---------- */
const NewRecord = {
  setup() {
    const init = S.newRecord || {};
    const form = reactive({ type: init.type || null, fields: { ...(init.fields || {}) }, attrs: { ...(init.attrs || {}) }, author_ids: [], authors: [...(init.authors || [])], external: '', year: S.boot.year });
    const chosen = ref([]);
    const preview = ref(null);
    const search = ref('');
    const results = ref([]);
    const saving = ref(false);
    const payload = () => ({ type: form.type, fields: form.fields, attrs: form.attrs, author_ids: chosen.value.map((c) => c.id), authors: form.authors,
      external_authors: form.external ? form.external.split(',').map((x) => x.trim()).filter(Boolean) : [], evidence: init.evidence || [], ai: init.ai, as_author: !!init.as_author, year: form.year });
    let timer;
    const refresh = () => { clearTimeout(timer); timer = setTimeout(async () => { if (form.type) preview.value = await api('/api/records/preview', { method: 'POST', body: payload() }); }, 300); };
    watch([() => form.fields, () => form.attrs, () => form.type, chosen, () => form.external, () => form.year], refresh, { deep: true });
    onMounted(refresh);
    watch(search, async (q) => { results.value = q.length > 1 ? (await api('/api/directory?q=' + encodeURIComponent(q))).items : []; });
    const spec = computed(() => (form.type ? S.boot.types[form.type] : null));
    const add = (p) => { if (!chosen.value.some((c) => c.id === p.id)) chosen.value.push(p); search.value = ''; results.value = []; };
    const save = async (send) => {
      saving.value = true;
      try {
        const r = await api('/api/records', { method: 'POST', body: { ...payload(), source: init.ai ? 'chat' : 'form', allow_missing: !send } });
        S.newRecord = null;
        if (r.claimed) toast('Такая запись уже есть. Ответственный проверит и добавит вас соавтором');
        else if (r.merged) toast('Эта запись уже есть в базе, недостающие сведения дополнены');
        else if (send) await sendForApproval(r.record.id);
        else toast('Черновик сохранён. Отправить можно в разделе «Мои результаты»');
        bump();
      } finally { saving.value = false; }
    };
    return { S, form, spec, preview, search, results, chosen, add, save, saving, ROLE_NAME };
  },
  template: `<div class="overlay" @click.self="S.newRecord = null"><div class="modal">
    <div class="drawer-head"><div><h2>Добавить научный результат</h2><div class="small muted" v-if="spec">{{ spec.label }} <button class="link small" @click="form.type = null">сменить тип</button></div></div>
      <span class="spacer"></span><button class="icon-btn" aria-label="Закрыть" @click="S.newRecord = null"><i class="fa-solid fa-xmark"></i></button></div>
    <div class="drawer-body" v-if="!form.type">
      <p class="muted" style="margin-top:0">Знать все 56 списков отчёта не нужно. Выберите тип, а раздел система определит сама.</p>
      <div class="type-grid"><button v-for="(t,k) in S.boot.types" :key="k" class="type-card" @click="form.type = k"><i class="fa-solid" :class="t.icon"></i><b>{{ t.label }}</b><span>В чат: {{ t.chat_hint }}</span></button></div>
    </div>
    <div class="drawer-body split" v-else>
      <div>
        <div class="form-grid">
          <label v-for="f in spec.fields" :key="f.key" class="f" :class="{wide: f.wide}">{{ f.label }}<span v-if="f.required" class="req"> *</span><input class="inp" v-model="form.fields[f.key]"></label>
          <label v-if="!spec.fields.some(f => f.key === 'year')" class="f">Отчётный год<input class="inp" type="number" v-model.number="form.year"></label>
          <label v-for="a in spec.attrs" :key="a.key" class="f">{{ a.label }}<span v-if="a.required" class="req"> *</span>
            <select class="inp" v-model="form.attrs[a.key]"><option value="">Выберите</option><option v-for="(v,k) in a.options" :key="k" :value="k">{{ v }}</option></select></label>
        </div>
        <div style="margin-top:12px"><label class="f">Соавторы (из университета)<input class="inp" v-model="search" placeholder="Поиск по ФИО"></label>
          <div class="search-results" v-if="results.length"><button v-for="r in results" :key="r.id" @click="add(r)">{{ r.name }} <span class="faint small">{{ ROLE_NAME[r.role] }} {{ r.group }}</span></button></div>
          <div style="margin-top:5px"><span v-for="(c,i) in chosen" :key="c.id" class="chip">{{ c.name }}<button aria-label="Удалить" @click="chosen.splice(i,1)"><i class="fa-solid fa-xmark"></i></button></span></div>
          <div v-if="form.authors.length" class="small muted">Авторы из файла: {{ form.authors.join(', ') }}</div>
          <label class="f" style="margin-top:8px">Внешние авторы (через запятую)<input class="inp" v-model="form.external"></label></div>
      </div>
      <div class="preview-box" v-if="preview">
        <h3>Как попадёт в отчёт</h3>
        <div style="margin:6px 0 10px"><span v-for="s in preview.record.sections" :key="s" class="section-badge">{{ s }}</span><span v-if="!preview.record.sections.length" class="muted small">Выберите признаки</span></div>
        <div v-if="preview.duplicate" class="notice warn"><b>Эта запись уже есть в базе.</b> Вносить её повторно не нужно: при сохранении дополнятся только недостающие сведения.<div class="small muted">{{ preview.duplicate.title }}</div></div>
        <div v-if="preview.missing.length" class="small"><b>Нужно заполнить:</b> {{ preview.missing.map(m => m.label).join(', ') }}</div>
        <div v-for="i in preview.issues" :key="i.code" class="small" :class="'lv-' + i.level" style="margin-top:4px">{{ i.text }}</div>
        <div v-if="preview.record.attrs.index_basis" class="small muted" style="margin-top:6px">Индекс: {{ preview.record.attrs.index_basis }}</div>
        <div class="small muted" style="margin-top:8px" v-if="preview.authors.length">Сопоставленные авторы: {{ preview.authors.map(a => a.display).join(', ') }}</div>
        <button class="btn primary" style="margin-top:12px;width:100%;justify-content:center" :disabled="saving || preview.missing.length > 0" @click="save(true)"><i class="pi pi-send"></i> {{ preview.duplicate ? 'Дополнить' : 'Сохранить и отправить на согласование' }}</button>
        <button v-if="!preview.duplicate" class="btn" style="margin-top:6px;width:100%;justify-content:center" :disabled="saving" @click="save(false)">Сохранить черновик</button>
      </div>
    </div>
  </div></div>`,
};

/* ---------- Табылған жарияланымдар ---------- */
const Found = {
  setup() {
    const { data, load } = useLoad(() => api('/api/candidates'));
    const orcid = ref('');
    const busy = ref(false);
    const result = ref(null);
    const search = async () => {
      busy.value = true;
      try {
        result.value = await api('/api/candidates/search', { method: 'POST', body: { orcid: orcid.value } });
        await load();
      } finally { busy.value = false; }
    };
    const decide = async (c, mine) => {
      const r = await api(`/api/candidates/${c.id}/decide`, { method: 'POST', body: { mine } });
      toast(mine ? (r.merged ? 'Такая запись уже есть, повторно вводить не нужно' : 'Сохранено как черновик. Отправьте запись на согласование в разделе «Мои результаты»') : 'Отмечено, больше предлагаться не будет');
      bump();
    };
    return { S, data, orcid, busy, result, search, decide };
  },
  template: `<div>
    <div class="page-title"><h1>Найденные публикации</h1><p>Система сама ищет публикации, вам остаётся нажать «Моя» или «Не моя».</p></div>
    <div class="card"><div class="card-body" style="display:flex;gap:8px;align-items:flex-end;flex-wrap:wrap">
      <label class="f" style="width:280px">Поиск по ORCID (Crossref)<input class="inp" v-model="orcid" placeholder="0000-0002-1825-0097"></label>
      <button class="btn primary" :disabled="busy" @click="search"><i class="fa-solid fa-magnifying-glass"></i> {{ busy ? 'Идёт поиск…' : 'Найти' }}</button>
      <span v-if="result" class="small muted">Найдено: {{ result.found }}, новых: {{ result.added }}, уже в базе: {{ result.already }}.<span v-if="!result.network_ok"> Crossref не ответил, либо у этого ORCID нет публикаций.</span></span>
    </div></div>
    <div class="card" v-if="data">
      <div v-for="c in data.items" :key="c.id" class="task" style="cursor:default">
        <span class="ic"><i class="fa-regular fa-file-lines"></i></span>
        <span style="min-width:0"><b>{{ c.title }}</b><span class="small muted">{{ c.journal }}, {{ c.year }}<span v-if="c.pages">, {{ c.pages }}</span> · {{ c.source }}<span v-if="c.index"> · {{ S.boot.labels.index[c.index] }}</span></span></span>
        <span style="margin-left:auto;display:flex;gap:6px;flex:none"><button class="btn sm primary" @click="decide(c, true)">Моя</button><button class="btn sm" @click="decide(c, false)">Не моя</button></span>
      </div>
      <div v-if="!data.items.length" class="empty">Новых публикаций для вас нет.</div>
    </div>
  </div>`,
};

/* ---------- Басылымда ---------- */
const InPress = {
  components: { Tag },
  setup() {
    const { data } = useLoad(() => api('/api/inpress'));
    return { S, data };
  },
  template: `<div>
    <div class="page-title"><h1>Записи в печати</h1><p>Когда статья выйдет, не забудьте обновить номера страниц: откройте запись и нажмите «Проверить выход статьи».</p></div>
    <div class="card" v-if="data"><div class="table-wrap"><table>
      <thead><tr><th>Название</th><th>Издание</th><th>Автор</th><th>Раздел</th></tr></thead>
      <tbody><tr v-for="r in data.items" :key="r.id"><td><button class="link" @click="S.drawerId = r.id">{{ r.title }}</button></td><td class="small">{{ r.source_text.slice(0,70) }}</td><td class="small">{{ r.authors.slice(0,2).join(', ') }}</td><td><span v-for="s in r.sections" :key="s" class="section-badge">{{ s }}</span></td></tr></tbody>
    </table></div><div v-if="!data.items.length" class="empty">Записей со статусом «в печати» нет.</div></div>
  </div>`,
};

/* ---------- Тексеру кезегі ---------- */
const Review = {
  components: { IssueLine },
  setup() {
    const { data, load } = useLoad(() => api('/api/review'));
    const tab = ref('queue');
    const LABELS = { exact: 'Полный дубль', cross_section: 'В двух разделах', cross_role: 'В разделах по статусу автора', conflict: 'Сведения расходятся', similar: 'Похожее название' };
    const merge = async (d) => { await api('/api/duplicates/merge', { method: 'POST', body: { record_ids: d.record_ids } }); toast('Объединено'); bump(); };
    const mergeAll = async () => { const r = await api('/api/duplicates/merge-all', { method: 'POST' }); toast(`Объединено дублирующихся строк: ${r.merged}`); bump(); };
    const fix = async (id, code) => { await api(`/api/records/${id}/fix`, { method: 'POST', body: { code } }); toast('Исправлено'); bump(); };
    const dismiss = async (id, code) => { await api(`/api/records/${id}/dismiss`, { method: 'POST', body: { code } }); bump(); };
    const FIXES = { PLACE_MISMATCH: 'Исправить раздел', JOURNAL_IN_CONFERENCE: 'Перевести в статьи', ISSN_IN_ISBN: 'Перевести в статьи' };
    const share = computed(() => (data.value ? Math.round(data.value.auto_ok * 100 / data.value.total) : 0));
    const dupCount = computed(() => (data.value ? data.value.duplicates.filter((d) => d.kind !== 'similar').length : 0));
    const code = ref('');
    const codes = computed(() => {
      if (!data.value) return [];
      const c = {};
      data.value.items.forEach((i) => i.issues.forEach((x) => { c[x.code] = (c[x.code] || 0) + 1; }));
      return Object.entries(c).sort((a, b) => b[1] - a[1]).map(([k, n]) => ({ code: k, count: n, label: data.value.labels[k] || k }));
    });
    const shown = computed(() => {
      if (!data.value) return [];
      const rows = code.value ? data.value.items.filter((i) => i.issues.some((x) => x.code === code.value)) : data.value.items;
      return rows.slice(0, 60);
    });
    const dismissAll = async () => {
      const r = await api('/api/review/dismiss-code', { method: 'POST', body: { code: code.value } });
      toast(`Предупреждение принято, записей: ${r.dismissed}`);
      code.value = '';
      bump();
    };
    return { S, data, tab, LABELS, merge, mergeAll, fix, dismiss, FIXES, share, dupCount, code, codes, shown, dismissAll };
  },
  template: `<div v-if="data">
    <div class="page-title"><h1>Очередь проверки</h1><p>Ответственный просматривает не все строки, а только записи, которые правила и агент сочли сомнительными.</p></div>
    <div class="tiles">
      <div class="tile"><div class="label">Всего записей</div><div class="value">{{ data.total }}</div></div>
      <div class="tile"><div class="label">Прошли автоматически</div><div class="value">{{ data.auto_ok }}</div><div class="delta">{{ share }}%</div></div>
      <div class="tile"><div class="label">Проверяет человек</div><div class="value">{{ data.items.length }}</div></div>
      <div class="tile"><div class="label">Группы дублей</div><div class="value">{{ dupCount }}</div></div>
    </div>
    <div class="tabs"><button :class="{on: tab==='queue'}" @click="tab='queue'">Очередь ({{ data.items.length }})</button><button :class="{on: tab==='dups'}" @click="tab='dups'">Дубли ({{ data.duplicates.length }})</button></div>
    <div v-if="tab==='queue'" class="card">
      <div class="card-head" v-if="codes.length">
        <select class="inp" style="width:auto;margin:0" v-model="code"><option value="">Все проблемы ({{ data.items.length }})</option><option v-for="c in codes" :key="c.code" :value="c.code">{{ c.label }} ({{ c.count }})</option></select>
        <button v-if="code" class="btn sm" @click="dismissAll"><i class="fa-solid fa-check-double"></i> Принять все этого типа</button>
        <span class="spacer"></span><span class="small muted" v-if="shown.length < data.items.length && !code">Показаны первые 60 записей</span>
      </div>
      <div v-for="item in shown" :key="item.id" class="acc" style="padding:10px 14px">
        <button class="link" @click="S.drawerId = item.id">{{ item.title }}</button>
        <div style="margin:3px 0"><span v-for="s in item.sections" :key="s" class="section-badge">{{ s }}</span></div>
        <IssueLine v-for="i in item.issues" :key="i.code" :issue="i" :fixes="FIXES" :can-act="true" @fix="(c) => fix(item.id, c)" @dismiss="(c) => dismiss(item.id, c)"/>
        <div v-if="item.low_confidence.length" class="small lv-warn">Поля с низкой уверенностью ИИ: {{ item.low_confidence.join(', ') }}</div>
      </div>
      <div v-if="!data.items.length" class="empty"><i class="fa-solid fa-circle-check" style="color:var(--good)"></i> Очередь пуста.</div>
    </div>
    <div v-else class="card">
      <div class="card-head"><div class="muted small">Одна статья хранится как одна запись. Если у неё авторы с разным статусом, она показывается в двух разделах, но считается один раз.</div><span class="spacer"></span><button v-if="dupCount" class="btn primary sm" @click="mergeAll"><i class="fa-solid fa-object-group"></i> Объединить все</button></div>
      <div v-for="d in data.duplicates" :key="d.key" class="acc" style="padding:10px 14px">
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap"><span class="tag" :class="d.kind === 'similar' ? '' : 'warn'">{{ LABELS[d.kind] }}</span><span class="small muted">{{ d.text }}</span><span style="flex:1"></span><button v-if="d.kind !== 'similar'" class="btn sm" @click="merge(d)">Объединить</button></div>
        <div v-for="r in d.records" :key="r.id" class="small" style="margin-top:5px"><span v-for="s in r.sections" :key="s" class="section-badge">{{ s }}</span><button class="link small" @click="S.drawerId = r.id">{{ r.title.slice(0,90) }}</button> <span class="faint">{{ r.pages }}</span><span v-if="r.ref" class="faint"> · строка {{ r.ref.row }}</span></div>
      </div>
      <div v-if="!data.duplicates.length" class="empty">Дублей нет.</div>
    </div>
  </div>`,
};

/* ---------- ҒЗЖ есебі ---------- */
const Report = {
  components: { Tag },
  setup() {
    const unit = ref('mgmt');
    const { data, load } = useLoad(() => api(`/api/report/${unit.value}/2025`));
    const tab = ref('sections');
    const open = ref({});
    const note = ref('');
    const protocol = reactive({ no: '', date: '' });
    const manual = reactive({});
    watch(data, (d) => { if (d) Object.assign(manual, d.manual); });
    const STEPS = [['создано', 'Готовит ответственный'], ['на согласовании', 'Заведующий кафедрой'], ['на подписании', 'Директор'], ['согласовано', 'Утверждён директором'], ['принято', 'Департамент науки']];
    const stepIndex = computed(() => { const s = data.value ? data.value.state.status : ''; return s === 'на доработке' ? 0 : STEPS.findIndex((x) => x[0] === s); });
    const finished = computed(() => data.value && data.value.state.status === 'принято');
    const narrative = ref(null);
    const narrativeBusy = ref(false);
    const makeNarrative = async () => {
      narrativeBusy.value = true;
      try { narrative.value = await api(`/api/report/${unit.value}/2025/narrative`); } finally { narrativeBusy.value = false; }
    };
    const copyNarrative = async () => {
      try { await navigator.clipboard.writeText(narrative.value.text); toast('Скопировано'); } catch (e) { toast('Выделите текст и скопируйте вручную', true); }
    };
    const doAction = async (action, force) => {
      const body = { action, note: note.value, force: !!force };
      if (action === 'approve' && protocol.no) body.protocol = { no: protocol.no, date: protocol.date };
      const r = await api(`/api/report/${unit.value}/2025/transition`, { method: 'POST', body, allow: [200, 400, 403, 409] });
      if (r.status === 409) {
        if (window.confirm(`В отчёте есть ошибки: ${r.data.blocked}. Всё равно отправить на согласование?`)) return doAction(action, true);
        return null;
      }
      if (r.status >= 400) { toast((r.data && r.data.detail) || 'Действие не выполнено', true); return null; }
      toast(r.data.version ? `Отчёт утверждён, сохранена версия ${r.data.version}` : `Статус: ${r.data.status}`);
      note.value = '';
      bump();
      return null;
    };
    const saveManual = async () => { await api(`/api/report/${unit.value}/2025/manual`, { method: 'PUT', body: manual }); toast('Сохранено'); bump(); };
    const SOURCE = { auto: ['Из записей', 'good'], staff: ['По штатной численности', 'blue'], manual: ['Вручную', 'warn'] };
    const show = (v) => (v === null || v === undefined || v === '' ? '–' : v);
    const differs = (i) => i.reported !== '' && i.reported !== '-' && i.value !== null && Math.abs(Number(i.reported) - Number(i.value)) > 0.0005;
    const filledSections = computed(() => (data.value ? data.value.sections.filter((s) => s.count > 0).length : 0));
    return { S, can, unit, data, tab, open, note, protocol, manual, STEPS, stepIndex, finished, doAction, saveManual, SOURCE, show, differs, filledSections, dl, narrative, narrativeBusy, makeNarrative, copyNarrative };
  },
  template: `<div v-if="data">
    <div class="page-title"><h1>Отчёт НИР: {{ data.unit_name }}, {{ data.year }}</h1><Tag :status="data.state.status"/><p>Ф ЕНУ 605-02-25. Отчёт сам собирается из согласованных записей, сводить таблицу вручную не нужно.</p></div>
    <div class="card"><div class="steps">
      <div v-for="(st,i) in STEPS" :key="st[0]" class="step" :class="{done: i < stepIndex || finished, cur: i === stepIndex && !finished}">
        <span class="dot"><i v-if="i < stepIndex || finished" class="fa-solid fa-check"></i></span><b>{{ st[0] }}</b><span>{{ st[1] }}</span></div>
    </div>
    <div class="card-body" style="padding-top:0">
      <div class="notice" v-if="data.outside.length && !finished">В отчёт вошли согласованные записи: <b>{{ data.rows }}</b>. Пока не вошли: <b>{{ data.outside.length }}</b>. <button class="link" @click="tab = 'outside'">Показать</button></div>
      <div v-if="data.state.status === 'на доработке'" class="notice warn">Отчёт возвращён на доработку.</div>
      <div v-if="data.blocking && !['согласовано','принято'].includes(data.state.status)" class="notice bad"><i class="fa-solid fa-circle-xmark"></i> Ошибок в отчёте: <b>{{ data.blocking }}</b>. <button class="link" @click="S.view = 'review'" v-if="can('responsible','head')">Открыть очередь проверки</button></div>
      <div v-if="data.diff && (data.diff.added.length || data.diff.removed.length || data.diff.changed.length)" class="notice warn"><b>После утверждённой версии есть изменения:</b> добавлено {{ data.diff.added.length }}, удалено {{ data.diff.removed.length }}, изменено {{ data.diff.changed.length }}. Утверждённый файл не изменился.</div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:flex-end">
        <template v-if="data.actions.length">
          <label class="f" v-if="data.actions.some(a => a.action === 'approve')">Протокол №<input class="inp" style="width:90px" v-model="protocol.no"></label>
          <label class="f" v-if="data.actions.some(a => a.action === 'approve')">Дата<input class="inp" style="width:120px" v-model="protocol.date" placeholder="12.01.2026"></label>
          <label class="f" style="flex:1;min-width:180px">Комментарий<input class="inp" v-model="note"></label>
          <button v-for="a in data.actions" :key="a.action" class="btn" :class="a.action === 'return' ? 'danger' : 'primary'" @click="doAction(a.action)">{{ a.label }}</button>
        </template>
        <span style="flex:1" v-else></span>
        <button class="btn outline" @click="dl('/api/export/f605/' + unit + '/2025')"><i class="fa-regular fa-file-excel"></i> Выгрузить в Excel</button>
      </div>
    </div></div>
    <div class="tabs" style="margin-top:14px">
      <button :class="{on: tab==='sections'}" @click="tab='sections'">Разделы ({{ filledSections }}/{{ data.sections.length }})</button>
      <button :class="{on: tab==='outside'}" @click="tab='outside'">Не вошло ({{ data.outside.length }})</button>
      <button :class="{on: tab==='analysis'}" @click="tab='analysis'">Итоговая страница ({{ data.indicators.length }})</button>
      <button :class="{on: tab==='evidence'}" @click="tab='evidence'">Подтверждающие документы ({{ data.evidence.have }}/{{ data.evidence.need }})</button>
      <button :class="{on: tab==='versions'}" @click="tab='versions'">Версии ({{ data.versions.length }})</button>
      <button :class="{on: tab==='other'}" @click="tab='other'">Другие отчёты</button>
    </div>
    <div v-if="tab==='outside'" class="card">
      <div class="card-head"><div class="small muted">Эти записи войдут в отчёт после согласования. Здесь видно, у кого они сейчас.</div></div>
      <div class="table-wrap" v-if="data.outside.length"><table><thead><tr><th style="width:46%">Запись</th><th>Автор</th><th>Статус</th><th>Сейчас</th></tr></thead>
        <tbody><tr v-for="r in data.outside" :key="r.id"><td><button class="link" @click="S.drawerId = r.id">{{ r.title }}</button></td><td class="small">{{ r.authors.join(', ') }}</td><td><Tag :status="r.status"/></td><td class="small">{{ r.stage }}<template v-if="r.days">, {{ r.days }} дн.</template></td></tr></tbody></table></div>
      <div v-else class="empty">Все записи кафедры вошли в отчёт.</div>
    </div>
    <div v-else-if="tab==='sections'" class="card">
      <div v-for="s in data.sections" :key="s.id" class="acc">
        <button class="acc-head" @click="open[s.id] = !open[s.id]" :disabled="!s.count" :style="s.count ? '' : 'opacity:.55;cursor:default'">
          <i class="fa-solid small faint" :class="open[s.id] ? 'fa-chevron-down' : 'fa-chevron-right'"></i><span class="section-badge">{{ s.id }}</span>
          <span style="flex:1;min-width:200px">{{ s.title.replace(/^[^ ]+ /,'').slice(0,110) }}</span><span v-if="s.evidence" class="tag">{{ s.evidence }}</span><b>{{ s.count }}</b></button>
        <div v-if="open[s.id]" style="padding:0 14px 10px 44px"><div v-for="r in s.items" :key="r.id" class="small" style="padding:3px 0"><button class="link small" @click="S.drawerId = r.id">{{ r.title.slice(0,110) }}</button> <span class="faint">{{ r.authors.slice(0,2).join(', ') }}</span></div></div>
      </div>
    </div>
    <div v-else-if="tab==='analysis'">
      <div class="card" style="margin-bottom:14px"><div class="card-head"><div><h2>Аналитическая справка</h2><div class="small muted">Черновик текста для заседания кафедры: сравнение с прошлым годом и что требует внимания.</div></div><span class="spacer"></span>
        <button class="btn sm" :disabled="narrativeBusy" @click="makeNarrative"><i class="fa-solid fa-robot"></i> {{ narrativeBusy ? 'Готовлю…' : narrative ? 'Обновить' : 'Подготовить черновик' }}</button><button v-if="narrative" class="btn sm" @click="copyNarrative"><i class="pi pi-copy"></i> Копировать</button></div>
        <div class="card-body" v-if="narrative" style="white-space:pre-wrap">{{ narrative.text }}</div></div>
      <div class="notice">Всего показателей: {{ data.indicators.length }}. Считаются автоматически: <b>{{ data.auto_count }}</b>, вносит человек: <b>{{ data.manual_count }}</b>. В колонке «В отчёте» указано значение, набранное ранее вручную; при расхождении оно выделяется. Тип соавтора агент определяет по аффилиации в статье, а пока отметки нет, стоит «–». Число ЦУР посчитано по ключевым словам в названии.</div>
      <div class="card" v-if="data.can_edit_manual" style="margin-bottom:14px"><div class="card-body form-grid" style="grid-template-columns:repeat(auto-fit,minmax(170px,1fr));align-items:end">
        <label class="f">Доля остепенённых<input class="inp" type="number" step="0.001" v-model="manual.degree_share"></label>
        <label class="f">Доля зарубежных учёных<input class="inp" type="number" step="0.001" v-model="manual.foreign_scholar_share"></label>
        <label class="f">Финансирование, тыс. ₸<input class="inp" type="number" step="0.01" v-model="manual.funding"></label>
        <label class="f">Штатная численность<input class="inp" type="number" v-model="manual.staff_count"></label>
        <button class="btn primary" @click="saveManual">Сохранить</button></div></div>
      <div class="card"><div class="table-wrap"><table>
        <thead><tr><th>Показатель (по форме)</th><th class="num">Прошлый год</th><th class="num">В отчёте</th><th class="num">Система</th><th>Источник</th></tr></thead>
        <tbody><tr v-for="i in data.indicators" :key="i.row"><td>{{ i.label }}</td><td class="num">{{ show(i.prev) }}</td><td class="num" :class="{'lv-warn': differs(i)}">{{ show(i.reported) }}</td><td class="num"><b>{{ show(i.value) }}</b></td><td><span class="tag" :class="SOURCE[i.source][1]">{{ SOURCE[i.source][0] }}</span></td></tr></tbody>
      </table></div></div>
    </div>
    <div v-else-if="tab==='evidence'" class="card">
      <div class="card-head"><div><h2>Пакет подтверждающих документов</h2><div class="small muted">Форма требует скриншот, подтверждающий документ и титульный лист. Файл прикрепляется к записи, поэтому собирать его заново не нужно.</div></div><span class="spacer"></span><button class="btn sm" @click="dl('/api/export/evidence/' + unit + '/2025')"><i class="fa-regular fa-file-zipper"></i> Скачать ZIP</button></div>
      <div class="card-body"><div class="tiles"><div v-for="(v,k) in data.evidence.kinds" :key="k" class="tile"><div class="label">{{ k }}</div><div class="value">{{ v.have }}/{{ v.need }}</div></div></div>
        <div v-for="m in data.evidence.missing.slice(0,30)" :key="m.id + m.kind" class="small" style="padding:3px 0"><span class="tag warn">нет: {{ m.kind }}</span> <button class="link small" @click="S.drawerId = m.id">{{ m.title.slice(0,100) }}</button></div></div>
    </div>
    <div v-else-if="tab==='versions'" class="card">
      <div v-if="data.versions.length"><table><thead><tr><th>Версия</th><th>Кто утвердил</th><th>Время</th><th></th></tr></thead>
        <tbody><tr v-for="v in data.versions" :key="v.id"><td><b>{{ v.version }}</b></td><td>{{ v.approved_by }}</td><td class="small">{{ v.approved_at.replace('T',' ').slice(0,16) }}</td><td><button class="btn sm" @click="dl('/api/export/f605/' + unit + '/2025?version=' + v.version)"><i class="fa-regular fa-file-excel"></i> Excel</button></td></tr></tbody></table></div>
      <div v-else class="empty">Утверждённых версий пока нет. Версия сохраняется, когда отчёт подписывает директор, и её цифры потом не меняются.</div>
    </div>
    <div v-else class="card"><div class="card-body">
      <p class="muted" style="margin-top:0">Эти же данные подходят и для других отчётов, собирать заново ничего не нужно.</p>
      <div class="task" style="cursor:default"><span class="ic"><i class="fa-regular fa-file-excel"></i></span><span><b>Научный раздел годового отчёта кафедры</b><span class="small muted">Цифры, план и факт, таблица преподавателей</span></span><button class="btn sm" style="margin-left:auto" @click="dl('/api/export/department/' + unit + '/2025')">Выгрузить</button></div>
      <div class="task" style="cursor:default"><span class="ic"><i class="fa-solid fa-list-ol"></i></span><span><b>Список научных работ</b><span class="small muted">По сотруднику. Выгружается со страницы «Научные работы»</span></span><button class="btn sm" style="margin-left:auto" @click="dl('/api/export/person/' + S.boot.position.person)">Выгрузить</button></div>
      <div class="task" style="cursor:default" v-if="can('director','science')"><span class="ic"><i class="fa-solid fa-table"></i></span><span><b>Сводная таблица по высшей школе</b><span class="small muted">Сравнение кафедр</span></span><button class="btn sm" style="margin-left:auto" @click="dl('/api/export/summary/vshet/2025')">Выгрузить</button></div>
    </div></div>
  </div>`,
};

/* ---------- Есеп аудиті ---------- */
const Audit = {
  setup() {
    const result = ref(null);
    const busy = ref(false);
    const imported = ref(null);
    const upload = async (e) => {
      const f = e.target.files[0];
      if (!f) return;
      busy.value = true;
      result.value = null;
      imported.value = null;
      const form = new FormData();
      form.append('file', f);
      try { result.value = await api('/api/audit/upload', { method: 'POST', body: form }); } finally { busy.value = false; e.target.value = ''; }
    };
    const doImport = async () => {
      imported.value = await api(`/api/audit/${result.value.audit_id}/import`, { method: 'POST' });
      toast(`Добавлено: ${imported.value.added}, уже в базе: ${imported.value.skipped}`);
      bump();
    };
    const LV = { error: 'bad', warn: 'warn', info: '' };
    return { result, busy, upload, doImport, imported, LV, can };
  },
  template: `<div>
    <div class="page-title"><h1>Аудит отчёта</h1><p>Загрузите прежний отчёт в формате Excel. Система покажет ошибки, дубли и расхождения с итоговой страницей. В результатах указываются не имена людей, а раздел и номер строки.</p></div>
    <div class="card"><div class="card-body" style="text-align:center;padding:28px">
      <label class="btn primary"><i class="fa-solid fa-upload"></i> {{ busy ? 'Идёт проверка…' : 'Выбрать файл XLSX' }}<input type="file" accept=".xlsx" hidden :disabled="busy" @change="upload"></label>
      <div class="small muted" style="margin-top:8px">Файл по форме Ф ЕНУ 605-02-25. Телефоны и email при импорте не сохраняются, новые строки уходят на согласование заведующему кафедрой.</div></div></div>
    <template v-if="result">
      <div class="tiles" style="margin-top:14px">
        <div class="tile"><div class="label">Заполненные строки</div><div class="value">{{ result.rows }}</div></div>
        <div class="tile"><div class="label">Ошибки</div><div class="value">{{ result.errors }}</div></div>
        <div class="tile"><div class="label">Требуют внимания</div><div class="value">{{ result.warnings }}</div></div>
        <div class="tile"><div class="label">Лишние дублирующиеся строки</div><div class="value">{{ result.duplicate_rows }}</div></div></div>
      <div class="grid-2">
        <div class="card"><div class="card-head"><h2>Итоговая страница и строки</h2></div><table><thead><tr><th>Показатель</th><th class="num">В отчёте</th><th class="num">Фактически</th><th></th></tr></thead>
          <tbody><tr v-for="c in result.compare" :key="c.label"><td>{{ c.label }}</td><td class="num">{{ c.reported }}</td><td class="num"><b>{{ c.actual }}</b></td><td><span class="tag" :class="c.match ? 'good' : 'warn'">{{ c.match ? 'совпадает' : 'не совпадает' }}</span></td></tr></tbody></table></div>
        <div class="card"><div class="card-head"><h2>Найденные проблемы</h2></div><table><tbody><tr v-for="c in result.counts" :key="c.code"><td><span class="tag" :class="LV[c.level]">{{ {error:'ошибка',warn:'внимание',info:'примечание'}[c.level] }}</span> {{ c.label }}</td><td class="num"><b>{{ c.count }}</b></td></tr></tbody></table></div>
      </div>
      <div class="card" style="margin-top:14px"><div class="card-head"><h2>Дублирующиеся строки</h2></div><div class="card-body" style="padding-top:6px">
        <div v-for="(d,i) in result.duplicates" :key="i" class="issue"><i class="fa-regular fa-clone lv-warn"></i><div>{{ d.text }}<div class="small muted"><span v-for="r in d.rows" :key="r.sheet + r.row" style="margin-right:10px"><span class="section-badge">{{ r.section }}</span>«{{ r.sheet }}», строка {{ r.row }}</span></div></div></div></div></div>
      <div class="card"><div class="card-head"><h2>Список проблем</h2><span class="spacer"></span><button v-if="can('responsible','head') && !imported" class="btn sm primary" @click="doImport">Перенести новые строки в базу</button><span v-if="imported" class="small muted">Добавлено: {{ imported.added }}, пропущено: {{ imported.skipped }}</span></div><div class="table-wrap" style="max-height:380px;overflow-y:auto"><table>
        <thead><tr><th>Раздел</th><th>Лист, строка</th><th>Проблема</th></tr></thead><tbody><tr v-for="(f,i) in result.findings" :key="i"><td><span class="section-badge">{{ f.section }}</span></td><td class="small nowrap">{{ f.sheet }}, {{ f.row }}</td><td :class="'lv-' + f.level">{{ f.text }}</td></tr></tbody></table></div></div>
    </template>
  </div>`,
};

/* ---------- Интеграциялар ---------- */
const Integrations = {
  setup() {
    const { data } = useLoad(() => api('/api/integrations'));
    const LABEL = { live: ['Подключено', 'good'], mock: ['Тестовый адаптер', 'warn'], needs_key: ['Нужен ключ', ''] };
    const run = async (name) => { const r = await api(`/api/integrations/${name}/import`, { method: 'POST' }); toast(r.text); bump(); };
    const contract = `POST /api/bilge/specialist\nmultipart/form-data: session, text, file?\n\n200 OK\n{\n  "reply": "Это попадёт в раздел 3.7...",\n  "mode": "ai",\n  "draft": { "record": { "type": "prize", "sections": ["3.7"] }, "missing": [], "issues": [] }\n}`;
    const map = [['publicationName', 'Название публикации'], ['publicationDate', 'Год'], ['scienceWorkType', 'Тип записи'], ['editionName', 'Журнал или сборник'], ['editionNumber', 'Номер'], ['editionPages', 'Страницы'], ['issn, isbn', 'ISSN, ISBN'], ['printedPages', 'Печатные листы'], ['coauthorsInternal', 'Внутренние авторы'], ['coauthorsExternal', 'Внешние авторы'], ['attachments', 'Подтверждающие документы']];
    return { data, LABEL, run, contract, map };
  },
  template: `<div v-if="data">
    <div class="page-title"><h1>Интеграции</h1><p>Модуль опирается на данные Smart.ENU. Статус каждого подключения указан справа, для боевого подключения нужна официальная документация API.</p></div>
    <div class="card"><div v-for="i in data.items" :key="i.id" class="task" style="cursor:default">
      <span class="ic"><i class="fa-solid fa-plug"></i></span><span style="min-width:0"><b>{{ i.name }}</b><span class="small muted">{{ i.text }}</span></span>
      <span style="margin-left:auto;display:flex;gap:6px;align-items:center;flex:none"><span class="tag" :class="LABEL[i.status][1]">{{ LABEL[i.status][0] }}</span><button v-if="i.id === 'platonus' || i.id === 'scopus'" class="btn sm" @click="run(i.id)">Импортировать</button></span></div></div>
    <div class="grid-2" style="margin-top:14px">
      <div class="card"><div class="card-head"><h2>Модель данных: поля Smart.ENU</h2></div><table><thead><tr><th>Поле Smart.ENU</th><th>SciAgent</th></tr></thead><tbody><tr v-for="m in map" :key="m[0]"><td><code>{{ m[0] }}</code></td><td>{{ m[1] }}</td></tr></tbody></table></div>
      <div class="card"><div class="card-head"><h2>Специалист Bilge: контракт вызова</h2><span class="spacer"></span><a class="btn sm" href="/docs" target="_blank" rel="noopener">OpenAPI</a></div><div class="card-body"><pre class="code">{{ contract }}</pre><p class="small muted">Стандарты: DOI, ORCID, ISSN/ISBN, OpenAPI 3. Названия полей взяты из текстов интерфейса Smart.ENU. Для подключения нужна официальная документация API от Департамента цифрового развития.</p></div></div>
    </div>
  </div>`,
};

/* ---------- Баптаулар және журнал ---------- */
const Settings = {
  setup() {
    const { data, load } = useLoad(() => api('/api/settings'));
    const fresh = reactive({ issn: '', name: '', reason: '' });
    const save = async () => { await api('/api/settings', { method: 'PUT', body: data.value }); toast('Сохранено'); await load(); };
    const addJournal = () => { if (fresh.name) { data.value.journal_watchlist.push({ ...fresh }); fresh.issn = ''; fresh.name = ''; fresh.reason = ''; } };
    const reset = async () => {
      if (!window.confirm('Вернуть данные в исходное состояние? Внесённые изменения будут удалены.')) return;
      await api('/api/demo/reset', { method: 'POST' });
      toast('Данные возвращены в исходное состояние');
      bump();
    };
    return { data, fresh, save, addJournal, reset, can };
  },
  template: `<div v-if="data">
    <div class="page-title"><h1>Настройки</h1><p>Требования к защите и список журналов ведёт Департамент науки. Менять код для этого не нужно.</p></div>
    <div class="card"><div class="card-head"><div><h2>Требования к докторантам</h2><div class="muted small">Значения условные, их задаёт Департамент науки.</div></div></div><div class="card-body form-grid" style="grid-template-columns:repeat(auto-fit,minmax(150px,1fr))">
      <label class="f">Scopus или WoS<input class="inp" type="number" v-model.number="data.doctoral_requirements.scopus_or_wos" :disabled="!can('science')"></label>
      <label class="f">КОКСНВО<input class="inp" type="number" v-model.number="data.doctoral_requirements.koksnvo" :disabled="!can('science')"></label>
      <label class="f">Конференция<input class="inp" type="number" v-model.number="data.doctoral_requirements.conference" :disabled="!can('science')"></label></div></div>
    <div class="card"><div class="card-head"><div><h2>Список рискованных журналов</h2><div class="muted small">Значения условные, их задаёт Департамент науки.</div></div></div><table><thead><tr><th>ISSN</th><th>Журнал</th><th>Причина</th></tr></thead><tbody><tr v-for="j in data.journal_watchlist" :key="j.name"><td>{{ j.issn }}</td><td>{{ j.name }}</td><td>{{ j.reason }}</td></tr></tbody></table>
      <div class="card-body form-grid" style="grid-template-columns:1fr 2fr 2fr auto;align-items:end" v-if="can('science')"><label class="f">ISSN<input class="inp" v-model="fresh.issn"></label><label class="f">Журнал<input class="inp" v-model="fresh.name"></label><label class="f">Причина<input class="inp" v-model="fresh.reason"></label><button class="btn" @click="addJournal">Добавить</button></div></div>
    <div style="display:flex;gap:8px;margin-top:12px"><button v-if="can('science')" class="btn primary" @click="save">Сохранить</button><button v-if="can('responsible','head','director','science')" class="btn danger" @click="reset"><i class="fa-solid fa-rotate-left"></i> Сбросить данные</button></div>
  </div>`,
};
const Log = {
  setup() { const { data } = useLoad(() => api('/api/log')); return { data }; },
  template: `<div v-if="data"><div class="page-title"><h1>Журнал действий</h1><p>Кто, когда и что сделал. Выгрузка в Excel и просмотр контактных данных тоже записываются.</p></div>
    <div class="card"><div class="table-wrap"><table><thead><tr><th>Время</th><th>Должность</th><th>Действие</th><th>Объект</th><th>Подробнее</th></tr></thead>
      <tbody><tr v-for="l in data.items" :key="l.id"><td class="small nowrap">{{ l.at.replace('T',' ').slice(0,16) }}</td><td class="small">{{ l.position }}</td><td>{{ l.action }}</td><td class="small">{{ l.entity }}</td><td class="small muted">{{ l.detail }}</td></tr></tbody></table></div>
      <div v-if="!data.items.length" class="empty">Журнал пуст.</div></div></div>`,
};
