"""
akshare 接口健康检查脚本

用法：
    cd lixinger-local
    python scripts/check_akshare.py

功能：逐一测试所有使用的 akshare 接口，生成可用性报告
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import akshare as ak
from utils.api_compat import AKSHARE_API_MAP


def _resolve_function(module, dotted_path: str):
    parts = dotted_path.split(".")
    obj = module
    for part in parts[1:]:
        obj = getattr(obj, part)
    return obj


def check_all_apis():
    print(f"\nakshare 版本: {ak.__version__}")
    print("=" * 65)
    print("akshare 接口健康检查报告")
    print("=" * 65)

    results = []

    for key, config in AKSHARE_API_MAP.items():
        api_path = config["primary"]
        desc = config.get("description", "")
        print(f"检查: {key} ({api_path})")
        print(f"      {desc}")

        try:
            func = _resolve_function(ak, api_path)

            # 用最小参数试探（不做真实请求，只验证函数存在且可调用）
            if key == "stock_list":
                result = func()
            elif key == "industry_list":
                result = func()
            elif key == "stock_realtime":
                # 实时行情数据量大，只检查函数存在
                print(f"  ⚠️  跳过实际请求（数据量过大）")
                results.append({"key": key, "api": api_path, "status": "⚠️ 未验证", "detail": "跳过实际请求"})
                print()
                continue
            elif key == "industry_constituents":
                result = func(symbol="饮料乳品")
            elif key in ("daily_quotes",):
                result = func(symbol="000001", period="daily", start_date="20240101", end_date="20240110", adjust="qfq")
            elif key in ("financial_income", "financial_balance", "financial_cashflow"):
                # 新浪财报: stock=交易所前缀+代码, symbol=中文报表类型
                report_type = config["params"].get("symbol", "利润表")
                result = func(stock="sz000001", symbol=report_type)
            elif key == "valuation_indicator":
                result = func(symbol="000001")
            elif key == "dividends":
                result = func(symbol="000001")
            else:
                result = func()

            status = "✅ 可用"
            detail = f"返回 {len(result)} 条数据" if hasattr(result, "__len__") else "返回成功"

        except AttributeError as e:
            status = "❌ 接口不存在"
            detail = str(e)
        except Exception as e:
            status = "❌ 调用失败"
            detail = str(e)[:120]

        results.append({"key": key, "api": api_path, "status": status, "detail": detail})
        print(f"  {status}: {detail}")
        print()

    # 汇总报告
    print("\n" + "=" * 65)
    print("汇总:")
    ok = sum(1 for r in results if r["status"].startswith("✅"))
    fail = sum(1 for r in results if r["status"].startswith("❌"))
    warn = sum(1 for r in results if r["status"].startswith("⚠️"))
    print(f"  ✅ 可用: {ok}  ❌ 失败: {fail}  ⚠️ 未验证: {warn}")

    if fail > 0:
        print("\n失败的接口:")
        for r in results:
            if r["status"].startswith("❌"):
                print(f"  - {r['key']}: {r['api']}")
                print(f"    错误: {r['detail']}")
        print("\n建议:")
        print("  1. 运行 pip install akshare --upgrade 更新到最新版本")
        print("  2. 查阅官方文档: https://akshare.akfamily.xyz/")
        print("  3. 更新 backend/utils/api_compat.py 中的映射表")
    print("=" * 65)


if __name__ == "__main__":
    check_all_apis()
