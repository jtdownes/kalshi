import { useEffect, useMemo, useState } from 'react';
import {
  ComposedChart,
  Bar,
  Cell,
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
}

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

export default function CryptoCandleChart({ ticker, strikeNum = null }: Props) {
  const assetKey = detectCryptoAsset(ticker);
  const assetInfo = cryptoAssetConfig(ticker);

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

  // Floating-bar ranges: wick spans low→high, body spans open↔close.
  const chartData = useMemo(() => data.map(c => ({
    ...c,
    wick: [c.low, c.high] as [number, number],
    body: [Math.min(c.open, c.close), Math.max(c.open, c.close)] as [number, number],
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

  const ToggleRow = (
    opts: { secs: number; label: string }[],
    value: number,
    onPick: (v: number) => void,
  ) => (
    <div style={{ display: 'flex', borderRadius: 4, overflow: 'hidden', border: '1px solid #333' }}>
      {opts.map(o => (
        <button
          key={o.secs}
          onClick={() => onPick(o.secs)}
          style={{
            fontSize: 10,
            padding: '2px 8px',
            cursor: 'pointer',
            border: 'none',
            background: value === o.secs ? '#374151' : 'transparent',
            color: value === o.secs ? '#fff' : '#888',
          }}
        >
          {o.label}
        </button>
      ))}
    </div>
  );

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
    <div className="chart-card" style={{ marginTop: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4, flexWrap: 'wrap', gap: 8 }}>
        <span style={{ fontSize: 11, color: '#888' }}>
          {assetInfo ? `${assetInfo.label} candles (USD)` : 'Candles (USD)'} — {data.length} bars
          {effInterval !== interval && (
            <span style={{ color: '#f5c842' }}> · auto {effInterval >= 60 ? `${Math.round(effInterval / 60)}m` : `${effInterval}s`}</span>
          )}
        </span>
        <div style={{ display: 'flex', gap: 12 }}>
          {ToggleRow(INTERVALS, interval, setInterval)}
          {ToggleRow(LOOKBACKS, lookback, setLookback)}
        </div>
      </div>
      <div style={{ height: 260 }}>
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
              {/* Wick: thin floating bar low→high */}
              <Bar dataKey="wick" barSize={1} isAnimationActive={false}>
                {chartData.map((c, i) => (
                  <Cell key={`w-${i}`} fill={c.up ? UP : DOWN} />
                ))}
              </Bar>
              {/* Body: floating bar open↔close */}
              <Bar dataKey="body" isAnimationActive={false} maxBarSize={14}>
                {chartData.map((c, i) => (
                  <Cell key={`b-${i}`} fill={c.up ? UP : DOWN} />
                ))}
              </Bar>
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}
