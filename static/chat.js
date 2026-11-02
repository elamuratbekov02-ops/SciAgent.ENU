/* Чат-агент: қадамдар, карточкалар, диаграмма мен файл сервер дайын болған сайын келеді. */
const CHECK_LABEL = { crossref: 'Подтверждено Crossref', document: 'Найдено в документе', unverified: 'Не подтверждено, проверьте' };

const DraftCard = {
  props: ['d'],
  emits: ['saved'],
  setup(p, { emit }) {
    const type = computed(() => S.boot.types[p.d.record.type]);
    const label = (key) => { const f = type.value.fields.find((x) => x.key === key); return f ? f.label : key; };
    const keys = computed(() => {
      const order = type.value.fields.map((f) => f.key);
      return Object.keys(p.d.record.fields).filter((k) => order.includes(k)).sort((a, b) => order.indexOf(a) - order.indexOf(b));
    });
    const ai = computed(() => p.d.payload.ai || {});
    const check = (k) => (ai.value.checks ? ai.value.checks[k] : undefined);
    const dot = (k) => ({ crossref: 'ok', document: 'ok', unverified: 'low' }[check(k)] || 'none');
    const title = (k) => {
      const c = ai.value.confidence ? ai.value.confidence[k] : undefined;
      const parts = [CHECK_LABEL[check(k)]];
      if (c !== undefined && c !== null) parts.push(`уверенность ${Math.round(c * 100)}%`);
      return parts.filter(Boolean).join(', ');
    };
    const quote = (k) => { const e = ai.value.evidence ? ai.value.evidence[k] : null; return e ? `«${e.quote}»${e.page ? `, с. ${e.page}` : ''}` : ''; };
    const mismatches = computed(() => ai.value.mismatches || []);
    const useCrossref = (m) => {
      p.d.payload.fields[m.key] = m.crossref;
      p.d.record.fields[m.key] = m.crossref;
      ai.value.checks[m.key] = 'crossref';
      ai.value.mismatches = mismatches.value.filter((x) => x.key !== m.key);
    };
    const confirm = async (send) => {
      if (p.d.missing.length) { edit(); return; }
      const r = await api('/api/records', { method: 'POST', body: { ...p.d.payload, source: 'chat', allow_missing: true } });
      if (r.merged) {
        p.d.saved = r.claimed ? 'claimed' : 'merged';
        toast(r.claimed ? 'Такая запись уже есть. Ответственный проверит и добавит вас соавтором' : 'Запись уже была в базе, добавлены недостающие сведения');
      } else if (send) {
        p.d.saved = (await sendForApproval(r.record.id)) ? 'sent' : 'saved';
      } else {
        p.d.saved = 'saved';
        toast('Черновик сохранён в разделе «Мои результаты»');
      }
      bump();
      emit('saved');
    };
    const edit = () => { const x = p.d.payload; S.newRecord = { type: x.type, fields: x.fields, attrs: x.attrs, authors: x.authors, evidence: x.evidence, ai: x.ai }; };
    return { type, label, keys, dot, title, quote, mismatches, useCrossref, confirm, edit };
  },
  template: `<div class="draft">
    <div class="draft-head"><b>{{ type.label }}</b><span v-for="s in d.record.sections" :key="s" class="section-badge">{{ s }}</span></div>
    <div v-for="k in keys" :key="k" class="draft-row"><span class="muted">{{ label(k) }}</span>
      <span :title="quote(k)">{{ d.record.fields[k] }}<span v-if="quote(k)" class="small faint" style="display:block">{{ quote(k) }}</span></span>
      <span class="conf" :class="dot(k)" :title="title(k)" :aria-label="title(k)"></span></div>
    <div v-if="d.authors.length" class="small draft-line"><span class="muted">Сопоставленные авторы:</span> {{ d.authors.map(a => a.display).join(', ') }}</div>
    <div v-if="d.external.length" class="small draft-line"><span class="muted">Нет в справочнике:</span> {{ d.external.join(', ') }}</div>
    <div v-if="d.duplicate" class="small lv-warn draft-line"><i class="pi pi-clone"></i> Уже есть в базе, повторно не вводится</div>
    <div v-if="d.missing.length" class="small lv-warn draft-line">Не хватает: {{ d.missing.map(x => x.label).join(', ') }}</div>
    <div v-for="iss in d.issues" :key="iss.code" class="small draft-line" :class="'lv-' + iss.level">{{ iss.text }}</div>
    <div v-for="m in mismatches" :key="m.key" class="small draft-mismatch"><i class="pi pi-exclamation-triangle lv-warn"></i>
      <span>{{ label(m.key) }}: в документе «{{ m.value }}», в Crossref «{{ m.crossref }}».</span> <button class="link small" @click="useCrossref(m)">Взять из Crossref</button></div>
    <div v-if="!d.saved" class="draft-actions">
      <button class="btn sm primary" @click="confirm(true)"><i class="pi" :class="d.duplicate ? 'pi-check' : 'pi-send'"></i> {{ d.missing.length ? 'Дополнить' : d.duplicate ? 'Добавить к записи' : 'Сохранить и отправить' }}</button>
      <button v-if="!d.duplicate && !d.missing.length" class="btn sm" @click="confirm(false)">Черновик</button>
      <button class="btn sm" @click="edit">Изменить</button></div>
    <div v-else class="small draft-done"><i class="pi pi-check-circle"></i> {{ { merged: 'Добавлено к существующей записи', claimed: 'Запись уже есть, заявка на соавторство передана ответственному', sent: 'Отправлено на согласование', saved: 'Сохранено в «Мои результаты»' }[d.saved] }}</div>
  </div>`,
};

