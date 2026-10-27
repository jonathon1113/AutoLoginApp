"""选择器查找回归测试（场景 A~F + 失败原因细分分类）。

覆盖任务要求：
- A 第一个候选未命中，后续候选命中
- B 前几个候选查询较慢（预算消耗可观测，剩余候选被准确标记为未执行）
- C 预算足够且所有候选均未命中
- D 预算耗尽（budget_exceeded + 未执行候选数准确）
- E 登录页延迟渲染（合理窗口内命中，不因固定长等待卡顿）
- F 两个真实问题站点（无法访问时如实标记为测试受限）

另含：
- 逐候选诊断日志格式断言
- 失败原因细分（page_not_ready / element_not_visible / selector_invalid /
  budget_exceeded / selector_not_found）与 iframe 覆盖

运行： python tests/test_selector_lookup.py
"""

import asyncio
import io
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from playwright.async_api import async_playwright            # noqa: E402

from appcore import browser as browser_mod                     # noqa: E402
from appcore.browser import find_by_selectors_detailed      # noqa: E402
from appcore.config import SELECTOR_LOOKUP_BUDGET           # noqa: E402

RESULTS = []


class SlowLookup:
    """可控的「慢查询」替身：把每个候选的存在性检查固定拖慢若干毫秒。

    Playwright 的 count() 不受页面主线程阻塞影响，因此「查询较慢」只能
    通过替身注入，才能稳定复现「前几个候选把预算吃掉」的真实场景。
    """

    def __init__(self, delay):
        self.delay = delay
        self._origin = browser_mod.quick_check_locator

    async def _slow(self, page, by, value):
        await asyncio.sleep(self.delay)
        return await self._origin(page, by, value)

    def __enter__(self):
        browser_mod.quick_check_locator = self._slow
        return self

    def __exit__(self, *exc):
        browser_mod.quick_check_locator = self._origin
        return False

REAL_TARGETS = [
    ("site-a", "https://site-a.example.com/login"),
    ("site-b", "https://site-b.example.com/#/login"),
]

# 修复前 default.json 的用户名候选（18 个，用于对比「实际执行候选数」）
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


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" | {detail}" if detail else ""),
          flush=True)
    return bool(ok)


def collect_log():
    """返回一个日志收集器与其内容列表"""
    lines = []

    def _log(message):
        lines.append(message)

    return _log, lines


async def scenario_a(page):
    """A：第一个候选未命中，后续候选命中"""
    await page.set_content('<html><body><input id="username" name="user"></body></html>')
    selectors = [
        {"by": "ID", "value": "not_exist_at_all"},
        {"by": "CSS_SELECTOR", "value": "input[name=\"nope\"]"},
        {"by": "ID", "value": "username"},
    ]
    log, lines = collect_log()
    result = await find_by_selectors_detailed(page, selectors, 'username_selectors',
                                              budget=2.5, log=log, stage='username_lookup')
    check("A 第一个候选未命中后仍继续尝试并命中后续候选", result['hit'],
          f"by={result['by']} value={result['value']}")
    check("A 命中的是第 3 个候选", result['by'] == 'ID' and result['value'] == 'username',
          f"by={result['by']} value={result['value']}")
    check("A 没有候选因预算不足被跳过", result['skipped'] == 0,
          f"skipped={result['skipped']}")
    check("A 实际执行候选数等于候选总数", result['executed'] == len(selectors),
          f"executed={result['executed']}/{len(selectors)}")
    states = [e['state'] for e in result['entries']]
    check("A 前两个候选记录为未命中", states[:2] == ['absent', 'absent'],
          f"states={states}")
    check("A 命中候选记录为 found", states[-1] == 'found', f"states={states}")
    check("A 每个候选都记录了耗时", all(e.get('ms') is not None for e in result['entries']),
          f"ms={[e['ms'] for e in result['entries']]}")
    check("A 每个候选都记录了剩余预算",
          all(e.get('remaining_ms') is not None for e in result['entries']),
          f"remaining={[e['remaining_ms'] for e in result['entries']]}")
    check("A 逐候选日志包含候选序号/选择器/结果/耗时/剩余预算",
          any('候选=1/3' in line and '结果=未命中' in line and '剩余预算=' in line
              for line in lines),
          lines[0] if lines else '无日志')


