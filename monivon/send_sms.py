#!/usr/bin/env python3
"""
Mac Messages 앱을 이용한 엑셀 기반 단체 문자 발송 스크립트

사용법:
  python3 send_sms.py 연락처.xlsx

엑셀 형식:
  A열: 이름 (선택)
  B열: 전화번호 (필수)
  * 1행은 헤더로 건너뜁니다

실행 전:
  1. iPhone → 설정 → 메시지 → 문자 메시지 전달 → Mac 활성화
  2. Mac Messages 앱이 로그인되어 있어야 합니다
"""

import subprocess
import sys
import time
import re
import openpyxl


def normalize_phone(phone):
    """전화번호를 정규화 (010-1234-5678 → 01012345678)"""
    phone = str(phone).strip()
    phone = re.sub(r'[^0-9+]', '', phone)
    # +82 처리
    if phone.startswith('+82'):
        phone = '0' + phone[3:]
    return phone


def format_phone(phone):
    """전화번호를 하이픈 형식으로 (01012345678 → 010-1234-5678)"""
    if len(phone) == 11:
        return f"{phone[:3]}-{phone[3:7]}-{phone[7:]}"
    return phone


def send_imessage(phone, message):
    """AppleScript를 통해 Messages 앱으로 문자 발송"""
    script = f'''
    tell application "Messages"
        set targetService to 1st account whose service type = SMS
        set targetBuddy to participant "{phone}" of targetService
        send "{message}" to targetBuddy
    end tell
    '''
    result = subprocess.run(
        ['osascript', '-e', script],
        capture_output=True, text=True, timeout=30
    )
    return result.returncode == 0, result.stderr.strip()


def send_imessage_v2(phone, message):
    """대안 방식: iMessage 서비스로 발송"""
    script = f'''
    tell application "Messages"
        set targetService to 1st account whose service type = iMessage
        set targetBuddy to participant "{phone}" of targetService
        send "{message}" to targetBuddy
    end tell
    '''
    result = subprocess.run(
        ['osascript', '-e', script],
        capture_output=True, text=True, timeout=30
    )
    return result.returncode == 0, result.stderr.strip()


def read_excel(filepath):
    """엑셀에서 연락처 목록 읽기"""
    wb = openpyxl.load_workbook(filepath)
    ws = wb.active
    contacts = []

    for row in ws.iter_rows(min_row=2, values_only=True):
        if row is None:
            continue
        # A열: 이름, B열: 전화번호
        if len(row) >= 2 and row[1]:
            name = str(row[0]).strip() if row[0] else ""
            phone = normalize_phone(row[1])
            if phone and len(phone) >= 10:
                contacts.append({"name": name, "phone": phone})
        # B열이 없으면 A열을 전화번호로
        elif len(row) >= 1 and row[0]:
            phone = normalize_phone(row[0])
            if phone and len(phone) >= 10:
                contacts.append({"name": "", "phone": phone})

    return contacts


def main():
    if len(sys.argv) < 2:
        print("사용법: python3 send_sms.py <엑셀파일.xlsx>")
        print()
        print("엑셀 형식:")
        print("  A열: 이름 (선택)")
        print("  B열: 전화번호 (필수)")
        print("  * 1행은 헤더로 건너뜁니다")
        sys.exit(1)

    filepath = sys.argv[1]

    # 1. 엑셀 읽기
    print(f"엑셀 파일 로드: {filepath}")
    contacts = read_excel(filepath)
    print(f"  -> {len(contacts)}명 로드\n")

    if not contacts:
        print("발송할 연락처가 없습니다.")
        sys.exit(1)

    # 2. 연락처 미리보기
    print("=== 발송 대상 목록 ===")
    for i, c in enumerate(contacts, 1):
        print(f"  {i:3}. {c['name'] or '(이름없음)':15} {format_phone(c['phone'])}")
    print()

    # 3. 메시지 입력
    print("=== 발송할 메시지를 입력하세요 (빈 줄 입력 시 완료) ===")
    lines = []
    while True:
        line = input()
        if line == "":
            if lines:
                break
            continue
        lines.append(line)

    message = "\n".join(lines)
    # AppleScript 안전 처리
    message_escaped = message.replace('\\', '\\\\').replace('"', '\\"')

    print(f"\n=== 발송 내용 미리보기 ===")
    print(f"대상: {len(contacts)}명")
    print(f"메시지:\n{message}\n")

    # 4. 최종 확인
    confirm = input(f"{len(contacts)}명에게 발송하시겠습니까? (y/n): ").strip().lower()
    if confirm != 'y':
        print("취소되었습니다.")
        sys.exit(0)

    # 5. 발송
    print(f"\n=== 발송 시작 ===")
    success = 0
    fail = 0
    fail_list = []
    DELAY = 3  # 메시지 간 대기 시간 (초)

    for i, c in enumerate(contacts, 1):
        phone = c['phone']
        name = c['name'] or format_phone(phone)
        print(f"  [{i}/{len(contacts)}] {name} ({format_phone(phone)})...", end=" ", flush=True)

        # SMS 먼저 시도, 실패 시 iMessage로
        ok, err = send_imessage(phone, message_escaped)
        if not ok:
            ok, err = send_imessage_v2(phone, message_escaped)

        if ok:
            print("OK")
            success += 1
        else:
            print(f"FAIL - {err[:80]}")
            fail += 1
            fail_list.append(c)

        if i < len(contacts):
            time.sleep(DELAY)

    # 6. 결과
    print(f"\n=== 발송 결과 ===")
    print(f"  성공: {success}건")
    print(f"  실패: {fail}건")
    if fail_list:
        print(f"\n  [실패 목록]")
        for c in fail_list:
            print(f"    - {c['name'] or '(이름없음)'} {format_phone(c['phone'])}")


if __name__ == "__main__":
    main()
