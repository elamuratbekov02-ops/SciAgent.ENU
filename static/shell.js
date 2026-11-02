/* Smart.ENU қабығы. Модуль «Научная деятельность» бөлімінің үшінші тармағы, қалған мәзір орнында тұрады. */
const MENU = [
  { label: 'Документы', icon: 'pi pi-fw pi-folder', children: [
    { label: 'Документы с моим участием', icon: 'pi pi-fw pi-file' }, { label: 'Договоры', icon: 'fa-solid fa-file-signature' },
    { label: 'Каталог нормативных документов', icon: 'pi pi-fw pi-folder' }, { label: 'Конструктор учебно-методического комплекса дисциплины', icon: 'pi pi-fw pi-folder' },
    { label: 'Учебно-методический комплекс дисциплины', icon: 'pi pi-fw pi-folder' }, { label: 'Сертификаты', icon: 'fa-solid fa-award' },
    { label: 'Отчеты', icon: 'pi pi-fw pi-chart-line', children: [
      { label: 'Отчет по мониторингу после самооценки и аккредитации', icon: 'pi pi-fw pi-folder' },
      { label: 'Отчеты Государственной аттестационной комиссии', icon: 'pi pi-fw pi-folder' },
      { label: 'Отчеты о прохождении научной стажировки', icon: 'pi pi-fw pi-folder' }] }] },
  { label: 'Bilge', icon: 'fa-solid fa-robot', children: [{ label: 'Bilge Workspace', icon: 'fa-solid fa-comments' }] },
  { label: 'Контрагенты', icon: 'pi pi-fw pi-users', children: [{ label: 'Организации', icon: 'pi pi-fw pi-building' }] },
  { label: 'Новости', icon: 'fa-solid fa-newspaper', children: [{ label: 'Список новостей', icon: 'fa-solid fa-rss' }] },
  { label: 'Мероприятия', icon: 'fa-solid fa-calendar-days' },
  { label: 'Конкурсы', icon: 'fa-solid fa-trophy' },
  { label: 'Научная деятельность', icon: 'fa-solid fa-atom', open: true, children: [
    { label: 'Профиль ученых', icon: 'fa-solid fa-user-tie', page: 'scientists' },
    { label: 'Научные работы', icon: 'fa-solid fa-file-lines', page: 'works' },
    { label: 'Научная отчётность', icon: 'fa-solid fa-chart-column', page: 'module' }] },
  { label: 'Планы', icon: 'fa-solid fa-list-check' },
  { label: 'Для студентов и выпускников', icon: 'fa-solid fa-user-graduate', children: [
    { label: 'Вакансии', icon: 'pi pi-fw pi-user-plus' },
    { label: 'Проектные команды', icon: 'fa-solid fa-people-group', children: [{ label: 'Мои команды', icon: 'pi pi-fw pi-users' }] }] },
  { label: 'Вакансии', icon: 'pi pi-fw pi-user-plus' },
  { label: 'Онлайн курсы', icon: 'fa-solid fa-chalkboard-user', children: [{ label: 'Курсы', icon: 'fa-solid fa-chalkboard' }, { label: 'Мои курсы', icon: 'fa-solid fa-book-open' }] },
  { label: 'Мои заявки', icon: 'fa-solid fa-headset' },
  { label: 'Тестирование', icon: 'fa-solid fa-vial-circle-check', children: [{ label: 'Пройти опросник', icon: 'fa-solid fa-clipboard-list' }] },
];

const USER_MENU = [
  { label: 'Личный кабинет', icon: 'pi-user' }, { label: 'Мои справки', icon: 'pi-file' }, { label: 'Мои финансы', icon: 'pi-wallet' },
  { label: 'QR генератор', icon: 'pi-qrcode' }, { label: 'Сессии', icon: 'pi-desktop' }, { label: 'Проверка подписи документа', icon: 'pi-verified' },
  { label: 'Поменять позицию', icon: 'pi-sync', action: 'position' }, { sep: true },
  { label: 'Язык интерфейса', icon: 'pi-globe', more: true }, { label: 'Версия для слабовидящих', icon: 'pi-eye' },
  { label: 'Сменить тему', icon: 'pi-moon', more: true }, { label: 'Telegram', icon: 'pi-send' }, { sep: true }, { label: 'Выход', icon: 'pi-sign-out' },
];

