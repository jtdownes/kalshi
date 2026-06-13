import { useEffect, useMemo, useRef, useState } from 'react';
import {
  ComposedChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ReferenceDot,
  ResponsiveContainer,
} from 'recharts';
import { detectCryptoAsset, cryptoAssetConfig } from '../utils';
import type { Order } from '../types';

interface Candle {
  bucket: number;  // epoch seconds (bucket start)
  open: number;
  high: number;
  low: number;
  close: number;
  n: number;
}

interface Props {
  ticker: string;
  strikeNum?: number | null;
  // Latest live tick for the asset, so the in-progress candle updates without
  // re-fetching. livePrice = consolidated USD price; liveTs = its scanned_at.
  livePrice?: number | null;
  liveTs?: string | null;
}

// scanned_at is a UTC wall-clock ISO string with no zone marker; JS would read
// it as local time, so force UTC to match the server's bucket epochs.
const epochFromScanned = (iso: string): number => {
  const hasZone = /[zZ]$/.test(iso) || /[+-]\d\d:?\d\d$/.test(iso);
  return Date.parse(hasZone ? iso : iso + 'Z') / 1000;
};

// Candle interval (seconds) → label
const INTERVALS: { secs: number; label: string }[] = [
  { secs: 5,   label: '5s'  },
  { secs: 30,  label: '30s' },
  { secs: 60,  label: '1m'  },
  { secs: 180, label: '3m'  },
  { secs: 300, label: '5m'  },
  { secs: 900, label: '15m' },
  { secs: 1800, label: '30m' },
];

// Lookback window (seconds) → label
const LOOKBACKS: { secs: number; label: string }[] = [
  { secs: 900,    label: '15m' },
  { secs: 1800,   label: '30m' },
  { secs: 3600,   label: '1h' },
  { secs: 14400,  label: '4h' },
  { secs: 43200,  label: '12h' },
  { secs: 86400,  label: '1d' },
  { secs: 604800, label: '1w' },
];

const UP = '#00d4a0';
const DOWN = '#ff4444';

const fmtClock = (epochSecs: number) => {
  const d = new Date(epochSecs * 1000);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
};

// Day-and-month label, e.g. "Jun 12".
const fmtDay = (epochSecs: number) => {
  const d = new Date(epochSecs * 1000);
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
};

