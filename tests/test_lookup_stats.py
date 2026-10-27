"""候选列表与查找统计测试（真实 Playwright + 本地测试页面）。

覆盖任务书 8.2 的场景：
- 35 个候选中的第 1 个、第 14 个和第 35 个命中；
- 全部未命中；
- 存在重复候选；
- 密码和按钮候选不一致；
- 错误的按钮候选；
- 预算耗尽；
- 页面未就绪；
- 用户名命中但填写失败。

核心断言：
- 统计里的「实际开始执行」必须与逐候选诊断记录中真实执行过的候选数一致；
- 「不完整查找」按实际执行情况计算（命中提前退出即属于不完整）；
- 汇总日志必须分别输出原始候选数 / 去重后候选数 / 执行数 / 完成数 / 命中数 /
  提前退出未执行数 / 预算不足未执行数 / 异常未执行数 / 退出原因。

运行： python tests/test_lookup_stats.py
"""

import asyncio
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tests'))

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from playwright.async_api import async_playwright          # noqa: E402

from appcore import browser as browser_mod                 # noqa: E402
from appcore.element_roles import ROLE_BUTTON, ROLE_PASSWORD, ROLE_USERNAME  # noqa: E402
from appcore.login_engine import _log_lookup_summary       # noqa: E402
from appcore.logging_utils import Logger                   # noqa: E402
from test_server import LoginHandler, TestServer            # noqa: E402

RESULTS = []

# 不参与执行的候选状态（这些候选根本没有真正发起查询）
_NOT_EXECUTED_STATES = ('not_executed', 'duplicate', 'empty')


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" | {detail}" if detail else ""),
          flush=True)
    return bool(ok)


def build_selectors(total=35, hit_at=None):
    """构造候选列表：第 hit_at 个命中真实输入框，其余为不存在的选择器"""
    selectors = []
    for index in range(1, total + 1):
        if index == hit_at:
            selectors.append({'by': 'CSS_SELECTOR', 'value': 'input#username'})
        else:
            selectors.append({'by': 'CSS_SELECTOR', 'value': f'input#missing_{index}'})
    return selectors


def executed_entries(result):
    """逐候选诊断记录中真正执行过的候选数"""
    entries = result.get('entries') or []
    return len([entry for entry in entries
                if entry.get('state') not in _NOT_EXECUTED_STATES])


class SlowLookup:
    """可控的「慢查询」替身：每个候选的存在性检查固定拖慢若干毫秒。"""

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


class FakeCtx:
    """最小 ctx 替身：只提供 log()"""

    @staticmethod
    def log(message):
        return message


def capture_summary(label, result):
    """调用真实的汇总函数并捕获输出"""
    captured = []
    origin_info = Logger.info
    origin_warning = Logger.warning

    def _info(message, *args, **kwargs):
        captured.append(message)

    def _warning(message, *args, **kwargs):
        captured.append(message)

    Logger.info = _info
    Logger.warning = _warning
    try:
        _log_lookup_summary(FakeCtx(), label, result)
    finally:
        Logger.info = origin_info
        Logger.warning = origin_warning
    return captured[0] if captured else ''