const SideItem = {
  name: 'SideItem',
  props: ['item', 'level'],
  setup(p) {
    const open = ref(!!p.item.open);
    const active = computed(() => p.item.page && S.page === p.item.page);
    const click = () => {
      if (p.item.children) open.value = !open.value;
      else if (p.item.page) { S.page = p.item.page; S.sideOpen = false; window.scrollTo(0, 0); }
    };
    return { open, active, click };
  },
  template: `<li :class="{'active-menuitem': open && item.children}">
    <a class="menu-link" :class="{active, sub: level > 0, inert: !item.children && !item.page}" role="menuitem" href="#" @click.prevent="click">
      <i :class="item.icon"></i><span>{{ item.label }}</span>
      <i v-if="item.children" class="pi pi-fw toggle" :class="open ? 'pi-angle-up' : 'pi-angle-down'"></i>
    </a>
    <ul v-if="item.children && open" class="submenu"><SideItem v-for="c in item.children" :key="c.label" :item="c" :level="level + 1"/></ul>
  </li>`,
};

/* «Добавить научную работу»: Smart.ENU-дағы терезе, алдымен түр таңдалады. */
const WorkForm = {
  emits: ['close'],
  setup(_, { emit }) {
    const kind = ref('');
    const fields = reactive({});
    const saving = ref(false);
    const spec = computed(() => (kind.value ? S.boot.work_types[kind.value] : null));
    const ready = computed(() => !!spec.value && spec.value.fields.filter((f) => f.required).every((f) => String(fields[f.key] || '').trim()));
    const save = async () => {
      saving.value = true;
      try {
        const r = await api('/api/works', { method: 'POST', body: { work_type: kind.value, fields: { ...fields } } });
        toast(r.claimed ? 'Такая работа уже есть. Ответственный проверит и добавит вас соавтором' : r.merged ? 'Такая работа уже есть в списке' : 'Работа сохранена');
        emit('close');
        bump();
      } finally { saving.value = false; }
    };
    return { S, kind, fields, spec, ready, saving, save };
  },
  template: `<div class="overlay" @click.self="$emit('close')"><div class="modal narrow">
    <div class="drawer-head"><h2>Добавить научную работу</h2><span class="spacer"></span><button class="icon-btn" aria-label="Закрыть" @click="$emit('close')"><i class="pi pi-times"></i></button></div>
    <div class="drawer-body">
      <label class="f">Тип научной работы<select class="inp" v-model="kind"><option value="" disabled></option><option v-for="(t,k) in S.boot.work_types" :key="k" :value="k">{{ t.label }}</option></select></label>
      <div v-if="spec" class="form-grid" style="margin-top:12px"><label v-for="f in spec.fields" :key="f.key" class="f" :class="{wide: f.key === 'title' || f.key === 'source'}">{{ f.label }}<span v-if="f.required" class="req"> *</span><input class="inp" v-model="fields[f.key]"></label></div>
      <div v-if="spec" style="margin-top:14px;display:flex;justify-content:flex-end"><button class="btn primary" :disabled="!ready || saving" @click="save">Сохранить</button></div>
    </div></div></div>`,
};

