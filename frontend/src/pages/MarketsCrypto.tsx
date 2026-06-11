import type { Snapshot, Order, Profile } from '../types'
import Snapshots from './Snapshots'
import { isCryptoMarket } from '../utils'

interface Props {
  snapshots: Snapshot[]
  orders?: Order[]
  openOrders?: Order[]
  profiles?: Profile[]
}

export default function MarketsCrypto({ snapshots, orders = [], openOrders = [], profiles = [] }: Props) {
  return <Snapshots snapshots={snapshots} orders={orders} openOrders={openOrders} profiles={profiles} filterFn={isCryptoMarket} />
}
