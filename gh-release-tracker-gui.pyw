#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gh-release-tracker-gui.pyw —— GH Release Tracker（bilingual GUI / 中英双语界面）

Double-click to open the window. Switch the UI language with the button at the top-right.
双击本文件即可打开窗口；右上角按钮可切换中英文。
Only the Python standard library (tkinter) is required.
"""
import importlib.util
import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog

# Explicit imports so PyInstaller bundles the core's dependencies (the core is loaded dynamically).
import argparse          # noqa: F401
import datetime          # noqa: F401
import re                # noqa: F401
import shutil            # noqa: F401
import sqlite3           # noqa: F401
import tempfile          # noqa: F401
import urllib.error      # noqa: F401
import urllib.parse      # noqa: F401
import urllib.request    # noqa: F401


def _load_core():
    """加载同目录下的 gh-release-tracker.py（文件名带连字符，不能直接 import）。"""
    bases = []
    if getattr(sys, '_MEIPASS', None):          # PyInstaller 打包后的解压目录
        bases.append(sys._MEIPASS)
    bases.append(os.path.dirname(os.path.abspath(__file__)))
    for d in bases:
        p = os.path.join(d, 'gh-release-tracker.py')
        if os.path.exists(p):
            spec = importlib.util.spec_from_file_location('ghrt_core', p)
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
            return m
    raise RuntimeError('gh-release-tracker.py not found / 找不到 gh-release-tracker.py')


core = _load_core()

HOME = os.path.expanduser('~')
SCAN_DIRS = [core.DOWNLOADS,
             os.path.join(HOME, 'Desktop'),
             os.path.join(HOME, 'Documents')]
WATCH_DIRS = [core.DOWNLOADS]

if os.name == 'nt':
    MONO_FONT = ('Consolas', 10)
elif sys.platform == 'darwin':
    MONO_FONT = ('Menlo', 10)
else:
    MONO_FONT = ('DejaVu Sans Mono', 10)

_TOP = object()   # 队列特殊标记：把视图滚到顶部


def detect_default_lang():
    """初始语言：环境变量 GHRT_LANG > 系统语言。"""
    env = (os.environ.get('GHRT_LANG') or '').strip().lower()
    if env.startswith('en'):
        return 'en'
    if env.startswith('zh'):
        return 'zh'
    try:
        import locale
        loc = (locale.getdefaultlocale()[0] or '').lower()
    except Exception:
        loc = ''
    return 'zh' if loc.startswith('zh') else 'en'


class App:
    def __init__(self, root, lang=None):
        self.root = root
        core.set_lang(lang or detect_default_lang())
        self.lang = core.LANG
        self._ever_watched = False

        self.log = core.DEFAULT_LOG
        self.q = queue.Queue()
        self.lock = threading.Lock()
        self.watching = False
        self.interval = 15
        self.sigs = core.load_signatures(self.log)

        root.geometry('880x660')
        self._build_ui()
        self._retranslate()
        self._out(self.T('gui_started', self.log) + '\n')
        self._out(self.T('gui_tip', self.T('btn_scan'), self.T('btn_watch')) + '\n\n')
        self.root.after(200, self._poll_queue)
        if self.auto_var.get():
            self.start_watch()

    # ---------------- 语言 ----------------
    def T(self, key, *args):
        return core.t(key, *args)

    def toggle_lang(self):
        self.set_language('en' if self.lang == 'zh' else 'zh')

    def set_language(self, lang):
        core.set_lang(lang)
        self.lang = core.LANG
        self._retranslate()
        self._out('\n' + self.T('gui_lang_switched') + '\n')

    def _retranslate(self):
        self.root.title(self.T('app_title'))
        self.btn_scan.config(text=self.T('btn_scan'))
        self.watch_btn.config(text=self.T('btn_stop') if self.watching else self.T('btn_watch'))
        self.btn_list.config(text=self.T('btn_list'))
        self.btn_check.config(text=self.T('btn_check'))
        self.btn_export.config(text=self.T('btn_export'))
        self.chk_auto.config(text=self.T('chk_auto'))
        self.lang_btn.config(text=self.T('lang_btn'))
        if self.watching:
            self.status.set(self.T('status_watching', self.interval))
        elif self._ever_watched:
            self.status.set(self.T('status_stopped'))
        else:
            self.status.set(self.T('status_ready'))

    # ---------------- 界面 ----------------
    def _build_ui(self):
        bar = ttk.Frame(self.root, padding=8)
        bar.pack(fill='x')
        self.btn_scan = ttk.Button(bar, command=self.on_scan)
        self.btn_scan.pack(side='left', padx=3)
        self.watch_btn = ttk.Button(bar, command=self.on_watch)
        self.watch_btn.pack(side='left', padx=3)
        self.btn_list = ttk.Button(bar, command=self.on_list)
        self.btn_list.pack(side='left', padx=3)
        self.btn_check = ttk.Button(bar, command=self.on_check)
        self.btn_check.pack(side='left', padx=3)
        self.btn_export = ttk.Button(bar, command=self.on_export)
        self.btn_export.pack(side='left', padx=3)

        self.lang_btn = ttk.Button(bar, width=9, command=self.toggle_lang)
        self.lang_btn.pack(side='right', padx=3)
        self.auto_var = tk.BooleanVar(value=True)
        self.chk_auto = ttk.Checkbutton(bar, variable=self.auto_var)
        self.chk_auto.pack(side='right', padx=3)

        self.text = scrolledtext.ScrolledText(
            self.root, wrap='char', font=MONO_FONT,
            background='#1e1e1e', foreground='#d4d4d4', insertbackground='#d4d4d4')
        self.text.pack(fill='both', expand=True, padx=8, pady=(0, 4))

        self.status = tk.StringVar(value='')
        ttk.Label(self.root, textvariable=self.status, relief='sunken', anchor='w',
                  padding=(6, 2)).pack(fill='x', side='bottom')

    # ---------------- 输出 ----------------
    def _out(self, s):
        self.q.put(('text', s))

    def _status(self, s):
        self.q.put(('status', s))

    def _scroll_top(self):
        self.q.put(('top', None))

    def _poll_queue(self):
        inserted = False
        jump_top = False
        status = None
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == 'text':
                    self.text.insert('end', payload)
                    inserted = True
                elif kind == 'status':
                    status = payload
                elif kind == 'top':
                    jump_top = True
        except queue.Empty:
            pass
        if status is not None:
            self.status.set(status)
        if jump_top:
            self.text.see('1.0')
        elif inserted:
            _t, bottom = self.text.yview()
            if bottom >= 0.99:
                self.text.see('end')
        self.root.after(200, self._poll_queue)

    def _run_bg(self, fn):
        def w():
            try:
                fn()
            except Exception as e:
                self._out('\n' + self.T('gui_error', e) + '\n')
        threading.Thread(target=w, daemon=True).start()

    # ---------------- 动作 ----------------
    def on_scan(self):
        self._status(self.T('status_scanning'))
        self._run_bg(self.do_scan)

    def do_scan(self):
        with self.lock:
            recs = core.merge_by_path(core.browser_records(core.BROWSERS) + core.motw_records(SCAN_DIRS))
            new = core.append_records(self.log, recs, self.sigs)
        self._out(self.T('gui_scan_banner', len(new), len(self.sigs)) + '\n')
        for r in new:
            self._out(self.T('new_item', core.fmt_line(r)) + '\n')
        self._out('\n')
        self._print_summary()
        self._status(self.T('status_scan_done', core.now_str()))

    def _print_summary(self):
        rows = core.read_records(self.log)
        rows.sort(key=lambda r: r.get('downloaded_at') or '', reverse=True)
        self._out(self.T('summary_header', len(rows)) + '\n\n')
        for r in rows[:10]:
            self._out(core.pretty_card(r) + '\n\n')
        if len(rows) > 10:
            self._out(self.T('gui_more', len(rows) - 10, self.T('btn_list')) + '\n')

    def on_list(self):
        self._run_bg(self.do_list)

    def do_list(self):
        rows = core.read_records(self.log)
        if not rows:
            self._out(self.T('gui_no_records', self.T('btn_scan')) + '\n')
            return
        rows.sort(key=lambda r: r.get('downloaded_at') or '', reverse=True)
        self._out('\n' + self.T('list_header', len(rows)) + '\n')
        for r in rows:
            self._out(core.pretty_card(r) + '\n\n')
        self._scroll_top()

    def on_check(self):
        self._status(self.T('status_checking'))
        self._run_bg(self.do_check)

    def do_check(self):
        records = core.read_records(self.log)
        repos = {}
        for r in records:
            repo = (r.get('repo') or '').strip()
            if repo:
                repos.setdefault(repo, set()).add(r.get('tag') or '')
        if not repos:
            self._out(self.T('gui_norepo', self.T('btn_scan')) + '\n')
            self._status(self.T('status_norepo'))
            return
        self._out('\n' + self.T('check_header', len(repos)) + '\n\n')
        n_up = 0
        for repo in sorted(repos):
            tags = sorted(t for t in repos[repo] if t)
            latest = core.github_latest(repo, None)
            if not latest.get('ok'):
                self._out(self.T('check_failed', repo, ', '.join(tags) or self.T('no_version'),
                                latest.get('error')) + '\n\n')
                continue
            if not tags:
                status = 'unknown'
            elif latest['tag'] in tags:
                status = 'latest'
            else:
                best = tags[0]
                for t in tags[1:]:
                    c = core.cmp_version(t, best)
                    if c is not None and c > 0:
                        best = t
                c = core.cmp_version(latest['tag'], best)
                if c is None:
                    status = 'unknown'
                elif c > 0:
                    status = 'update'
                elif c < 0:
                    status = 'have_newer'
                else:
                    status = 'latest'
            mark = {'latest': self.T('mark_latest'), 'update': self.T('mark_update'),
                    'have_newer': self.T('mark_newer'), 'unknown': self.T('mark_unknown')}[status]
            if status == 'update':
                n_up += 1
            self._out('  %s %s\n' % (mark, repo))
            self._out(self.T('check_line', ', '.join(tags) or self.T('no_version'),
                             latest['tag'] or '?', latest.get('published') or '?',
                             self.T('prerelease') if latest.get('prerelease') else '') + '\n')
            if latest.get('url'):
                self._out('        %s\n' % latest['url'])
            self._out('\n')
        self._out(self.T('check_done', len(repos), n_up) + '\n')
        self._status(self.T('status_check_done'))

    def on_export(self):
        rows = core.read_records(self.log)
        if not rows:
            messagebox.showinfo(self.T('gui_export_title'), self.T('gui_export_none'))
            return
        path = filedialog.asksaveasfilename(defaultextension='.json',
                                            filetypes=[(self.T('gui_export_filter'), '*.json')],
                                            initialfile=self.T('gui_export_name'))
        if not path:
            return
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(rows, fh, ensure_ascii=False, indent=2)
        messagebox.showinfo(self.T('gui_export_title'), self.T('gui_export_done', len(rows), path))

    def on_watch(self):
        if self.watching:
            self.stop_watch()
        else:
            self.start_watch()

    def start_watch(self):
        if self.watching:
            return
        self.watching = True
        self._ever_watched = True
        self.watch_btn.config(text=self.T('btn_stop'))
        self._status(self.T('status_watching', self.interval))
        self._out('\n' + self.T('gui_watch_on') + '\n\n')

        def loop():
            while self.watching:
                try:
                    with self.lock:
                        recs = core.merge_by_path(core.browser_records(core.BROWSERS) + core.motw_records(WATCH_DIRS))
                        new = core.append_records(self.log, recs, self.sigs)
                    for r in new:
                        self._out(self.T('new_record', core.now_str(), core.fmt_line(r)) + '\n')
                except Exception as e:
                    self._out(self.T('gui_watch_error', e) + '\n')
                for _ in range(self.interval):
                    if not self.watching:
                        break
                    time.sleep(1)

        threading.Thread(target=loop, daemon=True).start()

    def stop_watch(self):
        self.watching = False
        self.watch_btn.config(text=self.T('btn_watch'))
        self._status(self.T('status_stopped'))
        self._out(self.T('gui_watch_off') + '\n')


def main():
    try:
        core.cleanup_temp_dirs()      # 兜底清理崩溃残留的临时目录
    except Exception:
        pass
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == '__main__':
    main()
