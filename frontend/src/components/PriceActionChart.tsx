import { useEffect, useId, useState } from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
  ReferenceLine,
  ReferenceDot,
  ReferenceArea,
} from 'recharts';
import { fmtTime, detectCryptoAsset, cryptoAssetConfig } from '../utils';
import type { Snapshot, Order } from '../types';
import type { TtcWindow } from '../utils';

interface SeriesData {
  scanned_at: string;
  yes_bid: number | null;
  no_bid: number | null;
  time_to_close_secs: number | null;
  btc_price: number | null;       // consolidated BTC multi-venue price
  brti_price: number | null;      // consolidated BTC price (BRTI proxy)
  coinbase_price: number | null;  // BTC Coinbase venue
  kraken_price: number | null;    // BTC Kraken venue
  bitstamp_price: number | null;  // BTC Bitstamp venue
  gemini_price: number | null;    // BTC Gemini venue
  eth_price: number | null;       // consolidated ETH multi-venue price
  eth_coinbase_price: number | null;
  eth_kraken_price: number | null;
  eth_bitstamp_price: number | null;
  eth_gemini_price: number | null;
  strike_str: string | null;
}

interface Props {
  ticker: string;
  globalSnapshots: Snapshot[];
  openOrders?: Order[];
  historyOrders?: Order[];
  // Time-to-close windows where a rule allowed entry; shaded grey on the charts.
  ttcWindows?: TtcWindow[];
}

function closestTs(data: SeriesData[], isoStr: string): string | null {
  if (data.length === 0) return null;
  const target = new Date(isoStr).getTime();
  return data.reduce((best, d) => {
    return Math.abs(new Date(d.scanned_at).getTime() - target) <
           Math.abs(new Date(best).getTime() - target)
      ? d.scanned_at : best;
  }, data[0].scanned_at);
}

const fmtBtc = (val: number) =>
  val >= 1000 ? `$${(val / 1000).toFixed(2)}k` : `$${val.toFixed(0)}`;

