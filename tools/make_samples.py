"""生成 demo 样例数据（端子清单 + 传感器清单），方便第一次打开就能试。

用法：python tools/make_samples.py
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"

TERMINALS = [
    ("RM.MP.RNB.020", "圆形裸端子", "RNBS5.5-4-90D"),
    ("RM.MP.RNB.019", "圆形裸端子", "RNB8-4"),
    ("RM.MP.RNB.018", "圆形裸端子", "RNB14-8"),
    ("RM.MP.RNB.017", "圆形裸端子", "RNB14-5"),
    ("RM.MP.RNB.016", "圆形裸端子", "RNB14-6S"),
    ("RM.MP.RNB.015", "圆形裸端子", "RNB3.5-5S"),
    ("RM.MP.RNB.014", "圆形裸端子", "RNB2-10"),
    ("RM.MP.RNB.013", "圆形裸端子", "RNB3.5-4"),
    ("RM.MP.RNB.012", "圆形裸端子", "RNB3.5-5"),
    ("RM.MP.RNB.011", "圆形裸端子", "RNB3.5-4S"),
    ("RM.MP.RNB.010", "圆形裸端子", "RNB5.5-3"),
    ("RM.MP.RNB.009", "圆形裸端子", "RNB1.25-5S"),
    ("RM.MP.RNB.008", "圆形裸端子", "RNB1.25-4L"),
    ("RM.MP.RNB.007", "圆形裸端子", "RNB1.25-3"),
    ("RM.MP.RNB.006", "圆形裸端子", "RNB5.5-4S"),
    ("RM.MP.RNB.005", "圆形裸端子", "RNB5.5-4L"),
    ("RM.MP.RNB.004", "圆形裸端子", "RNB2-4S"),
    ("RM.MP.RNB.003", "圆形裸端子", "RNB2-3"),
    ("RM.MP.RNB.002", "圆形裸端子", "RNB2-5S"),
    ("RM.MP.RNB.001", "圆形裸端子", "RNB5.5-5"),
]

SENSORS = [
    ("SN.PT100.A01", "铂电阻温度传感器", "PT100-A级-3线-4米", "上海自动化仪表", "2024-03-12"),
    ("SN.PT100.A02", "铂电阻温度传感器", "PT100-B级-2线-2米", "上海自动化仪表", "2024-03-12"),
    ("SN.KTYPE.001", "铠装热电偶", "K型-Φ3-300mm-耐高温", "安徽天康", "2024-04-02"),
    ("SN.KTYPE.002", "铠装热电偶", "K型-Φ5-500mm-标准", "安徽天康", "2024-04-02"),
    ("SN.PRS.0101", "压力变送器", "0-1.6MPa-4-20mA-G1/2", "重庆川仪", "2024-05-18"),
    ("SN.PRS.0102", "压力变送器", "0-10MPa-4-20mA-M20", "重庆川仪", "2024-05-18"),
    ("SN.LVL.201", "投入式液位计", "0-5m-24VDC-4-20mA", "北京昆仑海岸", "2024-06-01"),
    ("SN.FLW.301", "电磁流量计", "DN50-1.6MPa-4-20mA", "横河川仪", "2024-06-21"),
    ("SN.ENC.401", "增量式编码器", "1000P/R-ABZ-φ8", "欧姆龙", "2024-07-09"),
    ("SN.PRX.402", "接近开关", "M18-NPN-NO-常开", "欧姆龙", "2024-07-09"),
    ("SN.PWR.501", "开关电源", "24V/5A-120W-导轨式", "明纬", "2024-08-15"),
    ("SN.PWR.502", "开关电源", "12V/10A-120W-导轨式", "明纬", "2024-08-15"),
]


def write_xlsx(path: Path, header: list[str], rows: list[tuple], title: str) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = title
    ws.append(header)
    for i, row in enumerate(rows, start=1):
        ws.append([i, *row])
    for i, _ in enumerate(header, start=1):
        ws.column_dimensions["ABCDEFGHIJ"[i - 1]].width = 14 if i > 1 else 6
    wb.save(str(path))


def main() -> int:
    SAMPLES.mkdir(parents=True, exist_ok=True)

    write_xlsx(
        SAMPLES / "端子清单.xlsx",
        ["序号", "数据标题", "产品名称", "产品规格"],
        TERMINALS,
        "圆形裸端子",
    )
    write_xlsx(
        SAMPLES / "传感器清单.xlsx",
        ["序号", "物料编码", "产品名称", "产品规格", "品牌", "入库日期"],
        SENSORS,
        "传感器",
    )

    with (SAMPLES / "端子清单.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["序号", "数据标题", "产品名称", "产品规格"])
        for i, row in enumerate(TERMINALS, start=1):
            w.writerow([i, *row])

    print(f"已生成样例到 {SAMPLES}")
    for p in sorted(SAMPLES.glob("*")):
        if p.is_file():
            print(" -", p.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
