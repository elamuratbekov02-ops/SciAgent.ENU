/* Жұмыс процесі: автордың беті, келісу кезегі, есеп науқаны және «Как это работает». */
async function sendForApproval(id, supervisorId, quiet) {
  const body = supervisorId ? { supervisor_id: supervisorId } : {};
  const r = await api(`/api/records/${id}/submit`, { method: 'POST', body, allow: [200, 403, 404, 409, 422] });
  if (r.status === 200) {
    if (!quiet) toast(`Отправлено. Сейчас: ${r.data.stage.toLowerCase()}`);
    bump();
    return true;
  }
  if (r.data && r.data.needs_supervisor) {
    S.drawerId = id;
    toast('Выберите научного руководителя');
    return false;
  }
  toast((r.data && r.data.detail) || 'Не удалось отправить', true);
  return false;
}

/* Жазбаның бағыты: автордан есепке дейін. */
const RouteLine = {
  props: ['route', 'status', 'first', 'last'],
  setup() {
    const icon = { done: 'pi-check', current: 'pi-clock', returned: 'pi-undo', wait: 'pi-circle' };
    const text = { done: 'согласовано', current: 'сейчас здесь', returned: 'вернул(а) автору', wait: 'далее' };
    return { icon, text };
  },
  template: `<div class="route">
    <div class="route-step done"><i class="pi pi-user"></i><div><b>{{ first || 'Автор' }}</b><span>вносит запись</span></div></div>
    <template v-for="s in route" :key="s.label"><i class="pi pi-angle-right route-arrow"></i>
      <div class="route-step" :class="s.state"><i class="pi" :class="icon[s.state]"></i><div><b>{{ s.label }}</b><span>{{ s.on_behalf ? 'согласовал заведующий' : text[s.state] }}</span></div></div></template>
    <i class="pi pi-angle-right route-arrow"></i>
    <div class="route-step" :class="status === 'согласовано' ? 'done' : 'wait'"><i class="pi" :class="status === 'согласовано' ? 'pi-check' : 'pi-file-excel'"></i><div><b>{{ last || 'Отчёт НИР' }}</b><span>{{ status === 'согласовано' ? 'запись вошла' : 'после согласования' }}</span></div></div>
  </div>`,
};

