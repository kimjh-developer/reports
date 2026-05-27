#!/usr/bin/env python3
"""Notion 대리점 DB에서 데이터를 가져와 서비스 지역 현황 보고서를 자동 생성합니다."""

import json
import subprocess
from datetime import datetime
from collections import defaultdict

TOKEN_FILE = "key.txt"
SOURCE_DB = "3484918520a8801ab030fd96d2d492c1"
REF_DB = "1b64918520a883a4b4210169376fe29f"
COUPON_DB = "1b649185-20a8-83a4-b421-0169376fe29f"
OUTPUT_FILE = "index.html"

# 사용자 현황 (수동 업데이트)
USER_STATS = {
    "heroes": 126,
    "users": 1244,
    "pass_verified": 419,
    "card_registered": 171,
}

TODAY = datetime.now().strftime("%Y-%m-%d")
TODAY_KR = datetime.now().strftime("%Y년 %m월 %d일")
WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]
TODAY_DOW = WEEKDAYS[datetime.now().weekday()]


def read_token():
    with open(TOKEN_FILE) as f:
        return f.read().strip()


def fetch_db(token, db_id):
    """curl로 Notion DB 전체 데이터를 가져옵니다."""
    results = []
    cursor = None
    while True:
        payload = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        cmd = [
            "curl", "-s", "-X", "POST",
            f"https://api.notion.com/v1/databases/{db_id}/query",
            "-H", f"Authorization: Bearer {token}",
            "-H", "Notion-Version: 2022-06-28",
            "-H", "Content-Type: application/json",
            "-d", json.dumps(payload)
        ]
        out = subprocess.run(cmd, capture_output=True, text=True).stdout
        data = json.loads(out)
        results.extend(data["results"])
        if not data.get("has_more"):
            break
        cursor = data["next_cursor"]
    return results


def get_text(prop):
    return "".join(t["plain_text"] for t in prop.get("rich_text", [])).strip()


def get_title(prop):
    return "".join(t["plain_text"] for t in prop.get("title", [])).strip()


def get_select(prop):
    s = prop.get("select")
    return s["name"] if s else ""


def get_multi(prop):
    return [x["name"] for x in prop.get("multi_select", [])]


def get_date(prop):
    d = prop.get("date")
    return d["start"] if d else ""


def get_number(prop):
    return prop.get("number") or 0


def normalize_phone(p):
    return p.replace("-", "").replace(" ", "").replace("(", "").replace(")", "").strip()


def parse_source(entries):
    result = []
    for e in entries:
        p = e["properties"]
        result.append({
            "id": e["id"],
            "name": get_title(p.get("대리점명", {})),
            "phone": normalize_phone(get_text(p.get("연락처", {}))),
            "region_status": get_select(p.get("지역상태", {})),
            "status": get_select(p.get("상태값", {})),
            "regions": get_multi(p.get("지역", {})),
            "date": get_date(p.get("날짜", {})),
            "reason": get_text(p.get("미오픈 사유", {})),
            "contract": get_date(p.get("전자 계약일", {})),
        })
    return result


def parse_ref(entries):
    result = []
    for e in entries:
        p = e["properties"]
        result.append({
            "name": get_title(p.get("대리점명", {})),
            "phone": normalize_phone(get_text(p.get("연락처", {}))),
            "part_date": get_date(p.get("참가 날짜", {})),
            "coupon_no": get_text(p.get("쿠폰No.", {})),
            "coupon_qty": get_number(p.get("발급량", {})),
            "coupon_target": get_select(p.get("쿠폰발행대상", {})),
            "coupon_invited": get_number(p.get("쿠폰초대수", {})),
            "coupon_used": get_number(p.get("쿠폰사용수", {})),
        })
    return result


def classify_reason(reason):
    """미오픈 사유를 카테고리로 분류"""
    if not reason:
        return "사유 미입력"
    if "히어로키트" in reason:
        return "히어로키트 미수령"
    if "협의" in reason:
        return "교육 미참가 (참가예정일 협의중)"
    if "참가예정일" in reason or "미참가" in reason:
        # 날짜 추출
        for part in reason.split():
            if part.startswith("20") and len(part) == 10:
                return f"교육 미참가 ({part} 예정)"
        return "교육 미참가 (참가예정일 협의중)"
    return reason