/* «Научные работы»: Smart.ENU-дағы бет. Жарияланым осы жерге енгізіледі, модуль оны осы тізімнен алады. */
const WorksPage = {
  components: { Tag, WorkForm },
  setup() {
    const mine = ref(true);
    const { data, load } = useLoad(() => api('/api/works?mine=' + mine.value));
    watch(mine, load);
    const authorName = computed(() => S.boot.person.name || S.boot.position.label.split(' · ')[0]);
    const addOpen = ref(false);
    const formOpen = ref(false);
    const page = ref(0);
    const size = ref(10);
    watch([data, size], () => { page.value = 0; });
    const pages = computed(() => (data.value ? Math.max(1, Math.ceil(data.value.items.length / size.value)) : 1));
    const rows = computed(() => (data.value ? data.value.items.slice(page.value * size.value, (page.value + 1) * size.value) : []));
    const first = computed(() => (rows.value.length ? page.value * size.value + 1 : 0));
    const last = computed(() => page.value * size.value + rows.value.length);
    const importFrom = async (name) => {
      addOpen.value = false;
      const r = await api(`/api/integrations/${name}/import`, { method: 'POST' });
      toast(r.text);
      bump();
    };
    const go = (n) => { page.value = Math.min(pages.value - 1, Math.max(0, n)); };
    return { S, data, mine, authorName, addOpen, formOpen, page, size, pages, rows, first, last, importFrom, go, dl };
  },
  template: `<div>
    <div class="head-row"><i class="fa-solid fa-arrow-left back"></i><h3>Научные работы</h3></div>
    <div class="s-toolbar">
      <button class="s-btn off"><i class="pi pi-map"></i> Карта</button>
      <div class="dropdown"><button class="s-btn" @click="addOpen = !addOpen">Добавить научную работу <i class="pi pi-angle-down"></i></button>
        <div class="menu" v-if="addOpen" @mouseleave="addOpen = false">
          <button @click="addOpen = false; formOpen = true">Добавить новую</button>
          <button @click="importFrom('platonus')">Platonus</button>
          <button @click="importFrom('scopus')">Scopus</button>
        </div></div>
      <button class="s-btn" @click="dl('/api/export/person/' + S.boot.position.person)"><i class="fa-solid fa-print"></i> Список научных работ</button>
      <button class="s-btn off">КОКСНВО <i class="pi pi-angle-down"></i></button>
      <span class="spacer"></span>
      <button class="s-btn off filter-btn" aria-label="Фильтр"><i class="pi pi-filter-fill"></i><span class="filter-dot"></span></button>
    </div>
    <div class="s-chips" v-if="mine"><span class="s-chip">Автор: {{ authorName }} <i class="pi pi-times-circle" style="cursor:pointer" @click="mine = false"></i></span><button class="s-clear" style="cursor:pointer" @click="mine = false"><i class="pi pi-times"></i> Очистить</button></div>
    <div class="s-chips" v-else><button class="s-clear" style="cursor:pointer" @click="mine = true"><i class="pi pi-user"></i> Только мои</button></div>
    <div class="card s-table" v-if="data"><div class="table-wrap"><table>
      <thead><tr><th style="width:36%"><i class="pi pi-align-left"></i> Название публикации</th><th><i class="pi pi-file"></i> Тип публикации</th><th><i class="pi pi-user"></i> Автор</th><th><i class="pi pi-calendar"></i> Год</th><th><i class="pi pi-tag"></i> Статус</th><th><i class="pi pi-cog"></i> Действия</th></tr></thead>
      <tbody><tr v-for="r in rows" :key="r.id"><td><button class="link" @click="S.drawerId = r.id">{{ r.title }}</button></td><td>{{ r.work_type_label }}</td><td>{{ mine ? authorName : r.authors.slice(0, 2).join(', ') }}</td><td>{{ r.year }}</td><td><Tag :status="r.status"/></td><td></td></tr></tbody>
    </table></div>
    <div v-if="!rows.length" class="empty">Записей нет.</div>
    <div class="s-pager"><i class="pi pi-angle-double-left" style="cursor:pointer" @click="go(0)"></i><i class="pi pi-angle-left" style="cursor:pointer" @click="go(page - 1)"></i><span class="cur">{{ page + 1 }}</span><i class="pi pi-angle-right" style="cursor:pointer" @click="go(page + 1)"></i><i class="pi pi-angle-double-right" style="cursor:pointer" @click="go(pages - 1)"></i><span class="muted">Показаны записи с {{ first }} по {{ last }} из {{ data.total }}</span>
      <select class="inp" style="width:auto;margin:0" v-model.number="size"><option :value="10">10</option><option :value="25">25</option><option :value="50">50</option></select></div></div>
    <WorkForm v-if="formOpen" @close="formOpen = false"/>
  </div>`,
};