/* Жазба панеліндегі келісу блогы. */
const RecordFlow = {
  components: { RouteLine },
  props: ['flow', 'rid'],
  emits: ['changed'],
  setup(p, { emit }) {
    const note = ref('');
    const teachers = ref([]);
    const supervisor = ref('');
    const busy = ref(false);
    onMounted(async () => { if (p.flow.needs_supervisor) teachers.value = (await api('/api/scientists')).items; });
    const run = async (fn) => { busy.value = true; try { await fn(); note.value = ''; emit('changed'); } finally { busy.value = false; } };
    const submit = () => run(async () => {
      const ok = await sendForApproval(p.rid, supervisor.value);
      if (ok) S.drawerId = null;
    });
    const act = (action, okText) => run(async () => {
      await api(`/api/records/${p.rid}/${action}`, { method: 'POST', body: { note: note.value } });
      toast(okText);
      bump();
    });
    const LEVEL = { ok: ['Замечаний нет', 'good'], warn: ['Есть на что посмотреть', 'warn'], error: ['Есть ошибки', 'bad'] };
    const claim = (person, accept) => run(async () => {
      await api(`/api/records/${p.rid}/claim`, { method: 'POST', body: { person, accept } });
      toast(accept ? 'Соавтор добавлен' : 'Заявка отклонена');
      bump();
    });
    const check = () => run(async () => {
      const r = await api(`/api/records/${p.rid}/check-published`, { method: 'POST' });
      toast(r.text, !r.found);
      bump();
    });
    return { note, teachers, supervisor, busy, submit, act, LEVEL, claim, check };
  },
  template: `<div class="flow card">
    <div class="card-head"><h2>Согласование</h2><span class="tag" :class="flow.in_report ? 'good' : ''">{{ flow.stage }}</span><span v-if="flow.days && !flow.in_report" class="small muted">{{ flow.days }} дн. на этом этапе</span></div>
    <div class="card-body">
      <RouteLine :route="flow.route" :status="flow.status"/>
      <div v-if="flow.return_note" class="notice warn" style="margin-top:10px"><b>Что исправить:</b> {{ flow.return_note }}</div>
      <div class="flow-check"><span class="tag" :class="LEVEL[flow.precheck.level][1]">{{ LEVEL[flow.precheck.level][0] }}</span>
        <span v-for="g in flow.precheck.good" :key="g" class="small muted"><i class="pi pi-check"></i> {{ g }}</span>
        <div v-for="r in flow.precheck.reasons" :key="r.text" class="small" :class="'lv-' + r.level">{{ r.text }}</div></div>
      <div v-for="c in flow.claims" :key="c.id" class="notice warn" style="margin-top:10px"><b>{{ c.name }}</b> указывает себя соавтором.
        <button class="btn sm" :disabled="busy" @click="claim(c.id, true)">Добавить</button> <button class="btn sm" :disabled="busy" @click="claim(c.id, false)">Отклонить</button></div>
      <div v-if="flow.actions.length" class="flow-actions">
        <label v-if="flow.needs_supervisor" class="f">Научный руководитель<select class="inp" v-model="supervisor"><option value="">Выберите из списка кафедры</option><option v-for="t in teachers" :key="t.id" :value="t.id">{{ t.name }}</option></select></label>
        <label v-if="flow.actions.includes('return') || flow.actions.includes('reopen')" class="f">{{ flow.actions.includes('return') ? 'Комментарий (для возврата обязателен)' : 'Что хотите изменить' }}<input class="inp" v-model="note"></label>
        <div class="flow-buttons">
          <button v-if="flow.actions.includes('submit')" class="btn primary" :disabled="busy || (flow.needs_supervisor && !supervisor)" @click="submit"><i class="pi pi-send"></i> Отправить на согласование</button>
          <button v-if="flow.actions.includes('approve')" class="btn primary" :disabled="busy" @click="act('approve', 'Согласовано')"><i class="pi pi-check"></i> Согласовать</button>
          <button v-if="flow.actions.includes('return')" class="btn danger" :disabled="busy || !note.trim()" @click="act('return', 'Возвращено автору')"><i class="pi pi-undo"></i> Вернуть на доработку</button>
          <button v-if="flow.actions.includes('confirm')" class="btn primary" :disabled="busy" @click="act('confirm', 'Подтверждено')"><i class="pi pi-check"></i> Да, это моя запись</button>
          <button v-if="flow.actions.includes('check')" class="btn" :disabled="busy" @click="check"><i class="pi pi-search"></i> Проверить выход статьи</button>
          <button v-if="flow.actions.includes('reopen')" class="btn" :disabled="busy" @click="act('reopen', 'Запись открыта. После изменения отправьте её снова')"><i class="pi pi-pencil"></i> Изменить запись</button>
        </div>
        <div v-if="flow.actions.includes('reopen')" class="small muted">Запись выйдет из отчёта и снова пройдёт согласование.</div>
      </div>
      <details v-if="flow.history.length" class="more"><summary>История ({{ flow.history.length }})</summary>
        <div v-for="(h,i) in flow.history" :key="i" class="flow-hist"><span class="faint">{{ (h.at || '').replace('T',' ').slice(0,16) }}</span> <b>{{ h.action }}</b> <span class="muted">{{ h.by }}</span><div v-if="h.note" class="small">{{ h.note }}</div></div></details>
    </div></div>`,
};

