import type { Snapshot, Order } from '../types'
import Snapshots from './Snapshots'

interface Props {
  snapshots: Snapshot[]
  orders?: Order[]
  openOrders?: Order[]
}

function cryptoFilter(ticker: string, title: string): boolean {
  const t = ticker.toUpperCase()
  const tl = title.toLowerCase()
  return (
    t.includes('BTC') || tl.includes('bitcoin') || tl.includes('btc') ||
    t.includes('ETH') || tl.includes('ethereum') || tl.includes('eth')
  )
}

export default function MarketsCrypto({ snapshots, orders = [], openOrders = [] }: Props) {
  return <Snapshots snapshots={snapshots} orders={orders} openOrders={openOrders} filterFn={cryptoFilter} />
}
