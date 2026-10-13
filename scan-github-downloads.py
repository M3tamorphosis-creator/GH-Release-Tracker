#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scan-github-downloads.py —— 找出本机从 GitHub Releases 下载过的文件。

三条取证途径：
  途径 1  Windows Mark-of-the-Web：文件上的 Zone.Identifier 备用数据流
          记录了 HostUrl（真实下载直链，GitHub 的 release-assets 签名链接里带 assets 名字）
          和 ReferrerUrl（来源页面，通常是 .../releases/tag/<tag>）
  途径 2  Chromium 系浏览器（Edge / Chrome）History 数据库的 downloads 表
  途径 3  Firefox places.sqlite 里 downloads/* 注解

用法：
    python scan-github-downloads.py                # 扫描默认目录（下载/桌面/文档）
    python scan-github-downloads.py D:\\ E:\\       # 追加要扫描的目录
    python scan-github-downloads.py --json out.json
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
import urllib.parse

GITHUB_HOST = re.compile(r'github', re.I)
MIRROR_HINT = re.compile(r'github[-_]release', re.I)

DEFAULT_ROOTS = [
    os.path.join(os.path.expanduser('~'), 'Downloads'),
    os.path.join(os.path.expanduser('~'), 'Desktop'),
    os.path.join(os.path.expanduser('~'), 'Documents'),
    os.path.join(os.path.expanduser('~'), 'OneDrive', 'Desktop'),
    os.path.join(os.path.expanduser('~'), 'OneDrive', 'Documents'),
]


# ---------------------------------------------------------------- 途径 1
def read_zone(path):
    """读取 NTFS 备用数据流 Zone.Identifier（Mark-of-the-Web）。"""
    try:
        with open(path + ':Zone.Identifier', 'r', encoding='utf-8', errors='replace') as fh:
            return fh.read()
    except OSError:
        return None


def parse_zone(text):
    # 有些浏览器会写入被截断的 HostUrl（后面跟 NUL），先清掉控制字符
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text or '')
    host = re.search(r'HostUrl=([^\r\n]+)', text)
    ref = re.search(r'ReferrerUrl=([^\r\n]+)', text)
    return (host.group(1).strip() if host else '',
            ref.group(1).strip() if ref else '')


def asset_name(host):
    """从下载直链里还原 release 资产名。"""
    m = re.search(r'filename%3D([^&]+)', host)
    if m:
        return urllib.parse.unquote_plus(m.group(1))
    m = re.search(r'filename=([^&]+)', host)
    if m:
        return urllib.parse.unquote_plus(m.group(1))
    m = re.search(r'github\.com/([^?]+)', host)
    if m:
        return m.group(1).rstrip('/').rsplit('/', 1)[-1]
    return ''


def repo_tag(url):
    """从 releases 页面 / 直链里解析出 owner/repo 和 tag。"""
    m = re.search(r'github\.com/([^/]+/[^/]+)/releases/tag/([^/?#]+)', url)
    if m:
        return m.group(1), urllib.parse.unquote(m.group(2))
    m = re.search(r'github\.com/([^/]+/[^/]+)/releases/download/([^/]+)/', url)
    if m:
        return m.group(1), urllib.parse.unquote(m.group(2))
    m = re.search(r'github\.com/([^/]+/[^/]+)', url)
    if m:
        return m.group(1), ''
    return '', ''


def scan_motw(roots):
    hits = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, _dirnames, filenames in os.walk(root, onerror=lambda e: None):
            for name in filenames:
                full = os.path.join(dirpath, name)
                text = read_zone(full)
                if not text or not GITHUB_HOST.search(text):
                    continue
                host, ref = parse_zone(text)
                if not (GITHUB_HOST.search(host) or GITHUB_HOST.search(ref)
                        or MIRROR_HINT.search(host) or MIRROR_HINT.search(ref)):
                    continue
                repo, tag = repo_tag(ref or host)
                try:
                    mtime = os.path.getmtime(full)
                except OSError:
                    mtime = 0
                hits.append({
                    'source': 'MOTW',
                    'asset': asset_name(host) or name,
                    'file': name,
                    'path': full,
                    'date': datetime.datetime.fromtimestamp(mtime).strftime('%Y-%m-%d') if mtime else '',
                    'repo': repo,
                    'tag': tag,
                    'host_url': host,
                    'referrer': ref,
                })
    return hits


# ---------------------------------------------------------------- 途径 2
def chrome_time(us):
    if not us:
        return ''
    try:
        return (datetime.datetime(1601, 1, 1) + datetime.timedelta(microseconds=us)).strftime('%Y-%m-%d %H:%M')
    except Exception:
        return ''


def open_sqlite(path):
    """先复制再打开，避免被正在运行的浏览器锁住；失败则用 immutable 只读模式。"""
    tmp = os.path.join(tempfile.mkdtemp(prefix='ghscan-'), os.path.basename(path))
    try:
        shutil.copy2(path, tmp)
        for suffix in ('-wal', '-shm'):
            if os.path.exists(path + suffix):
                shutil.copy2(path + suffix, tmp + suffix)
        return sqlite3.connect(tmp)
    except Exception:
        return sqlite3.connect('file:%s?immutable=1' % path.replace('\\', '/'), uri=True)


def scan_chromium():
    hits = []
    local = os.environ.get('LOCALAPPDATA', '')
    bases = {
        'Edge': os.path.join(local, 'Microsoft', 'Edge', 'User Data'),
        'Chrome': os.path.join(local, 'Google', 'Chrome', 'User Data'),
        'Chromium': os.path.join(local, 'Chromium', 'User Data'),
        'Brave': os.path.join(local, 'BraveSoftware', 'Brave-Browser', 'User Data'),
    }
    for browser, base in bases.items():
        if not os.path.isdir(base):
            continue
        for profile in sorted(os.listdir(base)):
            hist = os.path.join(base, profile, 'History')
            if not os.path.isfile(hist):
                continue
            try:
                con = open_sqlite(hist)
                rows = con.execute(
                    "select target_path, tab_url, site_url, referrer, start_time, total_bytes , state"
                    " from downloads order by start_time desc").fetchall()
            except Exception as exc:
                print('  [%s/%s] 读取失败: %s' % (browser, profile, exc), file=sys.stderr)
                continue
            finally:
                try:
                    con.close()
                except Exception:
                    pass
            for target, tab_url, site_url, referrer, start, size, state in rows:
                blob = ' '.join(x or '' for x in (target, tab_url, site_url, referrer))
                if not GITHUB_HOST.search(blob):
                    continue
                repo, tag = repo_tag(tab_url or site_url or referrer)
                hits.append({
                    'source': '%s 下载历史' % browser,
                    'asset': os.path.basename(target or ''),
                    'file': os.path.basename(target or ''),
                    'path': target or '',
                    'date': chrome_time(start),
                    'size_mb': round((size or 0) / 1048576.0, 2),
                    'repo': repo,
                    'tag': tag,
                    'host_url': tab_url or '',
                    'referrer': referrer or site_url or '',
                    'state': state,
                })
    return hits


# ---------------------------------------------------------------- 途径 3
def scan_firefox():
    hits = []
    appdata = os.environ.get('APPDATA', '')
    profiles = os.path.join(appdata, 'Mozilla', 'Firefox', 'Profiles')
    if not os.path.isdir(profiles):
        return hits
    for profile in sorted(os.listdir(profiles)):
        places = os.path.join(profiles, profile, 'places.sqlite')
        if not os.path.isfile(places):
            continue
        try:
            con = open_sqlite(places)
            rows = con.execute(
                "select a.content, n.name, p.url from moz_annos a"
                " join moz_anno_attributes n on n.id = a.anno_attribute_id"
                " join moz_places p on p.id = a.place_id"
                " where n.name like 'downloads/%'").fetchall()
            con.close()
        except Exception as exc:
            print('  [Firefox/%s] 读取失败: %s' % (profile, exc), file=sys.stderr)
            continue
        for content, annoname, pageurl in rows:
            blob = '%s %s %s' % (content or '', pageurl or '', annoname or '')
            if not GITHUB_HOST.search(blob):
                continue
            dest, ref, url = '', '', ''
            if annoname.endswith('destinationFileURI'):
                dest = urllib.parse.unquote((content or '').replace('file:///', ''))
            else:
                try:
                    meta = json.loads(content or '{}')
                    url = meta.get('url', '')
                    ref = meta.get('referrer', '')
                except Exception:
                    pass
            repo, tag = repo_tag(ref or url or pageurl or '')
            hits.append({
                'source': 'Firefox 下载历史',
                'asset': os.path.basename(dest) if dest else (url.rsplit('/', 1)[-1] if url else ''),
                'file': os.path.basename(dest) if dest else '',
                'path': dest,
                'date': '',
                'repo': repo,
                'tag': tag,
                'host_url': url,
                'referrer': ref or pageurl or '',
            })
    return hits


# ---------------------------------------------------------------- 汇总
def dedupe(hits):
    """同一资产的多次出现（解压出来的副本、重复下载）合并为一条。"""
    groups = {}
    for hit in hits:
        # 只按资产名合并：同一资产可能只有一条记录带得出仓库信息
        key = (hit.get('asset') or hit.get('file') or hit.get('referrer', '')).lower()
        if not key:
            key = hit.get('referrer', '')
        entry = groups.setdefault(key, {
            'asset': hit.get('asset') or hit.get('file'),
            'repo': hit.get('repo', ''),
            'tag': hit.get('tag', ''),
            'referrer': hit.get('referrer', ''),
            'dates': [],
            'sources': [],
            'paths': [],
        })
        if hit.get('date'):
            entry['dates'].append(hit['date'])
        entry['sources'].append(hit['source'])
        if hit.get('path') and hit['path'] not in entry['paths']:
            entry['paths'].append(hit['path'])
        if not entry['tag'] and hit.get('tag'):
            entry['tag'] = hit['tag']
        if not entry['referrer'] and hit.get('referrer'):
            entry['referrer'] = hit['referrer']
    out = []
    for entry in groups.values():
        entry['date'] = min(entry['dates']) if entry['dates'] else ''
        entry['last_date'] = max(entry['dates']) if entry['dates'] else ''
        entry['sources'] = sorted(set(entry['sources']))
        entry['copies'] = len(entry['paths'])
        del entry['dates']
        out.append(entry)
    out.sort(key=lambda e: e['date'] or '9999', reverse=True)
    return out


def main():
    parser = argparse.ArgumentParser(description='扫描本机从 GitHub Releases 下载过的文件')
    parser.add_argument('roots', nargs='*', help='要扫描的额外目录')
    parser.add_argument('--json', help='把结果写成 JSON 文件')
    parser.add_argument('--quiet', action='store_true', help='只输出汇总表')
    args = parser.parse_args()

    roots = DEFAULT_ROOTS + [os.path.abspath(r) for r in args.roots]
    hits = []
    if not args.quiet:
        print('扫描目录:')
        for root in roots:
            print('  %s%s' % (root, '' if os.path.isdir(root) else '  (不存在，跳过)'))
    hits += scan_motw(roots)
    hits += scan_chromium()
    hits += scan_firefox()

    merged = dedupe(hits)
    print('')
    print('=' * 100)
    print('从 GitHub Releases 下载过的内容：共 %d 项（原始命中 %d 条）' % (len(merged), len(hits)))
    print('=' * 100)
    for i, item in enumerate(merged, 1):
        print('%2d. %s' % (i, item['asset']))
        if item['repo']:
            print('    仓库/版本 : %s%s' % (item['repo'], (' @ ' + item['tag']) if item['tag'] else ''))
        print('    时间      : %s%s' % (item['date'] or '未知',
                                        ('  ~ ' + item['last_date']) if item['last_date'] != item['date'] else ''))
        print('    依据      : %s' % ' + '.join(item['sources']))
        if item['referrer']:
            print('    来源页面  : %s' % item['referrer'])
        for path in item['paths'][:3]:
            print('    本地文件  : %s' % path)
        if item['copies'] > 3:
            print('    (另有 %d 个副本)' % (item['copies'] - 3))
        print('')

    if args.json:
        with open(args.json, 'w', encoding='utf-8') as fh:
            json.dump(merged, fh, ensure_ascii=False, indent=2)
        print('JSON 已写入: %s' % args.json)


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    main()