/* Нәтиже қайдан келеді: жарияланым «Научные работы» бетінен, қалғаны осы жерден. */
const AddResult = {
  props: ['total', 'fresh'],
  setup() {
    const drag = ref(false);
    const toChat = (payload) => { S.chatOpen = true; S.chatQueue = payload; };
    const pick = (e) => { const f = e.target.files[0]; e.target.value = ''; if (f) toChat({ file: f, text: '' }); };
    const drop = (e) => { drag.value = false; const f = e.dataTransfer.files[0]; if (f) toChat({ file: f, text: '' }); };
    const form = () => { S.newRecord = { as_author: true }; };
    const openWorks = () => { S.page = 'works'; };
    return { drag, pick, drop, form, openWorks };
  },
  template: `<div class="card add-result">
    <div class="card-head"><div><h2>Откуда берутся результаты</h2><div class="small muted">Модуль берёт то, что уже есть в Smart.ENU. Вносить одно и то же дважды не нужно.</div></div></div>
    <div class="add-grid">
      <div class="add-opt add-works"><i class="pi pi-file"></i><b>Публикации: из «Научных работ»</b><span>Статьи, конференции и монографии вы вносите как обычно: вручную или импортом из Platonus и Scopus. Сюда они приходят сами.</span>
        <span class="add-stat">Там работ: <b>{{ total }}</b>. Ещё не отправлено на согласование: <b>{{ fresh }}</b>.</span>
        <button class="btn sm" style="align-self:flex-start;margin-top:6px" @click="openWorks"><i class="pi pi-external-link"></i> Открыть «Научные работы»</button></div>
      <label class="add-drop" :class="{on: drag}" @dragover.prevent="drag = true" @dragleave="drag = false" @drop.prevent="drop">
        <i class="pi pi-cloud-upload"></i><b>Чего там нет: загрузите файл</b><span>Диплом, грамота, удостоверение, приказ, договор о гранте. Перетащите сюда или выберите.</span><span class="add-ai"><i class="fa-solid fa-robot"></i> ИИ прочитает и заполнит карточку</span>
        <input type="file" accept=".pdf,.png,.jpg,.jpeg,.webp" hidden @change="pick"></label>
      <button class="add-opt add-btn" @click="form"><i class="pi pi-pencil"></i><b>Или заполните форму</b><span>Награда, призовое место, стипендия или грант, редколлегия, проект. Раздел отчёта система определит сама.</span></button>
    </div>
  </div>`,
};

