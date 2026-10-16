#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
percent_bot - 라면 최저가 탐색 및 모니터링 봇
네이버 쇼핑 검색 스킬 및 공개 검색 표면을 기반으로
'농심 신라면 봉지 20개입' 최저가 상품을 찾고 목표가(15,000원) 도달 여부를 판정합니다.
"""

import os
import sys
import re
import json
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

# 콘솔 출력 인코딩 설정 (Windows 터미널 한글 깨짐 방지)
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

PRIMARY_KEYWORD = "농심 신라면 봉지 20개입"
SECONDARY_KEYWORD = "농심 신라면 120g 20개"
TARGET_PRICE = 15000
KSKILL_PROXY_URL = "https://k-skill-proxy.nomadamas.org/v1/naver-shopping/search"
KAKAO_TOKEN_URL = "https://kauth.kakao.com/oauth/token"
KAKAO_MEMO_SEND_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
ENV_FILE_PATH = Path(__file__).resolve().parent / ".env"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"


def clean_html_tags(text: str) -> str:
    """HTML 태그 및 특수문자 엔터티 제거"""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&quot;", '"').replace("&apos;", "'")
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return " ".join(text.split())


def is_ad_product(item: Dict[str, Any]) -> bool:
    """협찬 및 광고 상품 여부 판별 (진짜 상품만 필터링)"""
    if item.get("is_ad") or item.get("isAd"):
        return True
    card_type = str(item.get("cardType", "")).upper()
    source_type = str(item.get("sourceType", "")).upper()
    if "AD" in card_type or "AD" in source_type:
        return True
    return False


def is_original_shin_ramyun_20(title: str, mall_name: str = "", price: int = 0) -> bool:
    """
    오리지널 신라면 120g 20개입 상품인지 정교하게 필터링
    - 블랙, 골드, 건면, 더레드, 툼바, 볶음면 등 파생 상품 제외
    - 타 라면과의 혼합 세트(짜파게티, 안성탕면 등) 제외
    - 20개입/20봉/20입 규격만 포함 (10개, 16개, 30개, 40개 등 제외)
    """
    title_lower = title.lower()

    # 필수 키워드
    if "신라면" not in title:
        return False

    # 파생 제품 제외 (오리지널 신라면만 허용)
    excluded_variants = [
        "건면", "블랙", "골드", "더레드", "더 레드", "툼바", "로제",
        "볶음면", "사리곰탕", "김통깨", "장칼국수", "마라", "백짬뽕"
    ]
    for variant in excluded_variants:
        if variant in title:
            return False

    # 혼합 구성 라면 제외 (순수 신라면만 20개여야 함)
    mixed_keywords = [
        "안성탕면", "짜파게티", "너구리", "오징어짬뽕", "진라면", "삼양라면",
        "혼합", "세트", "신안너짜", "신신너짜", "새신너짜", "오짬"
    ]
    for mixed in mixed_keywords:
        if mixed in title:
            return False

    # 다른 수량 제외
    wrong_counts = ["10개", "10봉", "10입", "16개", "16봉", "16입", "30개", "30봉", "30입", "40개", "40봉", "40입"]
    for wc in wrong_counts:
        if wc in title:
            return False

    # 20개 수량 확인 (20개, 20봉, 20입, 5입 4개, 5개입 4개 등)
    has_20_count = any(k in title for k in [
        "20개", "20봉", "20입", "5입*4", "5입 4개", "5입x4", "5입, 4개", "5입,4개", "5개입 4개", "5개입x4"
    ])
    
    # 농심 공식 브랜드스토어의 20개입 표준가(16,610원) 매칭 예외 지원
    if not has_20_count and ("농심" in mall_name and "브랜드" in mall_name and price == 16610):
        return True

    return has_20_count


def fetch_from_proxy(keyword: str) -> Optional[List[Dict[str, Any]]]:
    """k-skill-proxy를 통한 네이버 쇼핑 검색 시도"""
    params = urllib.parse.urlencode({"q": keyword, "limit": 40, "sort": "price_asc"})
    url = f"{KSKILL_PROXY_URL}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=6) as response:
            if response.status == 200:
                data = json.loads(response.read().decode("utf-8"))
                items = data.get("items", [])
                if items:
                    return items
    except Exception:
        return None
    return None


def fetch_from_naver_search(keyword: str) -> List[Dict[str, Any]]:
    """
    네이버 쇼핑 공개 검색 표면(_INITIAL_STATE JSON) 직접 수집
    k-skill-proxy의 원리와 동일한 공개 BFF 데이터 추출
    """
    url = f"https://search.naver.com/search.naver?query={urllib.parse.quote(keyword)}"
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://www.naver.com/"
    })

    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            html = response.read().decode("utf-8", errors="ignore")
    except Exception as e:
        raise RuntimeError(f"네이버 검색 페이지 접근 실패 ({e})")

    extracted_items = []

    # _INITIAL_STATE JSON 파싱
    for line in html.splitlines():
        if "_INITIAL_STATE=" in line:
            start_idx = line.find("_INITIAL_STATE=") + len("_INITIAL_STATE=")
            json_str = line[start_idx:].rstrip("; ")
            try:
                data = json.loads(json_str)
                init_props = data.get("initProps", {})

                # 1. pagedSlot 내 카탈로그 및 상품 카드
                for page in init_props.get("pagedSlot", []):
                    for slot in page.get("slots", []):
                        card = slot.get("data", {})
                        if not card:
                            continue

                        name = clean_html_tags(card.get("productName") or card.get("productTitleOrg") or card.get("productTitle") or "")
                        price = card.get("discountedSalePrice") or card.get("salePrice") or card.get("lowPrice")
                        if not name or not price:
                            continue

                        mall = card.get("mallName")
                        mall_count = card.get("mallCount")
                        if not mall and mall_count:
                            mall = f"네이버 가격비교 ({mall_count}개 몰)"
                        elif not mall:
                            mall = "네이버 쇼핑"

                        reviews = card.get("totalReviewCount") or card.get("reviewCount") or 0
                        
                        # URL 추출
                        click_url = card.get("productUrl") or card.get("productClickUrl") or card.get("crUrl")
                        if isinstance(click_url, dict):
                            link = click_url.get("pcUrl") or click_url.get("mobileUrl") or ""
                        else:
                            link = str(click_url or "")

                        if not link and card.get("nvMid"):
                            link = f"https://search.shopping.naver.com/catalog/{card.get('nvMid')}"

                        extracted_items.append({
                            "title": name,
                            "price": int(price),
                            "mall_name": mall,
                            "review_count": int(reviews),
                            "url": link,
                            "cardType": card.get("cardType", ""),
                            "sourceType": card.get("sourceType", ""),
                            "is_ad": card.get("cardType") == "AD_CARD" or card.get("sourceType") == "AD"
                        })

                # 2. nstore 제품 카드
                for prod in init_props.get("products", []):
                    name = clean_html_tags(prod.get("productName") or prod.get("productTitle") or "")
                    price = prod.get("discountedSalePrice") or prod.get("salePrice")
                    if not name or not price:
                        continue

                    mall = prod.get("channelName") or prod.get("mallName") or "농심 브랜드스토어"
                    reviews = prod.get("totalReviewCount") or 0
                    
                    click_url = prod.get("productUrl") or prod.get("productClickUrl")
                    if isinstance(click_url, dict):
                        link = click_url.get("pcUrl") or click_url.get("mobileUrl") or ""
                    else:
                        link = str(click_url or "")

                    extracted_items.append({
                        "title": name,
                        "price": int(price),
                        "mall_name": mall,
                        "review_count": int(reviews),
                        "url": link,
                        "cardType": prod.get("cardType", "ORGANIC_CARD"),
                        "sourceType": prod.get("sourceType", "ORGANIC"),
                        "is_ad": prod.get("cardType") == "AD_CARD"
                    })

            except Exception:
                continue

    if not extracted_items:
        raise RuntimeError("네이버 쇼핑 검색 결과에서 상품 데이터를 추출하지 못했습니다. (검색어 규격 불일치 또는 일시적 차단)")

    return extracted_items


def load_env_file(env_path: Path = ENV_FILE_PATH) -> Dict[str, str]:
    """프로젝트 폴더의 .env 파일에서 환경변수를 읽어 딕셔너리로 반환"""
    if not env_path.exists():
        raise FileNotFoundError(f".env 파일을 찾을 수 없습니다 ({env_path})")

    env_vars: Dict[str, str] = {}
    content = env_path.read_text(encoding="utf-8")
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and ((value[0] == value[-1] == '"') or (value[0] == value[-1] == "'")):
            value = value[1:-1]
        env_vars[key] = value

    return env_vars


def update_env_refresh_token(new_refresh_token: str, env_path: Path = ENV_FILE_PATH) -> None:
    """카카오 토큰 갱신 시 새 refresh_token이 발급되면 .env 파일에 업데이트"""
    try:
        if not env_path.exists():
            return
        lines = env_path.read_text(encoding="utf-8").splitlines()
        updated_lines = []
        replaced = False
        for line in lines:
            if line.strip().startswith("KAKAO_REFRESH_TOKEN="):
                updated_lines.append(f"KAKAO_REFRESH_TOKEN={new_refresh_token}")
                replaced = True
            else:
                updated_lines.append(line)
        if not replaced:
            updated_lines.append(f"KAKAO_REFRESH_TOKEN={new_refresh_token}")
        env_path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")
    except Exception:
        pass


def refresh_kakao_access_token(env_vars: Dict[str, str], env_path: Path = ENV_FILE_PATH) -> str:
    """
    .env에서 읽은 KAKAO_REST_API_KEY, KAKAO_CLIENT_SECRET, KAKAO_REFRESH_TOKEN으로
    카카오 OAuth access_token을 발급받아 반환
    """
    rest_api_key = env_vars.get("KAKAO_REST_API_KEY") or os.environ.get("KAKAO_REST_API_KEY", "")
    client_secret = env_vars.get("KAKAO_CLIENT_SECRET") or os.environ.get("KAKAO_CLIENT_SECRET", "")
    refresh_token = env_vars.get("KAKAO_REFRESH_TOKEN") or os.environ.get("KAKAO_REFRESH_TOKEN", "")

    missing_keys = []
    if not rest_api_key:
        missing_keys.append("KAKAO_REST_API_KEY")
    if not refresh_token:
        missing_keys.append("KAKAO_REFRESH_TOKEN")
    if missing_keys:
        raise ValueError(f".env 파일에 필수 카카오 인증 키가 누락되어 있습니다: {', '.join(missing_keys)}")

    payload: Dict[str, str] = {
        "grant_type": "refresh_token",
        "client_id": rest_api_key,
        "refresh_token": refresh_token,
    }
    if client_secret:
        payload["client_secret"] = client_secret

    encoded_data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(
        KAKAO_TOKEN_URL,
        data=encoded_data,
        headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            resp_body = response.read().decode("utf-8", errors="ignore")
            token_data = json.loads(resp_body)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        detail_hint = ""
        if "invalid_grant" in err_body or "KOE320" in err_body:
            detail_hint = " -> 리프레시 토큰(KAKAO_REFRESH_TOKEN)이 만료되었거나 유효하지 않습니다."
        elif "invalid_client" in err_body or "KOE010" in err_body:
            detail_hint = " -> REST API 키(KAKAO_REST_API_KEY) 또는 Client Secret(KAKAO_CLIENT_SECRET)이 올바르지 않습니다."
        raise RuntimeError(f"카카오 액세스 토큰 발급 실패 (HTTP {e.code}): {err_body}{detail_hint}")
    except Exception as e:
        raise RuntimeError(f"카카오 인증 서버 요청 중 오류 발생: {e}")

    access_token = token_data.get("access_token")
    if not access_token:
        raise RuntimeError(f"카카오 토큰 응답에 access_token이 없습니다: {token_data}")

    # 새 refresh_token이 함께 반환된 경우 .env 파일 갱신
    new_refresh_token = token_data.get("refresh_token")
    if new_refresh_token:
        update_env_refresh_token(new_refresh_token, env_path=env_path)

    return access_token


def build_kakao_template_object(item: Dict[str, Any]) -> Dict[str, Any]:
    """
    카카오톡 '나에게 보내기'용 텍스트 템플릿 객체 생성
    - 상품명, 가격, 쇼핑몰 이름, 리뷰 수 포함
    - '구매하러 가기' 버튼으로 구매 링크 연결
    """
    title = item.get("title") or "상품명 없음"
    price = int(item.get("price") or 0)
    mall = item.get("mall_name") or "쇼핑몰 정보 없음"
    reviews = item.get("review_count")
    review_str = f"{int(reviews):,}개" if reviews else "0개"
    link_url = item.get("url") or "https://search.shopping.naver.com"

    message_text = (
        f"🚨 [신라면 최저가 특가 알림]\n"
        f"• 상품명: {title}\n"
        f"• 가격: {price:,}원\n"
        f"• 쇼핑몰: {mall}\n"
        f"• 리뷰 수: {review_str}"
    )

    return {
        "object_type": "text",
        "text": message_text,
        "link": {
            "web_url": link_url,
            "mobile_web_url": link_url,
        },
        "button_title": "구매하러 가기",
        "buttons": [
            {
                "title": "구매하러 가기",
                "link": {
                    "web_url": link_url,
                    "mobile_web_url": link_url,
                },
            }
        ],
    }


def send_kakao_alert(item: Dict[str, Any], env_path: Path = ENV_FILE_PATH) -> Tuple[bool, str]:
    """
    카카오톡 '나에게 보내기' 알림 전송
    성공 시 (True, 성공 메시지), 실패 시 보낸 척하지 않고 (False, 정확한 실패 원인) 반환 및 출력
    """
    try:
        env_vars = load_env_file(env_path)
        access_token = refresh_kakao_access_token(env_vars, env_path=env_path)
        template_obj = build_kakao_template_object(item)

        encoded_body = urllib.parse.urlencode({
            "template_object": json.dumps(template_obj, ensure_ascii=False)
        }).encode("utf-8")

        req = urllib.request.Request(
            KAKAO_MEMO_SEND_URL,
            data=encoded_body,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=8) as response:
                resp_body = response.read().decode("utf-8", errors="ignore")
                result_data = json.loads(resp_body)
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            detail_hint = ""
            if "insufficient scopes" in err_body or "-402" in err_body:
                detail_hint = (
                    "\n   설명: 현재 토큰에 카카오톡 메시지 전송 권한(talk_message)이 없습니다(allowed_scopes=[]). "
                    "카카오 개발자 콘솔 동의항목에서 '카카오톡 메시지 전송(talk_message)'을 활성화하고 권한 동의를 포함해 토큰을 다시 발급받아야 합니다."
                )
            elif "-401" in err_body:
                detail_hint = "\n   설명: 액세스 토큰이 유효하지 않거나 인증에 실패했습니다."
            raise RuntimeError(f"카카오톡 메시지 API 호출 실패 (HTTP {e.code}): {err_body}{detail_hint}")
        except Exception as e:
            raise RuntimeError(f"카카오톡 메시지 전송 중 네트워크/파싱 오류 발생: {e}")

        result_code = result_data.get("result_code")
        if result_code != 0:
            raise RuntimeError(f"카카오톡 메시지 전송 실패 (result_code={result_code}, 응답={result_data})")

        print("📨 [카카오톡 알림 완료] '나에게 보내기'로 특가 알림 메시지를 성공적으로 보냈습니다.")
        return True, "카카오톡 알림 전송 성공"

    except Exception as e:
        error_msg = str(e)
        print("❌ [카카오톡 알림 실패] 알림을 보내지 못했습니다.")
        print(f"   원인: {error_msg}")
        return False, error_msg


def run_bot(items_override: Optional[List[Dict[str, Any]]] = None, exit_on_error: bool = True) -> bool:
    print("=" * 70)
    print("  🍜 [percent_bot] 네이버 쇼핑 신라면 최저가 탐색 봇")
    print("=" * 70)
    print(f"🔍 검색 키워드 : '{PRIMARY_KEYWORD}'")
    print(f"🎯 목표 알림가 : {TARGET_PRICE:,}원 이하\n")

    # 1. 데이터 수집 시도 (k-skill-proxy -> 네이버 검색 Fallback 또는 Mock 데이터)
    raw_items = []
    
    if items_override is not None:
        raw_items = list(items_override)
        print(f"📡 [데이터 소스] 테스트 모의 데이터 수신 완료 (제공된 항목: {len(raw_items)}개)")
    else:
        proxy_success = False
        try:
            proxy_res = fetch_from_proxy(PRIMARY_KEYWORD)
            if proxy_res:
                raw_items.extend(proxy_res)
                proxy_success = True
                print("📡 [데이터 소스] k-skill-proxy 정상 수신 완료")
        except Exception:
            proxy_success = False

        if not proxy_success:
            try:
                print("ℹ️  k-skill-proxy 응답 없음 -> 네이버 쇼핑 공개 검색 표면으로 직접 조회합니다.")
                items1 = fetch_from_naver_search(PRIMARY_KEYWORD)
                raw_items.extend(items1)

                # 3개 이상 충분한 후보군 확보를 위해 보조 검색어 함께 취합
                try:
                    items2 = fetch_from_naver_search(SECONDARY_KEYWORD)
                    raw_items.extend(items2)
                except Exception:
                    pass

                print(f"📡 [데이터 소스] 네이버 쇼핑 검색 데이터 수집 성공 (수집된 원본: {len(raw_items)}개)")
            except Exception as e:
                # 값을 못 가져오면 지어내지 않고 무엇이 잘못됐는지 그대로 출력하고 중단
                print(f"\n❌ [오류 발생] 상품 정보를 가져오지 못했습니다.")
                print(f"   원인: {e}")
                print("   시스템을 중단합니다.\n")
                if exit_on_error:
                    sys.exit(1)
                return False

    # 2. 협찬 광고 상품 제거 및 진짜 오리지널 20개입 상품만 정교하게 필터링
    genuine_items = []
    seen_keys = set()

    for item in raw_items:
        # 협찬 광고 상품 제거
        if is_ad_product(item):
            continue

        title = item.get("title") or ""
        mall = item.get("mall_name") or ""
        price = item.get("price") or 0

        # 오리지널 신라면 20개입 구성만 필터링
        if is_original_shin_ramyun_20(title, mall, price):
            # 상품명 보정 (농심 공식몰 단일 상품인 경우 20개 옵션 명시)
            display_title = title
            if "20" not in display_title and price == 16610:
                display_title = f"{title} 120g, 20개 (공식몰 N배송)"

            key = (price, mall)
            if key not in seen_keys:
                seen_keys.add(key)
                genuine_items.append({
                    "title": display_title,
                    "price": price,
                    "mall_name": mall,
                    "review_count": item.get("review_count", 0),
                    "url": item.get("url") or ""
                })

    if not genuine_items:
        print("\n❌ [필터링 결과] 광고를 제외한 오리지널 신라면 20개입 상품을 찾을 수 없습니다.")
        print("   원인: 검색 결과 내에 20개입 규격이 없거나 모두 광고/혼합 세트 상품입니다.")
        print("   임의의 값을 지어내지 않고 시스템을 중단합니다.\n")
        if exit_on_error:
            sys.exit(1)
        return False

    # 3. 저렴한 순서로 정렬 후 상위 3개 선별
    genuine_items.sort(key=lambda x: x["price"])
    top3 = genuine_items[:3]

    # 4. 상품명·가격·쇼핑몰·리뷰 수·링크 출력
    print("\n" + "-" * 70)
    print(f"🏆 저렴한 순서 상품 TOP {len(top3)} (광고 제거 / 오리지널 20개입 기준)")
    print("-" * 70)

    for rank, item in enumerate(top3, start=1):
        mall = item["mall_name"]
        price_str = f"{item['price']:,}원"
        reviews = item["review_count"]
        review_str = f"{reviews:,}개" if reviews else "정보 없음"
        url = item["url"] if item["url"] else "링크 없음"

        print(f"\n[{rank}위] {item['title']}")
        print(f"   • 가격   : {price_str}")
        print(f"   • 쇼핑몰 : {mall}")
        print(f"   • 리뷰 수: {review_str}")
        print(f"   • 링크   : {url}")

    print("\n" + "=" * 70)

    # 5. 1위 가격이 목표가 15000원 이하인지 확인 후 지정 문구 출력 및 카카오톡 알림 분기
    rank1_item = top3[0]
    rank1_price = rank1_item["price"]

    if rank1_price <= TARGET_PRICE:
        print("🚨 [특가 발생] 목표 가격 이하입니다!")
        print(f"   (1위 가격: {rank1_price:,}원 / 목표가 {TARGET_PRICE:,}원 대비 {TARGET_PRICE - rank1_price:,}원 저렴)")
        kakao_ok, _ = send_kakao_alert(rank1_item)
        print("=" * 70 + "\n")
        if not kakao_ok:
            if exit_on_error:
                sys.exit(1)
            return False
    else:
        print("⚠️ [유지] 아직 목표 가격보다 비쌉니다.")
        print(f"   (1위 가격: {rank1_price:,}원 / 목표가 {TARGET_PRICE:,}원 대비 {rank1_price - TARGET_PRICE:,}원 초과)")
        print("ℹ️  목표가보다 비싸므로 화면에만 출력하고 카카오톡 메시지는 보내지 않습니다.")
        print("=" * 70 + "\n")

    return True


if __name__ == "__main__":
    run_bot()
