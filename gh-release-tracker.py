#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gh-release-tracker.py —— 自动记录你在 GitHub 上下载的 release。

原理（GitHub 官方没有"我的下载记录"，只能本机取证）：
  1) 轮询 Edge / Chrome 的下载历史数据库（History 里的 downloads 表），
     抓到新出现的、来源含 github 的下载行（有精确时间、大小、保存路径、来源页）；
  2) 轮询指定目录，读取每个文件自带的 Mark-of-the-Web 备用数据流
     （Zone.Identifier），识别来自 github.com / release-assets / 镜像的下载。
  两者按签名去重，追加写入 JSONL 日志。

用法（无参数直接运行 = 自动模式：扫描记录 → 输出列表 → 继续监听）：
  python gh-release-tracker.py                       # 自动模式（推荐，双击 start.bat 即等价）
  python gh-release-tracker.py auto --once           # 只做一次扫描 + 输出，不进入监听
  python gh-release-tracker.py watch                 # 常驻监听（Ctrl+C 退出）
  python gh-release-tracker.py watch --once          # 只轮询一次（适合计划任务/调试）
  python gh-release-tracker.py scan                  # 一次性回填：扫描目录 + 全量读历史库
  python gh-release-tracker.py list                  # 查看已记录的下载（新→旧）
  python gh-release-tracker.py list --json out.json
  python gh-release-tracker.py check                 # 检查已下载仓库是否有新版本
  python gh-release-tracker.py check --token <PAT>   # 带令牌（提升 API 限流）

Windows 上也可以直接双击 start.bat，无需输入任何命令。

通用参数：
  --log PATH      记录文件（JSONL）。默认 ~/.gh-release-tracker/downloads.jsonl
  --dirs D1 [D2]  额外监听/扫描的目录（watch 默认只有 Downloads；scan 默认加桌面/文档）
  --interval N    watch 轮询间隔秒数（默认 15）