/* Автордың жеке беті. */
const MyResults = {
  components: { Tag, AddResult, RouteLine },
  setup() {
    const { data, load } = useLoad(() => api('/api/pipeline'));
    const tab = ref('all');
    const TABS = [['all', 'Все'], ['создано', 'Черновики'], ['на доработке', 'На доработке'], ['на согласовании', 'На согласовании'], ['согласовано', 'Согласовано']];
    const count = (key) => { if (!data.value) return 0; return key === 'all' ? data.value.items.length : data.value.counts[key] || 0; };
    const rows = computed(() => (data.value ? data.value.items.filter((i) => tab.value === 'all' || i.status === tab.value) : []));
    const route = computed(() => {
      const role = S.boot.person.role;
      const head = can('head');
      const steps = [];
      if (['student', 'master', 'doctoral'].includes(role)) steps.push({ label: 'Научный руководитель', state: 'wait' });
      steps.push({ label: head ? 'Директор' : 'Заведующий кафедрой', state: 'wait' });
      return steps;
    });
    const send = async (i) => { await sendForApproval(i.id); };
    const confirmOwn = async (i) => { await api(`/api/records/${i.id}/confirm`, { method: 'POST' }); toast('Подтверждено'); bump(); };
    const attest = async () => { await api('/api/pipeline/attest', { method: 'POST' }); toast('Спасибо, список подтверждён'); await load(); };
    const openFound = () => go('found');
    const openWorks = () => { S.page = 'works'; };
    return { S, data, tab, TABS, count, rows, route, send, confirmOwn, attest, openFound, openWorks };
  },
  template: `<div v-if="data">
    <div class="notice" v-if="S.boot.inbox"><i class="pi pi-inbox"></i> На вашем согласовании записей: <b>{{ S.boot.inbox }}</b>. <button class="link" @click="S.view = 'approvals'">Открыть</button></div>
    <AddResult :total="data.works_total" :fresh="data.works_new"/>
    <div class="card path-card"><div class="card-head"><div><h2>Что будет дальше</h2><div class="small muted">Весь путь записи виден здесь. Вносить заново и пересылать по почте ничего не нужно.</div></div></div><div class="card-body"><RouteLine :route="route" first="Вы" status="создано"/></div></div>
    <div class="notice campaign-note" v-if="data.campaign.deadline">
      <div><b>{{ data.campaign.title }}.</b> Срок: {{ data.campaign.deadline.split('-').reverse().join('.') }}<template v-if="data.campaign.days_left >= 0">, осталось дней: {{ data.campaign.days_left }}</template>. В отчёт войдут согласованные записи: {{ data.in_report }}.
        <span v-if="data.counts['создано'] || data.counts['на доработке']"> Не отправлено: {{ (data.counts['создано'] || 0) + (data.counts['на доработке'] || 0) }}.</span></div>
      <button v-if="!data.attested_at" class="btn sm" @click="attest"><i class="pi pi-check-circle"></i> Мой список верен</button>
      <span v-else class="small" style="color:var(--good);white-space:nowrap"><i class="pi pi-check-circle"></i> Список подтверждён</span>
    </div>
    <div class="notice" v-if="data.found"><i class="pi pi-search"></i> Система нашла публикации, которые могут быть вашими: <b>{{ data.found }}</b>. <button class="link" @click="openFound">Посмотреть</button></div>
    <div class="tabs"><button v-for="t in TABS" :key="t[0]" :class="{on: tab === t[0]}" @click="tab = t[0]">{{ t[1] }} ({{ count(t[0]) }})</button></div>
    <div class="card"><div class="table-wrap"><table>
      <thead><tr><th style="width:42%">Результат</th><th>Вид</th><th>Раздел</th><th>Статус</th><th>Что дальше</th></tr></thead>
      <tbody><tr v-for="i in rows" :key="i.id">
        <td><button class="link" @click="S.drawerId = i.id">{{ i.title }}</button><div class="small muted">{{ i.year }}<template v-if="i.origin === 'works'"> · из «Научных работ»</template></div><div v-if="i.return_note" class="small lv-warn"><i class="pi pi-comment"></i> {{ i.return_note }}</div></td>
        <td class="small">{{ i.index ? S.boot.labels.index[i.index] : i.type_label }}</td>
        <td class="nowrap"><span v-for="s in i.sections" :key="s" class="section-badge">{{ s }}</span></td>
        <td><Tag :status="i.status"/><div class="small muted" style="margin-top:3px">{{ i.stage }}<template v-if="i.days && !i.in_report">, {{ i.days }} дн.</template></div></td>
        <td class="small">
          <template v-if="i.can_submit && i.missing.length"><span class="lv-warn">Не хватает: {{ i.missing.join(', ') }}</span><br><button class="link small" @click="S.drawerId = i.id">Дополнить</button></template>
          <template v-else-if="i.can_submit"><div v-if="i.evidence_need.length && !i.has_evidence" class="muted" style="margin-bottom:4px">Приложите: {{ i.evidence_need.join(', ') }}</div><button class="btn sm primary" @click="send(i)"><i class="pi pi-send"></i> Отправить</button> <button class="btn sm" @click="S.drawerId = i.id">Открыть</button></template>
          <template v-else-if="i.in_report"><span style="color:var(--good)"><i class="pi pi-check"></i> В отчёте</span><div v-if="i.needs_confirm" style="margin-top:4px"><button class="btn sm" @click="confirmOwn(i)"><i class="pi pi-check"></i> Да, это моя запись</button></div></template>
          <template v-else><span class="muted">Ждём решения</span></template>
        </td></tr></tbody>
    </table></div><div v-if="!rows.length" class="empty">Здесь пока пусто.</div></div>
    <div class="notice" v-if="data.others" style="margin-top:12px"><i class="pi pi-info-circle"></i> В «Научных работах» есть ещё записи, которые в отчёт за {{ data.year }} год не входят: <b>{{ data.others }}</b> (другой год, учебники, патенты). <button class="link" @click="openWorks">Открыть</button></div>
  </div>`,
};

