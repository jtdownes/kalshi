import { useEffect, useState } from 'react';
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
} from 'recharts';
import { fmtTime, Snapshot, Order } from '../App';

interface SeriesData {
  scanned_at: string;
  yes_bid: number | null;
  no_bid: number | null;
  btc_price: number | null;
  strike_str: string | null;
}

interface Props {
  ticker: string;
  globalSnapshots: Snapshot[];
  openOrders?: Order[];
  historyOrders?: Order[];
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

export default function PriceActionChart({ ticker, globalSnapshots, openOrders = [], historyOrders = [] }: Props) {
  const [data, setData] = useState<SeriesData[]>([]);
  const [loading, setLoading] = useState(false);
  const [showStrikeLabel, setShowStrikeLabel] = useState(false);

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
          btc_price: latest.btc_price,
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

  const btcDomain: [number, number] | ['auto', 'auto'] = (() => {
    const prices = data.map(d => d.btc_price).filter((p): p is number => p != null);
    if (prices.length === 0) return ['auto', 'auto'];
    const candidates = strikeNum != null ? [...prices, strikeNum] : prices;
    const mn = Math.min(...candidates);
    const mx = Math.max(...candidates);
    const pad = Math.max((mx - mn) * 0.2, mn * 0.002);
    return [Math.floor(mn - pad), Math.ceil(mx + pad)];
  })();

  const btcTicks: number[] | undefined = (() => {
    if (btcDomain[0] === 'auto') return undefined;
    const [lo, hi] = btcDomain as [number, number];
    const range = hi - lo;
    const step = Math.pow(10, Math.floor(Math.log10(range))) * (range / Math.pow(10, Math.floor(Math.log10(range))) > 5 ? 2 : 1);
    const ticks: number[] = [];
    const start = Math.ceil(lo / step) * step;
    for (let v = start; v <= hi; v += step) ticks.push(Math.round(v));
    if (strikeNum != null && !ticks.some(t => Math.abs(t - strikeNum) < step * 0.1)) ticks.push(strikeNum);
    return ticks.sort((a, b) => a - b);
  })();

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

  const chartStyle = {
    background: 'rgba(255,255,255,0.03)',
    padding: '16px',
    borderRadius: '8px',
    border: '1px solid rgba(255,255,255,0.1)',
  };

  return (
    <div style={{ marginBottom: '24px' }}>
      {/* header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
        <h3 style={{ margin: 0, color: '#eee', fontSize: '16px' }}>Price Action: {ticker}</h3>
        <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
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
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>

          {/* ── Contract price chart ── */}
          <div style={{ ...chartStyle, height: 320 }}>
            <div style={{ fontSize: 11, color: '#888', marginBottom: 4 }}>Contract (¢)</div>
            <ResponsiveContainer width="100%" height="93%">
              <LineChart data={data} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#333" vertical={false} />
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
                  width={36}
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

          {/* ── BTC price chart ── */}
          <div style={{ ...chartStyle, height: 320 }}>
            <div style={{ fontSize: 11, color: '#888', marginBottom: 4 }}>Bitcoin (USD)</div>
            <ResponsiveContainer width="100%" height="93%">
              <LineChart data={data} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#333" vertical={false} />
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
                  ticks={btcTicks}
                  tick={<BtcTick />}
                  width={52}
                />
                <Tooltip
                  labelFormatter={fmtTime}
                  contentStyle={{ backgroundColor: '#1a1a1a', borderColor: '#444', color: '#eee', borderRadius: '4px' }}
                  itemStyle={{ fontSize: 11 }}
                  formatter={(val: number) => [`$${val.toLocaleString()}`, 'BTC']}
                />

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

                <Line type="monotone" dataKey="btc_price" name="BTC" stroke="#f7931a" dot={false} strokeWidth={2} isAnimationActive={false} connectNulls />
              </LineChart>
            </ResponsiveContainer>
          </div>

        </div>
      )}
    </div>
  );
}
