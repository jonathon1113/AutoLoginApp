# -*- coding: utf-8 -*-
"""修复前 / 修复后 逐候选耗时对比工具（验收证据，可重复执行）。

用法： python tests/compare_before_after.py

修复前的查找算法在本仓库中仍可精确复现：
- `appcore/browser.py::probe_locator()`（旧实现保留）——元素不存在时进入
  「复查窗口」轮询（ID/NAME 0.5s、普通 CSS/XPath 0.3s、宽泛选择器 0.15s）；
- 旧循环在累计耗时超过 `SELECTOR_LOOKUP_BUDGET` 时 `break`，剩余候选从未执行。

本脚本用旧函数 + 旧循环规则跑一遍「修复前」，再用新实现
`find_by_selectors_detailed()` 跑一遍「修复后」，输出逐候选对照表。

对照页面：本地构造页（DOM 与 site-a 一致）+ 两个真实站点。
"""
import asyncio
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from playwright.async_api import async_playwright          # noqa: E402
from appcore import browser as browser_mod                 # noqa: E402
from appcore.browser import find_by_selectors_detailed     # noqa: E402
from appcore.config import SELECTOR_LOOKUP_BUDGET          # noqa: E402

# 修复前 default.json 的 18 个用户名候选
LEGACY_18 = [
    {"by": "CSS_SELECTOR", "value": "input[autocomplete=\"username\"]"},
    {"by": "NAME", "value": "username"},
    {"by": "ID", "value": "username"},
    {"by": "CSS_SELECTOR", "value": "input[name=\"username\"]"},
    {"by": "CSS_SELECTOR", "value": "input[name=\"user\"]"},
    {"by": "CSS_SELECTOR", "value": "input[name=\"userName\"]"},
    {"by": "CSS_SELECTOR", "value": "input[name=\"login\"]"},
    {"by": "CSS_SELECTOR", "value": "input[id=\"user\"]"},
    {"by": "CSS_SELECTOR", "value": "input[id=\"account\"]"},
    {"by": "CSS_SELECTOR", "value": "input[id=\"login\"]"},
    {"by": "CSS_SELECTOR", "value": "input[type=\"email\"]"},
    {"by": "CSS_SELECTOR", "value": "input[placeholder=\"用户名\"]"},
    {"by": "CSS_SELECTOR", "value": "input[placeholder=\"请输入用户名\"]"},
    {"by": "CSS_SELECTOR", "value": "input[placeholder=\"账号\"]"},
    {"by": "CSS_SELECTOR", "value": "input[placeholder=\"邮箱\"]"},
    {"by": "XPATH", "value": "//input[contains(@placeholder, '用户')]"},
    {"by": "XPATH", "value": "//input[contains(@id, 'username')]"},
    {"by": "XPATH", "value": "//input[@type='text']"},
]

LOCAL_HTML = ('<html><body><form>'
              '<input id="email" name="email" type="email" autocomplete="email">'
              '<input id="password" name="password" type="password">'
              '<button type="submit">Sign In</button>'
              '</form></body></html>')

REAL_TARGETS = [
    ("site-a", "https://site-a.example.com/login"),
    ("site-b", "https://site-b.example.com/#/login"),
]


def w(text=''):
    print(text, flush=True)


async def old_lookup(page, selectors, budget):
    """精确复现修复前的查找循环（使用仓库中仍保留的 probe_locator）。"""
    started = time.monotonic()
    entries = []
    executed = 0
    skipped = 0
    hit = None
    for index, selector in enumerate(selectors):
        if (time.monotonic() - started) > budget:
            skipped = len(selectors) - index
            break
        by = selector['by']
        value = selector['value']
        t0 = time.monotonic()
        state, _loc = await browser_mod.probe_locator(page, by, value,
                                                      probe_timeout=0.5)
        ms = int((time.monotonic() - t0) * 1000)
        executed += 1
        entries.append({'index': index + 1, 'by': by, 'value': value,
                        'state': state, 'ms': ms})
        if state == 'found':
            hit = (by, value)
            break
    elapsed = int((time.monotonic() - started) * 1000)
    return {'hit': hit, 'entries': entries, 'executed': executed,
            'skipped': skipped, 'total': len(selectors), 'elapsed_ms': elapsed}