/* «Профиль ученых»: ашық тізімдегі кафедра оқытушылары. */
const ScientistsPage = {
  setup() {
    const { data } = useLoad(() => api('/api/scientists'));
    const page = ref(0);
    const size = 12;
    const shown = computed(() => (data.value ? data.value.items.slice(page.value * size, (page.value + 1) * size) : []));
    const pages = computed(() => (data.value ? Math.ceil(data.value.items.length / size) : 0));
    return { shown, page, pages };
  },
  template: `<div>
    <div class="head-row"><h3>Ученые университета</h3></div>
    <div class="sc-bar"><a class="link" href="#" @click.prevent>Личный кабинет</a><span class="spacer"></span><button class="sc-filter"><i class="pi pi-filter-fill"></i> Фильтр</button><span class="sc-view on"><i class="pi pi-th-large"></i></span><span class="sc-view"><i class="pi pi-list"></i></span></div>
    <div class="sc-grid"><div v-for="p in shown" :key="p.id" class="sc-card"><div class="sc-photo"><i class="pi pi-user"></i></div><div class="sc-name">{{ p.name }}</div></div></div>
    <div class="card s-pager" v-if="pages > 1"><span v-for="n in pages" :key="n" :class="{cur: n - 1 === page}" @click="page = n - 1">{{ n }}</span></div>
  </div>`,
};

/* Модуль: барлық функция осының ішінде, рөлге қарай. */
const VIEWS = { home: Overview, mine: MyResults, approvals: Approvals, how: HowItWorks, records: Records, found: Found, inpress: InPress, review: Review, analytics: Analytics, supervision: Analytics, report: Report, campaign: Campaign, audit: Audit, integrations: Integrations, settings: Settings, log: Log };

const ModulePage = {
  setup() {
    const moreOpen = ref(false);
    const sections = computed(() => {
      const r = S.boot.position.role;
      const item = (id, label, icon, badge) => ({ id, label, icon, badge });
      const inbox = item('approvals', 'На согласовании', 'pi-inbox', S.boot.inbox);
      const how = item('how', 'Как это работает', 'pi-question-circle');
      const found = item('found', 'Найденные', 'pi-search');
      const press = item('inpress', 'В печати', 'pi-hourglass');
      const mine = item('mine', 'Мои результаты', 'pi-user');
      const records = item('records', 'Все записи', 'pi-file');
      const review = item('review', 'Очередь проверки', 'pi-check-square');
      const analytics = item('analytics', 'Аналитика', 'pi-chart-bar');
      const report = item('report', 'Отчёт НИР', 'pi-file-excel');
      const campaign = item('campaign', 'Кампания', 'pi-flag');
      const audit = item('audit', 'Аудит отчёта', 'pi-shield');
      const links = item('integrations', 'Интеграции', 'pi-link');
      const settings = item('settings', 'Настройки', 'pi-cog');
      const log = item('log', 'Журнал действий', 'pi-history');
      if (r === 'author') return { main: [item('home', 'Мои результаты', 'pi-user'), found, press, item('analytics', 'Подготовка к защите', 'pi-graduation-cap'), how], more: [] };
      if (r === 'supervisor') return { main: [item('home', 'Мои результаты', 'pi-user'), inbox, item('analytics', 'Мои обучающиеся', 'pi-users'), found, press, how], more: [] };
      const home = item('home', 'Обзор', 'pi-home');
      if (r === 'responsible') return { main: [home, review, records, report, analytics, campaign], more: [mine, inbox, found, press, audit, links, settings, log, how] };
      if (r === 'head') return { main: [home, inbox, report, analytics, campaign, records], more: [mine, review, found, press, audit, links, settings, log, how] };
      if (r === 'director') return { main: [home, report, analytics, campaign, inbox], more: [records, audit, links, settings, log, how] };
      return { main: [home, campaign, analytics, report], more: [records, audit, links, settings, log, how] };
    });
    const moreActive = computed(() => sections.value.more.some((m) => m.id === S.view));
    const current = computed(() => VIEWS[S.view] || Overview);
    const pick = (id) => { moreOpen.value = false; go(id); };
    const roleName = computed(() => S.boot.position.label.split(' · ')[0]);
    return { S, sections, moreOpen, moreActive, current, pick, roleName };
  },
  template: `<div>
    <div class="head-row"><h3>Научная отчётность</h3>
      <button class="pos-switch" @click="S.posOpen = true"><i class="pi pi-id-card"></i><span>{{ roleName }}</span><b><i class="pi pi-sync"></i> Сменить</b></button></div>
    <div class="s-toolbar">
      <button v-for="m in sections.main" :key="m.id" class="s-btn" :class="{on: S.view === m.id}" @click="pick(m.id)"><i class="pi" :class="m.icon"></i> {{ m.label }}<span v-if="m.badge" class="s-badge">{{ m.badge }}</span></button>
      <div class="dropdown" v-if="sections.more.length"><button class="s-btn" :class="{on: moreActive}" @click="moreOpen = !moreOpen">Ещё <i class="pi pi-angle-down"></i></button>
        <div class="menu" v-if="moreOpen" @mouseleave="moreOpen = false"><button v-for="m in sections.more" :key="m.id" @click="pick(m.id)"><i class="pi" :class="m.icon"></i> {{ m.label }}<span v-if="m.badge" class="s-badge">{{ m.badge }}</span></button></div></div>
      <span class="spacer"></span>
      <button class="s-btn primary-ghost" @click="S.chatOpen = true"><i class="fa-solid fa-robot"></i> Ассистент</button>
    </div>
    <component :is="current" :key="S.pos + S.view"/>
  </div>`,
};

