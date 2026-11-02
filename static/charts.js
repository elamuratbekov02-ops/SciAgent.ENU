/* Диаграммалар. Кітапханасыз: сандар серверден, белгілер түсімен ғана емес, аңыз бен кесте арқылы да оқылады. */
const SERIES_COLORS = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6', '#e34948'];
const PREV_COLOR = '#86b6ef';
const STATUS_COLORS = { good: '#0ca30c', warning: '#fab219', critical: '#d03b3b' };

const TIP = reactive({ show: false, x: 0, y: 0, title: '', lines: [] });
function showTip(e, title, lines) {
  TIP.show = true;
  TIP.x = Math.min(e.clientX + 14, window.innerWidth - 240);
  TIP.y = e.clientY + 14;
  TIP.title = title;
  TIP.lines = lines;
}
function hideTip() { TIP.show = false; }

const VizTip = {
  setup() { return { TIP }; },
  template: `<div v-if="TIP.show" class="viz-tip" :style="{left: TIP.x + 'px', top: TIP.y + 'px'}" role="status">
    <b>{{ TIP.title }}</b>
    <div v-for="l in TIP.lines" :key="l.label" class="viz-tip-row"><i v-if="l.color" :style="{background: l.color}"></i><span>{{ l.label }}</span><b>{{ l.value }}</b></div>
  </div>`,
};

/* Диаграмма картасы: атауы, аңызы және кесте түрінде ашу батырмасы. */
const ChartCard = {
  props: ['title', 'sub', 'legend', 'table', 'note'],
  setup() { return { asTable: ref(false) }; },
  template: `<div class="card viz-card">
    <div class="card-head"><div><h2>{{ title }}</h2><div v-if="sub" class="small muted">{{ sub }}</div></div><span class="spacer"></span>
      <button v-if="table" class="viz-switch" :aria-pressed="asTable" @click="asTable = !asTable"><i class="pi" :class="asTable ? 'pi-chart-bar' : 'pi-table'"></i> {{ asTable ? 'Диаграмма' : 'Таблица' }}</button></div>
    <div class="card-body">
      <div v-if="legend && legend.length > 1 && !asTable" class="viz-legend"><span v-for="l in legend" :key="l.label"><i :style="{background: l.color}"></i>{{ l.label }}</span></div>
      <slot v-if="!asTable"></slot>
      <div v-else class="table-wrap"><table><thead><tr><th v-for="c in table.cols" :key="c">{{ c }}</th></tr></thead><tbody><tr v-for="(r,i) in table.rows" :key="i"><td v-for="(v,j) in r" :key="j" :class="{num: j > 0}">{{ v }}</td></tr></tbody></table></div>
      <div v-if="note" class="small muted viz-note">{{ note }}</div>
    </div></div>`,
};

/* Көлденең бағандар. Бірнеше серия болса, қабатталады. */
const HBars = {
  props: ['rows', 'series', 'labelWidth'],
  emits: ['pick'],
  setup(p) {
    const colored = computed(() => p.series.map((s, i) => ({ ...s, color: s.color || SERIES_COLORS[i % SERIES_COLORS.length] })));
    const total = (r) => colored.value.reduce((n, s) => n + (Number(r.values[s.key]) || 0), 0);
    const max = computed(() => Math.max(1, ...p.rows.map(total)));
    const segs = (r) => colored.value.filter((s) => Number(r.values[s.key]) > 0).map((s) => ({ ...s, value: Number(r.values[s.key]) }));
    const tip = (e, r) => showTip(e, r.label, colored.value.map((s) => ({ label: s.label, value: Number(r.values[s.key]) || 0, color: s.color })));
    return { total, max, segs, tip, hideTip };
  },
  template: `<div class="viz-hbars" :style="{'--viz-label': (labelWidth || 170) + 'px'}">
    <div v-for="r in rows" :key="r.label" class="viz-hrow" @mousemove="tip($event, r)" @mouseleave="hideTip">
      <div class="viz-hlabel" :title="r.label">{{ r.label }}</div>
      <div class="viz-htrack">
        <div class="viz-hbar" :style="{width: (total(r) * 100 / max) + '%'}"><span v-for="s in segs(r)" :key="s.key" :style="{flexGrow: s.value, background: s.color}"></span></div>
        <b class="viz-hval">{{ total(r) }}</b>
      </div>
    </div>
  </div>`,
};

