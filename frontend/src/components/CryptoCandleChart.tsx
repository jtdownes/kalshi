import { useEffect, useMemo, useRef, useState } from 'react';
import {
  ComposedChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
} from 'recharts';
import { detectCryptoAsset, cryptoAssetConfig } from '../utils';

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

const fmtPrice = (val: number) =>
  val >= 1000 ? `$${(val / 1000).toFixed(2)}k` : `$${val.toFixed(0)}`;

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

export default function CryptoCandleChart({ ticker, strikeNum = null, livePrice = null, liveTs = null }: Props) {
  const assetKey = detectCryptoAsset(ticker);
  const assetInfo = cryptoAssetConfig(ticker);

  const mobile = useIsMobile();
  const [interval, setInterval] = useState(60);
  const [lookback, setLookback] = useState(14400);
  const [data, setData] = useState<Candle[]>([]);
  const [loading, setLoading] = useState(false);

  // Keep the candle count sane: a tiny interval over a wide window (e.g. 5s
  // over 1w ≈ 120k bars) is unreadable and slow, so floor the interval at
  // whatever keeps us under MAX_BARS for the chosen lookback.
  const MAX_BARS = 1500;
  const effInterval = Math.max(interval, Math.ceil(lookback / MAX_BARS));

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
    const pad = Math.max((mx - mn) * 0.08, mn * 0.001);
    return [Math.floor(mn - pad), Math.ceil(mx + pad)];
  }, [chartData, strikeNum]);

  if (!assetKey) return null;

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
          {fmtClock(c.bucket)} · {c.n} ticks
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
    <div className="chart-card" style={{ marginTop: 12, minWidth: 0, height: 'auto', overflow: 'hidden' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4, flexWrap: 'wrap', gap: 8 }}>
        <span style={{ fontSize: 11, color: '#888' }}>
          {assetInfo ? `${assetInfo.label} candles (USD)` : 'Candles (USD)'} — {data.length} bars
          {effInterval !== interval && (
            <span style={{ color: '#f5c842' }}> · auto {effInterval >= 60 ? `${Math.round(effInterval / 60)}m` : `${effInterval}s`}</span>
          )}
        </span>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, justifyContent: 'flex-end' }}>
          <Picker opts={INTERVALS} value={interval} onPick={setInterval} mobile={mobile} />
          <Picker opts={LOOKBACKS} value={lookback} onPick={setLookback} mobile={mobile} />
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
                tickFormatter={fmtClock}
                stroke="#666"
                fontSize={10}
                minTickGap={50}
                tick={{ fill: '#888' }}
              />
              <YAxis
                stroke="#666"
                domain={priceDomain}
                tickFormatter={fmtPrice}
                fontSize={10}
                tick={{ fill: '#888' }}
                width={52}
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
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}
