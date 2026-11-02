/* Аналитика беттері: кафедра, факультет және университет деңгейі диаграммамен. */
const DeptOverview = {
  components: { ChartCard, HBars, YearBars, ShareBar, PlanBars },
  props: ['unit'],
  setup(p) {
    const { data } = useLoad(async () => {
      const [overview, teachers, supervision, plan] = await Promise.all([
        api(`/api/analytics/overview?unit=${p.unit}`), api(`/api/analytics/teachers?unit=${p.unit}`),
        api(`/api/analytics/supervision?unit=${p.unit}`), api(`/api/analytics/plan?unit=${p.unit}`),
      ]);
      return { overview, teachers, supervision, plan };
    });
    const delta = (c) => {
      if (c.prev === null || c.prev === undefined) return '';
      if (c.pps !== undefined) return `Преподаватели: ${c.pps}, в прошлом году ${c.prev}`;
      return `В прошлом году ${c.prev}`;
    };
    const years = computed(() => (data.value ? data.value.overview.cards.filter((c) => c.prev !== null && c.prev !== undefined).map((c) => ({ label: c.label, prev: c.prev, cur: c.pps !== undefined ? c.pps : c.value })) : []));
    const roles = computed(() => (data.value ? data.value.overview.by_role.map((r) => ({ label: r.role, value: r.value })) : []));
    const types = computed(() => (data.value ? data.value.overview.by_type.map((t) => ({ label: S.boot.types[t.type].label, values: { value: t.value } })).sort((a, b) => b.values.value - a.values.value) : []));
    const TEACHER_SERIES = [{ key: 'scopus', label: 'Scopus' }, { key: 'wos', label: 'WoS' }, { key: 'koksnvo', label: 'КОКСНВО' }, { key: 'conference', label: 'Конференции' }, { key: 'monograph', label: 'Монографии' }];
    const SUP_SERIES = [{ key: 'students', label: 'Студенты' }, { key: 'masters', label: 'Магистранты' }, { key: 'doctorals', label: 'Докторанты' }];
    const legendOf = (series) => series.map((s, i) => ({ label: s.label, color: SERIES_COLORS[i] }));
    const top = computed(() => (data.value ? [...data.value.teachers.items].sort((a, b) => b.total - a.total).slice(0, 10).map((t) => ({ label: t.name, values: t })) : []));
    const sup = computed(() => (data.value ? data.value.supervision.groups.filter((g) => !g.external).slice(0, 10).map((g) => ({ label: g.supervisor, values: g })) : []));
    const tableOf = (rows, series) => ({ cols: ['', ...series.map((s) => s.label), 'Всего'], rows: rows.map((r) => [r.label, ...series.map((s) => r.values[s.key] || 0), series.reduce((n, s) => n + (Number(r.values[s.key]) || 0), 0)]) });
    return { data, delta, years, roles, types, top, sup, TEACHER_SERIES, SUP_SERIES, legendOf, tableOf, PREV_COLOR, SERIES_COLORS };
  },
  template: `<div v-if="data">
    <div class="tiles"><div v-for="c in data.overview.cards" :key="c.key" class="tile"><div class="label">{{ c.label }}</div><div class="value">{{ c.value }}</div><div class="delta">{{ delta(c) }}</div></div></div>
    <div class="notice" v-if="data.overview.rows_total !== data.overview.rows_unique"><b>{{ data.overview.rows_total }}</b> исходных строк объединены в <b>{{ data.overview.rows_unique }}</b> записей, поэтому числа уточнены.</div>
    <div class="grid-2">
      <ChartCard title="Прошлый и отчётный год" sub="Публикации преподавателей по показателям формы" :legend="[{label: '2024', color: PREV_COLOR}, {label: '2025', color: SERIES_COLORS[0]}]" :table="{cols: ['Показатель', '2024', '2025'], rows: years.map(r => [r.label, r.prev, r.cur])}"><YearBars :rows="years" prev-label="2024" cur-label="2025"/></ChartCard>
      <ChartCard title="Кто публикуется" sub="Публикации по категориям авторов" :table="{cols: ['Категория', 'Записей'], rows: roles.map(r => [r.label, r.value])}"><ShareBar :items="roles"/></ChartCard>
      <ChartCard title="Преподаватели" sub="10 авторов с наибольшим числом публикаций" :legend="legendOf(TEACHER_SERIES)" :table="tableOf(top, TEACHER_SERIES)"><HBars :rows="top" :series="TEACHER_SERIES"/></ChartCard>
      <ChartCard title="Научное руководство" sub="Подопечные по уровням обучения" :legend="legendOf(SUP_SERIES)" :table="tableOf(sup, SUP_SERIES)"><HBars :rows="sup" :series="SUP_SERIES"/></ChartCard>
      <ChartCard title="Виды записей" sub="Все результаты 2025 года" :table="{cols: ['Вид', 'Записей'], rows: types.map(t => [t.label, t.values.value])}"><HBars :rows="types" :series="[{key: 'value', label: 'Записей'}]"/></ChartCard>
      <ChartCard title="Выполнение плана" sub="Факт относительно плановых значений" note="Плановые значения условные." :table="{cols: ['Показатель', 'План', 'Факт', '%'], rows: data.plan.items.map(i => [i.label, i.plan, i.fact, i.percent])}"><PlanBars :rows="data.plan.items"/></ChartCard>
    </div>
  </div>`,
};
const Teachers = {
  components: { ChartCard, HBars },
  props: ['unit'],
  setup(p) {
    const { data } = useLoad(() => api(`/api/analytics/teachers?unit=${p.unit}`));
    const SERIES = [{ key: 'students', label: 'Студенты' }, { key: 'masters', label: 'Магистранты' }, { key: 'doctorals', label: 'Докторанты' }];
    return { data, SERIES };
  },
  template: `<div class="card" v-if="data"><div class="card-head"><div class="small muted">Показаны преподаватели с записями в отчёте за 2025 год: {{ data.items.length }}. В открытом списке кафедры на портале: {{ data.portal_total }}. Учёные степени взяты с этих страниц.</div></div><div class="table-wrap"><table>
    <thead><tr><th>Преподаватель</th><th>Степень</th><th class="num">Scopus</th><th class="num">WoS</th><th class="num">КОКСНВО</th><th class="num">Конф.</th><th class="num">Моногр.</th><th class="num">Студенты</th><th class="num">Магистранты</th><th class="num">Докторанты</th><th class="num">Публикации подопечных</th><th class="num">Всего</th></tr></thead>
    <tbody><tr v-for="t in data.items" :key="t.id"><td><b>{{ t.name }}</b><div v-if="t.unconfirmed" class="small lv-warn">не подтверждено: {{ t.unconfirmed }}</div></td><td class="small">{{ t.degree }}</td><td class="num">{{ t.scopus }}</td><td class="num">{{ t.wos }}</td><td class="num">{{ t.koksnvo }}</td><td class="num">{{ t.conference }}</td><td class="num">{{ t.monograph }}</td><td class="num">{{ t.students }}</td><td class="num">{{ t.masters }}</td><td class="num">{{ t.doctorals }}</td><td class="num">{{ t.learner_pubs }}</td><td class="num"><b>{{ t.total }}</b></td></tr></tbody>
  </table></div></div>`,
};
const Supervision = {
  components: { ChartCard, HBars },
  props: ['unit'],
  setup(p) {
    const { data } = useLoad(() => api(`/api/analytics/supervision?unit=${p.unit}`));
    const open = ref({});
    const SERIES = [{ key: 'students', label: 'Студенты' }, { key: 'masters', label: 'Магистранты' }, { key: 'doctorals', label: 'Докторанты' }];
    const legend = SERIES.map((s, i) => ({ label: s.label, color: SERIES_COLORS[i] }));
    const rows = computed(() => (data.value ? data.value.groups.map((g) => ({ label: g.supervisor, values: g })) : []));
    return { data, open, ROLE_NAME, SERIES, legend, rows };
  },
  template: `<div v-if="data">
    <div class="tiles"><div class="tile"><div class="label">Обучающихся с руководителем</div><div class="value">{{ data.linked }}</div></div>
      <div class="tile"><div class="label">Руководитель не указан в отчёте</div><div class="value">{{ data.missing.length }}</div></div>
      <div class="tile"><div class="label">Научные руководители</div><div class="value">{{ data.groups.filter(g => !g.external).length }}</div></div></div>
    <ChartCard v-if="rows.length > 1" title="Нагрузка научных руководителей" sub="Подопечные по уровням обучения" :legend="legend" style="margin-bottom:14px"><HBars :rows="rows" :series="SERIES"/></ChartCard>
    <div class="card">
      <div v-for="g in data.groups" :key="g.supervisor_id" class="acc">
        <button class="acc-head" @click="open[g.supervisor_id] = !open[g.supervisor_id]">
          <i class="pi small faint" :class="open[g.supervisor_id] ? 'pi-chevron-down' : 'pi-chevron-right'"></i><b>{{ g.supervisor }}</b>
          <span v-if="g.external" class="tag">зарубежный консультант</span>
          <span class="small muted">студенты {{ g.students }} · магистранты {{ g.masters }} · докторанты {{ g.doctorals }}</span>
          <span class="small muted" style="margin-left:auto">записей: {{ g.pubs }}</span></button>
        <div v-if="open[g.supervisor_id]" class="table-wrap" style="padding:0 14px 10px"><table>
          <thead><tr><th>Обучающийся</th><th>Уровень</th><th>Группа</th><th class="num">Scopus, WoS</th><th class="num">КОКСНВО</th><th class="num">Конф.</th><th class="num">Призовые места</th></tr></thead>
          <tbody><tr v-for="l in g.learners" :key="l.learner_id + l.kind"><td>{{ l.learner }}</td><td class="small">{{ ROLE_NAME[l.level] }}</td><td class="small">{{ l.group }}</td><td class="num">{{ l.scopus }}</td><td class="num">{{ l.koksnvo }}</td><td class="num">{{ l.conference }}</td><td class="num">{{ l.prizes }}</td></tr></tbody>
        </table></div>
      </div>
      <div v-if="!data.groups.length" class="empty">Данных о научном руководстве нет.</div>
    </div>
    <p class="small muted">Связи взяты из записей «Научный руководитель» в отчёте за 2025 год, поэтому список неполный. При внедрении эти данные придут из Smart.ENU или Platonus.</p>
  </div>`,
};
const Plan = {
  components: { PlanBars },
  props: ['unit'],
  setup(p) {
    const { data, load } = useLoad(() => api(`/api/analytics/plan?unit=${p.unit}`));
    const edit = ref(false);
    const values = reactive({});
    watch(data, (d) => { if (d) d.items.forEach((i) => { values[i.key] = i.plan; }); });
    const save = async () => { await api('/api/analytics/plan', { method: 'PUT', body: values }); edit.value = false; toast('План сохранён'); await load(); };
    return { data, edit, values, save, can };
  },
  template: `<div class="card" v-if="data">
    <div class="card-head"><div><h2>План и факт</h2><div class="small muted">Плановые значения условные, их задаёт заведующий кафедрой.</div></div><span class="spacer"></span><button v-if="can('head','director')" class="btn sm" @click="edit ? save() : edit = true">{{ edit ? 'Сохранить' : 'Изменить план' }}</button></div>
    <div class="card-body" v-if="!edit"><PlanBars :rows="data.items"/></div>
    <div class="table-wrap" v-else><table>
      <thead><tr><th>Показатель</th><th class="num">План</th><th class="num">Факт</th></tr></thead>
      <tbody><tr v-for="i in data.items" :key="i.key"><td>{{ i.label }}</td><td class="num"><input class="inp" style="width:70px;display:inline;margin:0" type="number" v-model.number="values[i.key]"></td><td class="num">{{ i.fact }}</td></tr></tbody>
    </table></div></div>`,
};
const Risks = {
  setup() {
    const { data } = useLoad(() => api('/api/analytics/risks'));
    return { data };
  },
  template: `<div v-if="data">
    <div class="card"><div class="card-head"><h2>Готовность докторантов</h2></div>
      <div class="card-body small muted" style="padding-bottom:0">{{ data.requirements.note }} Сейчас: Scopus или WoS {{ data.requirements.scopus_or_wos }}, КОКСНВО {{ data.requirements.koksnvo }}, конференции {{ data.requirements.conference }}. Требования условные, а данные только за один год, поэтому имена других докторантов скрыты.</div>
      <div class="table-wrap"><table>
        <thead><tr><th>Докторант</th><th>Руководитель</th><th class="num">Scopus, WoS</th><th class="num">КОКСНВО</th><th class="num">Конф.</th><th>Состояние</th></tr></thead>
        <tbody><tr v-for="d in data.doctoral" :key="d.id"><td><b>{{ d.name }}</b></td><td class="small">{{ d.supervisors.join(', ') || '–' }}</td><td class="num">{{ d.have.scopus_or_wos }}</td><td class="num">{{ d.have.koksnvo }}</td><td class="num">{{ d.have.conference }}</td>
          <td><span v-if="d.ready" class="tag good"><i class="pi pi-check"></i> достаточно</span><span v-else class="tag warn"><i class="pi pi-exclamation-triangle"></i> не хватает: <template v-if="d.gaps.scopus_or_wos"> Scopus {{ d.gaps.scopus_or_wos }}</template><template v-if="d.gaps.koksnvo"> КОКСНВО {{ d.gaps.koksnvo }}</template><template v-if="d.gaps.conference"> конф. {{ d.gaps.conference }}</template></span></td></tr></tbody>
      </table></div><div v-if="!data.doctoral.length" class="empty">Докторантов нет.</div></div>
    <div class="card"><div class="card-head"><h2>Риски по журналам</h2></div><div class="card-body">
      <div v-for="j in data.journals" :key="j.id" class="issue"><i class="pi pi-times-circle lv-error"></i><div>{{ j.title }}<div class="small muted">{{ j.source }}: {{ j.reason }}</div></div></div>
      <div v-if="!data.journals.length" class="muted">Публикаций в журналах из списка не найдено. Список ведёт Департамент науки, журналов в нём: {{ data.watchlist.length }}.</div>
    </div></div>
  </div>`,
};
const Compare = {
  props: ['parent'],
  emits: ['open'],
  components: { Tag, ChartCard, HBars },
  setup(p) {
    const { data, load } = useLoad(() => api(`/api/analytics/compare?parent=${p.parent}`));
    watch(() => p.parent, load);
    const remind = async (unit) => { const r = await api('/api/campaign/remind', { method: 'POST', body: { unit } }); toast(`Напоминаний отправлено: ${r.sent}`); };
    const SERIES = [{ key: 'scopus', label: 'Scopus' }, { key: 'wos', label: 'WoS' }, { key: 'koksnvo', label: 'КОКСНВО' }];
    const SERIES2 = [{ key: 'conference', label: 'Конференции' }, { key: 'monograph', label: 'Монографии' }, { key: 'learner_pubs', label: 'Обучающиеся' }];
    const rows = computed(() => (data.value ? data.value.rows.map((r) => ({ label: r.name, values: r })) : []));
    const legendOf = (series) => series.map((s, i) => ({ label: s.label, color: SERIES_COLORS[i] }));
    const tableOf = (series) => ({ cols: ['Подразделение', ...series.map((s) => s.label)], rows: data.value.rows.map((r) => [r.name, ...series.map((s) => r[s.key])]) });
    return { data, dl, remind, S, SERIES, SERIES2, rows, legendOf, tableOf };
  },
  template: `<div v-if="data">
    <div class="tiles">
      <div class="tile"><div class="label">Scopus</div><div class="value">{{ data.total.scopus }}</div><div class="delta" v-if="data.shared">сумма {{ data.summed.scopus }}, совместные статьи ({{ data.shared }}) учтены один раз</div></div>
      <div class="tile"><div class="label">Web of Science</div><div class="value">{{ data.total.wos }}</div></div>
      <div class="tile"><div class="label">КОКСНВО</div><div class="value">{{ data.total.koksnvo }}</div></div>
      <div class="tile"><div class="label">Конференции</div><div class="value">{{ data.total.conference }}</div></div>
      <div class="tile"><div class="label">Монографии</div><div class="value">{{ data.total.monograph }}</div></div>
      <div class="tile"><div class="label">Публикации обучающихся</div><div class="value">{{ data.total.learner_pubs }}</div></div>
    </div>
    <div class="notice" v-if="data.facts">С сайта: преподавателей {{ data.facts.teachers }}, из них докторов наук {{ data.facts.doctors }}, кандидатов наук {{ data.facts.candidates }}, PhD {{ data.facts.phd }}. Остепенённость {{ Math.round(data.facts.degree_share * 100) }}%, научных проектов {{ data.facts.projects }}.</div>
    <div class="grid-2">
      <ChartCard title="Статьи по индексам" :sub="data.parent_name" :legend="legendOf(SERIES)" :table="tableOf(SERIES)" note="Показатели подразделений, кроме кафедры Менеджмент, условные."><HBars :rows="rows" :series="SERIES" :label-width="210"/></ChartCard>
      <ChartCard title="Другие результаты" :sub="data.parent_name" :legend="legendOf(SERIES2)" :table="tableOf(SERIES2)" note="Показатели подразделений, кроме кафедры Менеджмент, условные."><HBars :rows="rows" :series="SERIES2" :label-width="210"/></ChartCard>
    </div>
    <div class="card" style="margin-top:14px"><div class="card-head"><h2>{{ data.parent_name }}: подразделения</h2><span class="spacer"></span><button class="btn sm" @click="dl('/api/export/summary/' + data.parent + '/2025')"><i class="pi pi-file-excel"></i> Сводная в Excel</button></div>
      <div class="table-wrap"><table>
        <thead><tr><th>Подразделение</th><th class="num">Scopus</th><th class="num">WoS</th><th class="num">КОКСНВО</th><th class="num">Конф.</th><th class="num">Моногр.</th><th class="num">Обучающиеся</th><th class="num">Призёры</th><th v-if="data.rows.some(r => r.status)">Отчёт</th><th></th></tr></thead>
        <tbody><tr v-for="r in data.rows" :key="r.id">
          <td><button class="link" v-if="r.id === 'mgmt' || r.has_children" @click="$emit('open', r.id)">{{ r.name }}</button><span v-else>{{ r.name }}</span></td>
          <td class="num">{{ r.scopus }}</td><td class="num">{{ r.wos }}</td><td class="num">{{ r.koksnvo }}</td><td class="num">{{ r.conference }}</td><td class="num">{{ r.monograph }}</td><td class="num">{{ r.learner_pubs }}</td><td class="num">{{ r.prizes }}</td>
          <td v-if="data.rows.some(x => x.status)"><Tag v-if="r.status" :status="r.status"/></td>
          <td class="nowrap"><button v-if="r.status && r.status !== 'согласовано'" class="btn sm" @click="remind(r.id)">Напомнить</button></td>
        </tr></tbody></table></div></div>
  </div>`,
};
const Analytics = {
  components: { DeptOverview, Teachers, Supervision, Plan, Risks, Compare },
  setup() {
    const role = computed(() => S.boot.position.role);
    const levels = computed(() => (role.value === 'science' ? ['uni'] : role.value === 'director' ? ['vshet'] : []));
    const crumb = ref([]);
    const scope = computed(() => (crumb.value.length ? crumb.value[crumb.value.length - 1] : levels.value[0] || null));
    const deptUnit = computed(() => (scope.value === 'mgmt' || !levels.value.length ? 'mgmt' : null));
    const tabs = computed(() => {
      if (role.value === 'supervisor') return [['supervision', 'Мои обучающиеся'], ['risks', 'Готовность докторантов']];
      if (role.value === 'author') return [['risks', 'Подготовка к защите']];
      if (!deptUnit.value) return [['compare', 'Подразделения']];
      return [['overview', 'Обзор'], ['teachers', 'Преподаватели'], ['supervision', 'Научное руководство'], ['plan', 'План и факт'], ['risks', 'Риски']];
    });
    const tab = ref(tabs.value[0][0]);
    watch(tabs, (t) => { tab.value = t[0][0]; });
    const open = (id) => { crumb.value = [...crumb.value, id]; };
    const back = () => { crumb.value = crumb.value.slice(0, -1); };
    const title = computed(() => {
      const r = role.value;
      if (deptUnit.value && (r === 'head' || r === 'responsible')) return 'Аналитика кафедры «Менеджмент»';
      if (deptUnit.value && scope.value === 'mgmt') return 'Кафедра «Менеджмент»';
      if (r === 'science' && scope.value === 'uni') return 'Аналитика университета';
      if (scope.value === 'vshet') return 'Высшая школа экономики и туризма';
      return 'Аналитика';
    });
    return { tabs, tab, scope, deptUnit, open, back, crumb, title };
  },
  template: `<div>
    <div class="page-title"><button v-if="crumb.length" class="icon-btn" aria-label="Назад" @click="back"><i class="pi pi-arrow-left"></i></button><h1>{{ title }}</h1><span class="tag">2025 год</span></div>
    <div class="tabs" v-if="tabs.length > 1"><button v-for="t in tabs" :key="t[0]" :class="{on: tab === t[0]}" @click="tab = t[0]">{{ t[1] }}</button></div>
    <Compare v-if="tab === 'compare'" :parent="scope" :key="scope" @open="open"/>
    <DeptOverview v-else-if="tab === 'overview'" :unit="deptUnit"/>
    <Teachers v-else-if="tab === 'teachers'" :unit="deptUnit"/>
    <Supervision v-else-if="tab === 'supervision'" unit="mgmt"/>
    <Plan v-else-if="tab === 'plan'" :unit="deptUnit"/>
    <Risks v-else-if="tab === 'risks'"/>
  </div>`,
};
