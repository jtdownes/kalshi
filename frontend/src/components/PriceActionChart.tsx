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

export default function PriceActionChart({ ticker, globalSnapshots, openOrders = [], historyOrders = [] }: Props) {
  const [data, setData] = useState<SeriesData[]>([]);
  const [loading, setLoading] = useState(false);

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
        }].slice(-1000);
      });
    }
  }, [globalSnapshots, ticker]);

  if (!ticker) return null;

  const tickerOpen  = openOrders.filter(o => o.market_ticker === ticker);
  const tickerHist  = historyOrders.filter(o => o.market_ticker === ticker && o.status !== 'resting');

  return (
    <div className="price-action-chart" style={{
      width: '100%',
      height: 380,
      marginBottom: '24px',
      background: 'rgba(255,255,255,0.03)',
      padding: '20px',
      borderRadius: '8px',
      border: '1px solid rgba(255,255,255,0.1)',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '15px' }}>
        <h3 style={{ margin: 0, color: '#eee', fontSize: '16px' }}>Price Action: {ticker}</h3>
        <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
          {tickerOpen.length > 0 && (
            <span style={{ fontSize: 11, color: '#f5c842' }}>{tickerOpen.length} resting order{tickerOpen.length > 1 ? 's' : ''}</span>
          )}
          <span style={{ fontSize: 12, color: '#888' }}>{data.length} pts</span>
        </div>
      </div>
      {loading && data.length === 0 ? (
        <div style={{ color: '#888', textAlign: 'center', paddingTop: '100px' }}>Loading chart data...</div>
      ) : (
        <ResponsiveContainer width="100%" height="90%">
          <LineChart data={data} margin={{ top: 5, right: 60, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#333" vertical={false} />
            <XAxis
              dataKey="scanned_at"
              tickFormatter={fmtTime}
              stroke="#666"
              fontSize={11}
              minTickGap={60}
              tick={{ fill: '#888' }}
            />
            <YAxis
              stroke="#666"
              fontSize={11}
              domain={[0, 100]}
              tickFormatter={(val) => `${val}\u00a2`}
              tick={{ fill: '#888' }}
            />
            <Tooltip
              labelFormatter={fmtTime}
              contentStyle={{ backgroundColor: '#1a1a1a', borderColor: '#444', color: '#eee', borderRadius: '4px' }}
              itemStyle={{ fontSize: 12 }}
            />
            <Legend verticalAlign="top" height={36} iconType="circle" />

            {/* Resting orders — horizontal dashed lines at entry price */}
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
                  fontSize: 10,
                }}
              />
            ))}

            {/* History orders — dots at placement time */}
            {tickerHist.map(o => {
              const ts = closestTs(data, o.placed_at);
              if (!ts) return null;
              const color = o.outcome === 'win' ? '#00d4a0'
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
                  label={{
                    value: o.outcome === 'win' ? 'W' : o.outcome === 'loss' ? 'L' : o.status === 'canceled' ? 'X' : '?',
                    position: 'top',
                    fill: color,
                    fontSize: 9,
                  }}
                />
              );
            })}

            <Line
              type="monotone"
              dataKey="yes_bid"
              name="Yes Bid"
              stroke="#00d4a0"
              dot={false}
              strokeWidth={2}
              isAnimationActive={false}
              connectNulls
            />
            <Line
              type="monotone"
              dataKey="no_bid"
              name="No Bid"
              stroke="#ff4444"
              dot={false}
              strokeWidth={2}
              isAnimationActive={false}
              connectNulls
            />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