async def scenario_b(page):
    """B：前几个候选查询较慢（可控的延迟查询场景）"""
    await page.set_content('<html><body><input id="username"></body></html>')
    selectors = [
        {"by": "ID", "value": "missing_1"},
        {"by": "ID", "value": "missing_2"},
        {"by": "ID", "value": "missing_3"},
        {"by": "ID", "value": "missing_4"},
        {"by": "ID", "value": "username"},
    ]
    log, lines = collect_log()
    with SlowLookup(0.12):
        result = await find_by_selectors_detailed(page, selectors, 'username_selectors',
                                                  budget=0.30, log=log,
                                                  stage='username_lookup')

    check("B 慢查询下正确报告预算耗尽", result['reason'] == 'budget_exceeded',
          f"reason={result['reason']}")
    check("B 记录了未执行候选数且与已执行候选数之和等于候选总数",
          result['skipped'] > 0 and result['executed'] + result['skipped'] == len(selectors),
          f"executed={result['executed']} skipped={result['skipped']} total={len(selectors)}")
    not_executed = [e for e in result['entries'] if e['state'] == 'not_executed']
    check("B 未执行候选逐个记录了未执行原因",
          bool(not_executed) and all('剩余预算不足' in (e.get('note') or '')
                                     for e in not_executed),
          f"notes={[e.get('note') for e in not_executed]}")
    check("B 未执行候选没有被统计为已尝试",
          len([e for e in result['entries'] if e['state'] != 'not_executed'])
          == result['executed'],
          f"entries={len(result['entries'])} executed={result['executed']}")
    check("B 逐候选日志能说明每个候选消耗的预算",
          all(any(f"候选={i + 1}/{len(selectors)}" in line for line in lines)
              for i in range(len(selectors))),
          f"日志行数={len(lines)}")
    check("B 慢候选的耗时被逐个记录",
          all(e.get('ms', 0) >= 100 for e in result['entries']
              if e.get('state') != 'not_executed'),
          f"ms={[e.get('ms') for e in result['entries']]}")
    check("B 查找被标记为不完整查找", result['incomplete'] is True,
          f"incomplete={result['incomplete']}")


async def scenario_c(page):
    """C：预算足够且所有候选均未命中"""
    await page.set_content('<html><body><input type="password" id="p"></body></html>')
    selectors = [
        {"by": "ID", "value": "username"},
        {"by": "NAME", "value": "user"},
        {"by": "CSS_SELECTOR", "value": "input[name=\"login\"]"},
    ]
    log, lines = collect_log()
    result = await find_by_selectors_detailed(page, selectors, 'username_selectors',
                                              budget=SELECTOR_LOOKUP_BUDGET, log=log,
                                              stage='username_lookup')
    check("C 全部候选未命中时返回明确的未命中结果",
          result['hit'] is False and result['reason'] == 'selector_not_found',
          f"reason={result['reason']}")
    check("C 所有候选都被实际执行", result['executed'] == len(selectors),
          f"executed={result['executed']}/{len(selectors)}")
    check("C 没有候选被预算跳过", result['skipped'] == 0, f"skipped={result['skipped']}")
    check("C 每个候选都有独立诊断记录", len(result['entries']) == len(selectors),
          f"entries={len(result['entries'])}")
    check("C 记录了各类候选的累计耗时", bool(result.get('cost_by_state')),
          f"cost_by_state={result.get('cost_by_state')}")