const App = {
  components: { RecordDrawer, NewRecord, Chat, SideItem, VizTip, WorksPage, ScientistsPage, ModulePage },
  setup() {
    const boot = async () => { S.boot = await api('/api/bootstrap'); };
    onMounted(boot);
    S.page = 'module';
    watch(() => S.view, () => { S.page = 'module'; });
    watch(() => S.refresh, boot);
    const setPos = async (id) => {
      S.posOpen = false;
      S.userOpen = false;
      // Жаңа рөлдің деректері алдымен келеді: бет бірден ауысады, ескі рөлдің беті жаңа рөлмен сұраныс жібермейді.
      const next = await (await fetch('/api/bootstrap', { headers: { 'X-Position': id } })).json();
      S.pos = id;
      store.set('sa_pos', id);
      S.boot = next;
      S.page = 'module';
      S.view = 'home';
      bump();
    };
    const who = computed(() => {
      if (!S.boot) return { name: '', role: '' };
      const [title, place] = S.boot.position.label.split(' · ');
      return S.boot.person.name ? { name: S.boot.person.name, role: title } : { name: title, role: place || '' };
    });
    const initials = computed(() => who.value.name.slice(0, 1));
    const notif = ref([]);
    const openNotif = async () => {
      S.notifOpen = !S.notifOpen;
      if (S.notifOpen) {
        notif.value = (await api('/api/notifications')).items;
        await api('/api/notifications/read', { method: 'POST' });
        S.boot.unread = 0;
      }
    };
    const openNotice = (n) => {
      S.notifOpen = false;
      const [view, id] = (n.link || '').split('/');
      if (view === 'record' || view === 'records') {
        if (id) S.drawerId = id;
        else go('records');
      } else if (view) go(view);
    };
    const onSearch = () => { S.page = 'module'; if (S.view !== 'records') S.view = 'records'; };
    const searchBox = ref(null);
    window.addEventListener('keydown', (e) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k' && searchBox.value) { e.preventDefault(); searchBox.value.focus(); } });
    const userAction = (m) => { if (m.action === 'position') { S.userOpen = false; S.posOpen = true; } };
    return { S, MENU, USER_MENU, setPos, who, initials, notif, openNotif, openNotice, onSearch, searchBox, userAction };
  },
  template: `<div class="alayout" v-if="S.boot">
    <aside class="alayout__side" :class="{open: S.sideOpen}">
      <a class="abrand" href="#" @click.prevent><span class="abrand__mark"><i class="fa-solid fa-graduation-cap"></i></span><span class="abrand__text">SMART.ENU</span></a>
      <div class="alayout__menu"><ul class="layout-menu"><SideItem v-for="m in MENU" :key="m.label" :item="m" :level="0"/></ul></div>
      <div class="aside__foot">© Евразийский национальный университет имени Л.Н. Гумилева</div>
    </aside>
    <div class="alayout__main">
      <header class="atop">
        <button class="atop__burger" aria-label="Открыть меню" @click="S.sideOpen = !S.sideOpen"><i class="pi pi-bars"></i></button>
        <label class="atop__search"><i class="pi pi-search"></i><input ref="searchBox" v-model="S.q" placeholder="Найти документ, человека или раздел…" @input="onSearch"><kbd>Ctrl K</kbd></label>
        <span class="spacer"></span>
        <button class="atop__icon" aria-label="Справка"><i class="pi pi-question-circle"></i></button>
        <button class="atop__icon" aria-label="Версия для слабовидящих"><i class="pi pi-eye"></i></button>
        <button class="atop__icon" aria-label="Telegram"><i class="pi pi-send"></i></button>
        <button class="atop__icon" aria-label="Тёмная тема"><i class="pi pi-moon"></i></button>
        <div class="dropdown"><button class="atop__icon" aria-label="Уведомления" @click="openNotif"><i class="pi pi-bell"></i><span v-if="S.boot.unread" class="atop__badge">{{ S.boot.unread }}</span></button>
          <div class="menu notif-menu" v-if="S.notifOpen"><button v-for="n in notif" :key="n.id" class="notif-item" @click="openNotice(n)"><span>{{ n.text }}</span><span class="faint">{{ n.at.replace('T',' ').slice(0,16) }}</span></button><div v-if="!notif.length" class="muted small" style="padding:8px">Уведомлений нет.</div></div></div>
        <span class="atop__lang">Русский <i class="pi pi-angle-down"></i></span>
        <div class="dropdown"><button class="atop__who" @click="S.userOpen = !S.userOpen"><span class="atop__ava">{{ initials }}</span><span class="atop__who-text"><span class="atop__name">{{ who.name }}</span><span class="atop__role">{{ who.role }}</span></span><i class="pi pi-chevron-down atop__who-caret"></i></button>
          <div class="user-menu" v-if="S.userOpen" @mouseleave="S.userOpen = false">
            <div class="aum-head"><b>{{ who.name }}</b><span>{{ who.role }}</span></div>
            <template v-for="(m,i) in USER_MENU" :key="i"><div v-if="m.sep" class="aum-sep"></div>
              <button v-else :class="{inert: !m.action}" @click="userAction(m)"><i class="pi" :class="m.icon"></i> {{ m.label }}<i v-if="m.more" class="pi pi-angle-right more"></i></button></template>
          </div></div>
      </header>
      <main class="acontent">
        <WorksPage v-if="S.page === 'works'" :key="'w' + S.pos"/>
        <ScientistsPage v-else-if="S.page === 'scientists'"/>
        <ModulePage v-else/>
      </main>
    </div>
    <RecordDrawer v-if="S.drawerId" :key="S.drawerId"/>
    <NewRecord v-if="S.newRecord"/>
    <Chat v-show="S.chatOpen"/>
    <button v-if="!S.chatOpen" class="bilge-fab" aria-label="Открыть ассистента" @click="S.chatOpen = true"><i class="fa-solid fa-robot"></i><span class="bilge-fab__dot"></span></button>
    <div class="overlay" v-if="S.posOpen" @click.self="S.posOpen = false"><div class="modal narrow"><div class="drawer-head"><h2>Выберите позицию</h2><span class="spacer"></span><button class="icon-btn" aria-label="Закрыть" @click="S.posOpen = false"><i class="pi pi-times"></i></button></div>
      <div class="drawer-body"><button v-for="p in S.boot.positions" :key="p.id" class="pos-item" :class="{on: p.id === S.pos}" @click="setPos(p.id)"><i class="pi pi-id-card"></i> {{ p.label }}</button></div></div></div>
    <VizTip/>
    <div v-if="S.toast" class="toast" :class="{bad: S.toast.bad}" role="status">{{ S.toast.text }}</div>
  </div><div v-else class="boot">Загрузка…</div>`,
};

createApp(App).component('RecordFlow', RecordFlow).mount('#app');