async def new_lookup(page, selectors, budget):
    result = await find_by_selectors_detailed(page, selectors, 'username_selectors',
                                              budget=budget, log=lambda m: None,
                                              stage='username_lookup')
    return result


def dump_old(title, res):
    w(f'--- 修复前：{title} ---')
    w(f"总候选={res['total']} 实际执行={res['executed']} 未执行={res['skipped']} "
      f"命中={bool(res['hit'])} 总耗时={res['elapsed_ms']}ms")
    for e in res['entries']:
        w(f"  候选={e['index']}/{res['total']} {e['by']}={e['value']!r} "
          f"结果={e['state']} 耗时={e['ms']}ms")
    w()


def dump_new(title, res):
    w(f'--- 修复后：{title} ---')
    w(f"总候选={res['total']} 实际执行={res['executed']} 未执行={res['skipped']} "
      f"命中={res['hit']} 原因={res['reason']} 总耗时={res['elapsed_ms']}ms")
    for e in res['entries']:
        w(f"  候选={e['index']}/{res['total']} {e['by']}={e['value']!r} "
          f"结果={e['state']} 耗时={e['ms']}ms 剩余预算={e['remaining_ms']}ms")
    w()


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=['--no-sandbox'])
        context = await browser.new_context(ignore_https_errors=True)
        page = await context.new_page()

        # ---------- 本地构造页（模拟 site-a 的 DOM 结构） ----------
        await page.set_content(LOCAL_HTML)
        old = await old_lookup(page, LEGACY_18, SELECTOR_LOOKUP_BUDGET)
        dump_old('本地构造页（DOM 与 site-a 一致）', old)
        new = await new_lookup(page, LEGACY_18, SELECTOR_LOOKUP_BUDGET)
        dump_new('本地构造页（DOM 与 site-a 一致）', new)
        w('对照：'
          f"修复前执行 {old['executed']}/{old['total']}（未执行 {old['skipped']}），"
          f"修复后执行 {new['executed']}/{new['total']}（未执行 {new['skipped']}）")
        w(f"修复前单候选耗时区间 "
          f"{min(e['ms'] for e in old['entries'])}~"
          f"{max(e['ms'] for e in old['entries'])}ms，修复后 "
          f"{min(e['ms'] for e in new['entries'])}~"
          f"{max(e['ms'] for e in new['entries'])}ms")
        w()

        # ---------- 两个真实站点 ----------
        for name, url in REAL_TARGETS:
            p2 = await context.new_page()
            try:
                await p2.goto(url, wait_until='domcontentloaded', timeout=30000)
                await p2.wait_for_timeout(2000)
            except Exception as exc:
                w(f'--- {name}：测试受限，无法访问（{type(exc).__name__}） ---')
                w()
                await p2.close()
                continue
            old = await old_lookup(p2, LEGACY_18, SELECTOR_LOOKUP_BUDGET)
            dump_old(f'真实站点 {name} {url}', old)
            new = await new_lookup(p2, LEGACY_18, SELECTOR_LOOKUP_BUDGET)
            dump_new(f'真实站点 {name} {url}', new)
            w('对照：'
              f"修复前执行 {old['executed']}/{old['total']}（未执行 {old['skipped']}，"
              f"命中 {bool(old['hit'])}，耗时 {old['elapsed_ms']}ms）；"
              f"修复后执行 {new['executed']}/{new['total']}（未执行 {new['skipped']}，"
              f"命中 {new['hit']}，耗时 {new['elapsed_ms']}ms）")
            w()
            await p2.close()

        await browser.close()


asyncio.run(main())