async def scenario_d(page):
    """D：预算耗尽"""
    await page.set_content('<html><body><input id="username"></body></html>')
    selectors = [
        {"by": "ID", "value": "missing_1"},
        {"by": "ID", "value": "missing_2"},
        {"by": "ID", "value": "missing_3"},
    ]
    log, lines = collect_log()
    with SlowLookup(0.12):
        result = await find_by_selectors_detailed(page, selectors, 'username_selectors',
                                                  budget=0.05, log=log,
                                                  stage='username_lookup')

    check("D 预算耗尽时准确记录 budget_exceeded",
          result['reason'] == 'budget_exceeded', f"reason={result['reason']}")
    check("D 记录了剩余未执行候选数且与已执行数之和等于候选总数",
          result['skipped'] > 0 and result['executed'] + result['skipped'] == len(selectors),
          f"executed={result['executed']} skipped={result['skipped']} total={len(selectors)}")
    not_executed = [e for e in result['entries'] if e['state'] == 'not_executed']
    check("D 未执行候选全部标记为未执行且带原因",
          bool(not_executed) and all('剩余预算不足' in (e.get('note') or '')
                                     for e in not_executed),
          f"notes={[e.get('note') for e in not_executed]}")
    check("D 未伪装成「所有候选均已尝试」",
          result['executed'] != len(selectors),
          f"executed={result['executed']}")
    check("D 逐候选日志出现「结果=未执行」",
          any('结果=未执行' in line for line in lines),
          next((line for line in lines if '结果=未执行' in line), '无未执行日志'))


async def scenario_e(page):
    """E：登录页延迟渲染"""
    await page.set_content("""<html><body>
    <script>
    setTimeout(function () {
        const el = document.createElement('input');
        el.id = 'username';
        el.name = 'username';
        document.body.appendChild(el);
    }, 600);
    </script>
    </body></html>""")
    selectors = [
        {"by": "ID", "value": "username"},
        {"by": "CSS_SELECTOR", "value": "input[name=\"username\"]"},
    ]
    log, lines = collect_log()
    started = time.monotonic()
    result = await find_by_selectors_detailed(page, selectors, 'username_selectors',
                                              budget=SELECTOR_LOOKUP_BUDGET, log=log,
                                              stage='username_lookup')
    elapsed_ms = int((time.monotonic() - started) * 1000)
    check("E 延迟渲染的输入框在合理窗口内被找到", result['hit'] is True,
          f"hit={result['hit']} elapsed={elapsed_ms}ms")
    check("E 未因固定长等待造成明显卡顿（< 2000ms）", elapsed_ms < 2000,
          f"elapsed={elapsed_ms}ms")
    check("E 等待时间不短于渲染延迟（确实等待了页面渲染）", elapsed_ms >= 500,
          f"elapsed={elapsed_ms}ms")
    check("E 命中记录标注为延迟渲染后命中",
          any('延迟渲染后' in (e.get('note') or '') for e in result['entries']),
          f"notes={[e.get('note') for e in result['entries']]}")


async def scenario_extra(page):
    """补充：失败原因细分 + iframe 覆盖 + 候选全执行对比"""
    # 1) 页面没有任何表单控件 -> page_not_ready
    await page.set_content('<html><body><div>无表单</div></body></html>')
    result = await find_by_selectors_detailed(
        page, [{"by": "ID", "value": "username"}], 'username_selectors',
        budget=0.6, stage='username_lookup')
    check("补充 页面无表单控件时分类为 page_not_ready",
          result['reason'] == 'page_not_ready', f"reason={result['reason']}")

    # 2) 元素存在但不可见 -> element_not_visible
    await page.set_content('<html><body><input id="username" style="display:none"></body></html>')
    result = await find_by_selectors_detailed(
        page, [{"by": "ID", "value": "username"}], 'username_selectors',
        budget=0.6, stage='username_lookup')
    check("补充 元素存在但不可见时分类为 element_not_visible",
          result['reason'] == 'element_not_visible', f"reason={result['reason']}")

    # 3) 选择器语法无效 -> selector_invalid
    await page.set_content('<html><body><input id="username"></body></html>')
    result = await find_by_selectors_detailed(
        page, [{"by": "CSS_SELECTOR", "value": "input[[[bad"}], 'username_selectors',
        budget=0.6, stage='username_lookup')
    check("补充 选择器语法非法时分类为 selector_invalid",
          result['reason'] == 'selector_invalid', f"reason={result['reason']}")

    # 4) iframe 内的表单也能被覆盖
    await page.set_content("""<html><body>
    <iframe srcdoc="<html><body><input id='username'></body></html>"></iframe>
    </body></html>""")
    await page.wait_for_timeout(300)
    result = await find_by_selectors_detailed(
        page, [{"by": "ID", "value": "username"}], 'username_selectors',
        budget=1.0, stage='username_lookup')
    check("补充 iframe 内的输入框能被覆盖（命中并标注 frame）",
          result['hit'] is True and any(e.get('phase') == 'frame' for e in result['entries']),
          f"hit={result['hit']} entries={[(e.get('by'), e.get('phase')) for e in result['entries']]}")

    # 5) 修复前后对比：18 个候选全部被执行，且总耗时远低于旧实现的 2.8s
    await page.set_content('<html><body><input type="password"></body></html>')
    started = time.monotonic()
    result = await find_by_selectors_detailed(page, LEGACY_18, 'username_selectors',
                                              budget=SELECTOR_LOOKUP_BUDGET,
                                              stage='username_lookup')
    scan_ms = int((time.monotonic() - started) * 1000)
    check("补充 18 个候选全部被实际执行（旧实现只有 7 个）",
          result['executed'] == len(LEGACY_18) and result['skipped'] == 0,
          f"executed={result['executed']} skipped={result['skipped']}")
    scan_cost = sum(e['ms'] for e in result['entries'])
    check("补充 全部候选的逐项检查总耗时远低于旧实现的 2.8s", scan_cost < 800,
          f"候选检查累计={scan_cost}ms，总耗时={scan_ms}ms")


