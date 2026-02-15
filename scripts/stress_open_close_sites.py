#!/usr/bin/env python3
import json
import time
import urllib.request

BASE = 'http://127.0.0.1:8787'
SESSION = 'stress_sites'
ALLOWED = ['firefox','desktop','web_search','web_ask','model']

SITES = [
    'abrí youtube',
    'abrí chatgpt',
    'abrí gemini',
    'abrí wikipedia',
    'abrí firefox https://github.com/',
    'abrí firefox https://news.ycombinator.com/',
]


def api_chat(message: str) -> str:
    payload = {
        'message': message,
        'model': 'openai-codex/gpt-5.1-codex-mini',
        'history': [],
        'mode': 'operativo',
        'session_id': SESSION,
        'allowed_tools': ALLOWED,
        'attachments': [],
    }
    req = urllib.request.Request(
        BASE + '/api/chat',
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    return str(data.get('reply', ''))


def count_profile1_chrome() -> int:
    # Don't import psutil; use /proc via pgrep output.
    import subprocess

    try:
        proc = subprocess.run(
            ['bash', '-lc', "pgrep -af '(google-chrome|chromium).*--profile-directory=Profile 1' | wc -l"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return int((proc.stdout or '0').strip() or 0)
    except Exception:
        return -1


def main() -> None:
    print('Starting stress test: 5 rounds open+close in Chrome profile diego (Profile 1)')
    api_chat('reset ventanas web')

    for i in range(1, 6):
        print(f'Round {i}: opening {len(SITES)} sites...')
        for cmd in SITES:
            reply = api_chat(cmd)
            print('  ', cmd, '->', reply.splitlines()[0][:120])
            time.sleep(0.25)

        time.sleep(1.2)
        procs = count_profile1_chrome()
        print('  chrome_profile1_processes:', procs)

        reply = api_chat('cerrá las ventanas web que abriste')
        print('  close ->', reply.splitlines()[0][:200])
        time.sleep(0.6)

    api_chat('reset ventanas web')
    print('Stress test done.')


if __name__ == '__main__':
    main()