/* Келісушінің кезегі. */
const Approvals = {
  components: { Tag },
  setup() {
    const { data, load } = useLoad(() => api('/api/approvals'));
    const returning = ref(null);
    const note = ref('');
    const clean = computed(() => (data.value ? data.value.items.filter((i) => i.precheck.level === 'ok') : []));
    const approve = async (i) => { await api(`/api/records/${i.id}/approve`, { method: 'POST', body: {} }); toast('Согласовано'); bump(); };
    const bulk = async () => { const r = await api('/api/approvals/bulk', { method: 'POST', body: { ids: clean.value.map((i) => i.id) } }); toast(`Согласовано записей: ${r.approved}`); bump(); };
    const sendBack = async (i) => {
      await api(`/api/records/${i.id}/return`, { method: 'POST', body: { note: note.value } });
      toast('Возвращено автору');
      returning.value = null;
      note.value = '';
      bump();
    };
    const LEVEL = { ok: ['Замечаний нет', 'good'], warn: ['Посмотреть', 'warn'], error: ['Есть ошибки', 'bad'] };
    return { S, data, load, returning, note, clean, approve, bulk, sendBack, LEVEL };
  },
  template: `<div v-if="data">
    <div class="page-title"><h1>На согласовании</h1><p>Система заранее проверила каждую запись. Записи без замечаний можно согласовать одним нажатием, внимание нужно только остальным.</p></div>
    <div class="tiles"><div class="tile"><div class="label">Ждут решения</div><div class="value">{{ data.items.length }}</div></div>
      <div class="tile"><div class="label">Без замечаний</div><div class="value">{{ clean.length }}</div></div>
      <div class="tile"><div class="label">Нужно посмотреть</div><div class="value">{{ data.items.length - clean.length }}</div></div></div>
    <div class="card">
      <div class="card-head" v-if="clean.length"><span class="spacer"></span><button class="btn primary sm" @click="bulk"><i class="pi pi-check-square"></i> Согласовать без замечаний ({{ clean.length }})</button></div>
      <div v-for="i in data.items" :key="i.id" class="appr">
        <div class="appr-main"><button class="link" @click="S.drawerId = i.id">{{ i.title }}</button>
          <div class="small muted">{{ i.authors.join(', ') }}<span v-if="i.authors_more"> +{{ i.authors_more }}</span> · {{ i.index ? S.boot.labels.index[i.index] : i.type_label }} · {{ i.year }} · <span v-for="s in i.sections" :key="s" class="section-badge">{{ s }}</span> · ждёт {{ i.days }} дн.</div>
          <div class="appr-check"><span class="tag" :class="LEVEL[i.precheck.level][1]">{{ LEVEL[i.precheck.level][0] }}</span>
            <span v-for="g in i.precheck.good" :key="g" class="small muted"><i class="pi pi-check"></i> {{ g }}</span></div>
          <div v-for="r in i.precheck.reasons" :key="r.text" class="small" :class="'lv-' + r.level"><i class="pi pi-exclamation-circle"></i> {{ r.text }}</div>
          <div v-if="i.on_behalf" class="small muted"><i class="pi pi-info-circle"></i> Запись ждёт научного руководителя. Вы можете согласовать за него.</div>
          <div v-if="returning === i.id" class="appr-return"><input class="inp" v-model="note" placeholder="Что нужно исправить"><button class="btn sm danger" :disabled="!note.trim()" @click="sendBack(i)">Вернуть</button><button class="btn sm" @click="returning = null">Отмена</button></div>
        </div>
        <div class="appr-act"><button class="btn sm primary" @click="approve(i)"><i class="pi pi-check"></i> Согласовать</button><button class="btn sm" @click="returning = i.id; note = ''"><i class="pi pi-undo"></i> Вернуть</button></div>
      </div>
      <div v-if="!data.items.length" class="empty"><i class="pi pi-check-circle" style="color:var(--good)"></i> Всё согласовано, очередь пуста.</div>
    </div>
  </div>`,
};