export default function PriceActionChart({ ticker, globalSnapshots, openOrders = [], historyOrders = [], ttcWindows = [] }: Props) {
  const [data, setData] = useState<SeriesData[]>([]);
  const [loading, setLoading] = useState(false);
  const [showStrikeLabel, setShowStrikeLabel] = useState(false);
  const [priceView, setPriceView] = useState<'consolidated' | 'individual'>('consolidated');
  const gradientId = `consolidatedStrikeSplit-${useId()}`;

  // Detect which crypto asset this ticker tracks (BTC, ETH, etc.)
  const assetInfo = cryptoAssetConfig(ticker);
  const assetKey = detectCryptoAsset(ticker);

  useEffect(() => {
    if (!ticker) return;
    setLoading(true);
    fetch(`/api/snapshots/series?ticker=${encodeURIComponent(ticker)}`)
      .then(r => r.json())
      .then((initialData: SeriesData[]) => {
        setData(initialData);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [ticker]);

  useEffect(() => {
    if (!ticker) return;
    const latest = globalSnapshots.find(s => s.ticker === ticker);
    if (latest) {
      setData(prev => {
        if (prev.length > 0 && prev[prev.length - 1].scanned_at === latest.scanned_at) return prev;
        return [...prev, {
          scanned_at: latest.scanned_at,
          yes_bid: latest.yes_bid,
          no_bid: latest.no_bid,
          time_to_close_secs: latest.time_to_close_secs,
          btc_price: latest.btc_price,
          brti_price: latest.brti_price,
          coinbase_price: latest.coinbase_price,
          kraken_price: latest.kraken_price,
          bitstamp_price: latest.bitstamp_price,
          gemini_price: latest.gemini_price,
          eth_price: latest.eth_price,
          eth_coinbase_price: null,
          eth_kraken_price: null,
          eth_bitstamp_price: null,
          eth_gemini_price: null,
          strike_str: latest.strike_str,
        }].slice(-1000);
      });
    }
  }, [globalSnapshots, ticker]);

  if (!ticker) return null;

  const tickerOpen = openOrders.filter(o => o.market_ticker === ticker);
  const tickerHist = historyOrders.filter(o => o.market_ticker === ticker && o.status === 'filled');

  const strike = data.find(d => d.strike_str != null)?.strike_str ?? null;
  const strikeNum = strike != null ? parseFloat(strike) : null;

  // Map each allowed time-to-close window onto the x-axis. ttc decreases over a
  // market's life, so the eligible rows form one contiguous span — shade from
  // its first to its last scanned_at.
  const ttcBands = ttcWindows.map(w => {
    let x1: string | null = null;
    let x2: string | null = null;
    for (const d of data) {
      const ttc = d.time_to_close_secs;
      if (ttc == null) continue;
      if (w.minTtc != null && ttc < w.minTtc) continue;
      if (w.maxTtc != null && ttc > w.maxTtc) continue;
      if (x1 == null) x1 = d.scanned_at;
      x2 = d.scanned_at;
    }
    return x1 != null && x2 != null ? { x1, x2 } : null;
  }).filter((b): b is { x1: string; x2: string } => b != null);

  const bandEls = ttcBands.map((b, i) => (
    <ReferenceArea
      key={`ttc-${i}`}
      x1={b.x1}
      x2={b.x2}
      fill="#94a3b8"
      fillOpacity={0.12}
      stroke="#94a3b8"
      strokeOpacity={0.25}
      ifOverflow="extendDomain"
      label={i === 0 ? { value: 'entry window', position: 'insideTopRight', fill: '#94a3b8', fontSize: 9 } : undefined}
    />
  ));

  // Venue fields per asset — defines which raw columns to read for individual-venue view
  const venueFields: { key: keyof SeriesData; label: string; color: string }[] = assetKey === 'ETH'
    ? [
        { key: 'eth_coinbase_price', label: 'Coinbase', color: '#627eea' },
        { key: 'eth_kraken_price',   label: 'Kraken',   color: '#a855f7' },
        { key: 'eth_bitstamp_price', label: 'Bitstamp', color: '#86efac' },
        { key: 'eth_gemini_price',   label: 'Gemini',   color: '#38bdf8' },
      ]
    : [
        { key: 'coinbase_price', label: 'Coinbase', color: '#f7931a' },
        { key: 'kraken_price',   label: 'Kraken',   color: '#a855f7' },
        { key: 'bitstamp_price', label: 'Bitstamp', color: '#86efac' },
        { key: 'gemini_price',   label: 'Gemini',   color: '#38bdf8' },
      ];

  // Rows appended live from globalSnapshots carry only the asset's aggregate
  // price (btc_price / eth_price), not per-venue columns — fall back to it so
  // the consolidated line extends to the latest tick instead of gapping.
  const aggKey: keyof SeriesData = assetKey === 'ETH' ? 'eth_price' : 'btc_price';

  // The API can serialize prices as numeric strings (Postgres NUMERIC →
  // Decimal → JSON string); coerce before doing math on them.
  const toNum = (v: unknown): number | null => {
    if (v == null || v === '') return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  };

  // Consolidated = mean of whichever venues responded this tick
  const chartData = data.map(d => {
    const venuePrices = venueFields
      .map(f => toNum(d[f.key]))
      .filter((p): p is number => p != null);
    const consolidated = venuePrices.length
      ? Math.round((venuePrices.reduce((a, b) => a + b, 0) / venuePrices.length) * 100) / 100
      : toNum(d[aggKey]);
    return { ...d, consolidated };
  });

  const priceDomain: [number, number] | ['auto', 'auto'] = (() => {
    const prices = data
      .flatMap(d => [...venueFields.map(f => toNum(d[f.key])), toNum(d[aggKey])])
      .filter((p): p is number => p != null);
    if (prices.length === 0) return ['auto', 'auto'];
    const candidates = strikeNum != null ? [...prices, strikeNum] : prices;
    const mn = Math.min(...candidates);
    const mx = Math.max(...candidates);
    const pad = Math.max((mx - mn) * 0.2, mn * 0.002);
    return [Math.floor(mn - pad), Math.ceil(mx + pad)];
  })();

  const btcDomain = priceDomain;  // kept for backward compat with BtcTick/BtcTooltip

  const priceTicks: number[] | undefined = (() => {
    if (priceDomain[0] === 'auto') return undefined;
    const [lo, hi] = priceDomain as [number, number];
    const range = hi - lo;
    const mag = Math.pow(10, Math.floor(Math.log10(range)));
    const step = mag * (range / mag > 5 ? 2 : 1);
    let ticks: number[] = [];
    const start = Math.ceil(lo / step) * step;
    for (let v = start; v <= hi; v += step) ticks.push(Math.round(v));
    if (strikeNum != null) {
      ticks = ticks.filter(t => Math.abs(t - strikeNum) > step * 0.45);
      ticks.push(strikeNum);
    }
    return ticks.sort((a, b) => a - b);
  })();

  // Split point for the consolidated line's green(above)/red(below)-strike
  // gradient. SVG objectBoundingBox maps offset 0 -> top (max value) and
  // offset 1 -> bottom (min value) of the line's own bounding box, so the
  // strike's fractional height within [min,max] is where the color flips.
  const consolidatedSplit: number | null = (() => {
    if (strikeNum == null) return null;
    const vals = chartData.map(d => d.consolidated).filter((p): p is number => p != null);
    if (vals.length === 0) return null;
    const mn = Math.min(...vals);
    const mx = Math.max(...vals);
    if (mx === mn) return mx >= strikeNum ? 1 : 0;
    return Math.min(1, Math.max(0, (mx - strikeNum) / (mx - mn)));
  })();
  const ABOVE = '#00d4a0';  // above strike → green
  const BELOW = '#ff4444';  // below strike → red

  const BtcTick = ({ x, y, payload }: { x?: number; y?: number; payload?: { value: number } }) => {
    if (x == null || y == null || payload == null) return null;
    const isStrike = strikeNum != null && Math.abs(payload.value - strikeNum) < 1;
    if (isStrike) {
      return (
        <g
          onMouseEnter={() => setShowStrikeLabel(true)}
          onMouseLeave={() => setShowStrikeLabel(false)}
          style={{ cursor: 'default' }}
        >
          <rect x={x - 46} y={y - 8} width={46} height={16} fill="transparent" />
          <text x={x} y={y} textAnchor="end" dominantBaseline="middle" fontSize={10} fill="#ffffff" fontWeight={700}>
            {fmtBtc(payload.value)}
          </text>
        </g>
      );
    }
    return (
      <text x={x} y={y} textAnchor="end" dominantBaseline="middle" fontSize={10} fill="#888" fontWeight={400}>
        {fmtBtc(payload.value)}
      </text>
    );
  };

  const BtcTooltip = ({ active, payload, label }: {
    active?: boolean;
    payload?: Array<{ value: number; name: string; color: string }>;
    label?: string;
  }) => {
    if (!active || !payload || payload.length === 0) return null;
    return (
      <div style={{ backgroundColor: '#1a1a1a', border: '1px solid #444', color: '#eee', borderRadius: 4, padding: '6px 10px', fontSize: 11 }}>
        <div style={{ color: '#aaa', marginBottom: 4 }}>{label != null ? fmtTime(label) : ''}</div>
        {payload.map((p, i) => {
          if (p.value == null) return null;
          const dist = strikeNum != null ? p.value - strikeNum : null;
          const swatch = p.color && !p.color.startsWith('url')
            ? p.color
            : (dist != null ? (dist >= 0 ? ABOVE : BELOW) : '#eee');
          return (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6, lineHeight: 1.5 }}>
              <span style={{ display: 'inline-block', width: 12, height: 2, background: swatch, flexShrink: 0 }} />
              <span style={{ color: swatch }}>{p.name}: ${p.value.toLocaleString()}</span>
              {dist != null && (
                <span style={{ color: dist >= 0 ? ABOVE : BELOW }}>
                  ({dist >= 0 ? '+' : '−'}${Math.abs(Math.round(dist)).toLocaleString()} to strike)
                </span>
              )}
            </div>
          );
        })}
      </div>
    );
  };

  return (
    <div className="chart-block">
      {/* header */}
      <div className="chart-head">
        <h3>Price Action: {ticker}</h3>
        <div className="chart-meta">
          {tickerOpen.length > 0 && (
            <span style={{ fontSize: 11, color: '#f5c842' }}>{tickerOpen.length} resting order{tickerOpen.length > 1 ? 's' : ''}</span>
          )}
          {strikeNum != null && (
            <span style={{ fontSize: 11, color: '#888' }}>Strike: ${strikeNum.toLocaleString()}</span>
          )}
          <span style={{ fontSize: 12, color: '#888' }}>{data.length} pts</span>
        </div>
      </div>

      {loading && data.length === 0 ? (
        <div style={{ color: '#888', textAlign: 'center', paddingTop: '100px' }}>Loading chart data...</div>
      ) : (
        <div className="chart-grid">

          {/* ── Contract price chart ── */}
          <div className="chart-card">
            <div style={{ fontSize: 11, color: '#888', marginBottom: 4 }}>Contract (¢)</div>
            <ResponsiveContainer width="100%" height="93%">
              <LineChart data={data} margin={{ top: 5, right: 10, left: 0, bottom: 5 }} syncId="priceAction">
                <CartesianGrid strokeDasharray="3 3" stroke="#333" vertical={false} />
                {bandEls}
                <XAxis
                  dataKey="scanned_at"
                  tickFormatter={fmtTime}
                  stroke="#666"
                  fontSize={10}
                  minTickGap={60}
                  tick={{ fill: '#888' }}
                />
                <YAxis
                  stroke="#666"
                  fontSize={10}
                  domain={[0, 100]}
                  tickFormatter={(val) => `${val}¢`}
                  tick={{ fill: '#888' }}
                  width={52}
                />
                <Tooltip
                  labelFormatter={fmtTime}
                  contentStyle={{ backgroundColor: '#1a1a1a', borderColor: '#444', color: '#eee', borderRadius: '4px' }}
                  itemStyle={{ fontSize: 11 }}
                />
                <Legend verticalAlign="top" height={28} iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 11 }} />

                {/* Resting orders */}
                {tickerOpen.map(o => (
                  <ReferenceLine
                    key={o.id}
                    y={o.entry_price_cents}
                    stroke={o.side === 'yes' ? '#00d4a0' : '#f97316'}
                    strokeDasharray="5 3"
                    strokeWidth={1.5}
                    label={{
                      value: `${o.side.toUpperCase()} ${o.entry_price_cents}¢`,
                      position: 'right',
                      fill: o.side === 'yes' ? '#00d4a0' : '#f97316',
                      fontSize: 9,
                    }}
                  />
                ))}

                {/* Filled order markers */}
                {tickerHist.map(o => {
                  const ts = closestTs(data, o.filled_at ?? o.placed_at);
                  if (!ts) return null;
                  const isBuy = o.order_role === 'entry';
                  const color = o.outcome === 'win'  ? '#00d4a0'
                              : o.outcome === 'loss' ? '#ff4444'
                              : '#9ca3af';
                  return (
                    <ReferenceDot
                      key={o.id}
                      x={ts}
                      y={o.entry_price_cents}
                      r={5}
                      fill={color}
                      stroke="#111"
                      strokeWidth={1}
                      label={{ value: isBuy ? 'B' : 'S', position: 'top', fill: color, fontSize: 10 }}
                    />
                  );
                })}

                <Line type="monotone" dataKey="yes_bid" name="Yes Bid" stroke="#00d4a0" dot={false} strokeWidth={2} isAnimationActive={false} connectNulls />
                <Line type="monotone" dataKey="no_bid"  name="No Bid"  stroke="#ff4444" dot={false} strokeWidth={2} isAnimationActive={false} connectNulls />
              </LineChart>
            </ResponsiveContainer>
          </div>

          {/* ── Crypto price chart ── */}
          <div className="chart-card">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
              <span style={{ fontSize: 11, color: '#888' }}>
                {assetInfo ? `${assetInfo.label} (USD)` : 'Price (USD)'}
              </span>
              <div style={{ display: 'flex', borderRadius: 4, overflow: 'hidden', border: '1px solid #333' }}>
                {(['consolidated', 'individual'] as const).map(v => (
                  <button
                    key={v}
                    onClick={() => setPriceView(v)}
                    style={{
                      fontSize: 10,
                      padding: '2px 8px',
                      cursor: 'pointer',
                      border: 'none',
                      background: priceView === v ? '#374151' : 'transparent',
                      color: priceView === v ? '#fff' : '#888',
                      textTransform: 'capitalize',
                    }}
                  >
                    {v}
                  </button>
                ))}
              </div>
            </div>
            <ResponsiveContainer width="100%" height="93%">
              <LineChart data={chartData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }} syncId="priceAction">
                {priceView === 'consolidated' && consolidatedSplit != null && (
                  <defs>
                    <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0" stopColor={ABOVE} />
                      <stop offset={consolidatedSplit} stopColor={ABOVE} />
                      <stop offset={consolidatedSplit} stopColor={BELOW} />
                      <stop offset="1" stopColor={BELOW} />
                    </linearGradient>
                  </defs>
                )}
                <CartesianGrid strokeDasharray="3 3" stroke="#333" vertical={false} />
                {bandEls}
                <XAxis
                  dataKey="scanned_at"
                  tickFormatter={fmtTime}
                  stroke="#666"
                  fontSize={10}
                  minTickGap={60}
                  tick={{ fill: '#888' }}
                />
                <YAxis
                  stroke="#666"
                  domain={btcDomain}
                  ticks={priceTicks}
                  tick={<BtcTick />}
                  width={52}
                />
                <Tooltip content={<BtcTooltip />} />
                <Legend verticalAlign="top" height={24} iconType="plainline" iconSize={12} wrapperStyle={{ fontSize: 11 }} />

                {/* Strike price line */}
                {strikeNum != null && (
                  <ReferenceLine
                    y={strikeNum}
                    stroke="#ffffff"
                    strokeDasharray="6 3"
                    strokeWidth={1}
                    label={showStrikeLabel ? {
                      value: `Strike $${strikeNum.toLocaleString()}`,
                      position: 'insideTopRight',
                      fill: '#ffffff',
                      fontSize: 10,
                    } : undefined}
                  />
                )}

                {priceView === 'consolidated'
                  ? <Line key="consolidated" type="monotone" dataKey="consolidated" name="Consolidated (avg available)" stroke={consolidatedSplit != null ? `url(#${gradientId})` : (assetInfo?.color ?? '#ffffff')} dot={false} strokeWidth={2.5} isAnimationActive={false} connectNulls />
                  : venueFields.map(vf => (
                      <Line key={vf.key as string} type="monotone" dataKey={vf.key as string} name={vf.label} stroke={vf.color} dot={false} strokeWidth={2} isAnimationActive={false} connectNulls />
                    ))
                }
              </LineChart>
            </ResponsiveContainer>
          </div>

        </div>
      )}
    </div>
  );
}
