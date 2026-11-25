import requests
import time
from bs4 import BeautifulSoup
import re
import json
from datetime import datetime
import os
import base64
import sys

# ============================================================
# 实时水情数据相关（来源：广西水利厅API）
# ============================================================

REALTIME_API_URL = "http://slt.gxzf.gov.cn/gxsl/api/sl323/realtime/river/"
REALTIME_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "http://slt.gxzf.gov.cn/page/index.html?act=3",
    "Accept": "application/json, text/plain, */*",
}
REALTIME_TARGET_STATIONS = [
    "梧州（四）（水文）",
    "南宁（三）（水文）",
    "贵港（水文）",
    "平南（水文）",
    "来宾（水文）",
    "武宣",
]
REALTIME_JSON_FILE = "realtime_water_level.json"


def realtime_clean_station_name(name):
    """清洗站名：去掉所有括号及括号内的内容"""
    name = re.sub(r'[（(].*?[)）]', '', name)
    return name.strip()


def realtime_fetch_water_data(st_name=""):
    """从 API 获取实时水情数据"""
    url = REALTIME_API_URL + st_name
    print(f"正在请求实时水情API: {url}")
    try:
        resp = requests.get(url, headers=REALTIME_HEADERS, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        result = data.get("result", [])
        print(f"成功获取 {len(result)} 条实时水情记录")
        return result
    except requests.RequestException as e:
        print(f"实时水情请求失败: {e}")
        return []
    except json.JSONDecodeError as e:
        print(f"实时水情JSON解析失败: {e}")
        return []


def realtime_filter_stations(data, station_names):
    """从全部数据中筛选目标站点"""
    target_set = set(station_names)
    filtered = []
    for row in data:
        stnm = str(row.get("STNM", "")).strip()
        if stnm in target_set:
            filtered.append(row)
    print(f"筛选目标站点: {len(filtered)}/{len(station_names)} 个")
    found = {str(r.get("STNM", "")).strip() for r in filtered}
    missing = target_set - found
    if missing:
        print(f"警告: 未找到以下站点: {', '.join(missing)}")
    return filtered


def realtime_extract_fields(data):
    """提取需要的字段，以纯净站名为 key 组织成字典"""
    cleaned = {}
    for row in data:
        raw_name = str(row.get("STNM", "")).strip()
        name = realtime_clean_station_name(raw_name)
        tm = row.get("TM")
        if tm and isinstance(tm, (int, float)):
            try:
                tm = datetime.fromtimestamp(tm / 1000).strftime("%m-%d %H:%M")
            except (ValueError, OSError):
                pass
        cleaned[name] = {
            "Z": row.get("Z"),
            "ZWRNDLT": row.get("ZWRNDLT"),
            "TM": tm,
        }
    return cleaned


def realtime_load_existing(filename=REALTIME_JSON_FILE):
    """读取已有的实时 JSON 数据文件"""
    filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
    if not os.path.exists(filepath):
        return []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            existing = json.load(f)
        if not isinstance(existing, list):
            return []
        return existing
    except (json.JSONDecodeError, OSError):
        return []


def realtime_calc_water_change(data, existing):
    """计算各站水位变化值（与上一批数据对比）"""
    prev_stations = {}
    if existing:
        prev_batch = existing[-1]
        prev_stations = prev_batch.get("站点实时数据", {})
    for name, info in data.items():
        prev_z = prev_stations.get(name, {}).get("Z")
        curr_z = info.get("Z")
        if prev_z is not None and curr_z is not None:
            delta = round(curr_z - prev_z, 2)
            info["变化值"] = f"{delta:+.2f}"
            info["变化"] = 1 if delta > 0 else 0
            info["情况"] = "▲" if delta > 0 else "▼"
            info["颜色"] = "wRed" if delta > 0 else "wGreen"
        else:
            info["变化值"] = None
            info["变化"] = None
            info["情况"] = None
            info["颜色"] = None
    return data


def realtime_calc_summary(data):
    """计算统计信息"""
    total = len(data)
    over_warning = sum(1 for v in data.values() if v.get("ZWRNDLT") is not None and float(v["ZWRNDLT"]) > 0)
    rising = sum(1 for v in data.values() if v.get("变化") == 1)
    falling = sum(1 for v in data.values() if v.get("变化") == 0)
    return {
        "站点总数": total,
        "超警戒数": over_warning,
        "上升站点数": rising,
        "下降站点数": falling,
    }


def realtime_save_to_json(data, summary, existing, filename=REALTIME_JSON_FILE):
    """将实时数据以批次形式追加保存到 JSON 文件"""
    if not data:
        print("无实时数据可保存")
        return
    filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
    data_time = ""
    first_tm = next(iter(data.values()), {}).get("TM", "")
    tm_str = str(first_tm) if first_tm else ""
    match = re.search(r"(\d{2}:\d{2})", tm_str)
    if match:
        data_time = match.group(1)
    batch = {
        "爬取时间": datetime.now().strftime("%m-%d %H:%M:%S"),
        "数据时间": data_time,
        "站点实时数据": data,
        "统计信息": summary,
    }
    existing.append(batch)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    print(f"实时数据已保存到: {filepath}（当前共 {len(existing)} 批）")


def realtime_print_summary(data):
    """打印实时数据摘要"""
    if not data:
        print("无实时数据")
        return
    print("\n" + "=" * 70)
    print(f"实时水情数据（共 {len(data)} 个站点）")
    print("=" * 70)
    print(f"{'测站名称':<10} {'水位(m)':>8} {'超警戒(m)':>10} {'变化值':>8} {'情况':>4} {'时间':<22}")
    print("-" * 70)
    for name, info in data.items():
        z = info.get("Z")
        zwrndlt = info.get("ZWRNDLT")
        tm = info.get("TM", "")
        delta = info.get("变化值")
        trend = info.get("情况", "")
        z_str = f"{z:.2f}" if z is not None else "-"
        zwrndlt_str = f"{zwrndlt:+.2f}" if zwrndlt is not None else "-"
        delta_str = delta if delta is not None else "-"
        print(f"{name:<10} {z_str:>8} {zwrndlt_str:>10} {delta_str:>8} {trend:>4} {str(tm):<22}")
    print("=" * 70)
    over_warning = sum(1 for v in data.values() if v.get("ZWRNDLT") is not None and float(v["ZWRNDLT"]) > 0)
    rising = sum(1 for v in data.values() if v.get("变化") == 1)
    print(f"统计: 总站点 {len(data)} | 超警戒 {over_warning} | 水位上升 {rising} | 水位下降/持平 {len(data) - rising}")
    print()


def realtime_main():
    """实时水情爬取主函数"""
    print("=" * 60)
    print("广西水利厅实时水情")
    print("数据来源: http://slt.gxzf.gov.cn/page/index.html?act=3")
    print(f"目标站点: {', '.join(REALTIME_TARGET_STATIONS)}")
    print("=" * 60)

    data = realtime_fetch_water_data("")
    if not data:
        print("未获取到实时水情数据")
        return None

    filtered = realtime_filter_stations(data, REALTIME_TARGET_STATIONS)
    if not filtered:
        print("未筛选到目标站点数据")
        return None

    cleaned = realtime_extract_fields(filtered)
    existing = realtime_load_existing(REALTIME_JSON_FILE)
    if existing:
        print(f"已有 {len(existing)} 批实时历史数据")
    cleaned = realtime_calc_water_change(cleaned, existing)
    summary = realtime_calc_summary(cleaned)
    realtime_print_summary(cleaned)
    realtime_save_to_json(cleaned, summary, existing, REALTIME_JSON_FILE)
    print("\n实时水情爬取完成！")
    return cleaned


# ============================================================
# 原有早八点水情数据相关
# ============================================================


def load_data():
    """从JSON文件加载历史数据"""
    try:
        with open('water_level_data.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return []
    except json.JSONDecodeError:
        return []


def save_data(data):
    """保存数据到JSON文件"""
    with open('water_level_data.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def generate_html_report(data):
    """生成HTML可视化报告"""
    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>水位数据可视化报告</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.js"></script>
    <style>
        body {{
            font-family: 'Microsoft YaHei', Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        }}
        .container {{
            max-width: 1350px;
            min-width: 1350px;
            margin: 0 auto;
            background-color: white;
            padding: 5px 20px;
            border-radius: 10px;
            box-shadow: 2px 2px 3px 3px rgba(0,0,0,0.3);
        }}
        h1 {{
            text-align: center;
            color: #333;
            margin: 0px;
        }}
        .chart-section {{
            margin-bottom: 0px;
        }}
        .chart-container {{
            position: relative;
            height: 400px;
            margin-bottom: 0px;
        }}
        .table-section {{
            margin-top: 20px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 20px;
        }}
        th, td {{
            border: 1px solid #ddd;
            padding: 12px;
            text-align: center;
        }}
        th {{
            background-color: #3a71cb;
            color: white;
            font-weight: bold;
            font-size: 18px;
        }}
        tr:nth-child(even) {{
            background-color: #f9f9f9;
        }}
        tr:hover {{
            background-color: #f1f1f1;
        }}
        .timestamp {{
            text-align: right;
            color: #666;
            font-size: 14px;
            margin-top: 20px;
        }}
        .status-section {{
            background-color: #f8f9fa;
            padding: 10px 10px;
            border-radius: 10px;
            margin: 10px 0;
            border: 2px solid #ddd;
            display: flex;
            justify-content: center;
            align-items: center;
            flex-wrap: wrap;
            gap: 0px;
        }}
        .status-item {{
            align-items: self-end;
        }}
        .status-label {{
            font-size: 20px;
            color: #414141;
            font-weight: bold;
        }}
        .status-value {{
            font-size: 40px;
            font-weight: bold;
        }}
        .warningStatus-value {{
            font-size: 25px;
            font-weight: bold;
            line-height: 32px;
        }}
        .status-red {{
            color: #fe2d2d;
        }}
        .status-orange {{
            color: #ff8400;
        }}
        .status-blue {{
            color: #007bff;
        }}

        .status-green {{
            color: #00d305;
        }}
        
        .status-wRed {{
            color: #d60000;
        }}
        .status-wGreen {{
            color: #009003;
        }}

        .cc {{
            color: green;
            font-size: 170%;
            font-weight: bold;
            line-height: 170%;
        }}
        .c-c {{
            color: orange;
        }}
        .image-section {{
            max-width: 90%;
            margin: 0px auto;
            text-align: center;
            position: relative;
            border-radius: 10px;
            box-shadow: 2px 2px 2px 2px rgba(0,0,0,0.3);
        }}
        .image-section img {{
            max-width: 100%;
            height: auto;
            display: block;
            border-radius: 10px;
            margin: 0 auto 20px auto;
        }}
        .image-overlay-text {{
            transform: translateX(-50%);
            font-size: 250%;
            font-weight: bold;
            z-index: 10;
            white-space: nowrap;
        }}
        .wz {{
            position: absolute;
            top: 52%;
            left: 92.5%;
        }}
        .jk {{
            position: absolute;
            top: 52%;
            left: 68%;  
        }}
        .wx {{
            position: absolute;
            top: 10%;
            left: 40%;
        }}
        .lb {{
            position: absolute;
            top: 10%;
            left: 11%;
        }}
        .lc {{
            position: absolute;
            top: 54.5%;
            left: 13%;
        }}
        .gg {{
            position: absolute;
            top: 54.5%;
            left: 46%;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>西江流域水位数据可视化报告</h1>
        
        <div class="chart-section">
            <div class="chart-container">
                <canvas id="waterLevelChart"></canvas>
                <div class="image-overlay-text " style="position: absolute; top: 7%; left: 48%; font-size:100%;opacity: 0.3;color: black;">单击站点名称↓，可选择是否显示其水位波动曲线</div>
            </div>
        </div>
"""

    # 按时间排序数据
    sorted_data = sorted(data, key=lambda x: x['时间'])

    # 测试输出
    #print(sorted_data)

    # 获取数据
    if sorted_data:
        #只拿早八点的水库船闸数据和梧州水位数据 
        am8_datengxia_data = sorted_data[-1].get('枢纽数据',{}).get('大藤峡枢纽', {}).get('上游水位', '0')
        am8_datengxia_fs = sorted_data[-1].get('枢纽数据',{}).get('大藤峡枢纽', {}).get('是否放水', '0')
        am8_datengxia_rkll = sorted_data[-1].get('枢纽数据',{}).get('大藤峡枢纽', {}).get('入库流量', '-')
        am8_datengxia_ckll = sorted_data[-1].get('枢纽数据',{}).get('大藤峡枢纽', {}).get('出库流量', '0')

        am8_guigang_data = sorted_data[-1].get('枢纽数据',{}).get('贵港枢纽', {}).get('上游水位', '0')
        am8_guigang_fs = sorted_data[-1].get('枢纽数据',{}).get('贵港枢纽', {}).get('是否放水', '0')
        am8_guigang_rkll = sorted_data[-1].get('枢纽数据',{}).get('贵港枢纽', {}).get('入库流量', '-')
        am8_guigang_ckll = sorted_data[-1].get('枢纽数据',{}).get('贵港枢纽', {}).get('出库流量', '0')

        am8_changzhou_data = sorted_data[-1].get('枢纽数据',{}).get('长洲船闸', {}).get('上游水位', '0')
        am8_changzhou_fs = sorted_data[-1].get('枢纽数据',{}).get('长洲船闸', {}).get('是否放水', '0')
        am8_changzhou_rkll = sorted_data[-1].get('枢纽数据',{}).get('长洲船闸', {}).get('入库流量', '-')
        am8_changzhou_ckll = sorted_data[-1].get('枢纽数据',{}).get('长洲船闸', {}).get('出库流量', '0')

        #因为实时数据要和早八点数据分开，所以单独取出早八点数据新建变量
        am8_wuzhou_wcolor = sorted_data[-1].get('站点数据',{}).get('梧州', {}).get('颜色', 'black')
        am8_wuzhou_desc = sorted_data[-1].get('站点数据',{}).get('梧州', {}).get('情况', '-')
        am8_wuzhou_data = sorted_data[-1].get('站点数据',{}).get('梧州', {}).get('水位', '0')
        am8_wuzhou_change = sorted_data[-1].get('站点数据',{}).get('梧州', {}).get('变化值', '0')        

    # 加载实时水情数据（来源：realtime_water_level.json）
    realtime_history = realtime_load_existing(REALTIME_JSON_FILE)
    if realtime_history:
        rt = realtime_history[-1].get('站点实时数据', {})
        latest_wuzhou_time = realtime_history[-1].get('数据时间', '未知')

        latest_wuzhou_data = rt.get('梧州', {}).get('Z', '0')
        latest_wuzhou_change = rt.get('梧州', {}).get('变化值', '0')
        latest_wuzhou_overWarning = rt.get('梧州', {}).get('ZWRNDLT', '-99')
        latest_wuzhou_wcolor = rt.get('梧州', {}).get('颜色', 'black')
        latest_wuzhou_desc = rt.get('梧州', {}).get('情况', '-')

        latest_pn_data = rt.get('平南', {}).get('Z', '0')
        latest_pn_change = rt.get('平南', {}).get('变化值', '0')
        latest_pn_overWarning = rt.get('平南', {}).get('ZWRNDLT', '-99')
        latest_pn_wcolor = rt.get('平南', {}).get('颜色', 'black')
        latest_pn_desc = rt.get('平南', {}).get('情况', '-')

        latest_wuxuan_data = rt.get('武宣', {}).get('Z', '0')
        latest_wuxuan_change = rt.get('武宣', {}).get('变化值', '0')
        latest_wuxuan_overWarning = rt.get('武宣', {}).get('ZWRNDLT', '-99')
        latest_wuxuan_wcolor = rt.get('武宣', {}).get('颜色', 'black')
        latest_wuxuan_desc = rt.get('武宣', {}).get('情况', '-')

        latest_laibing_data = rt.get('来宾', {}).get('Z', '0')
        latest_laibing_change = rt.get('来宾', {}).get('变化值', '0')
        latest_laibing_overWarning = rt.get('来宾', {}).get('ZWRNDLT', '-99')
        latest_laibing_wcolor = rt.get('来宾', {}).get('颜色', 'black')
        latest_laibing_desc = rt.get('来宾', {}).get('情况', '-')

        latest_nn_data = rt.get('南宁', {}).get('Z', '0')
        latest_nn_change = rt.get('南宁', {}).get('变化值', '0')
        latest_nn_overWarning = rt.get('南宁', {}).get('ZWRNDLT', '-99')
        latest_nn_wcolor = rt.get('南宁', {}).get('颜色', 'black')
        latest_nn_desc = rt.get('南宁', {}).get('情况', '-')

        latest_gg_data = rt.get('贵港', {}).get('Z', '0')
        latest_gg_change = rt.get('贵港', {}).get('变化值', '0')
        latest_gg_overWarning = rt.get('贵港', {}).get('ZWRNDLT', '-99')
        latest_gg_wcolor = rt.get('贵港', {}).get('颜色', 'black')
        latest_gg_desc = rt.get('贵港', {}).get('情况', '-')

        latest_stationNumber = realtime_history[-1].get('统计信息', {}).get('站点总数', '0')
        latest_warningNumber = realtime_history[-1].get('统计信息', {}).get('超警戒线数', '0')
        latest_upNumber = realtime_history[-1].get('统计信息', {}).get('上升站点数', '0')
        latest_downNumber = realtime_history[-1].get('统计信息', {}).get('下降站点数', '0')
        print(f"已加载实时水情数据，最新批次时间: {realtime_history[-1].get('爬取时间', '未知')}")

    #站点告警文字
    station_warning = ' '

    #站点是否需要警告符号
    latest_wuzhou_wSymbol = ' '
    latest_pn_wSymbol = ' '
    latest_wuxuan_wSymbol = ' '
    latest_laibing_wSymbol = ' '
    latest_nn_wSymbol = ' '
    latest_gg_wSymbol = ' '

    #站点水位状态标识颜色
    latest_wuzhou_color = 'blue'
    latest_pn_color = 'blue'
    latest_wuxuan_color = 'blue'
    latest_laibing_color = 'blue'
    latest_nn_color = 'blue'
    latest_gg_color = 'blue'
    am8_wuzhou_color = 'blue'

    #梧州情况语句
    am8_wuzhou_QK = ''
    latest_wuzhou_QK = ''


    #早八点梧州水位状态判定
    if float(am8_wuzhou_data) >= 18.5: #早八点梧州水位大于18.5米
        am8_wuzhou_color = 'red'
        am8_wuzhou_QK += '<span class="status-red">超警&nbsp;</span>'

    if float(am8_wuzhou_data) >= 13 and float(am8_wuzhou_data) < 18.5: #早八点梧州水位较高
        am8_wuzhou_color = 'orange'
        am8_wuzhou_QK += '<span class="status-orange">水位高&nbsp;</span>'

    if float(am8_wuzhou_change) >= 2:    #早八点梧州水位快速上涨
        am8_wuzhou_color = 'red'
        am8_wuzhou_QK += '<span class="status-red">快速涨水&nbsp;</span>'

    if float(am8_wuzhou_data) < 4 and float(am8_wuzhou_data) >= 2.5:    #早八点梧州水位在4米到2.5之间
        am8_wuzhou_color = 'orange'
        am8_wuzhou_QK += '<span class="status-orange">水位较低&nbsp;</span>'


    if float(am8_wuzhou_data) < 2.5 and float(am8_wuzhou_data) >= 2:    #早八点梧州水位较低（<2.5m >2m 预留警告语句）
        am8_wuzhou_color = 'red'
        am8_wuzhou_QK += '<span class="status-red">水位低(<2.5m)&nbsp;</span>'

    if float(am8_wuzhou_data) < 2:   #早八点梧州水位较低（<2m 预留警告语句）
        am8_wuzhou_color = 'red'
        am8_wuzhou_QK += '<span class="status-red">水位极低(<2m)&nbsp;</span>'

    if am8_wuzhou_QK == '':   #如果没有任何情况 只显示正常
        am8_wuzhou_QK += '<span class="status-blue">水位正常&nbsp;</span>'

    #站点是否需要超警戒线警告
    s1 = 0
    if float(latest_wuzhou_overWarning) >= 0:  #梧州警戒线18.5
        latest_wuzhou_wSymbol = '🚨'
        latest_wuzhou_color = 'red'
        latest_wuzhou_QK += '<span class="status-red">超警&nbsp;</span>'
        station_warning += '<br> &nbsp;'
        station_warning += '梧州（已超警'
        station_warning += str(format(float(latest_wuzhou_overWarning)), '.2f')
        station_warning += '米）'
        s1 = 1

    if float(latest_pn_overWarning) >= 0:  #平南警戒线29 濛江25，藤县23
        latest_pn_wSymbol = '🚨'
        latest_pn_color = 'red'
        if s1 != 0:
            station_warning += '、'
        else:
            station_warning += '<br> &nbsp;'
        station_warning += '濛江（已超警'
        station_warning += str(format(float(latest_pn_overWarning)), '.2f')
        station_warning += '米）'
        s1 = 1

    if float(latest_gg_overWarning) >= 0:  #贵港坝下警戒线41.2米 横县警戒线54.2米
        latest_gg_wSymbol = '🚨'
        latest_gg_color = 'red'
        if s1 != 0:
            station_warning += '、'
        else:
            station_warning += '<br> &nbsp;'
        station_warning += '横县（已超警'
        station_warning += str(format(float(latest_gg_overWarning)), '.2f')
        station_warning += '米）'
        s1 = 1

    if float(latest_nn_overWarning) >= 0:     #南宁警戒线73 峦城64.2米
        latest_nn_wSymbol = '🚨'
        latest_nn_color = 'red'
        if s1 != 0:
            station_warning += '、'
        else:
            station_warning += '<br> &nbsp;'
        station_warning += '峦城（已超警'
        station_warning += str(format(float(latest_nn_overWarning)), '.2f')
        station_warning += '米）'
        s1 = 1

    if float(latest_wuxuan_overWarning) >= 62:  #武宣警戒线62
        latest_wuxuan_wSymbol = '🚨'
        latest_wuxuan_color = 'red'
        if s1 != 0:
            station_warning += '、'
        else:
            station_warning += '<br> &nbsp;'
        station_warning += '武宣（已超警'
        station_warning += str(format(float(latest_wuxuan_overWarning)), '.2f')
        station_warning += '米）'
        s1 = 1

    if float(latest_laibing_overWarning) >= 77.9:  #来宾警戒线77.4
        latest_laibing_wSymbol = '🚨'
        latest_laibing_color = 'red'
        if s1 != 0:
            station_warning += '、'
        else:
            station_warning += '<br> &nbsp;'
        station_warning += '来宾（已超警'
        station_warning += str(format(float(latest_laibing_overWarning)), '.2f')
        station_warning += '米）'
        s1 = 1

    if s1 != 0:
        station_warning += '站点水位已超警！请关注封航信息与水位未来变化！'

    s2 = 0
    if float(latest_wuzhou_data) >= 13 and float(latest_wuzhou_data) < 18.5:
        latest_wuzhou_wSymbol = '⚠️'
        latest_wuzhou_color = 'orange'
        latest_wuzhou_QK += '<span class="status-orange">水位高&nbsp;</span>'
        station_warning += '<br> &nbsp;'
        station_warning += '梧州（水位已超过13米）'

    if float(latest_pn_data) >= 25 and float(latest_pn_data) < 28:
        latest_pn_wSymbol = '⚠️'
        latest_pn_color = 'orange'
        if s2 != 0:
            station_warning += '、'
        else:
            station_warning += '<br> &nbsp;'
        station_warning += '濛江（水位已超过25米）'

    if s2 != 0:
        station_warning += '水位较高，注意留意封航通知！'

    #站点是否需要水位快速上涨警告
    s3 = 0
    if float(latest_wuzhou_change) > 0.2:
        latest_wuzhou_wSymbol = '🚨'
        latest_wuzhou_color = 'red'
        latest_wuzhou_QK += '<span class="status-red">快速涨水&nbsp;</span>'
        station_warning += '<br> &nbsp;'
        station_warning += '梧州'
        s3 = 1

    if float(latest_pn_change) > 0.2:
        latest_pn_wSymbol = '🚨'
        latest_pn_color = 'red'
        if s3 != 0:
            station_warning += '、'
        else:
            station_warning += '<br> &nbsp;'
        station_warning += '濛江'
        s3 = 1

    if float(latest_wuxuan_change) > 0.2:
        latest_wuxuan_wSymbol = '🚨'
        latest_wuxuan_color = 'red'
        if s3 != 0:
            station_warning += '、'
        else:
            station_warning += '<br> &nbsp;'
        station_warning += '武宣'
        s3 = 1

    if float(latest_laibing_change) > 0.2:
        latest_laibing_wSymbol = '🚨'
        latest_laibing_color = 'red'
        if s3 != 0:
            station_warning += '、'
        else:
            station_warning += '<br> &nbsp;'
        station_warning += '来宾'
        s3 = 1

    if float(latest_nn_change) > 0.2:
        latest_nn_wSymbol = '🚨'
        latest_nn_color = 'red'
        if s3 != 0:
            station_warning += '、'
        else:
            station_warning += '<br> &nbsp;'
        station_warning += '峦城'
        s3 = 1

    if float(latest_gg_change) > 0.2:
        latest_gg_wSymbol = '🚨'
        latest_gg_color = 'red'
        if s3 != 0:
            station_warning += '、'
        else:
            station_warning += '<br> &nbsp;'
        station_warning += '横县'
        s3 = 1

    if s3 != 0:
        station_warning += '水位快速上涨（一小时涨幅达0.2米）！请密切关注水位变化！'

    #梧州是否需要水位过低警告
    if float(latest_wuzhou_data) < 4:
        latest_wuzhou_wSymbol = '⚠️'
        latest_wuzhou_QK += '<span class="status-orange">水位较低&nbsp;</span>'
        latest_wuzhou_color = 'orange'
        station_warning += '<br> &nbsp;'
        station_warning += '梧州水位过低，可能影响船舶通航！'

    swC = "green"
    
    if station_warning != ' ':
        #station_warning += '加强船舶调度！'
        swC = "red"
    else:
        station_warning += '无预警信息'

    if latest_wuzhou_QK == ' ':
        latest_wuzhou_QK += '<span class="status-blue">水位正常&nbsp;</span>'

    #水库预警文字
    reservoir_warning = ' '

    am8_datengxia_wSymbol = ' '
    am8_guigang_wSymbol = ' '
    am8_changzhou_wSymbol = ' '
    am8_datengxia_color = 'blue'
    am8_guigang_color = 'blue'
    am8_changzhou_color = 'blue'
 
    #水库是否需要开闸预警
    r2 = 0
    if float(am8_datengxia_fs) == 1 or float(am8_datengxia_ckll) >= 12000:
        am8_datengxia_color = 'orange'
        am8_datengxia_wSymbol += '🌊'
        reservoir_warning += '<br> &nbsp;'
        reservoir_warning += '大藤峡枢纽'
        if float(am8_datengxia_ckll) >= 12000:
            reservoir_warning += '(出库流量达'
            reservoir_warning += am8_datengxia_ckll
            reservoir_warning += 'm³/秒，较大)'
        r2 = 1
    if float(am8_guigang_fs) == 1 or float(am8_guigang_ckll) >= 12000:
        am8_guigang_color = 'orange'
        am8_guigang_wSymbol += '🌊'
        if r2 != 0:
            reservoir_warning += '、'
        else:
            reservoir_warning += '<br> &nbsp;'
        reservoir_warning += '贵港枢纽'
        if float(am8_guigang_ckll) >= 12000:
            reservoir_warning += '(出库流量达'
            reservoir_warning += am8_guigang_ckll
            reservoir_warning += 'm³/秒，较大)'
        r2 = 1
    if float(am8_changzhou_fs) == 1 or float(am8_changzhou_ckll) >= 15000:
        am8_changzhou_color = 'orange'
        am8_changzhou_wSymbol += '🌊'
        if r2 != 0:
            reservoir_warning += '、'
        else:
            reservoir_warning += '<br> &nbsp;'
        reservoir_warning += '长洲枢纽'
        if float(am8_changzhou_ckll) >= 15000:
            reservoir_warning += '(出库流量达'
            reservoir_warning += am8_changzhou_ckll
            reservoir_warning += 'm³/秒，较大)'
        r2 = 1
    if r2 != 0:
        reservoir_warning += '出库流量更大，可能正在放水，对下游水位会有额外影响。'

    #水库是否需要水位超过正常水位警告
    r3 = 0
    if float(am8_datengxia_data) > 61:          #大藤峡61正常蓄水位
        am8_datengxia_wSymbol += '🚨'
        reservoir_warning += '<br> &nbsp;'
        reservoir_warning += '大藤峡枢纽（已超'
        resevoir_warning += str(format((float(am8_datengxia_data)-61), '.2f'))
        resevoir_warning += '米）'
        am8_datengxia_color = 'red'
        r3 = 1
    if float(am8_guigang_data) > 43.1:          #贵港43.1正常蓄水位    西津正常蓄水位取62米
        am8_guigang_wSymbol += '🚨'
        if r3 != 0:
            reservoir_warning += '、'
        else:
            reservoir_warning += '<br> &nbsp;'
        reservoir_warning += '贵港枢纽(已超'
        reservoir_warning += str(format((float(am8_guigang_data)-43.1), '.2f'))
        reservoir_warning += '米）'
        am8_guigang_color = 'red'
        r3 = 1
    if float(am8_changzhou_data) > 20.6:          #长洲20.6正常蓄水位
        am8_changzhou_wSymbol += '🚨'
        if r3 != 0:
            reservoir_warning += '、'
        else:
            reservoir_warning += '<br> &nbsp;'
        reservoir_warning += '长洲枢纽(已超'
        reservoir_warning += str(format((float(am8_changzhou_data)-20.6), '.2f'))
        reservoir_warning += '米）'
        am8_changzhou_color = 'red'
        r3 = 1
    if r3 != 0:
        reservoir_warning += '水位已超过正常蓄水位，可能进行泄洪放水！'

    #水库是否需要水位达到正常水位警告
    r4 = 0
    if float(am8_datengxia_data) == 61:
        am8_datengxia_wSymbol += '⚠️'
        reservoir_warning += '<br> &nbsp;'
        reservoir_warning += '大藤峡枢纽'
        am8_datengxia_color = 'orange'
        r4 = 1
    if float(am8_guigang_data) == 43.1:
        am8_guigang_wSymbol += '⚠️'
        if r4 != 0:
            reservoir_warning += '、'
        else:
            reservoir_warning += '<br> &nbsp;'
        reservoir_warning += '贵港枢纽'
        am8_guigang_color = 'orange'
        r4 = 1
    if float(am8_changzhou_data) == 20.6:
        am8_changzhou_wSymbol += '⚠️'
        if r4 != 0:
            reservoir_warning += '、'
        else:
            reservoir_warning += '<br> &nbsp;'
        reservoir_warning += '长洲枢纽'
        am8_changzhou_color = 'orange'
        r4 = 1
    if r4 != 0:
        reservoir_warning += '水位已达到正常蓄水位，请关注放水信息！'
    
     #水库是否需要水位高警告符号
    r1 = 0
    if float(am8_datengxia_data) >= 60 and float(am8_datengxia_data) < 61:
        am8_datengxia_wSymbol += '⚠️'
        reservoir_warning += '<br> &nbsp;'
        reservoir_warning += '大藤峡枢纽(还差'
        reservoir_warning += str(format(61-float(am8_datengxia_data), '.2f'))
        reservoir_warning += '米）'
        am8_datengxia_color = 'orange'
        r1 = 1
    if float(am8_guigang_data) >= 42 and float(am8_guigang_data) < 43.1:
        am8_guigang_wSymbol += '⚠️'
        if r1 != 0:
            reservoir_warning += '、'
        else:
            reservoir_warning += '<br> &nbsp;'
        reservoir_warning += '贵港枢纽(还差'
        reservoir_warning += str(format(43.1-float(am8_guigang_data), '.2f'))
        reservoir_warning += '米）'
        am8_guigang_color = 'orange'
        r1 = 1
    if float(am8_changzhou_data) >= 19.6 and float(am8_changzhou_data) < 20.6:
        am8_changzhou_wSymbol += '⚠️'
        if r1 != 0:
            reservoir_warning += '、'
        else:
            reservoir_warning += '<br> &nbsp;'
        reservoir_warning += '长洲枢纽(还差'
        reservoir_warning += str(format(20.6-float(am8_changzhou_data), '.2f'))
        reservoir_warning += '米）'
        am8_changzhou_color = 'orange'
        r1 = 1
    if r1 != 0:
        reservoir_warning += '接近正常蓄水位，请留意开闸放水信息！'

    if am8_datengxia_wSymbol == ' ':
        am8_datengxia_wSymbol += '正常'

    if am8_guigang_wSymbol == ' ':
        am8_guigang_wSymbol += '正常'

    if am8_changzhou_wSymbol == ' ':
        am8_changzhou_wSymbol += '正常'

    rwC = "green"
    
    if reservoir_warning != ' ':
        #reservoir_warning += '请及时注意水位变化，加强船舶调度！'
        rwC = "red"
    else:
        reservoir_warning += '无预警信息'

    #各站点是否获取数据标识
    wzS = '❎︎'
    pnS = '❎︎'
    wxS = '❎︎'
    lbS = '❎︎'
    ggS = '❎︎'
    nnS = '❎︎'
    czS = '❎︎'
    GgS = '❎︎'
    dtxS = '❎︎'

    if latest_wuzhou_desc != '-':
        wzS = '✅'
    if latest_pn_desc != '-':
        pnS = '✅'
    if latest_wuxuan_desc != '-':
        wxS = '✅'
    if latest_laibing_desc != '-':
        lbS = '✅'
    if latest_gg_desc != '-':
        ggS = '✅'
    if latest_nn_desc != '-':
        nnS = '✅'
    if am8_changzhou_rkll != '-':
        czS = '✅'
    if am8_guigang_rkll != '-':
        GgS = '✅'
    if am8_datengxia_rkll != '-':
        dtxS = '✅'

    # 添加状态显示区域
    html_content += f"""
        
        <div class="status-section">
            <div class="status-item">
                <span class="status-label">梧州实时水位（{latest_wuzhou_time}）：</span>
                    <span class="status-value status-{latest_wuzhou_color}">
                        {latest_wuzhou_data}m&nbsp;
                    </span>
                <span class="status-label">一小时变化：</span>
                    <span class="status-value status-{latest_wuzhou_wcolor}">
                        {latest_wuzhou_change}m{latest_wuzhou_desc}&nbsp;
                    </span>
                <span class="status-label">实时水位状态：</span>
                    <span class="status-value">
                        {latest_wuzhou_QK}
                    </span>
            </div>
            <div class="status-item">
                <span class="status-label">今早八点梧州水位：</span>
                    <span class="status-value status-{am8_wuzhou_color}">
                        {am8_wuzhou_data}m&nbsp;
                    </span>
                <span class="status-label">较昨日变化：</span>
                    <span class="status-value status-{am8_wuzhou_wcolor}">
                        {am8_wuzhou_change}m{am8_wuzhou_desc}
                    </span> 
                <span class="status-label">早八点状态：</span>
                    <span class="status-value">
                        {am8_wuzhou_QK}
                    </span>
            </div>
            <div class="status-item">
                <span class="status-label">整体情况：</span>
                <span class="status-value status-blue" style="font-size:50px;">
                    {latest_stationNumber} <span style="font-size:25px;">个测站&nbsp;&nbsp;&nbsp;</span>
                </span>
                <span class="status-value status-red" style="font-size:50px;">
                    {latest_warningNumber} <span style="font-size:25px;">站超警&nbsp;&nbsp;&nbsp;</span>
                </span>
                <span class="status-value status-wRed" style="font-size:50px;">
                    {latest_upNumber} <span style="font-size:25px;">站涨水&nbsp;&nbsp;&nbsp;</span>
                </span>
                <span class="status-value status-wGreen" style="font-size:50px;">
                    {latest_downNumber} <span style="font-size:25px;">站落水&nbsp;&nbsp;&nbsp;</span>
                </span>
            </div>
        </div>
        <div class="status-section" style="gap: 0px">
            <div class="status-item" style="min-width:1300px">
                <span class="status-label">🚨水库预警：</span>
                <span class="warningStatus-value status-{rwC}">
                    {reservoir_warning}
                </span>
            </div>
            <div class="status-item" style="min-width:1300px">
                <span class="status-label">🚨站点预警：</span>
                <span class="warningStatus-value status-{swC}">
                    {station_warning}
                </span>
            </div>
        </div>
        
        <div class="image-section">
            <div class="image-overlay-text status-{latest_wuzhou_color}" style="position: absolute; top: 52%; left: 92.5%; font-size:200%;">{latest_wuzhou_data}m</div>
            <div class="image-overlay-text status-{latest_wuzhou_wcolor}" style="position: absolute; top: 62%; left: 92.5%; font-size:150%;">{latest_wuzhou_change}m{latest_wuzhou_desc}</div>
            <div class="image-overlay-text status-{latest_wuzhou_wcolor}" style="position: absolute;top: 41.25%;left: 86%;">====</div>
            <div class="image-overlay-text status-{latest_pn_color}" style="position: absolute; top: 52%; left: 68%; font-size:200%;">{latest_pn_data}m</div>
            <div class="image-overlay-text status-{latest_pn_wcolor}" style="position: absolute; top: 62%; left: 68%; font-size:150%;">{latest_pn_change}m{latest_pn_desc}</div>
            <div class="image-overlay-text status-{latest_pn_wcolor}" style="position: absolute; top: 41.4%; left: 63.85%;">==</div>
            <div class="image-overlay-text status-{latest_wuxuan_color}" style="position: absolute; top: 12%; left: 39%; font-size:200%;">{latest_wuxuan_data}m</div>
            <div class="image-overlay-text status-{latest_wuxuan_wcolor}" style="position: absolute; top: 6%; left: 39%; font-size:150%;">{latest_wuxuan_change}m{latest_wuxuan_desc}</div>
            <div class="image-overlay-text status-{latest_wuxuan_wcolor}" style="position: absolute; top: 18.9%; left: 23.2%;">===========</div>
            <div class="image-overlay-text status-{latest_laibing_color}" style="position: absolute; top: 12%; left: 9%; font-size:200%;">{latest_laibing_data}m</div>
            <div class="image-overlay-text status-{latest_laibing_wcolor}" style="position: absolute; top: 6%; left: 9%; font-size:150%;">{latest_laibing_change}m{latest_laibing_desc}</div>
            <div class="image-overlay-text status-{latest_laibing_wcolor}" style="position: absolute; top: 18.9%; left: 4%;">===</div>
            <div class="image-overlay-text status-{latest_nn_color}" style="position: absolute; top: 57%; left: 13%; font-size:200%;">{latest_nn_data}m</div>
            <div class="image-overlay-text status-{latest_nn_wcolor}" style="position: absolute; top: 51%; left: 13%; font-size:150%;">{latest_nn_change}m{latest_nn_desc}</div>
            <div class="image-overlay-text status-{latest_nn_wcolor}" style="position: absolute; top: 63.8%; left: 6%;">====</div>
            <div class="image-overlay-text status-{latest_gg_color}" style="position: absolute; top: 57%; left: 46%; font-size:200%;">{latest_gg_data}m</div>
            <div class="image-overlay-text status-{latest_gg_wcolor}" style="position: absolute; top: 51%; left: 46%; font-size:150%;">{latest_gg_change}m{latest_gg_desc}</div>
            <div class="image-overlay-text status-{latest_gg_wcolor}" style="position: absolute; top: 63.8%; left: 28.5%;">============</div>
            <div class="image-overlay-text" style="position: absolute; top: 42.4%; left: 92.2%;font-size:200%">{latest_wuzhou_wSymbol}</div>
            <div class="image-overlay-text" style="position: absolute; top: 42.4%; left: 66.9%;font-size:200%">{latest_pn_wSymbol}</div>
            <div class="image-overlay-text" style="position: absolute; top: 20%; left: 37.9%;font-size:200%">{latest_wuxuan_wSymbol}</div>
            <div class="image-overlay-text" style="position: absolute; top: 20%; left: 8.6%;font-size:200%">{latest_laibing_wSymbol}</div>
            <div class="image-overlay-text" style="position: absolute; top: 65%; left: 12%;font-size:200%">{latest_nn_wSymbol}</div>
            <div class="image-overlay-text" style="position: absolute; top: 65%; left: 45%;font-size:200%">{latest_gg_wSymbol}</div>
            <div class="image-overlay-text" style="position: absolute;top: 17%;left: 53.75%;font-size: 180%;writing-mode: vertical-rl;text-orientation: mixed;justify-content: center;align-items: center;display: flex;height: 20%;color:blue">{am8_datengxia_wSymbol}</div>
            <div class="image-overlay-text" style="position: absolute; top: 59.9%;left: 56.1%;font-size: 180%;writing-mode: vertical-rl;text-orientation: mixed;justify-content: center;align-items: center;display: flex;height: 20%;color:blue">{am8_guigang_wSymbol}</div>
            <div class="image-overlay-text" style="position: absolute; top: 39%; left: 79%;font-size: 180%;writing-mode: vertical-rl;text-orientation: mixed;justify-content: center;align-items: center;display: flex; height: 20%;color:blue">{am8_changzhou_wSymbol}</div>
            <div class="image-overlay-text status-{am8_datengxia_color}" style="position: absolute;top: -0.5%;left: 53.8%;font-size: 180%;">{am8_datengxia_data}m</div>
            <div class="image-overlay-text status-{am8_datengxia_color}" style="position: absolute;top: 19%;left: 62%;font-size: 100%;">入库流量: {am8_datengxia_rkll}m³</div>
            <div class="image-overlay-text status-{am8_datengxia_color}" style="position: absolute;top: 39%;left: 51%;font-size: 100%;">出库流量: {am8_datengxia_ckll}m³</div>
            <div class="image-overlay-text status-{am8_guigang_color}" style="position: absolute;top: 88%;left: 56%;font-size: 180%;">{am8_guigang_data}m</div>
            <div class="image-overlay-text status-{am8_guigang_color}" style="position: absolute;top: 80%;left: 66.5%;font-size: 100%;">入库流量: {am8_guigang_rkll}m³</div>
            <div class="image-overlay-text status-{am8_guigang_color}" style="position: absolute;top: 86%;left: 66.5%;font-size: 100%;">出库流量: {am8_guigang_ckll}m³</div>
            <div class="image-overlay-text status-{am8_changzhou_color}" style="position: absolute;top: 3%;left: 79%;font-size: 180%;">{am8_changzhou_data}m</div>
            <div class="image-overlay-text status-{am8_changzhou_color}" style="position: absolute;top: 12.5%;left: 86.5%;font-size: 100%;">入库流量: {am8_changzhou_rkll}m³</div>
            <div class="image-overlay-text status-{am8_changzhou_color}" style="position: absolute;top: 18%;left: 86.5%;font-size: 100%;">出库流量: {am8_changzhou_ckll}m³</div>
            <img src="river.jpg" alt="西江流域图">
        </div>
        <div class="cc">
            <span style="color:#414141; font-size:120%"> 站点数据是否获取 </span> <span class="cc" style="font-size:75%">&nbsp;&nbsp;&nbsp;&nbsp;已获取到数据 </span><span class="c-c" style="font-size:75%">&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;未获取到数据</span> <br>
            <div style="display: flex; justify-content:space-between; align-items: center;">
                <span class="c{latest_wuzhou_desc}c">&nbsp;&nbsp;{wzS}梧州</span><span class="c{latest_pn_desc}c">{pnS}平南</span><span class="c{latest_gg_desc}c">{ggS}贵港</span><span class="c{latest_nn_desc}c">{nnS}南宁</span><span class="c{latest_wuxuan_desc}c">{wxS}武宣</span><span class="c{latest_laibing_desc}c">{lbS}来宾</span><span class="c{am8_changzhou_rkll}c">{czS}长洲枢纽</span><span class="c{am8_datengxia_rkll}c">{dtxS}大藤峡枢纽</span><span class="c{am8_guigang_rkll}c">{GgS}贵港枢纽&nbsp;&nbsp;</span>
            </div>
        </div>

"""

    # 准备图表数据 - 只显示最新的14条记录 只要实时水位的变化图（先看最近14小时内的）
    chart_data = realtime_history[-14:] if len(realtime_history) > 14 else realtime_history
    # 横坐标取数据时间（TM字段，格式如 "11-24 09:00"），转换为 "24日09:00" 的格式
    labels = []
    for record in chart_data:
        rt_data = record.get('站点实时数据', {})
        # 取第一个站点的 TM 作为数据时间（6个站点时间一致）
        first_station = next(iter(rt_data.values()), {})
        tm = first_station.get('TM', '')
        # "11-24 09:00" -> "24日09:00"
        match = re.match(r'\d{2}-(\d{2})\s+(\d{2}:\d{2})', str(tm))
        if match:
            labels.append(f"{match.group(1)}日{match.group(2)}")
        else:
            labels.append(str(tm))
    stations = ['梧州', '平南', '贵港', '武宣', '来宾', '南宁']
    colors = [
        'rgb(255, 99, 132)',
        'rgb(54, 162, 235)',
        'rgb(255, 205, 86)',
        'rgb(75, 192, 192)',
        'rgb(153, 102, 255)',
        'rgb(255, 159, 64)'
    ]

    datasets = []
    for i, station in enumerate(stations):
        water_levels = []
        for record in chart_data:
            station_data = record.get('站点实时数据', {})
            water_level = station_data.get(station, {}).get('Z', 0)
            # 尝试转换为浮点数，如果失败则使用0
            try:
                water_levels.append(float(water_level))
            except (ValueError, TypeError):
                water_levels.append(0)

        datasets.append(f"""
                {{
                    label: '{station}',
                    data: {water_levels},
                    borderColor: '{colors[i]}',
                    backgroundColor: '{colors[i]}',
                    tension: 0.1,
                    fill: false
                }}""")

    html_content += f"""

        <div class="timestamp">
            报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        </div>
    </div>

    <script>
        const ctx = document.getElementById('waterLevelChart').getContext('2d');
        new Chart(ctx, {{
            type: 'line',
            data: {{
                labels: {json.dumps(labels)},
                datasets: [{','.join(datasets)}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{
                    title: {{
                        display: true,
                        text: '各站点水位变化趋势图 (最近{len(chart_data)}小时)',
                        font: {{
                            size: 18
                        }}
                    }},
                    legend: {{
                        position: 'top'
                    }}
                }},
                scales: {{
                    y: {{
                        title: {{
                            display: true,
                            text: '水位 (米)'
                        }}
                    }},
                    x: {{
                        title: {{
                            display: true,
                            text: '时间'
                        }}
                    }}
                }}
            }}
        }});
    </script>
</body>
</html>
"""

    with open('water_level_report.html', 'w', encoding='utf-8') as f:
        f.write(html_content)


def parse_water_level_data(html_content, publish_date):
    """解析水位数据"""
    soup = BeautifulSoup(html_content, 'html.parser')

    # 目标站点（新数据源只爬取梧州）
    target_stations = ['梧州']

    # 查找所有表格
    tables = soup.find_all('table')

    results = {}

    for table in tables:
        rows = table.find_all('tr')

        # 跳过表头行
        for row in rows[3:]:  # 前3行是表头
            cells = row.find_all('td')
            if len(cells) >= 4:
                station_name = cells[0].get_text(strip=True)

                # 检查是否为目标站点
                if station_name in target_stations:
                    observation_time = cells[1].get_text(strip=True)
                    water_level = cells[2].get_text(strip=True)
                    change_value = cells[3].get_text(strip=True)

                    # 如果变化值大于0且不以+开头，则添加+号
                    try:
                        if float(change_value) > 0 and not change_value.startswith('+'):
                            change_value = '+' + change_value
                    except (ValueError, TypeError):
                        pass

                    # 如果时间不以0开头，则添加0
                    try:
                        if  not observation_time.startswith('0'):
                            observation_time = '0' + observation_time
                    except (ValueError, TypeError):
                        pass
                    

                    # 将变化值转换为数字：1表示上升，0表示持平或下降
                    try:
                        change_num = float(change_value)
                        if change_num > 0 :
                            change_value_num = 1  # 上升
                            change_des = "▲"
                            color = "wRed"
                        elif change_num <= 0 :
                            change_value_num = 0  # 持平或下降
                            change_des = "▼"
                            color = "wGreen"
                    except (ValueError, TypeError):
                        change_value_num = 0  # 无法解析时默认为0
                        change_des = "▼"
                        color = "wGreen"

                    # 组合完整日期时间
                    full_datetime = f"{publish_date} {observation_time}"

                    # 使用字典存储，站名为键，重复的会自动覆盖
                    results[station_name] = {
                        '站名': station_name,
                        '水位': water_level,
                        '变化值': change_value,
                        '变化': change_value_num,
                        '情况': change_des,
                        '颜色': color,
                        '时间': full_datetime
                    }

    return results


def ocr_image(img_filename):
    """对图片进行OCR识别，返回识别结果"""
    ocr_url = "https://open.bigmodel.cn/api/paas/v4/layout_parsing"

    with open(img_filename, "rb") as f:
        file_base64 = "data:image/png;base64," + base64.b64encode(f.read()).decode("utf-8")

    payload = {
        "model": "glm-ocr",
        "file": file_base64,
        "return_crop_images": False,
        "need_layout_visualization": False
    }
    ocr_headers = {
        "Authorization": "Bearer 86039bcf560d4f18b77f53e0e04e5166.GgAtkKiN9TUSAcpp",
        "Content-Type": "application/json"
    }

    response = requests.post(ocr_url, json=payload, headers=ocr_headers, timeout=60)
    print(f"OCR识别完成")
    return response.text


def parse_ocr_reservoir_data(ocr_json_str, publish_date):
    """从OCR识别结果中解析水库/枢纽数据"""
    target_reservoirs = ['贵港枢纽', '大藤峡枢纽']
    results = {}

    try:
        ocr_data = json.loads(ocr_json_str)
    except json.JSONDecodeError:
        print("OCR结果JSON解析失败")
        return results

    # layout_details 是一个列表的列表（按页）
    layout_details = ocr_data.get('layout_details', [])
    for page in layout_details:
        for item in page:
            content = item.get('content', '')
            # 只处理包含通航建筑物流量信息表的表格内容
            if '通航建筑物' in content and '<table' in content:
                soup = BeautifulSoup(content, 'html.parser')
                # 查找表格中的所有行
                rows = soup.find_all('tr')
                
                # 遍历每一行，提取数据
                for row in rows:
                    # 获取所有单元格（td 和 th），处理 colspan 属性
                    cells = []
                    for cell in row.find_all(['td', 'th']):
                        cell_text = cell.get_text(strip=True)
                        # 处理 colspan 属性，将单元格内容重复多次
                        colspan = int(cell.get('colspan', 1))
                        for _ in range(colspan):
                            cells.append(cell_text)
                    
                    # 需要至少 6 个单元格才能提取数据
                    if len(cells) >= 6:
                        reservoir_name = cells[0]
                        if reservoir_name in target_reservoirs:
                            observation_time = cells[1]
                            upstream_level = cells[2]
                            downstream_level = cells[3]
                            inflow = cells[4]
                            outflow = cells[5]

                            # 计算是否放水：出库流量 >= 入库流量则为1，否则为0
                            try:
                                inflow_float = float(inflow)
                                outflow_float = float(outflow)
                                is_releasing = 1 if outflow_float >= inflow_float else 0
                            except (ValueError, TypeError):
                                is_releasing = 0

                            # 组合完整日期时间
                            full_datetime = f"{publish_date} {observation_time}"

                            results[reservoir_name] = {
                                '站名': reservoir_name,
                                '时间': full_datetime,
                                '上游水位': upstream_level,
                                '入库流量': inflow,
                                '出库流量': outflow,
                                '是否放水': is_releasing
                            }
                            print(f"OCR提取枢纽数据: {reservoir_name} 上游水位={upstream_level} 入库={inflow} 出库={outflow}")

    return results


def parse_reservoir_data(html_content, publish_date):
    """解析水库/船闸数据"""
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # 目标枢纽
    target_reservoirs = ['大藤峡枢纽', '贵港枢纽', '长洲船闸']
    
    # 查找所有表格
    tables = soup.find_all('table')
    
    results = {}
    
    for table in tables:
        rows = table.find_all('tr')
        
        # 寻找通航建筑物流量信息表
        table_found = False
        for row_index, row in enumerate(rows):
            cells = row.find_all('td')
            if len(cells) >= 1 and '通航建筑物流量信息表' in cells[0].get_text():
                # 找到了正确的表格，从该行开始解析数据（跳过表头行）
                table_found = True
                # 从表头之后开始解析数据行
                for data_row in rows[row_index + 1:]:  # 跳过表头和可能的第二行表头
                    data_cells = data_row.find_all('td')
                    if len(data_cells) >= 6:
                        reservoir_name = data_cells[0].get_text(strip=True)
                        
                        # 检查是否为目标枢纽
                        if reservoir_name in target_reservoirs:
                            observation_time = data_cells[1].get_text(strip=True)
                            upstream_level = data_cells[2].get_text(strip=True)
                            downstream_level = data_cells[3].get_text(strip=True)
                            inflow = data_cells[4].get_text(strip=True)
                            outflow = data_cells[5].get_text(strip=True)
                            
                            # 计算是否放水：出库流量 >= 入库流量则为1，否则为0
                            try:
                                inflow_float = float(inflow)
                                outflow_float = float(outflow)
                                is_releasing = 1 if outflow_float >= inflow_float else 0
                            except (ValueError, TypeError):
                                is_releasing = 0
                            
                            # 组合完整日期时间
                            full_datetime = f"{publish_date} {observation_time}"
                            
                            # 使用字典存储，站名为键，重复的会自动覆盖
                            results[reservoir_name] = {
                                '站名': reservoir_name,
                                '时间': full_datetime,
                                '上游水位': upstream_level,
                                '入库流量': inflow,
                                '出库流量': outflow,
                                '是否放水': is_releasing
                            }
                break
        if table_found:
            break  # 找到表格后就停止搜索其他表格
    
    return results


def main():
    import sys
    import os

    # 设置标准输出编码为 UTF-8，避免 Windows 终端 GBK 编码问题
    if sys.platform == 'win32':
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    # ============================================================
    # 第一步：爬取实时水情数据（广西水利厅 API）
    # ============================================================
    print("\n" + "=" * 60)
    print("开始爬取实时水情数据...")
    print("=" * 60)
    realtime_main()

    # ============================================================
    # 第二步：爬取早八点水情数据 + 水库数据（广西港航局网站）
    # ============================================================
    print("\n" + "=" * 60)
    print("开始爬取早八点水情及水库数据...")
    print("=" * 60)

    # 设置请求头，模拟浏览器访问
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    # 访问目标网站
    print("正在打开网站...")
    base_url = "https://www.gxghj.cn/c/fw/slcx"
    try:
        response = requests.get(base_url, headers=headers, timeout=30)
        response.encoding = 'utf-8'
        print(f"网站访问成功，状态码: {response.status_code}")
    except Exception as e:
        print(f"访问网站失败: {e}")

    # 解析列表页HTML
    soup = BeautifulSoup(response.text, 'html.parser')

    # 获取所有新闻链接
    news_items = soup.select('.newsList li')

    # 获取今天的日期字符串，格式如 "20261012"
    today_str = datetime.now().strftime('%Y%m%d')

    #today_str = "20261101"  # 测试用

    # 筛选标题中包含今天日期的链接
    filtered_items = []
    for item in news_items:
        title_tag = item.select_one('.newsTitle')
        if title_tag:
            title_text = title_tag.get_text(strip=True)
            if today_str in title_text:
                filtered_items.append(item)

    print(f"找到 {len(news_items)} 条新闻，筛选出包含今天日期({today_str})的 {len(filtered_items)} 条")

    # 使用字典存储所有数据，站名为键
    all_water_data = {}

    # 使用字典存储水库数据，枢纽名为键
    all_reservoir_data = {}

    for i, news_item in enumerate(filtered_items):

        # 获取链接标题和URL
        title_tag = news_item.select_one('.newsTitle')
        link_tag = news_item.select_one('a')

        if not title_tag or not link_tag:
            continue

        link_title = title_tag.get_text(strip=True)
        link_url = link_tag.get('href')

        # 处理相对URL
        if link_url.startswith('/'):
            link_url = f"https://www.gxghj.cn{link_url}"
        elif not link_url.startswith('http'):
            link_url = f"https://www.gxghj.cn/c/fw/slcx/{link_url}"

        print(f"\n{'='*50}")
        print(f"正在处理第 {i+1} 条链接: {link_title}")
        print(f"{'='*50}")

        # 访问详情页
        try:
            detail_response = requests.get(link_url, headers=headers, timeout=30)
            detail_response.encoding = 'utf-8'
            print(f"详情页访问成功，状态码: {detail_response.status_code}")
        except Exception as e:
            print(f"访问详情页失败: {e}")
            continue

        # 解析详情页HTML
        detail_soup = BeautifulSoup(detail_response.text, 'html.parser')

        # 获取发布日期
        info_tag = detail_soup.select_one('.info')
        if info_tag:
            publish_date_info = info_tag.get_text()
            date_match = re.search(r'发布日期：(\d{4}-\d{2}-\d{2})', publish_date_info)
            if date_match:
                publish_date = date_match.group(1)
            else:
                publish_date = "未知日期"
        else:
            publish_date = "未知日期"

        print(f"发布日期: {publish_date}")

        # 如果是贵港的水情信息页面，页面内容是图片，下载并重命名
        if '贵港' in link_title:
            content_div = detail_soup.select_one('.content.html')
            if content_div:
                img_tag = content_div.find('img')
                if img_tag:
                    img_src = img_tag.get('src', '')
                    if img_src:
                        # 处理相对URL
                        if img_src.startswith('/'):
                            img_url = f"https://www.gxghj.cn{img_src}"
                        elif not img_src.startswith('http'):
                            img_url = f"https://www.gxghj.cn/{img_src}"
                        else:
                            img_url = img_src

                        # 获取图片扩展名
                        img_ext = os.path.splitext(img_src)[1] or '.png'

                        # 修改文件名
                        img_filename = f"guigang{img_ext}"

                        try:
                            img_response = requests.get(img_url, headers=headers, timeout=30)
                            with open(img_filename, 'wb') as f:
                                f.write(img_response.content)
                            print(f"已下载贵港水情图片: {img_filename}")

                            # 对下载的图片进行OCR识别
                            print("正在进行OCR识别...")
                            ocr_result = ocr_image(img_filename)
                            print(f"OCR结果: {ocr_result}")

                            # 从OCR结果中解析贵港枢纽和大藤峡枢纽数据
                            ocr_reservoir_data = parse_ocr_reservoir_data(ocr_result, publish_date)
                            all_reservoir_data.update(ocr_reservoir_data)
                        except Exception as e:
                            print(f"下载贵港水情图片失败: {e}")

        # 解析水位数据
        water_data = parse_water_level_data(detail_response.text, publish_date)
        # 合并到总数据中，重复站点会自动覆盖
        all_water_data.update(water_data)

        # 解析水库/船闸数据
        reservoir_data = parse_reservoir_data(detail_response.text, publish_date)
        # 合并到水库数据中，重复枢纽会自动覆盖
        all_reservoir_data.update(reservoir_data)

        print(f"本次获取水位数据: {len(water_data)} 个站点")
        print(f"本次获取水库数据: {len(reservoir_data)} 个枢纽")

        # 短暂延迟，避免请求过快
        time.sleep(1)

    # 输出所有爬取的数据
    print("\n")
    print("=" * 60)
    print("梧州早八点水位数据")
    print("=" * 60)

    for station_name in sorted(all_water_data.keys()):
        data = all_water_data[station_name]
        change_desc = "上升" if data['变化'] == 1 else "持平或下降"
        print(f"站名: {data['站名']}")
        print(f"水位: {data['水位']} 米")
        print(f"变化: {data['变化']} ({change_desc})")
        print(f"变化值: {data['变化值']}")
        print(f"情况: {data['情况']}")
        print(f"颜色: {data['颜色']}")
        print(f"时间: {data['时间']}")
        print("-" * 60)

    # 输出所有爬取的水库数据
    print("\n")
    print("=" * 60)
    print("水库船闸数据汇总")
    print("=" * 60)

    for reservoir_name in sorted(all_reservoir_data.keys()):
        data = all_reservoir_data[reservoir_name]
        releasing_status = "放水中" if data['是否放水'] == 1 else "未放水"
        print(f"站名: {data['站名']}")
        print(f"时间: {data['时间']}")
        print(f"上游水位: {data['上游水位']} 米")
        print(f"入库流量: {data['入库流量']} m³/s")
        print(f"出库流量: {data['出库流量']} m³/s")
        print(f"是否放水: {data['是否放水']} ({releasing_status})")
        print("-" * 60)

    # 加载历史数据
    print("\n正在加载历史数据...")
    historical_data = load_data()

    # 检查是否已存在相同时间的数据
    new_data_time = list(all_water_data.values())[0]['时间'] if all_water_data else None
    existing_index = -1
    if new_data_time:
        for i, record in enumerate(historical_data):
            if record['时间'] == new_data_time:
                existing_index = i
                break

    # 添加或更新数据
    if new_data_time:
        record_data = {
            '时间': new_data_time,
            '站点数据': all_water_data,
            '枢纽数据': all_reservoir_data,
        }

        if existing_index >= 0:
            print(f"更新时间 {new_data_time} 的数据")
            historical_data[existing_index] = record_data
        else:
            print(f"添加新的时间数据: {new_data_time}")
            historical_data.append(record_data)

    # 保存数据
    save_data(historical_data)
    print(f"数据已保存，当前共有 {len(historical_data)} 条记录")

    # 生成HTML报告
    print("\n正在生成HTML可视化报告...")
    generate_html_report(historical_data)
    print("报告已生成: water_level_report.html")

    print("\n数据爬取完成！")


if __name__ == "__main__":
    main()
