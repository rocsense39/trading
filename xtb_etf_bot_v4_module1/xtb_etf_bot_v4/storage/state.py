import json
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
MKT_TZ=ZoneInfo('Europe/Berlin')

class State:
    def __init__(self, path='bot_v4_state.json'):
        self.path=Path(path); self.data={'alerts':{},'daily_entry':{}}
        if self.path.exists():
            try: self.data=json.loads(self.path.read_text())
            except Exception: pass
    def save(self): self.path.write_text(json.dumps(self.data, indent=2))
    def alert_once(self,key,min_hours):
        now=pd.Timestamp.now(tz=MKT_TZ); last=self.data.setdefault('alerts',{}).get(key)
        if last:
            try:
                if (now-pd.Timestamp(last)).total_seconds()/3600 < min_hours: return False
            except Exception: pass
        self.data['alerts'][key]=now.isoformat(); self.save(); return True
    def daily_allowed(self, enabled=True):
        if not enabled: return True
        return self.data.setdefault('daily_entry',{}).get('date') != datetime.now(MKT_TZ).date().isoformat()
    def mark_daily(self,symbol):
        self.data['daily_entry']={'date':datetime.now(MKT_TZ).date().isoformat(),'symbol':symbol}; self.save()
