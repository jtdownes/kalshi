import type { Snapshot, Order, Profile } from '../types'
import Snapshots from './Snapshots'

interface Props {
  snapshots: Snapshot[]
  orders?: Order[]
  openOrders?: Order[]
  profiles?: Profile[]
}

const CLIMATE_KEYWORDS = ['climate', 'weather', 'temperature', 'temp', 'rain', 'precip', 'snow', 'wind', 'humidity', 'flood']

function climateFilter(ticker: string, title: string): boolean {
  const t = title.toLowerCase()
  const k = ticker.toLowerCase()
  return CLIMATE_KEYWORDS.some(w => t.includes(w) || k.includes(w))
}

export default function MarketsClimate({ snapshots, orders = [], openOrders = [], profiles = [] }: Props) {
  return <Snapshots snapshots={snapshots} orders={orders} openOrders={openOrders} profiles={profiles} filterFn={climateFilter} />
}
