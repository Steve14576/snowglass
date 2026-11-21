# /// script
# requires-python = ">=3.12"
# dependencies = ["playwright>=1.50,<2"]
# ///
"""小样的独立浏览器核验及截图，不使用／覆盖用户的浏览器工程状态。"""
import json
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
RUN = "run-20261121-211150-652530"
OUTPUT = ROOT / "prototype/data/gray_samples" / RUN / ("verification-" + datetime.now().strftime("%Y%m%d-%H%M%S"))


def main():
    OUTPUT.mkdir(exist_ok=False)
    errors = []
    result = {"run": RUN, "views": [], "errors": errors}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True,
                                    args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        page = browser.new_page(viewport={"width": 1520, "height": 1040}, device_scale_factor=1)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(f"http://localhost:8124/prototype/gray_samples.html?run={RUN}", wait_until="networkidle", timeout=45000)
        page.wait_for_function("window.graySampleTest && document.querySelectorAll('.viewport canvas').length===3", timeout=15000)
        result["checks"] = page.evaluate("async () => await (0,eval)(await (await fetch('../tests/gray_samples_checks.js')).text())")
        for key in ("attention", "mlp"):
            for view in ("baseline", "reveal", "threshold"):
                settings = {"tensor": key, "resolution": "fine", "gain": 1, "gamma": 1, "threshold": 0,
                            "residue": .15, "size": .45, "axis": 1, "slice": 8, "slab": False, "render-mode": "additive"}
                if view == "reveal":
                    settings.update(gain=3, gamma=.7)
                elif view == "threshold":
                    settings.update(threshold=.2 if key == "attention" else .1)
                page.evaluate("s=>window.graySampleTest.set(s)", settings)
                page.wait_for_timeout(350)
                record = page.evaluate("() => ({settings:window.graySampleTest.state.settings,statistics:window.graySampleTest.state.statistics})")
                record["name"] = f"{key}_{view}"
                page.screenshot(path=str(OUTPUT / (record["name"] + ".png")), full_page=True)
                result["views"].append(record)
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(200)
        result["mobile"] = page.evaluate("() => ({width:innerWidth,scroll:document.documentElement.scrollWidth})")
        assert result["mobile"]["scroll"] <= result["mobile"]["width"], "小屏出现横向溢出"
        # 无效目录必须给出可读错误，不加载随机替代物。
        page.goto("http://localhost:8124/prototype/gray_samples.html?run=invalid", wait_until="networkidle")
        result["invalid_input"] = page.locator("#status").inner_text()
        assert "运行目录格式无效" in result["invalid_input"]
        assert not errors, errors
        browser.close()
    with (OUTPUT / "verification.json").open("x", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps({"output": str(OUTPUT), "checks": result["checks"], "mobile": result["mobile"], "errors": errors}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