/* Науқан: кім не істеуі керек және есеп қашан дайын болады. */
const Campaign = {
  components: { Tag, ChartCard, HBars },
  setup() {
    const { data, load } = useLoad(() => api('/api/campaign'));
    const deadline = ref('');
    watch(data, (d) => { if (d && d.campaign) deadline.value = d.campaign.deadline; });
    const remind = async (body) => { const r = await api('/api/campaign/remind', { method: 'POST', body }); toast(`Напоминаний отправлено: ${r.sent}`); };
    const remindAll = async () => { const r = await api('/api/campaign/remind-all', { method: 'POST' }); toast(`Отправлено: авторам ${r.authors}, согласующим ${r.approvers}, ответственному ${r.responsible}`); };
    const saveDeadline = async () => { await api('/api/campaign', { method: 'PUT', body: { year: 2025, deadline: deadline.value, title: 'Отчёт НИР за 2025 год' } }); toast('Срок сохранён'); await load(); };
    const stages = computed(() => (data.value ? data.value.funnel.stages.map((s) => ({ label: s.label, values: { value: s.value } })) : []));
    const percent = computed(() => (data.value && data.value.funnel.total ? Math.round(data.value.funnel.approved * 100 / data.value.funnel.total) : 0));
    return { data, deadline, remind, remindAll, saveDeadline, can, ROLE_NAME, stages, percent };
  },
  template: `<div v-if="data">
    <div class="page-title"><h1>Кампания отчётности</h1><p>Кто сдал, кто задерживает и кому нужно напомнить. Письма писать не нужно: система напоминает каждому о его части работы.</p></div>
    <div class="card"><div class="card-body" style="display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap">
      <div><div class="small muted">Кампания</div><b>{{ data.campaign.title }}</b></div>
      <label class="f" style="margin-left:18px">Срок<input class="inp" type="date" v-model="deadline" :disabled="!can('science')"></label>
      <button v-if="can('science')" class="btn sm" @click="saveDeadline">Сохранить</button>
      <div v-if="data.days_left >= 0" class="small muted">Осталось дней: <b>{{ data.days_left }}</b></div>
      <span class="spacer"></span>
      <div style="text-align:right"><button class="btn primary sm" @click="remindAll"><i class="pi pi-bell"></i> Напомнить всем по этапам</button>
        <div class="small muted" style="margin-top:4px">Автоматически за {{ data.schedule.filter(d => d > 0).join(', ') }} дн. и в день срока</div></div>
    </div></div>
    <div class="tiles" style="margin-top:14px">
      <div class="tile"><div class="label">Кафедра Менеджмент: готово</div><div class="value">{{ percent }}%</div><div class="delta">{{ data.funnel.approved }} из {{ data.funnel.total }} записей</div></div>
      <div class="tile"><div class="label">Пока не войдут в отчёт</div><div class="value">{{ data.funnel.not_included }}</div></div>
      <div class="tile"><div class="label">Авторы подтвердили свой список</div><div class="value">{{ data.attested }}</div><div class="delta">из {{ data.authors }}</div></div>
      <div class="tile"><div class="label">Дольше всего ждёт согласования</div><div class="value">{{ data.funnel.longest_wait }}</div><div class="delta">дней</div></div>
    </div>
    <ChartCard title="Где сейчас записи кафедры" sub="Кафедра Менеджмент, 2025 год" :table="{cols: ['Этап', 'Записей'], rows: data.funnel.stages.map(s => [s.label, s.value])}"><HBars :rows="stages" :series="[{key: 'value', label: 'Записей'}]" :label-width="190"/></ChartCard>
    <div class="card" style="margin-top:14px"><div class="card-head"><h2>Кафедры Высшей школы экономики и туризма</h2></div><div class="table-wrap"><table>
      <thead><tr><th>Кафедра</th><th style="width:34%">Подтверждённые записи</th><th>Отчёт</th><th></th></tr></thead>
      <tbody><tr v-for="u in data.units" :key="u.id"><td><b>{{ u.name }}</b></td>
        <td><div class="bar-track" :title="u.done + ' / ' + u.total"><div class="bar-fill" :style="{width: u.percent+'%'}"></div></div><span class="small muted">{{ u.done }} / {{ u.total }} ({{ u.percent }}%)</span></td>
        <td><Tag :status="u.status"/></td><td class="nowrap"><button class="btn sm" @click="remind({unit: u.id})"><i class="pi pi-bell"></i> Напомнить</button></td></tr></tbody></table></div>
      <div class="small muted" style="padding:8px 14px">Показатели других кафедр условные.</div></div>
    <div class="card" v-if="data.pending.length"><div class="card-head"><h2>Менеджмент: кто ещё должен действовать</h2></div>
      <div class="table-wrap"><table><thead><tr><th>Ф.И.О.</th><th>Статус</th><th class="num">Записей</th><th></th></tr></thead>
        <tbody><tr v-for="p in data.pending.slice(0,25)" :key="p.id"><td>{{ p.name }}</td><td class="small">{{ ROLE_NAME[p.role] }}</td><td class="num">{{ p.count }}</td><td class="nowrap"><button class="btn sm" @click="remind({person: p.id})">Напомнить</button></td></tr></tbody></table></div></div>
  </div>`,
};

