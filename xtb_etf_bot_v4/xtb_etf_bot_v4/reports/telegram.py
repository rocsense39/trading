import os, re, requests

def clean_html(s):
    return re.sub(r'</?b>','',s).replace('&lt;','<').replace('&gt;','>')

def send(message: str) -> bool:
    token=(os.getenv('TELEGRAM_TOKEN') or os.getenv('BOT_TOKEN') or '').strip()
    chat_id=(os.getenv('TELEGRAM_CHAT_ID') or os.getenv('CHAT_ID') or '').strip()
    if not token or not chat_id:
        print('Telegram credentials missing. Message below:\n')
        print(clean_html(message))
        return False
    try:
        r=requests.post(f'https://api.telegram.org/bot{token}/sendMessage', json={'chat_id':chat_id,'text':message,'parse_mode':'HTML','disable_web_page_preview':True}, timeout=15)
        if r.status_code==200: return True
        r=requests.post(f'https://api.telegram.org/bot{token}/sendMessage', json={'chat_id':chat_id,'text':clean_html(message)}, timeout=15)
        return r.status_code==200
    except Exception as e:
        print('Telegram error:',e); return False