依赖：仅 Python 标准库（Windows / macOS / Linux 均可跑；MotW 识别仅 Windows 有效）。
"""
import argparse
import datetime
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

GITHUB = re.compile(r'github', re.I)
MIRROR = re.compile(r'github[-_]release', re.I)

HOME = os.path.expanduser('~')
DEFAULT_LOG = os.path.join(HOME, '.gh-release-tracker', 'downloads.jsonl')
DOWNLOADS = os.path.join(HOME, 'Downloads')

BROWSERS = {
    'edge': os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Microsoft', 'Edge', 'User Data'),
    'chrome': os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Google', 'Chrome', 'User Data'),
    'chromium': os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Chromium', 'User Data'),
    'brave': os.path.join(os.environ.get('LOCALAPPDATA', ''), 'BraveSoftware', 'Brave-Browser', 'User Data'),
}

# ---------------------------------------------------------------- 多语言（中文 / English）
LANG = 'zh'

_TEXT = {
    # 卡片标签
    'card_time':      ('下载时间', 'Downloaded'),
    'card_repo':      ('仓库', 'Repository'),
    'card_source':    ('来源页', 'Source'),
    'card_path':      ('保存于', 'Saved to'),
    'copy_hint':      ('└─ 复制上面 "%s" 到 GitHub 搜索框即可',
                       '└─ Copy "%s" into the GitHub search box'),
    'no_version':     ('(未记版本)', '(no version)'),
    # 通用
    'err_read':       ('  [%s/%s] 读取失败: %s', '  [%s/%s] read failed: %s'),
    'cleaned':        ('已清理 %d 个历史遗留的临时目录', 'cleaned %d leftover temp folders'),
    'none':           ('(无)', '(none)'),
    'json_written':   ('JSON 已写入 %s', 'JSON written to %s'),
    'json_written_n': ('JSON 已写入 %s（共 %d 条）', 'JSON written to %s (%d records)'),
    # 版本检查
    'err_404':        ('仓库不存在/私有/已改名 (404)', 'repo missing / private / renamed (404)'),
    'err_limit':      ('API 限流，建议加 --token <PAT>', 'API rate limited — pass --token <PAT>'),
    'check_nolog':    ('日志里还没有带仓库/版本信息的记录（先 scan 或 watch）。',
                       'No repo/version info in the log yet (run scan or watch first).'),
    'check_norepo':   ('日志里没有仓库 %s 的记录。', 'No log entries for repo %s.'),
    'check_header':   ('检查 %d 个仓库的最新版本…（未认证 60 次/小时，可 --token 提升）',
                       'Checking the latest release of %d repos... (60/h unauthenticated; use --token)'),
    'mark_latest':    ('✅已最新', '✅ up to date'),
    'mark_update':    ('⬆有更新', '⬆ update available'),
    'mark_newer':     ('⬇你下过更新版', '⬇ you have a newer build'),
    'mark_unknown':   ('？无法比较', '? cannot compare'),
    'check_failed':   ('  ✗ %s   你下过: %s   检查失败: %s',
                       '  ✗ %s   you have: %s   check failed: %s'),
    'check_line':     ('        你下过: %s   最新: %s (%s%s)',
                       '        you have: %s   latest: %s (%s%s)'),
    'prerelease':     ('，预发布', ', pre-release'),
    'check_done':     ('\n共 %d 个仓库，其中 %d 个有更新。',
                       '\nChecked %d repos: %d have updates.'),
    # 列表 / 汇总
    'summary_header': ('\n当前共 %d 条记录（新→旧）:', '\n%d records (newest first):'),
    'list_header':    ('共 %d 条记录（新→旧）\n', '%d records (newest first)\n'),
    'more_records':   ('  …（还有 %d 条，用 list 查看全部）', '  ...(%d more; run list to see all)'),
    'no_records':     ('暂无记录（日志不存在或为空: %s）', 'No records yet (log missing or empty: %s)'),
    # CLI 运行信息
    'auto_scan_done': ('自动扫描完成：本次新记录 %d 条，日志累计 %d 条 -> %s',
                       'Scan done: %d new, %d total -> %s'),
    'scan_done':      ('回填完成：本次新记录 %d 条，日志累计 %d 条 -> %s',
                       'Backfill done: %d new, %d total -> %s'),
    'new_item':       ('  [新] %s', '  [new] %s'),
    'new_record':     ('[%s] 新记录 %s', '[%s] new record %s'),
    'once_done':      ('\n单次运行结束（--once）。', '\nSingle run finished (--once).'),
    'auto_watch':     ('\n进入自动监听（%d 秒/次，Ctrl+C 退出）…',
                       '\nWatching (every %ds, Ctrl+C to stop)...'),
    'watch_start':    ('开始监听（%s 秒/次）。下载目录: %s；浏览器: %s',
                       'Watching (every %ss). Folders: %s; browsers: %s'),
    'log_line':       ('日志: %s   （Ctrl+C 退出）', 'Log: %s   (Ctrl+C to stop)'),
    'once_poll':      ('单次轮询结束（--once）。', 'Single poll finished (--once).'),
    'stopped':        ('\n已停止。', '\nStopped.'),
    # ---- GUI ----
    'app_title':      ('GitHub 下载记录器', 'GH Release Tracker'),
    'btn_scan':       ('扫描并记录', 'Scan & record'),
    'btn_watch':      ('开始监听', 'Start watching'),
    'btn_stop':       ('停止监听', 'Stop watching'),
    'btn_list':       ('查看记录', 'View records'),
    'btn_check':      ('检查新版本', 'Check updates'),
    'btn_export':     ('导出 JSON', 'Export JSON'),
    'chk_auto':       ('打开即开始监听', 'Watch on launch'),
    'lang_btn':       ('English', '中文'),
    'status_ready':   ('就绪', 'Ready'),
    'status_watching': ('监听中…（每 %d 秒检查一次）', 'Watching... (every %ds)'),
    'status_scanning': ('扫描中…', 'Scanning...'),
    'status_scan_done': ('扫描完成（%s）', 'Scan finished (%s)'),
    'status_checking': ('检查新版本中…', 'Checking for updates...'),
    'status_check_done': ('检查完成', 'Check finished'),
    'status_norepo':  ('无仓库信息', 'No repo info'),
    'status_stopped': ('已停止监听', 'Watching stopped'),
    'gui_started':    ('已启动。日志文件: %s', 'Started. Log file: %s'),
    'gui_tip':        ('提示：点「%s」找出历史下载；点「%s」以后自动记录。',
                       'Tip: click "%s" to find past downloads; click "%s" to record automatically.'),
    'gui_watch_on':   ('▶ 已开始监听。以后从 GitHub 下载软件会自动记录到这里。',
                       '▶ Watching. Anything you download from GitHub will be recorded here.'),
    'gui_watch_off':  ('⏹ 已停止监听。', '⏹ Watching stopped.'),
    'gui_scan_banner': ('\n━━ 扫描完成：本次新记录 %d 条，累计 %d 条 ━━',
                        '\n━━ Scan finished: %d new, %d total ━━'),
    'gui_more':       ('…（还有 %d 条，点「%s」看全部）', '...(%d more; click "%s" to see all)'),
    'gui_no_records': ('暂无记录。先点「%s」。', 'No records yet. Click "%s" first.'),
    'gui_norepo':     ('日志里还没有仓库/版本信息，先点「%s」。',
                       'No repo info in the log yet - click "%s" first.'),
    'gui_watch_error': ('监听出错: %s', 'Watch error: %s'),
    'gui_error':      ('出错: %s', 'Error: %s'),
    'gui_export_title': ('导出', 'Export'),
    'gui_export_none': ('暂无记录可导出。', 'No records to export.'),
    'gui_export_filter': ('JSON 文件', 'JSON file'),
    'gui_export_name': ('我的下载记录.json', 'my-downloads.json'),
    'gui_export_done': ('已导出 %d 条记录到:\n%s', 'Exported %d records to:\n%s'),
    'gui_lang_switched': ('界面语言已切换为中文。', 'UI language switched to English.'),
}


def set_lang(lang):
    """设置输出语言：'zh' 或 'en'。"""
    global LANG
    LANG = 'en' if str(lang or '').lower().startswith('en') else 'zh'


def t(key, *args):
    """取当前语言的文案；带参数时做 % 格式化。"""
    pair = _TEXT.get(key)
    if not pair:
        return key
    s = pair[1] if LANG == 'en' else pair[0]
    return s % args if args else s


def _dw(s):
    """字符串显示宽度（中日韩全角字符算 2 列）。"""
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1 for c in s)


def _pad(s, width):
    return s + ' ' * max(0, width - _dw(s))



# ---------------------------------------------------------------- 通用工具
def eprint(*a, **kw):
    print(*a, file=sys.stderr, **kw)


def chrome_time(us):
    if not us:
        return ''
    try:
        return (datetime.datetime(1601, 1, 1) + datetime.timedelta(microseconds=us)).strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        return ''


def now_str():
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def repo_tag(url):
    m = re.search(r'github\.com/([^/\s]+/[^/\s]+)/releases/tag/([^/?#\s]+)', url or '')
    if m:
        return m.group(1), urllib.parse.unquote(m.group(2))
    m = re.search(r'github\.com/([^/\s]+/[^/\s]+)/releases/download/([^/]+)/', url or '')
    if m:
        return m.group(1), urllib.parse.unquote(m.group(2))
    m = re.search(r'github\.com/([^/\s]+/[^/\s]+)', url or '')
    if m:
        return m.group(1), ''
    return '', ''


def asset_name(host):
    m = re.search(r'filename%3D([^&]+)', host or '')
    if m:
        return urllib.parse.unquote_plus(m.group(1))
    m = re.search(r'filename=([^&]+)', host or '')
    if m:
        return urllib.parse.unquote_plus(m.group(1))
    m = re.search(r'github\.com/([^?]+)', host or '')
    if m:
        return m.group(1).rstrip('/').rsplit('/', 1)[-1]
    return ''


def norm_name(n):
    """去掉浏览器重复下载加的数字后缀（如 'file (1).exe'），用于比对。"""
    n = os.path.basename(n or '')
    return re.sub(r' \(\d+\)(?=\.|$)', '', n).lower()


# ---------------------------------------------------------------- 途径 1：MotW
def read_zone(path):
    try:
        with open(path + ':Zone.Identifier', 'r', encoding='utf-8', errors='replace') as fh:
            return fh.read()
    except OSError:
        return None


def parse_zone(text):
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text or '')
    host = re.search(r'HostUrl=([^\r\n]+)', text)
    ref = re.search(r'ReferrerUrl=([^\r\n]+)', text)
    return (host.group(1).strip() if host else '',
            ref.group(1).strip() if ref else '')


def motw_records(dirs):
    out = []
    for root in dirs:
        if not os.path.isdir(root):
            continue
        for dirpath, _dn, filenames in os.walk(root, onerror=lambda e: None):
            for name in filenames:
                full = os.path.join(dirpath, name)
                text = read_zone(full)
                if not text or not (GITHUB.search(text) or MIRROR.search(text)):
                    continue
                host, ref = parse_zone(text)
                if not (GITHUB.search(host) or GITHUB.search(ref) or MIRROR.search(host) or MIRROR.search(ref)):
                    continue
                asset = asset_name(host)
                rel = os.path.relpath(full, root)
                depth = rel.count(os.sep)
                if asset and norm_name(asset) != norm_name(name):
                    continue          # 名字对不上：解压出来的内部文件
                if depth > 0 and not asset:
                    continue          # 嵌套且无资产名：解压内部文件
                repo, tag = repo_tag(ref or host)
                try:
                    st = os.stat(full)
                except OSError:
                    continue
                out.append({
                    'source': 'motw',
                    'filename': asset_name(host) or name,
                    'path': full,
                    'repo': repo,
                    'tag': tag,
                    'referrer': ref,
                    'host_url': host,
                    'downloaded_at': datetime.datetime.fromtimestamp(st.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                    'size_bytes': st.st_size,
                    'sig': 'motw|%s|%d|%d' % (full, int(st.st_mtime * 1000), st.st_size),
                })
    return out


# ---------------------------------------------------------------- 途径 2：浏览器历史库
def open_history(path):
    """复制 History(+wal/shm) 到临时目录再打开，绕开浏览器文件锁并含最新 WAL 数据。
    返回 (connection, tmpdir)；调用方读完必须删掉 tmpdir，否则会堆积大量浏览器数据副本。"""
    tmpdir = tempfile.mkdtemp(prefix='ghrt-')
    tmp = os.path.join(tmpdir, os.path.basename(path))
    try:
        shutil.copy2(path, tmp)
        for suffix in ('-wal', '-shm'):
            if os.path.exists(path + suffix):
                shutil.copy2(path + suffix, tmp + suffix)
        return sqlite3.connect(tmp), tmpdir
    except Exception:
        shutil.rmtree(tmpdir, ignore_errors=True)
        try:
            return sqlite3.connect('file:%s?immutable=1' % path.replace('\\', '/'), uri=True), None
        except Exception:
            raise


def cleanup_temp_dirs(max_age=3600):
    """兜底清理：删除本程序遗留的临时目录（正常用完即删，这里处理崩溃残留）。
    只删超过 max_age 秒的，避免影响正在运行的实例。返回清理数量。"""
    root = tempfile.gettempdir()
    now = time.time()
    removed = 0
    try:
        names = os.listdir(root)
    except OSError:
        return 0
    for name in names:
        if not name.startswith('ghrt-'):
            continue
        p = os.path.join(root, name)
        try:
            if now - os.path.getmtime(p) > max_age:
                shutil.rmtree(p, ignore_errors=True)
                removed += 1
        except OSError:
            pass
    return removed


def browser_records(browsers):
    out = []
    for name, base in browsers.items():
        if not base or not os.path.isdir(base):
            continue
        for profile in sorted(os.listdir(base)):
            hist = os.path.join(base, profile, 'History')
            if not os.path.isfile(hist):
                continue
            con = tmpdir = None
            try:
                con, tmpdir = open_history(hist)
                rows = con.execute(
                    "select target_path, tab_url, site_url, referrer, start_time, total_bytes, state"
                    " from downloads order by start_time").fetchall()
            except Exception as exc:
                eprint(t('err_read', name, profile, exc))
                continue
            finally:
                # 关键：读完立即删掉临时副本，否则会堆积成千上万个浏览器数据副本
                if con is not None:
                    try:
                        con.close()
                    except Exception:
                        pass
                if tmpdir:
                    shutil.rmtree(tmpdir, ignore_errors=True)
            for target, tab_url, site_url, referrer, start, size, state in rows:
                blob = ' '.join(x or '' for x in (target, tab_url, site_url, referrer))
                if not GITHUB.search(blob):
                    continue
                # 只记确实落盘的下载：state==1(完成)无条件保留；
                # 其它状态仅当最终文件真实存在才保留（Edge 常把已下好的记成 state=2）
                if state != 1 and not (target and os.path.exists(target)):
                    continue
                # 仓库/版本取第一个能解析出 github 的 URL：referrer -> tab_url -> site_url
                repo = tag = ''
                for u in (referrer, tab_url, site_url):
                    repo, tag = repo_tag(u)
                    if repo:
                        break
                out.append({
                    'source': name,
                    'filename': os.path.basename(target or ''),
                    'path': target or '',
                    'repo': repo,
                    'tag': tag,
                    'referrer': referrer or '',
                    'tab_url': tab_url or '',
                    'host_url': tab_url or referrer or site_url or '',
                    'downloaded_at': chrome_time(start),
                    'size_bytes': size or 0,
                    'sig': '%s|%s|%d|%d' % (name, target or '', start or 0, size or 0),
                })
    return out


# ---------------------------------------------------------------- 日志读写
def load_signatures(log):
    sigs = set()
    if not os.path.isfile(log):
        return sigs
    try:
        with open(log, 'r', encoding='utf-8') as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                p = os.path.normcase(os.path.abspath(r.get('path') or ''))
                if p:
                    sigs.add('file|%s|%d' % (p, r.get('size_bytes') or 0))
    except OSError:
        pass
    return sigs


def append_records(log, records, sigs):
    newly = []
    if not records:
        return newly
    d = os.path.dirname(log)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(log, 'a', encoding='utf-8') as fh:
        for r in records:
            sig = r['sig']
            if sig in sigs:
                continue
            sigs.add(sig)
            line = dict(r)
            line['recorded_at'] = now_str()
            line.pop('sig', None)
            fh.write(json.dumps(line, ensure_ascii=False) + '\n')
            newly.append(line)
    return newly


def repo_label(r):
    """仓库 + 版本 的展示文本；没有仓库信息则返回空串。"""
    repo = (r.get('repo') or '').strip()
    tag = (r.get('tag') or '').strip()
    if not repo:
        return ''
    return repo + ((' @ ' + tag) if tag else '')


def fmt_line(r):
    """紧凑单行（用于 [新记录] 等实时日志）。"""
    size = ' %.1f MB' % (r['size_bytes'] / 1048576.0) if r.get('size_bytes') else ''
    s = '%s  %-6s %s' % (r.get('downloaded_at') or '?', r.get('source', ''), r.get('filename', ''))
    repo = repo_label(r)
    if repo:
        s += '  【%s】' % repo
    return s + size


def pretty_card(r):
    """多行卡片：把仓库(owner/repo)单独成行突出显示，并提示可复制到 GitHub 搜索框。"""
    sep = '\u2500' * 70
    labels = [t('card_time'), t('card_repo'), t('card_source'), t('card_path')]
    w = max(_dw(x) for x in labels)
    name = r.get('filename') or ''
    size = '  %.1f MB' % (r['size_bytes'] / 1048576.0) if r.get('size_bytes') else ''
    lines = [sep, '  %s%s' % (name, size)]
    if r.get('downloaded_at'):
        lines.append('    %s : %s' % (_pad(t('card_time'), w), r['downloaded_at']))
    repo = (r.get('repo') or '').strip()
    if repo:
        lines.append('    %s : %s' % (_pad(t('card_repo'), w), repo_label(r)))
        lines.append('%s%s' % (' ' * (7 + w), t('copy_hint', repo)))
    if r.get('referrer') or r.get('host_url'):
        lines.append('    %s : %s' % (_pad(t('card_source'), w), r.get('referrer') or r.get('host_url') or ''))
    if r.get('path'):
        lines.append('    %s : %s' % (_pad(t('card_path'), w), r['path']))
    lines.append(sep)
    return '\n'.join(lines)


def merge_by_path(records):
    """同一文件可能同时被浏览器历史库和 MotW 抓到，按路径合并为一条（浏览器信息优先，MotW 补直链）。"""
    merged = {}
    order = []
    for r in records:
        key = os.path.normcase(os.path.abspath(r.get('path') or '')) or r['sig']
        if key in merged:
            base = merged[key]
            if r.get('repo') and not base.get('repo'):
                base['repo'], base['tag'] = r['repo'], r['tag']
            if r.get('tag') and not base.get('tag'):
                base['tag'] = r['tag']
            if r.get('referrer') and not base.get('referrer'):
                base['referrer'] = r['referrer']
            if r.get('tab_url') and not base.get('tab_url'):
                base['tab_url'] = r['tab_url']
            if r.get('host_url') and not base.get('host_url'):
                base['host_url'] = r['host_url']
            base['size_bytes'] = max(base.get('size_bytes') or 0, r.get('size_bytes') or 0)
            srcs = set(base.get('sources') or [base.get('source')])
            srcs.add(r.get('source'))
            base['sources'] = sorted(srcs)
            base['source'] = ' + '.join(sorted(srcs))
        else:
            r['sources'] = [r['source']]
            merged[key] = r
            order.append(key)
    out = []
    for key in order:
        m = merged[key]
        p = os.path.normcase(os.path.abspath(m.get('path') or ''))
        m['sig'] = 'file|%s|%d' % (p, m.get('size_bytes') or 0)
        out.append(m)
    return out


# ---------------------------------------------------------------- 版本检查
def read_records(log):
    rows = []
    if not os.path.isfile(log):
        return rows
    try:
        with open(log, 'r', encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except Exception:
                        continue
    except OSError:
        pass
    return rows


def version_key(tag):
    """把 tag 拆成 (数字元组, 后缀)，无法解析返回 None。"""
    s = re.sub(r'^[vV]', '', (tag or '').strip())
    m = re.match(r'(\d+(?:\.\d+)*)(.*)$', s)
    if not m:
        return None
    return (tuple(int(x) for x in m.group(1).split('.')), m.group(2))


def cmp_version(a, b):
    """比较两个版本：>0 表示 a 更新；返回 None 表示无法比较。"""
    ka, kb = version_key(a), version_key(b)
    if ka is None or kb is None:
        return None
    na, ra = ka
    nb, rb = kb
    for i in range(max(len(na), len(nb))):
        x = na[i] if i < len(na) else 0
        y = nb[i] if i < len(nb) else 0
        if x != y:
            return 1 if x > y else -1
    if ra == rb:
        return 0
    if ra and not rb:
        return -1
    if rb and not ra:
        return 1
    return 0


def github_latest(repo, token=None):
    url = 'https://api.github.com/repos/%s/releases/latest' % repo
    req = urllib.request.Request(url, headers={
        'User-Agent': 'gh-release-tracker',
        'Accept': 'application/vnd.github+json',
    })
    if token:
        req.add_header('Authorization', 'Bearer ' + token)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        return {'ok': True,
                'tag': data.get('tag_name') or '',
                'name': data.get('name') or data.get('tag_name') or '',
                'url': data.get('html_url') or '',
                'published': (data.get('published_at') or '')[:10],
                'prerelease': bool(data.get('prerelease'))}
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {'ok': False, 'error': t('err_404')}
        if e.code in (403, 429):
            return {'ok': False, 'error': t('err_limit')}
        return {'ok': False, 'error': 'HTTP %s' % e.code}
    except Exception as e:
        return {'ok': False, 'error': '%s' % e}


def cmd_check(args):
    records = read_records(args.log)
    repos = {}
    for r in records:
        repo = (r.get('repo') or '').strip()
        if repo:
            repos.setdefault(repo, set()).add(r.get('tag') or '')
    if not repos:
        print(t('check_nolog'))
        return

    order = sorted(repos)
    if getattr(args, 'repo', None):
        wanted = args.repo.strip('/')
        order = [x for x in order if x == wanted or x.endswith('/' + wanted)]
        if not order:
            print(t('check_norepo', args.repo))
            return

    print(t('check_header', len(order)))
    results = []
    n_up = 0
    for repo in order:
        tags = sorted(t for t in repos[repo] if t)
        latest = github_latest(repo, getattr(args, 'token', None))
        entry = {'repo': repo, 'have': tags, 'latest': latest}

        if not latest.get('ok'):
            entry['status'] = 'error'
        elif not tags:
            entry['status'] = 'unknown'
        else:
            ltag = latest['tag']
            if ltag in tags:
                entry['status'] = 'latest'
            else:
                # 用我下过的"数值最大"版本去比
                best = tags[0]
                for t in tags[1:]:
                    r = cmp_version(t, best)
                    if r is not None and r > 0:
                        best = t
                c = cmp_version(ltag, best)
                if c is None:
                    entry['status'] = 'unknown'
                elif c > 0:
                    entry['status'] = 'update'
                elif c < 0:
                    entry['status'] = 'have_newer'
                else:
                    entry['status'] = 'latest'
        if entry['status'] == 'update':
            n_up += 1
        results.append(entry)

        have = ', '.join(tags) if tags else t('no_version')
        if entry['status'] == 'error':
            print(t('check_failed', repo, have, latest.get('error')))
            continue
        mark = {'latest': t('mark_latest'), 'update': t('mark_update'),
                'have_newer': t('mark_newer'), 'unknown': t('mark_unknown')}[entry['status']]
        print('  %s %s' % (mark, repo))
        print(t('check_line', have, latest['tag'] or '?', latest.get('published') or '?',
                t('prerelease') if latest.get('prerelease') else ''))
        if latest.get('url'):
            print('        %s' % latest['url'])

    print(t('check_done', len(results), n_up))
    if getattr(args, 'json', None):
        with open(args.json, 'w', encoding='utf-8') as fh:
            json.dump(results, fh, ensure_ascii=False, indent=2)
        print(t('json_written', args.json))


# ---------------------------------------------------------------- 自动模式
def _print_summary(log, limit=10):
    rows = read_records(log)
    rows.sort(key=lambda r: r.get('downloaded_at') or '', reverse=True)
    print(t('summary_header', len(rows)))
    for r in rows[:limit]:
        print(pretty_card(r))
        print()
    if len(rows) > limit:
        print(t('more_records', len(rows) - limit))


def cmd_auto(args):
    """无参数运行：先扫描记录，再输出当前列表，然后进入常驻监听。"""
    sigs = load_signatures(args.log)
    recs = merge_by_path(browser_records(BROWSERS) + motw_records(args.dirs))
    new = append_records(args.log, recs, sigs)
    print(t('auto_scan_done', len(new), len(sigs), args.log))
    for r in new:
        print(t('new_item', fmt_line(r)))
    _print_summary(args.log)
    if getattr(args, 'once', False):
        print(t('once_done'))
        return
    print(t('auto_watch', args.interval))
    while True:
        recs = merge_by_path(browser_records(BROWSERS) + motw_records(args.dirs))
        for r in append_records(args.log, recs, sigs):
            print(t('new_record', now_str(), fmt_line(r)))
        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
            print(t('stopped'))
            return


# ---------------------------------------------------------------- 子命令
def cmd_scan(args):
    sigs = load_signatures(args.log)
    recs = browser_records(BROWSERS) + motw_records(args.dirs)
    recs = merge_by_path(recs)
    new = append_records(args.log, recs, sigs)
    print(t('scan_done', len(new), len(sigs), args.log))
    for r in new:
        print('  ' + fmt_line(r))


def cmd_watch(args):
    sigs = load_signatures(args.log)
    print(t('watch_start', args.interval, ', '.join(args.dirs) or t('none'), ', '.join(BROWSERS)))
    print(t('log_line', args.log))
    while True:
        recs = browser_records(BROWSERS) + motw_records(args.dirs)
        recs = merge_by_path(recs)
        new = append_records(args.log, recs, sigs)
        for r in new:
            print(t('new_record', now_str(), fmt_line(r)))
        if args.once:
            print(t('once_poll'))
            return
        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
            print(t('stopped'))
            return


def cmd_list(args):
    rows = read_records(args.log)
    if not rows:
        print(t('no_records', args.log))
        return
    rows.sort(key=lambda r: r.get('downloaded_at') or '', reverse=True)
    if args.json:
        with open(args.json, 'w', encoding='utf-8') as fh:
            json.dump(rows, fh, ensure_ascii=False, indent=2)
        print(t('json_written_n', args.json, len(rows)))
        return
    print(t('list_header', len(rows)))
    for r in rows:
        print(pretty_card(r))
        print()


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--log', default=argparse.SUPPRESS)
    common.add_argument('--dirs', nargs='*', default=argparse.SUPPRESS)
    common.add_argument('--interval', type=int, default=argparse.SUPPRESS)
    common.add_argument('--lang', choices=['zh', 'en'], default=argparse.SUPPRESS, help='output language / 输出语言')

    p = argparse.ArgumentParser(description='自动记录你在 GitHub 上下载的 release', parents=[common])
    sub = p.add_subparsers(dest='cmd')

    sa = sub.add_parser('auto', help='自动：先扫描记录，再输出列表，然后继续监听（无参数时默认）', parents=[common])
    sa.add_argument('--once', action='store_true', help='只做一次扫描+输出，不进入监听')
    sa.set_defaults(func=cmd_auto)

    sp = sub.add_parser('scan', help='一次性回填（扫描目录 + 全量读浏览器历史库）', parents=[common])
    sp.set_defaults(func=cmd_scan)

    sw = sub.add_parser('watch', help='常驻监听新下载', parents=[common])
    sw.add_argument('--once', action='store_true', help='只轮询一次')
    sw.set_defaults(func=cmd_watch)

    sl = sub.add_parser('list', help='查看记录', parents=[common])
    sl.add_argument('--json', help='导出为 JSON')
    sl.set_defaults(func=cmd_list)

    sc = sub.add_parser('check', help='检查已下载仓库是否有新版本', parents=[common])
    sc.add_argument('--token', help='GitHub 个人访问令牌，提升 API 限流')
    sc.add_argument('--repo', help='只检查某个仓库（owner/repo 或 repo）')
    sc.add_argument('--json', help='导出为 JSON')
    sc.set_defaults(func=cmd_check)

    args = p.parse_args()
    if args.cmd is None:
        args.cmd = 'auto'
        args.func = cmd_auto
        args.once = False

    args.log = getattr(args, 'log', DEFAULT_LOG)
    set_lang(getattr(args, 'lang', None) or os.environ.get('GHRT_LANG') or 'zh')
    args.interval = getattr(args, 'interval', 15)

    # 目录默认值：watch 只盯 Downloads（浏览器存哪都能被历史库覆盖），scan 多扫桌面/文档
    dirs = getattr(args, 'dirs', None)
    if dirs is None:
        if args.cmd == 'scan':
            dirs = [DOWNLOADS,
                    os.path.join(HOME, 'Desktop'),
                    os.path.join(HOME, 'Documents')]
        else:
            dirs = [DOWNLOADS]
    args.dirs = [os.path.abspath(d) for d in dirs if os.path.isdir(d)]

    # 兜底清理历史遗留的临时目录（崩溃残留）
    n = cleanup_temp_dirs()
    if n:
        eprint(t('cleaned', n))

    args.func(args)


if __name__ == '__main__':
    main()
