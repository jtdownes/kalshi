import { useEffect, useState } from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend
} from 'recharts';
import { fmtTime, Snapshot } from '../App';

interface SeriesData {
  scanned_at: string;
  yes_bid: number | null;
  no_bid: number | null;
}

interface Props {
  ticker: string;
  globalSnapshots: Snapshot[];
}

export default function PriceActionChart({ ticker, globalSnapshots }: Props) {
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

  // Update real-time
  useEffect(() => {
    if (!ticker) return;
    const latest = globalSnapshots.find(s => s.ticker === ticker);
    if (latest) {
      setData(prev => {
        // Avoid duplicates if the same timestamp is already there
        if (prev.length > 0 && prev[prev.length - 1].scanned_at === latest.scanned_at) {
          return prev;
        }
        return [...prev, {
            scanned_at: latest.scanned_at,
            yes_bid: latest.yes_bid,
            no_bid: latest.no_bid
        }].slice(-1000); // Keep a reasonable history
      });
    }
  }, [globalSnapshots, ticker]);

  if (!ticker) return null;

  return (
    <div className="price-action-chart" style={{ 
        width: '100%', 
        height: 350, 
        marginBottom: '24px', 
        background: 'rgba(255,255,255,0.03)', 
        padding: '20px', 
        borderRadius: '8px',
        border: '1px solid rgba(255,255,255,0.1)'
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '15px' }}>
        <h3 style={{ margin: 0, color: '#eee', fontSize: '16px' }}>Price Action: {ticker}</h3>
        <div style={{ fontSize: '12px', color: '#888' }}>
            {data.length} data points
        </div>
      </div>
      {loading && data.length === 0 ? (
          <div style={{ color: '#888', textAlign: 'center', paddingTop: '100px' }}>Loading chart data...</div>
      ) : (
        <ResponsiveContainer width="100%" height="90%">
          <LineChart data={data} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
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