def group_by_date(entries):
    """교육 미참가 항목을 날짜별로 그룹핑"""
    groups = defaultdict(list)
    for e in entries:
        reason = e["reason"]
        if "협의" in reason or not reason:
            groups["협의중"].append(e)
        else:
            # 날짜 추출
            date_found = None
            for part in reason.split():
                if part.startswith("20") and len(part) == 10:
                    date_found = part
            if date_found:
                groups[date_found].append(e)
            else:
                groups["협의중"].append(e)
    return groups


# ==================== HTML 생성 ====================

REASON_COLORS = [
    ("#c62828", "#c62828"),    # 1번째 사유
    ("#e65100", "#e65100"),    # 2번째
    ("#f9a825", "#f9a825"),    # 3번째
    ("#7b1fa2", "#7b1fa2"),    # 4번째
    ("#9e9e9e", "#9e9e9e"),    # 5번째
    ("#0277bd", "#0277bd"),    # 6번째
]


def generate_html(source_data, ref_data):
    total = len(source_data)
    open_list = [e for e in source_data if e["region_status"] == "오픈"]
    closed_list = [e for e in source_data if e["region_status"] == "미오픈"]
    open_count = len(open_list)
    closed_count = len(closed_list)
    open_rate = (open_count / total * 100) if total else 0

    # 시도별 집계
    regions = defaultdict(lambda: {"total": 0, "open": 0, "closed": 0})
    for e in source_data:
        for r in e["regions"]:
            regions[r]["total"] += 1
            if e["region_status"] == "오픈":
                regions[r]["open"] += 1
            else:
                regions[r]["closed"] += 1
    sorted_regions = sorted(regions.items(), key=lambda x: x[1]["total"], reverse=True)

    # 미오픈 사유 집계
    reason_counts = defaultdict(int)
    for e in closed_list:
        cat = classify_reason(e["reason"])
        reason_counts[cat] += 1
    sorted_reasons = sorted(reason_counts.items(), key=lambda x: x[1], reverse=True)

    # 미오픈 분류: 히어로키트 미수령 vs 교육 미참가
    kit_list = [e for e in closed_list if "히어로키트" in e.get("reason", "")]
    edu_list = [e for e in closed_list if e not in kit_list]

    # 교육 미참가 날짜별 그룹
    edu_groups = group_by_date(edu_list)

    # 계약 상태 집계
    status_counts = defaultdict(int)
    for e in source_data:
        s = e["status"] if e["status"] else "미정"
        status_counts[s] += 1

    STATUS_ORDER = ["완료", "예약", "취소", "미정"]
    STATUS_BADGE = {"완료": "badge-done", "예약": "badge-reserved", "취소": "badge-cancel", "미정": "badge-cancel"}
    STATUS_CHIP_STYLE = {
        "완료": "background:#e3f2fd; color:#1565c0;",
        "예약": "background:#fff3e0; color:#e65100;",
        "취소": "background:#f5f5f5; color:#757575;",
        "미정": "background:#f5f5f5; color:#999;",
    }
    STATUS_NOTE = {"완료": "계약 및 미팅 완료", "예약": "미팅 예약 대기중", "취소": "", "미정": ""}

    # 취소 대리점 이름 찾기
    cancel_names = [e["name"] for e in source_data if e["status"] == "취소"]

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>서비스 지역 현황 보고서</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif; background: #f4f6f9; color: #333; padding: 40px 20px; }}
  .container {{ max-width: 1200px; margin: 0 auto; }}
  .header {{ background: linear-gradient(135deg, #1a237e, #283593); color: #fff; padding: 40px; border-radius: 16px; margin-bottom: 32px; }}
  .header h1 {{ font-size: 28px; margin-bottom: 8px; }}
  .header .date {{ font-size: 14px; opacity: 0.8; }}
  .summary-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; margin-bottom: 32px; }}
  .summary-card {{ background: #fff; border-radius: 12px; padding: 28px 24px; text-align: center; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }}
  .summary-card .label {{ font-size: 13px; color: #888; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 1px; }}
  .summary-card .value {{ font-size: 42px; font-weight: 700; }}
  .summary-card .sub {{ font-size: 13px; color: #999; margin-top: 4px; }}
  .card-total .value {{ color: #1a237e; }}
  .card-open .value {{ color: #2e7d32; }}
  .card-closed .value {{ color: #c62828; }}
  .card-rate .value {{ color: #e65100; }}
  .card-hero .value {{ color: #6a1b9a; }}
  .card-user .value {{ color: #00695c; }}
  .card-pass .value {{ color: #0277bd; }}
  .card-card .value {{ color: #bf360c; }}
  .card-coupon .value {{ color: #4527a0; }}
  .card-coupon-inv .value {{ color: #00838f; }}
  .card-coupon-use .value {{ color: #2e7d32; }}
  .card-coupon-rate .value {{ color: #ad1457; }}
  .user-stats-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; margin-bottom: 32px; }}
  .coupon-bar {{ display: flex; align-items: center; gap: 6px; }}
  .coupon-bar-bg {{ flex: 1; height: 16px; background: #f0f0f0; border-radius: 8px; overflow: hidden; }}
  .coupon-bar-fill {{ height: 100%; border-radius: 8px; }}
  .coupon-bar-label {{ font-size: 11px; color: #666; min-width: 35px; text-align: right; }}
  .section {{ background: #fff; border-radius: 12px; padding: 32px; margin-bottom: 24px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }}
  .section h2 {{ font-size: 20px; color: #1a237e; margin-bottom: 20px; padding-bottom: 12px; border-bottom: 2px solid #e8eaf6; }}
  .section h3 {{ font-size: 16px; color: #444; margin: 20px 0 12px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th {{ background: #f5f6fa; color: #555; font-weight: 600; padding: 12px 10px; text-align: left; border-bottom: 2px solid #e0e0e0; white-space: nowrap; }}
  td {{ padding: 10px; border-bottom: 1px solid #f0f0f0; vertical-align: middle; }}
  tr:hover {{ background: #fafbff; }}
  .badge {{ display: inline-block; padding: 4px 10px; border-radius: 20px; font-size: 11px; font-weight: 600; }}
  .badge-open {{ background: #e8f5e9; color: #2e7d32; }}
  .badge-closed {{ background: #ffebee; color: #c62828; }}
  .badge-done {{ background: #e3f2fd; color: #1565c0; }}
  .badge-reserved {{ background: #fff3e0; color: #e65100; }}
  .badge-cancel {{ background: #f5f5f5; color: #757575; }}
  .bar-container {{ display: flex; align-items: center; gap: 8px; }}
  .bar-bg {{ flex: 1; height: 20px; background: #ffebee; border-radius: 10px; overflow: hidden; }}
  .bar-fill {{ height: 100%; background: linear-gradient(90deg, #43a047, #66bb6a); border-radius: 10px; transition: width 0.6s; }}
  .bar-label {{ font-size: 12px; color: #666; min-width: 40px; text-align: right; }}
  .reason-list {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }}
  .reason-item {{ display: flex; justify-content: space-between; align-items: center; padding: 14px 18px; background: #fafbfc; border-radius: 8px; border-left: 4px solid #c62828; }}
  .reason-item .reason-text {{ font-size: 14px; font-weight: 500; }}
  .reason-item .reason-count {{ font-size: 20px; font-weight: 700; color: #c62828; }}
  .status-chip {{ padding: 8px 20px; border-radius: 8px; font-size: 14px; font-weight: 600; }}
  .region-row td:first-child {{ font-weight: 600; }}
  .footer {{ text-align: center; color: #aaa; font-size: 12px; margin-top: 40px; padding: 20px; }}
  @media (max-width: 768px) {{
    .summary-grid {{ grid-template-columns: repeat(2, 1fr); }}
    .reason-list {{ grid-template-columns: 1fr; }}
    table {{ font-size: 11px; }}
  }}
</style>
</head>
<body>
<div class="container">

  <div class="header">
    <h1>서비스 지역 오픈 현황 보고서</h1>
    <div class="date">보고일: {TODAY_KR} ({TODAY_DOW}) | 기준 데이터: Notion 대리점 관리 DB</div>
  </div>

  <!-- 종합 총계 -->
  <div class="summary-grid">
    <div class="summary-card card-total">
      <div class="label">전체 대리점</div>
      <div class="value">{total}</div>
      <div class="sub">전국 {len(sorted_regions)}개 시도</div>
    </div>
    <div class="summary-card card-open">
      <div class="label">오픈 완료</div>
      <div class="value">{open_count}</div>
      <div class="sub">서비스 운영중</div>
    </div>
    <div class="summary-card card-closed">
      <div class="label">미오픈</div>
      <div class="value">{closed_count}</div>
      <div class="sub">오픈 준비중</div>
    </div>
    <div class="summary-card card-rate">
      <div class="label">오픈율</div>
      <div class="value">{open_rate:.1f}%</div>
      <div class="sub">목표 대비 진행중</div>
    </div>
  </div>

  <!-- 사용자 현황 -->
  <div class="section">
    <h2>사용자 현황</h2>
    <div class="user-stats-grid">
      <div class="summary-card card-hero">
        <div class="label">히어로</div>
        <div class="value">{USER_STATS["heroes"]}</div>
        <div class="sub">등록 히어로 수</div>
      </div>
      <div class="summary-card card-user">
        <div class="label">사용자</div>
        <div class="value">{USER_STATS["users"]:,}</div>
        <div class="sub">가입 사용자 수</div>
      </div>
      <div class="summary-card card-pass">
        <div class="label">PASS 인증 완료</div>
        <div class="value">{USER_STATS["pass_verified"]}</div>
        <div class="sub">전체 사용자 대비 {USER_STATS["pass_verified"]/USER_STATS["users"]*100:.1f}%</div>
      </div>
      <div class="summary-card card-card">
        <div class="label">카드 등록 완료</div>
        <div class="value">{USER_STATS["card_registered"]}</div>
        <div class="sub">전체 사용자 대비 {USER_STATS["card_registered"]/USER_STATS["users"]*100:.1f}%</div>
      </div>
    </div>
    <div style="padding: 0 4px;">
      <div style="display:flex; justify-content:space-between; font-size:12px; color:#888; margin-bottom:4px;">
        <span>사용자 전환 퍼널</span>
      </div>
      <div style="display:flex; align-items:center; gap:12px; margin-bottom:8px;">
        <span style="font-size:12px; min-width:90px; color:#555;">가입 ({USER_STATS["users"]:,})</span>
        <div style="flex:1; height:24px; background:#e0f2f1; border-radius:6px; overflow:hidden;">
          <div style="width:100%; height:100%; background:linear-gradient(90deg, #00897b, #26a69a); border-radius:6px;"></div>
        </div>
        <span style="font-size:12px; color:#666; min-width:40px;">100%</span>
      </div>
      <div style="display:flex; align-items:center; gap:12px; margin-bottom:8px;">
        <span style="font-size:12px; min-width:90px; color:#555;">PASS ({USER_STATS["pass_verified"]})</span>
        <div style="flex:1; height:24px; background:#e1f5fe; border-radius:6px; overflow:hidden;">
          <div style="width:{USER_STATS["pass_verified"]/USER_STATS["users"]*100:.1f}%; height:100%; background:linear-gradient(90deg, #0288d1, #29b6f6); border-radius:6px;"></div>
        </div>
        <span style="font-size:12px; color:#666; min-width:40px;">{USER_STATS["pass_verified"]/USER_STATS["users"]*100:.1f}%</span>
      </div>
      <div style="display:flex; align-items:center; gap:12px;">
        <span style="font-size:12px; min-width:90px; color:#555;">카드 ({USER_STATS["card_registered"]})</span>
        <div style="flex:1; height:24px; background:#fbe9e7; border-radius:6px; overflow:hidden;">
          <div style="width:{USER_STATS["card_registered"]/USER_STATS["users"]*100:.1f}%; height:100%; background:linear-gradient(90deg, #d84315, #ff7043); border-radius:6px;"></div>
        </div>
        <span style="font-size:12px; color:#666; min-width:40px;">{USER_STATS["card_registered"]/USER_STATS["users"]*100:.1f}%</span>
      </div>
    </div>
  </div>

  <!-- 미오픈 사유 분석 -->
  <div class="section">
    <h2>미오픈 사유 분석 ({closed_count}건)</h2>
    <div class="reason-list">
"""
    for i, (reason, count) in enumerate(sorted_reasons):
        bc, fc = REASON_COLORS[i % len(REASON_COLORS)]
        style = f' style="border-color:{bc};"' if i > 0 else ""
        count_style = f' style="color:{fc};"' if i > 0 else ""
        html += f"""      <div class="reason-item"{style}>
        <div class="reason-text">{reason}</div>
        <div class="reason-count"{count_style}>{count}건</div>
      </div>
"""
    html += """    </div>
  </div>

  <!-- 시도별 현황 -->
  <div class="section">
    <h2>시도별 오픈 현황</h2>
    <table>
      <thead>
        <tr>
          <th>시/도</th><th>전체</th><th>오픈</th><th>미오픈</th><th>오픈율</th>
          <th style="width:40%;">진행률</th>
        </tr>
      </thead>
      <tbody>
"""
    for region, v in sorted_regions:
        rate = (v["open"] / v["total"] * 100) if v["total"] else 0
        html += f"""        <tr class="region-row">
          <td>{region}</td><td>{v['total']}</td><td>{v['open']}</td><td>{v['closed']}</td><td>{rate:.1f}%</td>
          <td><div class="bar-container"><div class="bar-bg"><div class="bar-fill" style="width:{rate:.1f}%"></div></div><div class="bar-label">{rate:.0f}%</div></div></td>
        </tr>
"""
    html += """      </tbody>
    </table>
  </div>

  <!-- 오픈 완료 대리점 -->
  <div class="section">
"""
    html += f'    <h2>오픈 완료 대리점 ({open_count}건)</h2>\n'
    html += """    <table>
      <thead>
        <tr><th>No.</th><th>대리점명</th><th>지역</th><th>상태</th><th>계약일</th></tr>
      </thead>
      <tbody>
"""
    for i, e in enumerate(open_list, 1):
        rgn = ", ".join(e["regions"])
        html += f'        <tr><td>{i}</td><td>{e["name"]}</td><td>{rgn}</td><td><span class="badge badge-open">오픈</span></td><td>{e["contract"]}</td></tr>\n'
    html += """      </tbody>
    </table>
  </div>

"""
    # 미오픈 - 히어로키트 미수령
    if kit_list:
        html += f"""  <!-- 미오픈 - 히어로키트 미수령 -->
  <div class="section">
    <h2>미오픈 - 히어로키트 미수령 ({len(kit_list)}건)</h2>
    <p style="color:#888; font-size:13px; margin-bottom:16px;">교육 이수 완료, 히어로키트 수령 후 오픈 가능</p>
    <table>
      <thead>
        <tr><th>No.</th><th>대리점명</th><th>지역</th><th>상태</th><th>미오픈 사유</th></tr>
      </thead>
      <tbody>
"""
        for i, e in enumerate(kit_list, 1):
            rgn = ", ".join(e["regions"])
            html += f'        <tr><td>{i}</td><td>{e["name"]}</td><td>{rgn}</td><td><span class="badge badge-closed">미오픈</span></td><td>{e["reason"]}</td></tr>\n'
        html += """      </tbody>
    </table>
  </div>

"""

    # 미오픈 - 교육 미참가
    if edu_list:
        html += f"""  <!-- 미오픈 - 교육 미참가 -->
  <div class="section">
    <h2>미오픈 - 교육 미참가 ({len(edu_list)}건)</h2>
    <p style="color:#888; font-size:13px; margin-bottom:16px;">교육 참가 후 키트 수령 및 오픈 진행 예정</p>
"""
        # 날짜별 정렬: 가까운 날짜 먼저, 협의중은 마지막
        date_keys = sorted(
            edu_groups.keys(),
            key=lambda x: x if x != "협의중" else "9999-99-99"
        )
        for dk in date_keys:
            items = edu_groups[dk]
            if dk == "협의중":
                html += f'\n    <h3>참가예정일 협의중 ({len(items)}건)</h3>\n'
                html += """    <table>
      <thead>
        <tr><th>No.</th><th>대리점명</th><th>지역</th><th>미오픈 사유</th></tr>
      </thead>
      <tbody>
"""
                for i, e in enumerate(items, 1):
                    rgn = ", ".join(e["regions"])
                    html += f'        <tr><td>{i}</td><td>{e["name"]}</td><td>{rgn}</td><td>{e["reason"] or "교육 미참가 참가예정일 협의중"}</td></tr>\n'
            else:
                # 날짜를 간결하게 표시
                try:
                    dt = datetime.strptime(dk, "%Y-%m-%d")
                    label = f'{dt.month}/{dt.day}'
                except ValueError:
                    label = dk
                html += f'\n    <h3>{label} 교육 예정 ({len(items)}건)</h3>\n'
                html += """    <table>
      <thead>
        <tr><th>No.</th><th>대리점명</th><th>지역</th><th>참가예정일</th><th>미오픈 사유</th></tr>
      </thead>
      <tbody>
"""
                for i, e in enumerate(items, 1):
                    rgn = ", ".join(e["regions"])
                    html += f'        <tr><td>{i}</td><td>{e["name"]}</td><td>{rgn}</td><td>{dk}</td><td>{e["reason"]}</td></tr>\n'
            html += """      </tbody>
    </table>
"""
        html += """  </div>

"""

    # 계약 상태 요약
    active_statuses = [s for s in STATUS_ORDER if status_counts.get(s, 0) > 0]
    html += """  <!-- 계약 상태 요약 -->
  <div class="section">
    <h2>계약 진행 상태 요약</h2>
    <div style="display:flex; gap:16px; margin-bottom:20px;">
"""
    for s in active_statuses:
        html += f'      <div class="status-chip" style="{STATUS_CHIP_STYLE.get(s, "")}">{s}: {status_counts[s]}건</div>\n'
    html += """    </div>
    <table>
      <thead>
        <tr><th>구분</th><th>건수</th><th>비율</th><th>비고</th></tr>
      </thead>
      <tbody>
"""
    for s in active_statuses:
        cnt = status_counts[s]
        pct = cnt / total * 100 if total else 0
        badge = STATUS_BADGE.get(s, "badge-cancel")
        note = STATUS_NOTE.get(s, "")
        if s == "취소" and cancel_names:
            note = ", ".join(cancel_names)
        html += f'        <tr><td><span class="badge {badge}">{s}</span></td><td>{cnt}건</td><td>{pct:.1f}%</td><td>{note}</td></tr>\n'
    html += """      </tbody>
    </table>
  </div>

"""
    # 쿠폰 현황
    coupon_dealers = [e for e in ref_data if e["coupon_qty"] > 0]
    if coupon_dealers:
        total_issued = sum(e["coupon_qty"] for e in coupon_dealers)
        total_invited = sum(e["coupon_invited"] for e in coupon_dealers)
        total_used = sum(e["coupon_used"] for e in coupon_dealers)
        use_rate = (total_used / total_invited * 100) if total_invited else 0

        html += f"""  <!-- 쿠폰 현황 -->
  <div class="section">
    <h2>쿠폰 배포 현황</h2>
    <div class="user-stats-grid">
      <div class="summary-card card-coupon">
        <div class="label">총 발행량</div>
        <div class="value">{total_issued}</div>
        <div class="sub">{len(coupon_dealers)}개 대리점 배포</div>
      </div>
      <div class="summary-card card-coupon-inv">
        <div class="label">초대(등록)수</div>
        <div class="value">{total_invited}</div>
        <div class="sub">쿠폰 사용자 등록</div>
      </div>
      <div class="summary-card card-coupon-use">
        <div class="label">사용 완료</div>
        <div class="value">{total_used}</div>
        <div class="sub">실제 서비스 이용</div>
      </div>
      <div class="summary-card card-coupon-rate">
        <div class="label">사용률</div>
        <div class="value">{use_rate:.1f}%</div>
        <div class="sub">초대 대비 사용 비율</div>
      </div>
    </div>
"""
        # 초대 발생 대리점 성과 테이블
        active_coupons = [e for e in coupon_dealers if e["coupon_invited"] > 0]
        active_coupons.sort(key=lambda x: (-x["coupon_invited"], -x["coupon_qty"]))
        if active_coupons:
            html += '    <h3>대리점별 쿠폰 성과 (초대 발생 대리점)</h3>\n'
            html += '    <table>\n      <thead>\n'
            html += '        <tr><th>대리점</th><th>쿠폰번호</th><th>발급량</th><th>초대수</th><th>사용수</th><th>초대율</th><th>성과</th></tr>\n'
            html += '      </thead>\n      <tbody>\n'
            for e in active_coupons:
                inv_rate = (e["coupon_invited"] / e["coupon_qty"] * 100) if e["coupon_qty"] else 0
                if inv_rate >= 20:
                    bar_color = "linear-gradient(90deg,#2e7d32,#66bb6a)"
                elif inv_rate >= 10:
                    bar_color = "linear-gradient(90deg,#1565c0,#42a5f5)"
                else:
                    bar_color = "linear-gradient(90deg,#e65100,#ff9800)"
                html += f'        <tr><td style="font-weight:600;">{e["name"]}</td><td>{e["coupon_no"]}</td><td>{e["coupon_qty"]}</td><td>{e["coupon_invited"]}</td><td>{e["coupon_used"]}</td><td>{inv_rate:.1f}%</td>\n'
                html += f'          <td><div class="coupon-bar"><div class="coupon-bar-bg"><div class="coupon-bar-fill" style="width:{inv_rate:.1f}%; background:{bar_color};"></div></div><div class="coupon-bar-label">{inv_rate:.0f}%</div></div></td></tr>\n'
            html += '      </tbody>\n    </table>\n'

        # 전체 발급 현황 테이블
        all_coupons = sorted(coupon_dealers, key=lambda x: -x["coupon_qty"])
        html += '\n    <h3 style="margin-top:28px;">전체 대리점 쿠폰 발급 현황</h3>\n'
        html += '    <table>\n      <thead>\n'
        html += '        <tr><th>No.</th><th>대리점</th><th>쿠폰번호</th><th>발급량</th><th>초대</th><th>사용</th></tr>\n'
        html += '      </thead>\n      <tbody>\n'
        for i, e in enumerate(all_coupons, 1):
            html += f'        <tr><td>{i}</td><td>{e["name"]}</td><td>{e["coupon_no"]}</td><td>{e["coupon_qty"]}</td><td>{e["coupon_invited"]}</td><td>{e["coupon_used"]}</td></tr>\n'
        html += '      </tbody>\n    </table>\n  </div>\n\n'

    html += f"""  <div class="footer">
    본 보고서는 Notion 대리점 관리 데이터베이스 기준으로 자동 생성되었습니다. | {TODAY}
  </div>

</div>
</body>
</html>
"""
    return html


def main():
    print(f"[{TODAY}] 보고서 자동 생성 시작")

    token = read_token()
    print(f"  Notion 토큰 로드 완료")

    print(f"  원소스 DB 조회중...")
    source_raw = fetch_db(token, SOURCE_DB)
    source_data = parse_source(source_raw)
    print(f"  -> {len(source_data)}건 로드")

    print(f"  교육참가 DB 조회중...")
    ref_raw = fetch_db(token, REF_DB)
    ref_data = parse_ref(ref_raw)
    print(f"  -> {len(ref_data)}건 로드")

    print(f"  HTML 보고서 생성중...")
    html = generate_html(source_data, ref_data)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  -> {OUTPUT_FILE} 저장 완료")

    open_cnt = sum(1 for e in source_data if e["region_status"] == "오픈")
    closed_cnt = sum(1 for e in source_data if e["region_status"] == "미오픈")
    print(f"\n  [결과] 전체: {len(source_data)} | 오픈: {open_cnt} | 미오픈: {closed_cnt} | 오픈율: {open_cnt/len(source_data)*100:.1f}%")
    print(f"  완료!")


if __name__ == "__main__":
    main()