/* Басшылық пен жауаптыға арналған шолу. */
const ManagerOverview = {
  components: { IssueLine, ChartCard, HBars },
  setup() {
    const { data } = useLoad(async () => {
      const [home, campaign] = await Promise.all([api('/api/home'), api('/api/campaign')]);
      return { home, campaign };
    });
    const now = new Date();
    const WEEK = ['Воскресенье', 'Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота'];
    const MONTH = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
    const today = `${WEEK[now.getDay()]}, ${now.getDate()} ${MONTH[now.getMonth()]}`;
    const stages = computed(() => (data.value ? data.value.campaign.funnel.stages.map((s) => ({ label: s.label, values: { value: s.value } })) : []));
    return { S, data, today, go, stages };
  },
  template: `<div v-if="data">
    <div class="hello"><div><h1>Добрый день</h1><div class="muted">{{ today }}</div></div></div>
    <div class="card">
      <div class="card-head"><div><h2>Требует внимания</h2><div class="muted small">Что нужно сделать сейчас</div></div></div>
      <button v-for="t in data.home.tasks" :key="t.title" class="task" @click="go(t.link)">
        <span class="ic"><i class="fa-solid" :class="t.icon"></i></span>
        <span><b>{{ t.title }}</b><span class="muted small">{{ t.text }}</span></span>
        <span v-if="t.count !== null" class="pill">{{ t.count }}</span>
        <i class="pi pi-angle-right faint" :style="t.count === null ? 'margin-left:auto' : ''"></i>
      </button>
      <div v-if="!data.home.tasks.length" class="empty">Сейчас задач нет.</div>
    </div>
    <div class="grid-2" style="margin-top:14px">
      <ChartCard title="Где сейчас записи" sub="Кафедра Менеджмент, 2025 год"><HBars :rows="stages" :series="[{key: 'value', label: 'Записей'}]" :label-width="180"/></ChartCard>
      <div class="card" v-if="data.home.notifications.length"><div class="card-head"><h2>Последние уведомления</h2></div>
        <div class="card-body" style="padding-top:4px"><div v-for="n in data.home.notifications" :key="n.id" class="issue"><i class="pi pi-bell faint"></i><div>{{ n.text }}<div class="small faint">{{ n.at.replace('T',' ').slice(0,16) }}</div></div></div></div></div>
    </div>
  </div>`,
};

const Overview = {
  components: { MyResults, ManagerOverview },
  setup() { return { can }; },
  template: `<MyResults v-if="can('author','supervisor')"/><ManagerOverview v-else/>`,
};

