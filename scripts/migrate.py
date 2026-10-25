import os
from pathlib import Path
import psycopg

def load_env():
    for name in ('.env.local', '.env'):
        path = Path(name)
        if path.exists():
            for line in path.read_text().splitlines():
                if '=' in line and not line.startswith('#'):
                    key, value = line.split('=', 1)
                    os.environ.setdefault(key.strip(), value.strip().strip('"'))
            return

load_env()
url = os.environ.get('DATABASE_URL_UNPOOLED') or os.environ['DATABASE_URL']
sql = Path('migrations/001_initial.sql').read_text(encoding='utf-8')
with psycopg.connect(url) as conn:
    conn.execute(sql)
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("select count(*) from information_schema.tables where table_schema='public' and table_name in ('households','damage_records','simulation_runs','governance_audit_log')")
        print({'verified_core_tables': cur.fetchone()[0]})