/* Тік бағандар: өткен жыл мен есепті жыл. */
const YearBars = {
  props: ['rows', 'prevLabel', 'curLabel'],
  setup(p) {
    const max = computed(() => Math.max(1, ...p.rows.flatMap((r) => [Number(r.prev) || 0, Number(r.cur) || 0])));
    const h = (v) => `${(Number(v) || 0) * 100 / max.value}%`;
    const tip = (e, r) => showTip(e, r.label, [{ label: p.prevLabel, value: r.prev ?? '–', color: PREV_COLOR }, { label: p.curLabel, value: r.cur, color: SERIES_COLORS[0] }]);
    return { h, tip, hideTip, PREV_COLOR, SERIES_COLORS };
  },
  template: `<div class="viz-columns">
    <div v-for="r in rows" :key="r.label" class="viz-col" @mousemove="tip($event, r)" @mouseleave="hideTip">
      <div class="viz-col-plot">
        <div class="viz-col-bar" :style="{height: h(r.prev), background: PREV_COLOR}"><span>{{ r.prev ?? '' }}</span></div>
        <div class="viz-col-bar" :style="{height: h(r.cur), background: SERIES_COLORS[0]}"><span>{{ r.cur }}</span></div>
      </div>
      <div class="viz-col-label">{{ r.label }}</div>
    </div>
  </div>`,
};

/* Бүтіннің бөліктері: бір қабатталған жолақ. */
const ShareBar = {
  props: ['items'],
  setup(p) {
    const colored = computed(() => p.items.map((x, i) => ({ ...x, color: SERIES_COLORS[i % SERIES_COLORS.length] })).filter((x) => x.value > 0));
    const sum = computed(() => colored.value.reduce((n, x) => n + x.value, 0) || 1);
    const tip = (e, x) => showTip(e, x.label, [{ label: 'Записей', value: x.value, color: x.color }, { label: 'Доля', value: Math.round(x.value * 100 / sum.value) + '%' }]);
    return { colored, sum, tip, hideTip };
  },
  template: `<div>
    <div class="viz-share"><span v-for="x in colored" :key="x.label" :style="{flexGrow: x.value, background: x.color}" @mousemove="tip($event, x)" @mouseleave="hideTip"></span></div>
    <div class="viz-share-keys"><div v-for="x in colored" :key="x.label"><i :style="{background: x.color}"></i><span>{{ x.label }}</span><b>{{ x.value }}</b><span class="muted">{{ Math.round(x.value * 100 / sum) }}%</span></div></div>
  </div>`,
};

/* Жоспардың орындалуы. Күй түспен ғана емес, белгі мен сөзбен де беріледі. */
const PlanBars = {
  props: ['rows'],
  setup() {
    const state = (r) => {
      const v = r.percent || 0;
      if (v >= 100) return { color: STATUS_COLORS.good, icon: 'pi-check-circle', text: 'выполнено' };
      if (v >= 60) return { color: STATUS_COLORS.warning, icon: 'pi-exclamation-circle', text: 'в работе' };
      return { color: STATUS_COLORS.critical, icon: 'pi-times-circle', text: 'отстаёт' };
    };
    const tip = (e, r) => showTip(e, r.label, [{ label: 'Факт', value: r.fact }, { label: 'План', value: r.plan }, { label: 'Выполнение', value: (r.percent || 0) + '%' }]);
    return { state, tip, hideTip };
  },
  template: `<div class="viz-plan">
    <div v-for="r in rows" :key="r.key || r.label" class="viz-plan-row" @mousemove="tip($event, r)" @mouseleave="hideTip">
      <div class="viz-hlabel" :title="r.label">{{ r.label }}</div>
      <div class="viz-plan-track"><div class="viz-plan-fill" :style="{width: Math.min(r.percent || 0, 100) + '%', background: state(r).color}"></div></div>
      <div class="viz-plan-val"><b>{{ r.fact }}</b> из {{ r.plan }}</div>
      <div class="viz-plan-state"><i class="pi" :class="state(r).icon"></i> {{ state(r).text }}</div>
    </div>
  </div>`,
};

/* Чатта сервер жіберген диаграмма. */
const ChatChart = {
  components: { HBars, PlanBars },
  props: ['spec'],
  setup(p) {
    const legend = computed(() => (p.spec.series || []).map((s, i) => ({ label: s.label, color: SERIES_COLORS[i % SERIES_COLORS.length] })));
    return { legend };
  },
  template: `<div class="chat-chart">
    <b>{{ spec.title }}</b>
    <div v-if="legend.length > 1" class="viz-legend"><span v-for="l in legend" :key="l.label"><i :style="{background: l.color}"></i>{{ l.label }}</span></div>
    <PlanBars v-if="spec.type === 'bullet'" :rows="spec.rows"/>
    <HBars v-else :rows="spec.rows" :series="spec.series" :label-width="120"/>
    <div v-if="spec.note" class="small muted viz-note">{{ spec.note }}</div>
  </div>`,
};