// Date + time, for tooltips and wide-window axes where time alone is ambiguous.
const fmtDayTime = (epochSecs: number) => {
  const d = new Date(epochSecs * 1000);
  return `${d.toLocaleDateString([], { month: 'short', day: 'numeric' })} ${d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
};

// Below $10k, show whole dollars with separators ($1,668) so closely-spaced
// ticks stay distinct; above that, the compact $Nk form is enough.
const fmtPrice = (val: number) =>
  val >= 10000 ? `$${(val / 1000).toFixed(1)}k` : `$${Math.round(val).toLocaleString()}`;

// Custom shape for a single candle. Recharts gives us the floating bar's pixel
// box for the low→high range (y = pixel of `high`, height = span down to `low`),
// so we can build a local price→pixel map from this candle's own high/low and
// place the open/close body without needing the chart's y-scale.
// True when the viewport is phone-sized (matches the CSS mobile breakpoint).
function useIsMobile(): boolean {
  const [m, setM] = useState(
    () => typeof window !== 'undefined' && window.matchMedia('(max-width: 640px)').matches,
  );
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 640px)');
    const onChange = (e: MediaQueryListEvent) => setM(e.matches);
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, []);
  return m;
}

type Opt = { secs: number; label: string };

// Timeframe control: a full segmented button row on desktop; on mobile it
// collapses to the selected value and opens a dropdown on tap (TradingView-style)
// to save horizontal space.
function Picker({ opts, value, onPick, mobile }: {
  opts: Opt[]; value: number; onPick: (v: number) => void; mobile: boolean;
}) {
  const [open, setOpen] = useState(false);
  const cur = opts.find(o => o.secs === value);

  if (!mobile) {
    return (
      <div style={{ display: 'flex', flexWrap: 'wrap', borderRadius: 4, overflow: 'hidden', border: '1px solid #333' }}>
        {opts.map(o => (
          <button
            key={o.secs}
            onClick={() => onPick(o.secs)}
            style={{
              fontSize: 10, padding: '2px 8px', cursor: 'pointer', border: 'none',
              background: value === o.secs ? '#374151' : 'transparent',
              color: value === o.secs ? '#fff' : '#888',
            }}
          >
            {o.label}
          </button>
        ))}
      </div>
    );
  }

  return (
    <div style={{ position: 'relative' }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          fontSize: 11, padding: '4px 10px', cursor: 'pointer',
          borderRadius: 4, border: '1px solid #333', background: '#1f2937', color: '#fff',
          display: 'flex', alignItems: 'center', gap: 6,
        }}
      >
        {cur?.label ?? '—'}
        <span style={{ color: '#888', fontSize: 9 }}>▾</span>
      </button>
      {open && (
        <>
          {/* click-catcher to close */}
          <div onClick={() => setOpen(false)} style={{ position: 'fixed', inset: 0, zIndex: 20 }} />
          <div
            style={{
              position: 'absolute', top: '100%', right: 0, marginTop: 4, zIndex: 21,
              background: '#1a1a1a', border: '1px solid #333', borderRadius: 4,
              overflow: 'hidden', minWidth: 64, boxShadow: '0 4px 12px rgba(0,0,0,0.5)',
            }}
          >
            {opts.map(o => (
              <button
                key={o.secs}
                onClick={() => { onPick(o.secs); setOpen(false); }}
                style={{
                  display: 'block', width: '100%', textAlign: 'left',
                  fontSize: 12, padding: '7px 12px', cursor: 'pointer', border: 'none',
                  background: value === o.secs ? '#374151' : 'transparent',
                  color: value === o.secs ? '#fff' : '#bbb',
                }}
              >
                {o.label}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function Candle(props: {
  x?: number; y?: number; width?: number; height?: number;
  payload?: { open: number; high: number; low: number; close: number; up: boolean };
}) {
  const { x, y, width, height, payload } = props;
  if (x == null || y == null || width == null || height == null || !payload) return null;
  const { open, high, low, close, up } = payload;
  const color = up ? UP : DOWN;
  const cx = x + width / 2;
  const range = high - low;
  // price → pixel within [y (top=high) .. y+height (bottom=low)]
  const priceY = (p: number) => range === 0 ? y : y + ((high - p) / range) * height;
  const bodyTop = priceY(Math.max(open, close));
  const bodyBot = priceY(Math.min(open, close));
  const bodyW = Math.max(1, Math.min(width * 0.7, 12));
  return (
    <g>
      {/* wick */}
      <line x1={cx} y1={y} x2={cx} y2={y + height} stroke={color} strokeWidth={1} />
      {/* body (min 1px tall so doji candles stay visible) */}
      <rect
        x={cx - bodyW / 2}
        y={bodyTop}
        width={bodyW}
        height={Math.max(1, bodyBot - bodyTop)}
        fill={color}
      />
    </g>
  );
}

interface PaneProps extends Props {
  initialInterval?: number;
  initialLookback?: number;
  // When set, a control to close this pane (used by the split view).
  onClose?: () => void;
}

function CandlePane({
  ticker, strikeNum = null, livePrice = null, liveTs = null,
  initialInterval = 60, initialLookback = 14400, onClose,
}: PaneProps) {
  const assetKey = detectCryptoAsset(ticker);
  const assetInfo = cryptoAssetConfig(ticker);

  const mobile = useIsMobile();
  const [interval, setInterval] = useState(initialInterval);
  const [lookback, setLookback] = useState(initialLookback);
  const [data, setData] = useState<Candle[]>([]);
  const [loading, setLoading] = useState(false);
  const [orders, setOrders] = useState<Order[]>([]);
  const [showExecs, setShowExecs] = useState(true);

  // Keep the candle count sane: a tiny interval over a wide window (e.g. 5s
  // over 1w ≈ 120k bars) is unreadable and slow, so floor the interval at
  // whatever keeps us under MAX_BARS for the chosen lookback.
  const MAX_BARS = 1500;
  const MIN_BARS = 3;  // an interval coarser than this many bars per window is useless
  const minInterval = Math.ceil(lookback / MAX_BARS);
  const maxInterval = Math.floor(lookback / MIN_BARS);
  const effInterval = Math.max(interval, minInterval);

  // Hide interval choices that don't fit the current window: too fine blows past
  // MAX_BARS (1w only offers 15m+), too coarse yields too few candles to read
  // (the 30m window won't offer 15m/30m candles — just 1–2 bars).
  const intervalOpts = useMemo(
    () => INTERVALS.filter(o => o.secs >= minInterval && o.secs <= maxInterval),
    [minInterval, maxInterval],
  );

  // If the active interval is no longer valid for the new window, snap it to the
  // closest one that is.
  useEffect(() => {
    if (intervalOpts.length === 0) return;
    if (interval < minInterval) setInterval(intervalOpts[0].secs);
    else if (interval > maxInterval) setInterval(intervalOpts[intervalOpts.length - 1].secs);
  }, [minInterval, maxInterval, interval, intervalOpts]);

  useEffect(() => {
    if (!assetKey) return;
    setLoading(true);
    const url = `/api/crypto/ohlc?asset=${assetKey}&interval=${effInterval}&lookback=${lookback}`;
    fetch(url)
      .then(r => r.json())
      .then((rows: Candle[]) => {
        setData(Array.isArray(rows) ? rows : []);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [assetKey, effInterval, lookback]);

  // Pull all of this asset's orders (across every market) so they can be plotted
  // on the shared price timeline — the broad view spans many short-lived markets.
  useEffect(() => {
    if (!assetKey) return;
    const prefix = `KX${assetKey}`;
    fetch('/api/orders?limit=500')
      .then(r => r.json())
      .then((rows: Order[]) => {
        setOrders(Array.isArray(rows)
          ? rows.filter(o => (o.market_ticker ?? '').toUpperCase().startsWith(prefix))
          : []);
      })
      .catch(() => setOrders([]));
  }, [assetKey]);

  // Fold each new live tick into the in-progress candle (or open a new one when
  // the bucket rolls over). No network call — reuses the snapshot feed the line
  // charts already consume. A ref guards against double-counting the same tick.
  const lastFoldedTs = useRef<string | null>(null);
  useEffect(() => {
    if (livePrice == null || !Number.isFinite(livePrice) || !liveTs) return;
    if (liveTs === lastFoldedTs.current) return;
    const ts = epochFromScanned(liveTs);
    if (!Number.isFinite(ts)) return;
    lastFoldedTs.current = liveTs;
    const bucket = Math.floor(ts / effInterval) * effInterval;
    setData(prev => {
      if (prev.length === 0) return prev;  // wait for the fetched baseline
      const last = prev[prev.length - 1];
      if (bucket < last.bucket) return prev;  // stale tick
      if (bucket === last.bucket) {
        return [...prev.slice(0, -1), {
          ...last,
          high: Math.max(last.high, livePrice),
          low: Math.min(last.low, livePrice),
          close: livePrice,
          n: last.n + 1,
        }];
      }
      return [...prev, { bucket, open: livePrice, high: livePrice, low: livePrice, close: livePrice, n: 1 }];
    });
  }, [livePrice, liveTs, effInterval]);

  // Floating-bar ranges: wick spans low→high, body spans open↔close.
  const chartData = useMemo(() => data.map(c => ({
    ...c,
    wick: [c.low, c.high] as [number, number],
    up: c.close >= c.open,
  })), [data]);

  const priceDomain: [number, number] | ['auto', 'auto'] = useMemo(() => {
    if (chartData.length === 0) return ['auto', 'auto'];
    let mn = Infinity, mx = -Infinity;
    for (const c of chartData) { if (c.low < mn) mn = c.low; if (c.high > mx) mx = c.high; }
    if (strikeNum != null) { mn = Math.min(mn, strikeNum); mx = Math.max(mx, strikeNum); }
    if (!Number.isFinite(mn) || !Number.isFinite(mx)) return ['auto', 'auto'];
    // Pad by a small fraction of the actual range so the candles fill the chart
    // even when the price barely moves; only fall back to an absolute floor when
    // the range is effectively flat (avoids a zero-height domain).
    const range = mx - mn;
    const pad = range > 0 ? range * 0.06 : Math.max(mx * 0.0005, 1);
    return [mn - pad, mx + pad];
  }, [chartData, strikeNum]);

  // Place each order on the timeline at the candle nearest its placed_at, pinned
  // to that candle's close. Snapping to the nearest candle (not just an exact
  // bucket) keeps markers visible across data gaps. Orders whose time falls
  // outside the visible window simply drop.
  const execDots = useMemo(() => {
    if (data.length === 0) return [];
    const lo = data[0].bucket;
    const hi = data[data.length - 1].bucket;
    return orders.map(o => {
      const stamp = o.placed_at ?? o.filled_at;
      if (!stamp) return null;
      const ts = epochFromScanned(stamp);
      if (!Number.isFinite(ts) || ts < lo - effInterval || ts > hi + effInterval) return null;
      // nearest candle by time
      let best = data[0];
      for (const c of data) {
        if (Math.abs(c.bucket - ts) < Math.abs(best.bucket - ts)) best = c;
      }
      const color = o.outcome === 'win' ? UP : o.outcome === 'loss' ? DOWN : '#9ca3af';
      return { id: o.id, bucket: best.bucket, y: best.close, color, buy: o.order_role === 'entry' };
    }).filter((d): d is { id: number; bucket: number; y: number; color: string; buy: boolean } => d != null);
  }, [orders, data, effInterval]);

  if (!assetKey) return null;

  // Build the y-axis ticks ourselves so the strike price always appears as a
  // labelled tick (drawn white to match its dashed line). Evenly space a few
  // ticks across the domain, then inject the strike, dropping any auto tick that
  // would collide with it.
  const [yTicks, isStrikeTick] = useMemo<[number[], (v: number) => boolean]>(() => {
    if (priceDomain[0] === 'auto' || priceDomain[1] === 'auto') return [[], () => false];
    const [lo, hi] = priceDomain as [number, number];
    const span = hi - lo;
    if (span <= 0) return [[], () => false];
    const base: number[] = [];
    for (let i = 0; i <= 4; i++) base.push(lo + (span * i) / 4);
    if (strikeNum == null) return [base, () => false];
    const minGap = span * 0.08;  // keep auto ticks from crowding the strike
    const kept = base.filter(t => Math.abs(t - strikeNum) > minGap);
    const ticks = [...kept, strikeNum].sort((a, b) => a - b);
    return [ticks, (v: number) => v === strikeNum];
  }, [priceDomain, strikeNum]);

  // For windows spanning a day or more, time-only ticks are ambiguous — switch
  // the axis to a date label so the user can tell which day a candle is on.
  const axisFmt = lookback >= 86400 ? fmtDay : fmtClock;

  const CandleTooltip = ({ active, payload }: {
    active?: boolean;
    payload?: Array<{ payload: Candle }>;
  }) => {
    if (!active || !payload || payload.length === 0) return null;
    const c = payload[0].payload;
    const up = c.close >= c.open;
    const row = (k: string, v: number) => (
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
        <span style={{ color: '#888' }}>{k}</span>
        <span>${v.toLocaleString(undefined, { maximumFractionDigits: 2 })}</span>
      </div>
    );
    return (
      <div style={{ backgroundColor: '#1a1a1a', border: '1px solid #444', color: '#eee', borderRadius: 4, padding: '6px 10px', fontSize: 11 }}>
        <div style={{ color: '#aaa', marginBottom: 4 }}>
          {fmtDayTime(c.bucket)} · {c.n} ticks
        </div>
        {row('O', c.open)}
        {row('H', c.high)}
        {row('L', c.low)}
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, color: up ? UP : DOWN }}>
          <span>C</span>
          <span>${c.close.toLocaleString(undefined, { maximumFractionDigits: 2 })}</span>
        </div>
      </div>
    );
  };

  return (
    <div className="chart-card" style={{ minWidth: 0, height: 'auto', overflow: 'hidden' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4, flexWrap: 'wrap', gap: 8 }}>
        <span style={{ fontSize: 11, color: '#888' }}>
          {assetInfo ? `${assetInfo.label} candles (USD)` : 'Candles (USD)'} — {data.length} bars
          {effInterval !== interval && (
            <span style={{ color: '#f5c842' }}> · auto {effInterval >= 60 ? `${Math.round(effInterval / 60)}m` : `${effInterval}s`}</span>
          )}
        </span>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, justifyContent: 'flex-end' }}>
          <Picker opts={intervalOpts} value={interval} onPick={setInterval} mobile={mobile} />
          <Picker opts={LOOKBACKS} value={lookback} onPick={setLookback} mobile={mobile} />
          <button
            onClick={() => setShowExecs(s => !s)}
            title="Toggle execution markers"
            style={{
              fontSize: mobile ? 11 : 10, padding: mobile ? '4px 10px' : '2px 8px',
              cursor: 'pointer', borderRadius: 4, border: '1px solid #333',
              background: showExecs ? '#374151' : 'transparent',
              color: showExecs ? '#fff' : '#888',
            }}
          >
            Execs
          </button>
          {onClose && (
            <button
              onClick={onClose}
              title="Close this pane"
              style={{
                fontSize: mobile ? 13 : 12, padding: mobile ? '4px 10px' : '2px 8px',
                cursor: 'pointer', borderRadius: 4, border: '1px solid #333',
                background: 'transparent', color: '#888', lineHeight: 1,
              }}
            >
              ✕
            </button>
          )}
        </div>
      </div>
      <div style={{ height: mobile ? 200 : 260 }}>
        {loading && data.length === 0 ? (
          <div style={{ color: '#888', textAlign: 'center', paddingTop: 100 }}>Loading candles…</div>
        ) : chartData.length === 0 ? (
          <div style={{ color: '#888', textAlign: 'center', paddingTop: 100 }}>No data for this window</div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={chartData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#333" vertical={false} />
              <XAxis
                dataKey="bucket"
                tickFormatter={axisFmt}
                stroke="#666"
                fontSize={10}
                minTickGap={50}
                tick={{ fill: '#888' }}
              />
              <YAxis
                stroke="#666"
                domain={priceDomain}
                ticks={yTicks.length ? yTicks : undefined}
                tickFormatter={fmtPrice}
                fontSize={10}
                width={52}
                tick={(props: { x: number; y: number; payload: { value: number } }) => {
                  const strike = isStrikeTick(props.payload.value);
                  return (
                    <text
                      x={props.x}
                      y={props.y}
                      dy={3}
                      textAnchor="end"
                      fontSize={10}
                      fontWeight={strike ? 700 : 400}
                      fill={strike ? '#ffffff' : '#888'}
                    >
                      {fmtPrice(props.payload.value)}
                    </text>
                  );
                }}
              />
              <Tooltip content={<CandleTooltip />} />
              {strikeNum != null && (
                <ReferenceLine
                  y={strikeNum}
                  stroke="#ffffff"
                  strokeDasharray="6 3"
                  strokeWidth={1}
                />
              )}
              {/* One floating bar per candle spanning low→high; the custom
                  shape draws the wick + open/close body itself so the two
                  parts overlap (separate Bar series would render side-by-side). */}
              <Bar dataKey="wick" isAnimationActive={false} shape={<Candle />} />

              {/* Execution markers: B = entry, S = exit; colored by outcome */}
              {showExecs && execDots.map(d => (
                <ReferenceDot
                  key={d.id}
                  x={d.bucket}
                  y={d.y}
                  r={4}
                  fill={d.color}
                  stroke="#111"
                  strokeWidth={1}
                  ifOverflow="extendDomain"
                  label={{ value: d.buy ? 'B' : 'S', position: 'top', fill: d.color, fontSize: 9 }}
                />
              ))}
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}

// Wrapper: renders one CandlePane by default, with a "split" toggle that opens
// a second independent pane below it (each with its own interval/lookback) so
// you can watch, say, a 15m chart next to a tick-by-tick one. The two panes
// share the same ticker/strike/live feed but hold separate view state.
export default function CryptoCandleChart(props: Props) {
  const [split, setSplit] = useState(false);
  if (!detectCryptoAsset(props.ticker)) return null;

  return (
    <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <button
          onClick={() => setSplit(s => !s)}
          title={split ? 'Single chart' : 'Split into two charts'}
          style={{
            fontSize: 10, padding: '2px 8px', cursor: 'pointer', borderRadius: 4,
            border: '1px solid #333', display: 'flex', alignItems: 'center', gap: 5,
            background: split ? '#374151' : 'transparent', color: split ? '#fff' : '#888',
          }}
        >
          <span style={{ fontSize: 12, lineHeight: 1 }}>{split ? '▭' : '⊟'}</span>
          {split ? 'Single' : 'Split'}
        </button>
      </div>
      <CandlePane {...props} initialInterval={60} initialLookback={14400} />
      {split && (
        // Second pane defaults to a finer/closer view to complement the first.
        <CandlePane {...props} initialInterval={5} initialLookback={1800} onClose={() => setSplit(false)} />
      )}
    </div>
  );
}