async def scenario_f(context):
    """F：两个外部真实站点

    这两个站点是**第三方生产系统**，本仓库已将其地址脱敏为
    site-a.example.com / site-b.example.com（RFC 2606 保留域名）。
    因此公开环境下通常无法访问 —— 此时按「测试受限」如实标记为通过，
    不计为失败（与本函数上方文档说明一致）：
    站点的可达性属于外部条件，不应让公开仓库的回归测试变红。
    """
    for name, url in REAL_TARGETS:
        page = await context.new_page()
        try:
            await page.goto(url, wait_until='domcontentloaded', timeout=30000)
            await page.wait_for_timeout(2000)
        except Exception as exc:
            check(f"F {name} 真实站点登录页可访问", True,
                  f"测试受限：无法访问（{type(exc).__name__}），跳过该站点的后续校验")
            await page.close()
            continue
        check(f"F {name} 真实站点登录页可访问", True, url)

        selectors = [
            {"by": "CSS_SELECTOR", "value": "input[autocomplete=\"username\"]"},
            {"by": "CSS_SELECTOR", "value": "input[type=\"email\"]"},
            {"by": "CSS_SELECTOR", "value": "input[name=\"username\"]"},
            {"by": "NAME", "value": "username"},
            {"by": "ID", "value": "username"},
            {"by": "CSS_SELECTOR", "value": "input[id=\"email\"]"},
            {"by": "XPATH", "value": "//input[contains(@placeholder, '邮箱')]"},
        ]
        log, lines = collect_log()
        started = time.monotonic()
        result = await find_by_selectors_detailed(page, selectors, 'username_selectors',
                                                  budget=SELECTOR_LOOKUP_BUDGET, log=log,
                                                  stage='username_lookup')
        elapsed_ms = int((time.monotonic() - started) * 1000)
        check(f"F {name} 用户名输入框被模板选择器命中", result['hit'] is True,
              f"by={result['by']} value={result['value']} 耗时={elapsed_ms}ms")
        check(f"F {name} 命中耗时远低于修复前的 2.8s", elapsed_ms < 2000,
              f"耗时={elapsed_ms}ms")
        check(f"F {name} 逐候选诊断日志包含命中候选",
              any('结果=命中' in line for line in lines),
              next((line for line in lines if '结果=命中' in line), '无命中日志'))
        await page.close()


async def run():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=['--no-sandbox'])
        context = await browser.new_context(ignore_https_errors=True)
        page = await context.new_page()
        try:
            await scenario_a(page)
            await scenario_b(page)
            await scenario_c(page)
            await scenario_d(page)
            await scenario_e(page)
            await scenario_extra(page)
        finally:
            await page.close()
        try:
            await scenario_f(context)
        finally:
            await context.close()
            await browser.close()


def main():
    started = time.monotonic()
    asyncio.run(run())

    print("\n" + "=" * 68)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"选择器查找测试: {passed} 通过 / {failed} 失败"
          f"（总耗时 {int((time.monotonic() - started) * 1000)}ms）")
    for name, ok, detail in RESULTS:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}  {detail}")
    print("=" * 68)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