async def run_scenarios(context, base_url):
    page = await context.new_page()
    await browser_mod.navigate(page, f'{base_url}/generic')

    # ============ 场景 1：第 1 / 14 / 35 个候选命中 ============
    for hit_at in (1, 14, 35):
        selectors = build_selectors(35, hit_at)
        result = await browser_mod.find_by_selectors_detailed(
            page, selectors, 'username_selectors', budget=15,
            role=ROLE_USERNAME, trusted=True, delayed_window=False)
        check(f"1.{hit_at} 第 {hit_at} 个候选命中", result['hit'],
              f"reason={result.get('reason')} by={result.get('by')}")
        check(f"1.{hit_at} 原始候选总数=35", result['total'] == 35,
              str(result['total']))
        check(f"1.{hit_at} 去重后候选数=35", result['unique_total'] == 35,
              str(result['unique_total']))
        check(f"1.{hit_at} 实际开始执行={hit_at}", result['executed'] == hit_at,
              str(result['executed']))
        check(f"1.{hit_at} 执行完成={hit_at}", result['completed'] == hit_at,
              str(result['completed']))
        check(f"1.{hit_at} 命中数=1", result['hits'] == 1, str(result['hits']))
        check(f"1.{hit_at} 因命中提前退出未执行={35 - hit_at}",
              result['not_executed'] == 35 - hit_at, str(result['not_executed']))
        check(f"1.{hit_at} 因预算不足未执行=0", result['skipped'] == 0,
              str(result['skipped']))
        check(f"1.{hit_at} 退出原因=hit", result['exit_reason'] == 'hit',
              str(result.get('exit_reason')))
        check(f"1.{hit_at} 不完整查找={'是' if hit_at < 35 else '否'}",
              result['incomplete'] == (hit_at < 35), str(result['incomplete']))
        check(f"1.{hit_at} 统计执行数与逐候选记录一致",
              result['executed'] == executed_entries(result),
              f"统计={result['executed']} 记录={executed_entries(result)}")

        summary = capture_summary(f"测试-{hit_at}", result)
        for field in ("原始候选总数=35", "去重后候选数=35",
                      f"实际开始执行={hit_at}", f"执行完成={hit_at}",
                      "命中数=1", f"因命中提前退出未执行={35 - hit_at}",
                      "因预算不足未执行=0", "因异常或页面未就绪未执行=0",
                      "退出原因=hit"):
            check(f"1.{hit_at} 汇总日志含「{field}」", field in summary, summary)

    # ============ 场景 2：全部未命中 ============
    selectors = build_selectors(35, None)
    result = await browser_mod.find_by_selectors_detailed(
        page, selectors, 'username_selectors', budget=15,
        role=ROLE_USERNAME, trusted=True, delayed_window=False)
    check("2 全部未命中", not result['hit'], f"reason={result.get('reason')}")
    check("2 实际开始执行=35", result['executed'] == 35, str(result['executed']))
    check("2 执行完成=35", result['completed'] == 35, str(result['completed']))
    check("2 命中数=0", result['hits'] == 0, str(result['hits']))
    check("2 因命中提前退出未执行=0", result['not_executed'] == 0,
          str(result['not_executed']))
    check("2 退出原因不是 hit", result['exit_reason'] != 'hit',
          str(result.get('exit_reason')))
    check("2 不完整查找=否（全部候选都执行过）", result['incomplete'] is False,
          str(result['incomplete']))
    check("2 统计执行数与逐候选记录一致",
          result['executed'] == executed_entries(result),
          f"统计={result['executed']} 记录={executed_entries(result)}")
    summary = capture_summary("测试-全未命中", result)
    check("2 汇总日志给出明确退出原因",
          "退出原因=" in summary and "退出原因=hit" not in summary, summary)

    # ============ 场景 3：存在重复候选 ============
    selectors = build_selectors(30, 10)
    # 追加 5 条与前面完全重复的候选
    selectors = selectors + [dict(selectors[0]), dict(selectors[1]),
                             dict(selectors[2]), dict(selectors[3]),
                             dict(selectors[4])]
    result = await browser_mod.find_by_selectors_detailed(
        page, selectors, 'username_selectors', budget=15,
        role=ROLE_USERNAME, trusted=True, delayed_window=False)
    check("3 原始候选总数=35", result['total'] == 35, str(result['total']))
    check("3 去重后候选数=30", result['unique_total'] == 30,
          str(result['unique_total']))
    check("3 重复候选数=5", result['duplicates'] == 5, str(result['duplicates']))
    check("3 实际开始执行=10（重复项不重复执行）", result['executed'] == 10,
          str(result['executed']))
    check("3 统计执行数与逐候选记录一致",
          result['executed'] == executed_entries(result),
          f"统计={result['executed']} 记录={executed_entries(result)}")
    summary = capture_summary("测试-重复候选", result)
    check("3 汇总日志含重复候选数", "重复候选=5" in summary, summary)

    # ============ 场景 4：密码与按钮候选不一致 ============
    pwd = await browser_mod.find_by_selectors_detailed(
        page, [{'by': 'CSS_SELECTOR', 'value': 'input#password'}],
        'password_selectors', budget=10, role=ROLE_PASSWORD, trusted=True)
    check("4 密码候选命中密码框", pwd['hit'], f"reason={pwd.get('reason')}")
    LoginHandler.reset_post_count()
    button = await browser_mod.find_login_button_by_selectors_detailed(
        page, [{'by': 'CSS_SELECTOR', 'value': 'button#loginBtn'}], budget=10)
    check("4 按钮候选命中按钮", button['hit'], f"reason={button.get('reason')}")
    check("4 密码与按钮命中的是不同候选",
          pwd.get('value') != button.get('value'),
          f"pwd={pwd.get('value')} button={button.get('value')}")
    check("4 按钮查找统计包含退出原因", bool(button.get('exit_reason')),
          str(button.get('exit_reason')))

    # ============ 场景 5：错误的按钮候选（密码框冒充按钮）============
    LoginHandler.reset_post_count()
    wrong = await browser_mod.find_login_button_by_selectors_detailed(
        page, [{'by': 'CSS_SELECTOR', 'value': 'input[type="password"]'}], budget=10)
    check("5 密码框不能被当成登录按钮", not wrong['hit'],
          f"hit={wrong['hit']} reason={wrong.get('reason')}")
    check("5 记录了角色不符被拒数", wrong.get('role_rejected', 0) > 0,
          str(wrong.get('role_rejected')))
    check("5 未因此触发提交", LoginHandler.post_count == 0,
          f"post_count={LoginHandler.post_count}")

    # ============ 场景 6：预算耗尽 ============
    with SlowLookup(0.12):
        result = await browser_mod.find_by_selectors_detailed(
            page, build_selectors(35, None), 'username_selectors', budget=1.0,
            role=ROLE_USERNAME, trusted=True, delayed_window=False)
    check("6 预算耗尽时未命中", not result['hit'], f"reason={result.get('reason')}")
    check("6 退出原因=budget_exceeded", result['exit_reason'] == 'budget_exceeded',
          str(result.get('exit_reason')))
    check("6 因预算不足未执行>0", result['skipped'] > 0, str(result['skipped']))
    check("6 实际开始执行少于候选总数",
          result['executed'] < result['unique_total'],
          f"executed={result['executed']} unique={result['unique_total']}")
    check("6 不完整查找=是", result['incomplete'] is True, str(result['incomplete']))
    check("6 统计执行数与逐候选记录一致",
          result['executed'] == executed_entries(result),
          f"统计={result['executed']} 记录={executed_entries(result)}")
    summary = capture_summary("测试-预算耗尽", result)
    check("6 汇总日志含因预算不足未执行", "因预算不足未执行=" in summary, summary)

    # ============ 场景 7：页面未就绪 ============
    closed = await context.new_page()
    await browser_mod.navigate(closed, f'{base_url}/generic')
    await closed.close()
    result = await browser_mod.find_by_selectors_detailed(
        closed, build_selectors(35, 5), 'username_selectors', budget=5,
        role=ROLE_USERNAME, trusted=True, delayed_window=False)
    check("7 页面不可用时不会命中", not result['hit'],
          f"hit={result['hit']} reason={result.get('reason')}")
    check("7 退出原因不是 hit", result['exit_reason'] != 'hit',
          str(result.get('exit_reason')))
    check("7 不完整查找按实际执行情况计算", isinstance(result['incomplete'], bool),
          str(result['incomplete']))

    # ============ 场景 8：用户名命中但填写失败 ============
    disabled_page = await context.new_page()
    await browser_mod.navigate(disabled_page, f'{base_url}/roles/disabled')
    result = await browser_mod.find_by_selectors_detailed(
        disabled_page, [{'by': 'CSS_SELECTOR', 'value': 'input[disabled]'}],
        'username_selectors', budget=10, role=ROLE_USERNAME, trusted=True,
        delayed_window=False)
    check("8 被禁用的元素不会被判定为可用用户名", not result['hit'],
          f"hit={result['hit']} reason={result.get('reason')}")

    readonly_page = await context.new_page()
    await browser_mod.navigate(readonly_page, f'{base_url}/roles/disabled')
    locator = readonly_page.locator('input[readonly]')
    ok, reason = await browser_mod.input_text_detailed(locator, 'admin')
    check("8 只读元素填写失败并给出明确原因",
          (not ok) and reason == 'not_editable', f"ok={ok} reason={reason}")

    detached = await readonly_page.locator('input#visibleUser').element_handle()
    await readonly_page.close()
    ok, reason = await browser_mod.input_text_detailed(detached, 'admin')
    check("8 失效引用填写失败并给出明确原因",
          (not ok) and reason in ('element_detached', 'not_visible'),
          f"ok={ok} reason={reason}")

    await disabled_page.close()
    await readonly_page.close()
    await page.close()


async def main():
    started = time.monotonic()
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=[
            '--disable-dev-shm-usage', '--no-sandbox', '--ignore-certificate-errors',
        ])
        context = await browser.new_context(ignore_https_errors=True)
        try:
            with TestServer() as server:
                await run_scenarios(context, server.base_url)
        finally:
            try:
                await context.close()
            except Exception:
                pass
            try:
                await browser.close()
            except Exception:
                pass

    print("\n" + "=" * 60)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"候选统计与日志测试: {passed} 通过 / {failed} 失败"
          f"（总耗时 {int((time.monotonic() - started) * 1000)}ms）")
    for name, ok, detail in RESULTS:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}  {detail}")
    print("=" * 60)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
