#!/usr/bin/env python3
"""
모니본 보고서 데이터 자동 수집 스크립트
- 수거히어로 Admin API에서 데이터를 가져와 data/ JSON 파일을 업데이트
- 사용법: python3 fetch_report_data.py
"""

import json
import os
import sys
from datetime import datetime, date
from urllib.request import Request, urlopen
from urllib.error import HTTPError

# ============================================================
# 설정 (.env 파일에서 로드)
# ============================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
ENV_FILE = os.path.join(SCRIPT_DIR, ".env")


def load_env():
    """로컬 .env 파일에서 설정을 읽어옴"""
    env = {}
    if not os.path.exists(ENV_FILE):
        print(f"[오류] .env 파일이 없습니다: {ENV_FILE}", file=sys.stderr)
        print("  .env 파일을 생성하고 아래 내용을 입력하세요:", file=sys.stderr)
        print("    ADMIN_API_BASE=https://admin-api.sugohero.co.kr", file=sys.stderr)
        print("    ADMIN_ID=your_id", file=sys.stderr)
        print("    ADMIN_PWD=your_password", file=sys.stderr)
        sys.exit(1)
    with open(ENV_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                env[key.strip()] = val.strip()
    return env


ENV = load_env()
API_BASE = ENV.get("ADMIN_API_BASE", "https://admin-api.sugohero.co.kr")
ADMIN_ID = ENV["ADMIN_ID"]
ADMIN_PWD = ENV["ADMIN_PWD"]

# 대리점-쿠폰코드 범위 매핑 (SUGO-OPEN-EVENT-XXX)
DEALER_CODE_RANGES = {
    "구미 대리점": (1, 16),
    "경기 고양": (17, 42),
    "서울 강남구": (43, 60),
    "수영구 대리점": (61, 72),
    "연제구대리점": (73, 84),
    "해운대 대리점": (85, 100),
    "장유 대리점": (101, 113),
    "전주 완산구": (114, 127),
    "경남 거제": (128, 140),
    "삼척 대리점": (141, 150),
    "의정부/도봉/노원/강북": (151, 180),
    "경주 불국사히어로": (181, 193),
    "광주 동구": (194, 203),
    "경기 광주": (204, 218),
    "광주 북구": (219, 234),
    "경기 김포": (235, 251),
    "충북 청주": (252, 269),
    "경기 양주": (270, 282),
    "천안 동남구": (283, 297),
    "천안 서북구": (298, 311),
    "경기수원": (312, 336),
    "전남 여수": (337, 349),
    "경기 이천": (350, 362),
    "경기 파주": (363, 379),
    "전주 덕진구/완주군": (380, 394),
    "창원대리점": (395, 420),
    "서울 동대문/성북": (421, 441),
    "부산남구": (442, 454),
    "대구 달서구": (455, 472),
    "광주 광산구/서구": (473, 491),
    "경남 진주": (492, 506),
    "대전 대리점": (507, 523),
    "부산진구": (524, 538),
    "김해대리점": (539, 553),
    "인천 영종도": (554, 564),
    "경기 부천": (565, 586),
    "울산 대리점": (587, 613),
    "경기 여주": (614, 623),
    "인천 서해구/검단구": (624, 642),
    "삼척 대리점2": (643, 652),  # 삼척 추가분
}

# 삼척 대리점은 두 구간 합산
DEALER_MERGE = {"삼척 대리점2": "삼척 대리점"}

# 발급량 (대리점별 쿠폰 배포 수)
DEALER_ISSUED = {
    "구미 대리점": 16, "경기 고양": 26, "서울 강남구": 18, "수영구 대리점": 12,
    "연제구대리점": 12, "해운대 대리점": 16, "장유 대리점": 13, "전주 완산구": 14,
    "경남 거제": 13, "삼척 대리점": 20, "의정부/도봉/노원/강북": 30,
    "경주 불국사히어로": 13, "광주 동구": 10, "경기 광주": 15, "광주 북구": 16,
    "경기 김포": 17, "충북 청주": 18, "경기 양주": 13, "천안 동남구": 15,
    "천안 서북구": 14, "경기수원": 25, "전남 여수": 13, "경기 이천": 13,
    "경기 파주": 17, "전주 덕진구/완주군": 15, "창원대리점": 26,
    "서울 동대문/성북": 21, "부산남구": 13, "대구 달서구": 18,
    "광주 광산구/서구": 19, "경남 진주": 15, "대전 대리점": 17,
    "부산진구": 15, "김해대리점": 15, "인천 영종도": 11,
    "경기 부천": 22, "울산 대리점": 27, "경기 여주": 10,
    "인천 서해구/검단구": 19,
}


# ============================================================
# API 헬퍼
# ============================================================
class AdminAPI:
    def __init__(self):
        self.token = None

    def _request(self, method, path, data=None, params=None):
        url = f"{API_BASE}{path}"
        if params:
            qs = "&".join(f"{k}={v}" for k, v in params.items())
            url += f"?{qs}"

        body = json.dumps(data).encode() if data else None
        req = Request(url, data=body, method=method)
        req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")

        try:
            with urlopen(req) as resp:
                return json.loads(resp.read().decode())
        except HTTPError as e:
            body = e.read().decode()
            print(f"  API Error {e.code}: {body[:200]}", file=sys.stderr)
            return {"success": False}

    def login(self):
        print("[1/5] Admin API 로그인...")
        resp = self._request("POST", "/api/v1/admin/auth/login", {
            "admin_id": ADMIN_ID, "admin_pwd": ADMIN_PWD
        })
        if resp.get("success"):
            self.token = resp["data"]["access_token"]
            print(f"  로그인 성공 ({resp['data']['admin_name']})")
            return True
        print(f"  로그인 실패: {resp.get('message')}", file=sys.stderr)
        return False

    def get_dashboard(self):
        return self._request("GET", "/api/v1/admin/dashboard/summary")

    def get_sales_summary(self):
        return self._request("GET", "/api/v1/admin/payments/sales/summary")

    def get_payment_stats(self):
        return self._request("GET", "/api/v1/admin/payments/stats")

    def get_user_coupons(self, page=1, size=100):
        return self._request("GET", "/api/v1/admin/coupons/user-coupons",
                             params={"page": page, "size": size})

    def get_all_user_coupons(self):
        all_items = []
        page = 1
        while True:
            resp = self.get_user_coupons(page=page, size=100)
            if not resp.get("success") or not isinstance(resp.get("data"), dict):
                break
            items = resp["data"]["items"]
            if not items:
                break
            all_items.extend(items)
            total = resp["data"]["page_info"]["total_count"]
            if len(all_items) >= total:
                break
            page += 1
        return all_items


# ============================================================
# 데이터 처리
# ============================================================
def get_coupon_code_number(code):
    """SUGO-OPEN-EVENT-123 → 123"""
    parts = code.split("-")
    if len(parts) >= 4 and parts[0] == "SUGO" and parts[1] == "OPEN":
        try:
            return int(parts[-1])
        except ValueError:
            pass
    return None


def find_dealer_for_code(code_num):
    """코드 번호로 대리점 찾기"""
    for dealer, (start, end) in DEALER_CODE_RANGES.items():
        if start <= code_num <= end:
            return DEALER_MERGE.get(dealer, dealer)
    return None


def process_coupon_data(all_coupons):
    """쿠폰 데이터를 대리점별로 집계"""
    sugo_coupons = []
    for c in all_coupons:
        code_num = get_coupon_code_number(c["coupon_code"])
        if code_num is not None:
            c["_code_num"] = code_num
            c["_dealer"] = find_dealer_for_code(code_num)
            sugo_coupons.append(c)

    total_registered = len(sugo_coupons)
    total_used = sum(1 for c in sugo_coupons if c["status"] == "USED")
    total_unused = total_registered - total_used

    # 대리점별 집계
    dealer_data = {}
    for c in sugo_coupons:
        d = c["_dealer"]
        if not d:
            continue
        dealer_data.setdefault(d, {"invited": 0, "used": 0})
        dealer_data[d]["invited"] += 1
        if c["status"] == "USED":
            dealer_data[d]["used"] += 1

    return total_registered, total_used, total_unused, dealer_data


def load_json(filename):
    filepath = os.path.join(DATA_DIR, filename)
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def save_json(filename, data):
    os.makedirs(DATA_DIR, exist_ok=True)
    filepath = os.path.join(DATA_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  저장: {filepath}")


# ============================================================
# 메인
# ============================================================
def main():
    today = date.today().isoformat()
    print(f"=== 모니본 보고서 데이터 수집 ({today}) ===\n")

    api = AdminAPI()
    if not api.login():
        sys.exit(1)

    # --- 대시보드 + 매출 ---
    print("\n[2/5] 대시보드 & 매출 데이터 수집...")
    dash = api.get_dashboard()
    sales = api.get_sales_summary()
    pay_stats = api.get_payment_stats()

    if dash.get("success"):
        d = dash["data"]
        print(f"  오늘 매출: {d['sales']['today_sales']:,}원")
        print(f"  월 매출: {d['sales']['month_sales']:,}원")
        print(f"  총 사용자: {d['users']['total_users']:,}명")
        print(f"  총 히어로: {d['heroes']['total_heroes']}명 (활성 {d['heroes']['active_heroes']}명)")
        print(f"  대리점: {d['operations']['active_agencies']}개")

    # 대시보드 데이터 저장
    dashboard_data = {
        "updated": today,
        "sales": dash["data"]["sales"] if dash.get("success") else {},
        "users": dash["data"]["users"] if dash.get("success") else {},
        "heroes": dash["data"]["heroes"] if dash.get("success") else {},
        "collections": dash["data"]["collections"] if dash.get("success") else {},
        "operations": dash["data"]["operations"] if dash.get("success") else {},
        "monthly_sales": sales["data"]["monthly"] if sales.get("success") else [],
        "current_month_sales": sales["data"]["current_month"] if sales.get("success") else {},
        "payment_stats": pay_stats["data"] if pay_stats.get("success") else {},
    }
    save_json("dashboard.json", dashboard_data)

    # --- 쿠폰 데이터 ---
    print("\n[3/5] 사용자 쿠폰 데이터 수집...")
    all_coupons = api.get_all_user_coupons()
    print(f"  전체 쿠폰: {len(all_coupons)}건")

    registered, used, unused, dealer_coupon = process_coupon_data(all_coupons)
    print(f"  SUGO-OPEN-EVENT: 등록 {registered}, 사용 {used}, 미사용 {unused}")

    # --- coupon_daily.json 업데이트 ---
    print("\n[4/5] coupon_daily.json 업데이트...")
    daily = load_json("coupon_daily.json") or {"updated": today, "history": []}

    # 오늘 날짜 데이터가 이미 있으면 업데이트, 없으면 추가
    today_entry = {"date": today, "registered": registered, "used": used, "unused": unused}
    existing_idx = next((i for i, h in enumerate(daily["history"]) if h["date"] == today), None)
    if existing_idx is not None:
        daily["history"][existing_idx] = today_entry
        print(f"  {today} 데이터 업데이트")
    else:
        daily["history"].append(today_entry)
        print(f"  {today} 데이터 추가")

    daily["updated"] = today
    save_json("coupon_daily.json", daily)

    # --- dealer_stats.json 업데이트 ---
    print("\n[5/5] dealer_stats.json 업데이트...")
    dealer_stats = load_json("dealer_stats.json") or {
        "updated": today,
        "total_issued": 652,
        "total_dealers": len(DEALER_ISSUED),
        "dealers": []
    }

    # 대리점 목록 구성/업데이트
    dealer_map = {d["name"]: d for d in dealer_stats.get("dealers", [])}

    for dealer_name, issued in DEALER_ISSUED.items():
        coupon = dealer_coupon.get(dealer_name, {"invited": 0, "used": 0})

        if dealer_name not in dealer_map:
            dealer_map[dealer_name] = {
                "name": dealer_name,
                "issued": issued,
                "history": []
            }

        d = dealer_map[dealer_name]
        d["issued"] = issued

        today_dealer_entry = {
            "date": today,
            "invited": coupon["invited"],
            "used": coupon["used"]
        }

        existing_idx = next((i for i, h in enumerate(d["history"]) if h["date"] == today), None)
        if existing_idx is not None:
            d["history"][existing_idx] = today_dealer_entry
        else:
            d["history"].append(today_dealer_entry)

    dealer_stats["updated"] = today
    dealer_stats["total_issued"] = sum(DEALER_ISSUED.values())
    dealer_stats["total_dealers"] = len(DEALER_ISSUED)
    dealer_stats["dealers"] = list(dealer_map.values())
    save_json("dealer_stats.json", dealer_stats)

    # --- 요약 출력 ---
    print(f"\n{'='*50}")
    print(f"수집 완료! ({today})")
    print(f"  쿠폰 등록: {registered}건 / 사용: {used}건 / 사용률: {used/registered*100:.1f}%" if registered > 0 else "  쿠폰 데이터 없음")
    print(f"  초대 발생 대리점: {sum(1 for v in dealer_coupon.values() if v['invited'] > 0)}개")

    # 전일 대비 비교
    if len(daily["history"]) >= 2:
        prev = daily["history"][-2]
        cur = daily["history"][-1]
        reg_diff = cur["registered"] - prev["registered"]
        use_diff = cur["used"] - prev["used"]
        print(f"\n  전일({prev['date']}) 대비:")
        print(f"    등록: {prev['registered']} → {cur['registered']} ({'+' if reg_diff>=0 else ''}{reg_diff})")
        print(f"    사용: {prev['used']} → {cur['used']} ({'+' if use_diff>=0 else ''}{use_diff})")

    print(f"\n  data/coupon_daily.json  - 일별 쿠폰 추이")
    print(f"  data/dealer_stats.json  - 대리점별 성과")
    print(f"  data/dashboard.json     - 대시보드 종합 (매출/사용자/히어로)")
    print(f"\n  git add data/ && git commit && git push 로 보고서 반영")


if __name__ == "__main__":
    main()
