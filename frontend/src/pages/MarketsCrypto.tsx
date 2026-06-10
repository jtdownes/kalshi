import type { Snapshot, Order } from '../types'
import Snapshots from './Snapshots'
import { isCryptoMarket } from '../utils'

interface Props {
  snapshots: Snapshot[]
  orders?: Order[]
  openOrders?: Order[]
}

export default function MarketsCrypto({ snapshots, orders = [], openOrders = [] }: Props) {
  return <Snapshots snapshots={snapshots} orders={orders} openOrders={openOrders} filterFn={isCryptoMarket} />
}