const Chat = {
  components: { DraftCard, ChatChart },
  setup() {
    const GREETING = 'Здравствуйте! Я помогу внести научный результат один раз и в нужном формате. Пришлите PDF статьи, DOI, ссылку, фото диплома, титул монографии или старый отчёт Excel. Могу показать показатели диаграммой, проверить готовность отчёта и выгрузить файл.';
    const messages = ref([{ who: 'bot', text: GREETING, steps: [], drafts: [], charts: [], files: [] }]);
    const text = ref('');
    const busy = ref(false);
    const file = ref(null);
    const session = ref('s' + Math.random().toString(36).slice(2, 10));
    const body = ref(null);
    const dragging = ref(false);
    const scroll = () => nextTick(() => { if (body.value) body.value.scrollTop = body.value.scrollHeight; });

    const handle = (m, e) => {
      if (e.type === 'step') {
        const hit = m.steps.find((s) => s.label === e.label);
        if (hit) hit.status = e.status; else m.steps.push({ label: e.label, status: e.status });
      } else if (e.type === 'text') m.text += e.text;
      else if (e.type === 'draft') m.drafts.push(e.draft);
      else if (e.type === 'chart') m.charts.push(e.chart);
      else if (e.type === 'file') m.files.push(e.file);
      else if (e.type === 'done') m.text = e.reply;
      else if (e.type === 'error') m.text = e.text;
      scroll();
    };

    const send = async (preset) => {
      const value = preset || text.value.trim();
      if ((!value && !file.value) || busy.value) return;
      const f = file.value;
      messages.value.push({ who: 'me', text: value || f.name, file: f && f.name });
      text.value = '';
      file.value = null;
      busy.value = true;
      messages.value.push({ who: 'bot', text: '', steps: [], drafts: [], charts: [], files: [], live: true });
      const m = messages.value[messages.value.length - 1];
      scroll();
      const form = new FormData();
      form.append('session', session.value);
      form.append('text', value);
      if (f) form.append('file', f);
      try {
        const res = await fetch('/api/agent/stream', { method: 'POST', headers: { 'X-Position': S.pos }, body: form });
        if (!res.ok || !res.body) throw new Error(String(res.status));
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        for (;;) {
          const { value: chunk, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(chunk, { stream: true });
          let cut;
          while ((cut = buffer.indexOf('\n\n')) >= 0) {
            const line = buffer.slice(0, cut);
            buffer = buffer.slice(cut + 2);
            if (line.startsWith('data: ')) handle(m, JSON.parse(line.slice(6)));
          }
        }
      } catch (e) {
        m.text = 'Запрос не выполнен. Попробуйте ещё раз.';
      } finally { m.live = false; busy.value = false; scroll(); }
    };
    const pick = (e) => { file.value = e.target.files[0] || null; e.target.value = ''; };
    const drop = (e) => { dragging.value = false; if (e.dataTransfer.files[0]) file.value = e.dataTransfer.files[0]; };
    const fresh = async () => {
      await api('/api/agent/reset', { method: 'POST', body: { session: session.value } });
      session.value = 's' + Math.random().toString(36).slice(2, 10);
      messages.value = [{ who: 'bot', text: GREETING, steps: [], drafts: [], charts: [], files: [] }];
    };
    const ready = (m) => m.drafts.filter((d) => !d.saved && !d.missing.length);
    const confirmAll = async (m) => {
      const rows = ready(m);
      let sent = 0;
      for (const d of rows) {
        const r = await api('/api/records', { method: 'POST', body: { ...d.payload, source: 'chat', allow_missing: true } });
        if (r.merged) { d.saved = r.claimed ? 'claimed' : 'merged'; continue; }
        const res = await api(`/api/records/${r.record.id}/submit`, { method: 'POST', body: {}, allow: [200, 403, 404, 409, 422] });
        d.saved = res.status === 200 ? 'sent' : 'saved';
        if (res.status === 200) sent += 1;
      }
      toast(sent === rows.length ? `Отправлено на согласование: ${sent}` : `Отправлено: ${sent}. Остальные сохранены, откройте «Мои результаты» и выберите руководителя`, sent !== rows.length);
      bump();
    };
    watch(() => S.chatQueue, (q) => {
      if (!q) return;
      S.chatQueue = null;
      file.value = q.file || null;
      send(q.text || '');
    });
    const open = (f) => dl(f.href);
    const samples = computed(() => (can('author', 'supervisor')
      ? ['Где сейчас мои записи?', 'Что мне нужно сделать?', 'Занял 2 место на олимпиаде в Бишкеке', 'Сколько у меня статей в Scopus?', 'Сформируй список моих работ']
      : ['Что на моём согласовании?', 'Что мешает сдать отчёт?', 'Покажи диаграмму по преподавателям', 'Сформируй отчёт НИР', 'Как выполняется план?']));
    return { S, messages, text, busy, file, send, pick, drop, dragging, fresh, ready, confirmAll, open, body, samples };
  },
  template: `<div class="chat" :class="{dragging}" @dragover.prevent="dragging = true" @dragleave.self="dragging = false" @drop.prevent="drop">
    <div class="chat-head"><div class="chat-logo"><i class="fa-solid fa-robot"></i></div>
      <div><b>SciAgent</b><small>Специалист Bilge по научной отчётности</small></div><span class="spacer"></span>
      <button aria-label="Новый диалог" title="Новый диалог" @click="fresh"><i class="pi pi-refresh"></i></button>
      <button aria-label="Закрыть" @click="S.chatOpen = false"><i class="pi pi-times"></i></button></div>
    <div class="chat-body" ref="body">
      <template v-for="(m,i) in messages" :key="i">
        <div v-if="m.who === 'me'" class="msg me"><i v-if="m.file" class="pi pi-paperclip"></i> {{ m.text }}</div>
        <template v-else>
          <div v-if="m.steps.length" class="chat-steps"><div v-for="s in m.steps" :key="s.label" class="chat-step" :class="s.status">
            <i class="pi" :class="s.status === 'run' ? 'pi-spin pi-spinner' : s.status === 'warn' ? 'pi-exclamation-circle' : 'pi-check'"></i> {{ s.label }}</div></div>
          <div v-if="m.text" class="msg bot">{{ m.text }}</div>
          <div v-else-if="m.live && !m.steps.length" class="msg bot muted"><i class="pi pi-spin pi-spinner"></i> Думаю…</div>
          <ChatChart v-for="(c,j) in m.charts" :key="'c' + j" :spec="c"/>
          <button v-for="(f,j) in m.files" :key="'f' + j" class="chat-file" @click="open(f)"><i class="pi pi-file-excel"></i><span>{{ f.label }}</span><i class="pi pi-download"></i></button>
          <div v-if="ready(m).length > 1" class="chat-bulk"><span class="small muted">Готово к подтверждению: {{ ready(m).length }}</span><button class="btn sm primary" @click="confirmAll(m)"><i class="pi pi-send"></i> Отправить все</button></div>
          <DraftCard v-for="(d,j) in m.drafts" :key="'d' + j" :d="d"/>
        </template>
      </template>
    </div>
    <div class="chat-chips" v-if="messages.length < 3"><button v-for="s in samples" :key="s" @click="send(s)">{{ s }}</button></div>
    <div class="chat-chips" v-if="messages.length < 3"><a class="small" href="samples/" target="_blank" rel="noopener"><i class="pi pi-folder-open"></i> Образцы файлов</a></div>
    <div v-if="file" class="small chat-attached"><i class="pi pi-paperclip"></i> {{ file.name }} <button class="link small" @click="file = null">убрать</button></div>
    <div class="chat-input">
      <label class="icon-btn chat-clip" aria-label="Прикрепить файл"><i class="pi pi-paperclip"></i><input type="file" accept=".pdf,.png,.jpg,.jpeg,.webp,.xlsx" hidden @change="pick"></label>
      <textarea rows="1" v-model="text" placeholder="Напишите сообщение" @keydown.enter.exact.prevent="send()"></textarea>
      <button class="btn primary" aria-label="Отправить" :disabled="busy" @click="send()"><i class="pi pi-arrow-up"></i></button>
    </div>
  </div>`,
};
