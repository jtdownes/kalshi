import os, psycopg2
c = psycopg2.connect(os.environ['DB_URL'])
cur = c.cursor()

cur.execute("""
select count(*) n, sum(case when outcome='win' then 1 else 0 end) wins,
       sum(count) contracts, sum(net_profit_cents)/100.0 net,
       sum(fee_cents)/100.0 fees, avg(entry_price_cents) avg_entry
from orders where status='filled' and outcome is not null
""")
print('real filled orders (all profiles):', cur.fetchone())

cur.execute("""
select placed_at::date d, count(*), sum(net_profit_cents)/100.0
from orders where status='filled' and outcome is not null
group by 1 order by 1 desc limit 12
""")
print('by day:', cur.fetchall())

cur.execute("""
select outcome, count(*), sum(net_profit_cents)/100.0, avg(entry_price_cents)
from orders where status='filled' and outcome is not null group by 1
""")
print('by outcome:', cur.fetchall())

# fee per contract on wins
cur.execute("""
select avg(fee_cents::float/nullif(count,0)) from orders where status='filled' and outcome='win'
""")
print('avg fee cents/contract (wins):', cur.fetchone())