/* «Как это работает»: процесс және ЖИ-дің орны. */
const HowItWorks = {
  setup() {
    const YEAR = [
      { who: 'Автор', roles: ['author', 'supervisor', 'responsible', 'head'], title: 'Вносит публикацию в «Научные работы»', where: 'Научная деятельность → Научные работы', text: 'Это уже существующая функция Smart.ENU: форма, импорт из Platonus и Scopus. В модуль публикацию повторно вносить не нужно.', ai: 'В чате читает PDF и ссылку, заполняет карточку и сохраняет её на эту страницу.' },
      { who: 'Система', roles: [], title: 'Модуль сам забирает работу', where: 'Мои результаты', text: 'Работа появляется в списке автора. Система определяет раздел формы Ф ЕНУ 605-02-25 и показывает, чего не хватает: индекса, страниц, места проведения.', ai: 'Определяет индекс по ISSN и спискам журналов, находит соавторов в справочнике. Поиск по ORCID предлагает то, что ещё не внесено.' },
      { who: 'Автор', roles: ['author', 'supervisor', 'responsible', 'head'], title: 'Вносит то, чего нет в «Научных работах»', where: 'Мои результаты', text: 'Награды, призовые места, стипендии и гранты, редколлегии, проекты: на странице «Научные работы» таких типов нет.', ai: 'Читает фото диплома, грамоту или приказ и заполняет карточку.' },
      { who: 'Автор', roles: ['author', 'supervisor', 'responsible', 'head'], title: 'Дополняет и отправляет на согласование', where: 'Мои результаты → Отправить', text: 'Дополняет то, что требует форма. Прикладывает скриншот, диплом или титул, если они нужны.', auto: 'Система сверяет поля с Crossref и самим документом, показывает расхождения, дубли, журнал из списка риска и чего не хватает.' },
      { who: 'Научный руководитель', roles: ['supervisor'], title: 'Согласует работы своих обучающихся', where: 'На согласовании', text: 'Только для студентов, магистрантов и докторантов. Согласует или возвращает с комментарием. Статья преподавателя этот шаг пропускает.', auto: 'Система заранее показывает, какие записи без замечаний, а на какие нужно посмотреть и почему.' },
      { who: 'Заведующий кафедрой', roles: ['head'], title: 'Утверждает запись для кафедры', where: 'На согласовании', text: 'Записи без замечаний согласует одним нажатием. Если руководитель не отвечает, может согласовать за него. Свою работу отправляет директору.', auto: 'Та же проверка: разбирать нужно только записи с замечаниями.' },
      { who: 'Система', roles: [], title: 'Запись попадает в базу кафедры', where: 'Аналитика, Отчёт НИР', text: 'Статус «согласовано». Запись сразу видна в аналитике и в отчёте. Чтобы её изменить, автор открывает её снова, и она заново проходит согласование.', ai: null },
    ];
    const END = [
      { who: 'Департамент науки', roles: ['science'], title: 'Открывает кампанию и задаёт срок', where: 'Кампания', text: 'Срок один для всех кафедр. Перечень собирать не нужно, он уже есть в базе.', ai: null },
      { who: 'Система', roles: [], title: 'Напоминает каждому о его части', where: 'Уведомления', text: 'За 14, 7, 3 и 1 день и в день срока. Автору о неотправленных записях, согласующим об их очереди, ответственному о перечне.', ai: 'В чате отвечает, кто задерживает и что осталось сделать.' },
      { who: 'Автор', roles: ['author', 'supervisor'], title: 'Сверяет свой список за год', where: 'Мои результаты → Мой список верен', text: 'Видит, что войдёт в отчёт, дополняет пропущенное.', ai: 'Отвечает в чате: что у меня не отправлено, где сейчас статья.' },
      { who: 'Ответственный по научной работе', roles: ['responsible'], title: 'Проверяет перечень кафедры', where: 'Очередь проверки, Отчёт НИР', text: 'Видит ошибки, дубли и записи, не вошедшие в отчёт. Исправляет и отправляет отчёт на согласование.', auto: 'Система находит ошибки и дубли, предлагает исправить раздел и объединить повторы.', ai: 'Готовит черновик аналитической справки и отвечает на вопросы о перечне.' },
      { who: 'Заведующий кафедрой', roles: ['head'], title: 'Согласует отчёт', where: 'Отчёт НИР', text: 'Указывает номер и дату протокола заседания кафедры.', auto: 'Итоговая страница показывает показатели рядом с прошлым годом.' },
      { who: 'Директор', roles: ['director'], title: 'Подписывает отчёт', where: 'Отчёт НИР', text: 'Сохраняется неизменяемая версия и файл Excel по форме Ф ЕНУ 605-02-25.', ai: 'Отвечает на вопросы по показателям, сравнивает кафедры диаграммой.' },
      { who: 'Департамент науки', roles: ['science'], title: 'Принимает отчёт или возвращает', where: 'Отчёт НИР, Кампания', text: 'Видит все подразделения в одной сводке.', ai: 'Строит сводку и диаграммы по запросу.' },
    ];
    const role = computed(() => S.boot.position.role);
    const mine = (s) => s.roles.includes(role.value);
    return { YEAR, END, mine };
  },
  template: `<div>
    <div class="page-title"><h1>Как это работает</h1><p>Шаги вашей должности выделены. ИИ читает и заполняет, система проверяет по правилам, а решение всегда принимает человек: сам ИИ ничего не сохраняет.</p></div>
    <h2 class="how-lane">Весь год: каждый результат</h2>
    <div class="how"><div v-for="(s,i) in YEAR" :key="s.title" class="how-step" :class="{mine: mine(s)}"><div class="how-num">{{ i + 1 }}</div><div class="how-body">
      <div class="how-who">{{ s.who }}</div><b>{{ s.title }}</b><div class="small muted how-where"><i class="pi pi-map-marker"></i> {{ s.where }}</div><div class="small">{{ s.text }}</div>
      <div v-if="s.ai" class="how-ai"><i class="fa-solid fa-robot"></i> {{ s.ai }}</div><div v-if="s.auto" class="how-auto"><i class="pi pi-verified"></i> {{ s.auto }}</div></div></div></div>
    <h2 class="how-lane">Конец года: отчёт НИР</h2>
    <div class="how"><div v-for="(s,i) in END" :key="s.title" class="how-step" :class="{mine: mine(s)}"><div class="how-num">{{ YEAR.length + i + 1 }}</div><div class="how-body">
      <div class="how-who">{{ s.who }}</div><b>{{ s.title }}</b><div class="small muted how-where"><i class="pi pi-map-marker"></i> {{ s.where }}</div><div class="small">{{ s.text }}</div>
      <div v-if="s.ai" class="how-ai"><i class="fa-solid fa-robot"></i> {{ s.ai }}</div><div v-if="s.auto" class="how-auto"><i class="pi pi-verified"></i> {{ s.auto }}</div></div></div></div>
  </div>`,
};
