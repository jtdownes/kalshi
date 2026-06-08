import type { Snapshot, Order } from '../App'
import Snapshots from './Snapshots'

interface Props {
  snapshots: Snapshot[]
  orders?: Order[]
  openOrders?: Order[]
}

function cryptoFilter(ticker: string, title: string): boolean {
  return ticker.toUpperCase().includes('BTC')
    || title.toLowerCase().includes('bitcoin')
    || title.toLowerCase().includes('btc')
}

export default function MarketsCrypto({ snapshots, orders = [], openOrders = [] }: Props) {
  return <Snapshots snapshots={snapshots} orders={orders} openOrders={openOrders} filterFn={cryptoFilter} />
}
